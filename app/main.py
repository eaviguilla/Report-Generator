from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.models import Content, EvidenceItem, LibraryRef, Report, Scope, Vulnerability, normalise_scope_modes
from app.tester_identity import LIBRARY_PATH, load_or_bootstrap
from .docx_captions import update_docx_bytes_with_word
from .docx_report import ReportGenerationError, generation_issues, render_report_docx
from .library import Library
from .docx_import import parse_report_docx
from .report_service import applicable_poc_variants, apply_poc_variant, assign_fresh_fragment_ids, finding_is_complete, invalid_character_issue, provision, reconcile_targets, report_export_filename, setup_input_issues, setup_is_complete, sync_evidence_image_slots
from .storage import atomic_write_bytes
from .workspace import StaleReportError, Workspace, app_id_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
# One shared folder at the repo root so testers do not have to dig through per-report directories.
GENERATED = ROOT / "generated"
prefs = load_or_bootstrap(DATA / "prefs.json")
workspace = Workspace(DATA, prefs.get("tester", {}).get("display_name", ""))
configured_library = Path(prefs.get("library_path", LIBRARY_PATH))
configured_library = configured_library if configured_library.is_absolute() else ROOT / configured_library
library = Library.load_or_empty(configured_library)
if library.load_error:
    print(f"  vulnerability library unavailable -- {library.load_error}")

app = FastAPI(title="Report Generator")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "web" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "web" / "templates")
# One cache-buster for every asset, so the four pages can never load different CSS versions.
STATIC_DIR = ROOT / "app" / "web" / "static"


class _AssetVersion:
    """Recomputed per render, because a value frozen at import serves a stale cached script for the
    rest of the process and the tester sees an old page until they reload by hand."""

    def __str__(self) -> str:
        return str(int(max(path.stat().st_mtime for path in STATIC_DIR.glob("*.*"))))


templates.env.globals["asset_v"] = _AssetVersion()
logger = logging.getLogger(__name__)
ERROR_LOG_PATH = DATA / "vulnreport-errors.log"
STALE_REPORT_DETAIL = "This report changed in another browser tab. Choose whether to save your version or load the latest version."


def configure_error_logging() -> None:
    """Write actionable server diagnostics without allowing the log to grow unbounded."""
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if any(getattr(handler, "baseFilename", None) == str(ERROR_LOG_PATH.resolve()) for handler in logger.handlers):
        return
    handler = RotatingFileHandler(ERROR_LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


configure_error_logging()


def request_function(request: Request) -> str:
    """Return the FastAPI endpoint name handling a request."""
    endpoint = request.scope.get("endpoint")
    return getattr(endpoint, "__name__", "unknown_endpoint")


def detail_message(detail) -> str:
    """Extract a concise human message while preserving structured response details."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "Request failed")
        issues = [str(issue) for issue in detail.get("issues", []) if issue]
        return f"{message}: {'; '.join(issues)}" if issues else message
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict):
            return str(first.get("msg") or "Request validation failed")
    return "Request failed"


def error_diagnostic(
    request: Request,
    status: int,
    detail,
    *,
    code: str | None = None,
    exception_type: str | None = None,
) -> dict:
    """Build safe diagnostic metadata for the UI and local error log."""
    reference = uuid.uuid4().hex[:12]
    diagnostic = {
        "reference": reference,
        "code": code or f"http_{status}",
        "status": status,
        "message": detail_message(detail),
        "function": request_function(request),
        "method": request.method,
        "path": request.url.path,
        "timestamp": datetime.now().astimezone().isoformat(),
        "log_file": str(ERROR_LOG_PATH.relative_to(ROOT)),
    }
    if exception_type:
        diagnostic["exception_type"] = exception_type
    if isinstance(detail, dict):
        for key in ("recoverable", "latest_saved_at"):
            if key in detail:
                diagnostic[key] = detail[key]
    return diagnostic


def api_error_response(
    request: Request,
    status: int,
    detail,
    *,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return a backward-compatible API error with structured diagnostics."""
    diagnostic = error_diagnostic(request, status, detail, code=code)
    logger.warning(
        "[%s] %s %s failed in %s with %s (%s): %s",
        diagnostic["reference"],
        request.method,
        request.url.path,
        diagnostic["function"],
        status,
        diagnostic["code"],
        diagnostic["message"],
    )
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "error": diagnostic},
        headers={**(headers or {}), "X-VulnReport-Error": diagnostic["reference"]},
    )


def stale_report_detail(report_id: str) -> dict:
    """Describe a stale write and expose only the revision needed for recovery."""
    try:
        latest_saved_at = workspace.load(report_id).saved_at.isoformat()
    except (FileNotFoundError, OSError, ValueError, ValidationError):
        latest_saved_at = None
    return {
        "message": STALE_REPORT_DETAIL,
        "code": "stale_report",
        "recoverable": latest_saved_at is not None,
        "latest_saved_at": latest_saved_at,
    }


def configured_limit(name: str, default: int) -> int:
    """Read a positive integer limit without making startup depend on valid env input."""
    try:
        value = int(os.environ.get(name, default))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


MAX_JSON_IMPORT_BYTES = configured_limit("VULNREPORT_MAX_JSON_BYTES", 10 * 1024 * 1024)
MAX_BUNDLE_BYTES = configured_limit("VULNREPORT_MAX_BUNDLE_BYTES", 100 * 1024 * 1024)
MAX_BUNDLE_UNCOMPRESSED_BYTES = configured_limit("VULNREPORT_MAX_EXPANDED_BUNDLE_BYTES", 250 * 1024 * 1024)
MAX_BUNDLE_FILES = configured_limit("VULNREPORT_MAX_BUNDLE_FILES", 1000)
MAX_IMAGE_BYTES = configured_limit("VULNREPORT_MAX_IMAGE_BYTES", 20 * 1024 * 1024)
MAX_IMAGE_PIXELS = configured_limit("VULNREPORT_MAX_IMAGE_PIXELS", 40_000_000)
MAX_REPORT_EVIDENCE_BYTES = configured_limit("VULNREPORT_MAX_REPORT_EVIDENCE_BYTES", 250 * 1024 * 1024)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException):
    """Return a navigable 404 page for browser requests and JSON for APIs."""
    accepts_html = "text/html" in request.headers.get("accept", "")
    if error.status_code == 404 and request.method == "GET" and accepts_html:
        return HTMLResponse("<!doctype html><title>Report not found</title><main><h1>This report no longer exists.</h1><p>It may have been deleted. Folder renames are safe, but deletions are not.</p><p><a href=\"/\">Return to local reports</a></p></main>", status_code=404)
    if error.status_code == 422 and request.method == "GET" and accepts_html:
        return HTMLResponse(f"<!doctype html><title>Report needs repair</title><main><h1>This report cannot be opened yet.</h1><p>{error.detail}</p><p><a href=\"/\">Return to local reports</a></p></main>", status_code=422)
    code = error.detail.get("code") if isinstance(error.detail, dict) else None
    return api_error_response(request, error.status_code, error.detail, code=code, headers=error.headers)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, error: Exception):
    """Log unexpected faults without exposing a traceback to the tester."""
    diagnostic = error_diagnostic(
        request,
        500,
        "Unexpected server error",
        code="unexpected_error",
        exception_type=type(error).__name__,
    )
    logger.exception(
        "[%s] Unexpected error in %s for %s %s",
        diagnostic["reference"],
        diagnostic["function"],
        request.method,
        request.url.path,
        exc_info=error,
    )
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return HTMLResponse(f"<!doctype html><title>Unexpected error</title><main><h1>Something went wrong.</h1><p>Reference: {diagnostic['reference']}</p><p>Function: {diagnostic['function']}</p><p>The full error was written to {diagnostic['log_file']}.</p><p><a href=\"/\">Return to local reports</a></p></main>", status_code=500)
    return JSONResponse(
        status_code=500,
        content={"detail": "Unexpected error. Check the application log for details.", "error": diagnostic},
        headers={"X-VulnReport-Error": diagnostic["reference"]},
    )


def report_or_404(report_id: str) -> Report:
    """Load a report or convert a missing draft into an HTTP 404 response."""
    try:
        return workspace.load(report_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    except (OSError, ValueError, ValidationError) as error:
        raise HTTPException(422, "The draft is invalid. Return to the report manager to review available repair actions.") from error


def decode_json_object(contents: bytes) -> dict:
    """Decode a JSON object outside the event loop."""
    try:
        payload = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(422, "Request body must be valid JSON") from error
    if not isinstance(payload, dict):
        raise HTTPException(422, "Request body must be a JSON object")
    return payload


async def read_json_object(request: Request) -> dict:
    """Read a request body asynchronously and decode it in the worker pool."""
    try:
        contents = await request.body()
    except ClientDisconnect as error:
        raise HTTPException(400, "Request body was interrupted") from error
    return await run_in_threadpool(decode_json_object, contents)


def provision_report(report: Report) -> None:
    """Apply server-owned finding defaults outside the event loop."""
    for vulnerability in report.vulnerabilities:
        provision(vulnerability)
        sync_evidence_image_slots(vulnerability, report)


def expected_revision(request: Request, fallback: datetime) -> datetime:
    """Read an optional mutation revision header, defaulting to the loaded report."""
    value = request.headers.get("x-report-saved-at")
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(422, "Invalid report revision") from error


def save_if_current(report: Report, expected_saved_at: datetime) -> Path:
    """Persist a report or expose a consistent stale-write response."""
    try:
        return workspace.save_if_current(report, expected_saved_at)
    except StaleReportError as error:
        raise HTTPException(409, stale_report_detail(report.report_id)) from error


def safe_upload_name(value: str | None) -> str:
    """Normalize an untrusted upload name for display-only metadata."""
    name = Path((value or "image").replace("\\", "/")).name
    cleaned = "".join(character for character in name if character.isprintable()).strip()
    return cleaned[:255] or "image"


async def read_upload_limited(file: UploadFile, limit: int, label: str) -> bytes:
    """Read at most one byte beyond an upload limit so oversized input is rejected."""
    contents = await file.read(limit + 1)
    if len(contents) > limit:
        raise HTTPException(413, f"{label} exceeds the {limit // (1024 * 1024)} MB limit")
    return contents


def is_report_docx(contents: bytes) -> bool:
    """A .docx is itself a ZIP, so without this the bundle branch claims it and dies on a missing
    draft.json. No bundle can hold this name: set equality already limits one to draft.json plus
    evidence PNGs."""
    if not zipfile.is_zipfile(io.BytesIO(contents)):
        return False
    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if sum(info.file_size for info in infos) > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise HTTPException(413, "Expanded report bundle exceeds the 250 MB limit")
        return any(info.filename == "word/document.xml" for info in infos)


def _unreadable_upload(contents: bytes) -> str | None:
    """Name what was picked, because the JSON branch is the fallback for every non-ZIP and its
    decoder error ("Expecting value: line 1 column 1") tells a tester nothing about their PDF."""
    if not contents.strip():
        return "the file is empty"
    if contents[:5] == b"%PDF-":
        return "this is a PDF, and only a report DOCX can be read back"
    if contents.lstrip()[:1] not in (b"{", b"["):
        return "this is not a VulnReport ZIP, a JSON draft, or a report DOCX"
    return None


def parse_import(contents: bytes) -> tuple[dict, dict[str, bytes]]:
    """Parse a legacy JSON draft or a bounded ZIP bundle with verified evidence."""
    if not zipfile.is_zipfile(io.BytesIO(contents)):
        if unreadable := _unreadable_upload(contents):
            raise ValueError(unreadable)
        if len(contents) > MAX_JSON_IMPORT_BYTES:
            raise HTTPException(413, "JSON report exceeds the 10 MB limit")
        payload = json.loads(contents.decode("utf-8"))
        report = Report.model_validate(payload)
        if report.evidence:
            raise ValueError("Reports with evidence must be imported from a VulnReport ZIP bundle")
        return payload, {}

    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(infos) > MAX_BUNDLE_FILES:
            raise ValueError("Report bundle contains too many files")
        if len(names) != len(set(names)):
            raise ValueError("Report bundle contains duplicate paths")
        if "draft.json" not in names:
            raise ValueError("this ZIP is neither a VulnReport bundle nor a report DOCX")
        if any(info.flag_bits & 1 for info in infos):
            raise ValueError("Encrypted report bundles are not supported")
        if sum(info.file_size for info in infos) > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise HTTPException(413, "Expanded report bundle exceeds the 250 MB limit")
        draft_info = archive.getinfo("draft.json")
        if draft_info.file_size > MAX_JSON_IMPORT_BYTES:
            raise HTTPException(413, "JSON report exceeds the 10 MB limit")
        payload = json.loads(archive.read(draft_info).decode("utf-8"))
        report = Report.model_validate(payload)
        expected_files = {evidence.file for evidence in report.evidence.values()}
        if set(names) - {"draft.json"} != expected_files:
            raise ValueError("Report bundle evidence does not match draft metadata")
        files = {}
        for evidence in report.evidence.values():
            info = archive.getinfo(evidence.file)
            if info.file_size > MAX_IMAGE_BYTES:
                raise HTTPException(413, "An evidence image exceeds the 20 MB limit")
            image_bytes = archive.read(info)
            if hashlib.sha256(image_bytes).hexdigest() != evidence.sha256:
                raise ValueError(f"Evidence hash does not match: {evidence.file}")
            try:
                with Image.open(io.BytesIO(image_bytes)) as image:
                    if image.format != "PNG" or image.size != (evidence.width_px, evidence.height_px):
                        raise ValueError(f"Evidence metadata does not match: {evidence.file}")
                    if image.width * image.height > MAX_IMAGE_PIXELS:
                        raise HTTPException(413, "An evidence image exceeds the pixel limit")
                    image.verify()
            except Image.DecompressionBombError as error:
                raise HTTPException(413, "An evidence image exceeds the pixel limit") from error
            files[evidence.file] = image_bytes
        return payload, files


def normalize_uploaded_image(source: bytes) -> tuple[bytes, int, int]:
    """Validate and normalize an uploaded image outside the event loop."""
    with Image.open(io.BytesIO(source)) as candidate:
        if candidate.width * candidate.height > MAX_IMAGE_PIXELS:
            raise HTTPException(413, "Image exceeds the pixel limit")
        candidate.verify()
    with Image.open(io.BytesIO(source)) as candidate:
        image = ImageOps.exif_transpose(candidate).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    width, height = image.size
    image.close()
    contents = output.getvalue()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Normalized image exceeds the 20 MB limit")
    return contents, width, height


def persist_uploaded_evidence(
    report: Report,
    report_id: str,
    original_name: str | None,
    contents: bytes,
    width: int,
    height: int,
    expected_saved_at: datetime,
) -> tuple[str, EvidenceItem]:
    """Write normalized evidence and its report metadata as one recoverable operation."""
    evidence_id = f"ev_{uuid.uuid4().hex[:12]}"
    relative_file = f"evidence/{evidence_id}.png"
    evidence = EvidenceItem(
        file=relative_file,
        original_name=safe_upload_name(original_name),
        width_px=width,
        height_px=height,
        sha256=hashlib.sha256(contents).hexdigest(),
        uploaded_at=datetime.now().astimezone(),
    )
    report.evidence[evidence_id] = evidence
    try:
        workspace.save_evidence_if_current(
            report,
            expected_saved_at,
            relative_file,
            contents,
            MAX_REPORT_EVIDENCE_BYTES,
        )
    except ValueError as error:
        if "configured limit" in str(error):
            raise HTTPException(413, "Report evidence exceeds the 250 MB limit") from error
        raise
    return evidence_id, evidence


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Render the side-effect-free landing page."""
    return templates.TemplateResponse(request, "home.html")


@app.get("/new")
def new_report():
    """Create a blank report draft and redirect the tester to setup."""
    report = workspace.create_report()
    return RedirectResponse(f"/reports/{report.report_id}/setup", status_code=303)


@app.get("/reports")
def list_reports(request: Request):
    """Return report JSON to clients or direct browser visits to the manager."""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/", status_code=303)
    return [
        {
            "report_id": report.report_id,
            "app_name": report.engagement.app_name or "Untitled report",
            # Grouped by the live name rather than the folder, so a rename is right immediately and
            # folder drift never shows.
            "app_folder": report.engagement.app_name.strip() or "Unassigned",
            "saved_at": report.saved_at.isoformat(),
            "finding_count": len(report.vulnerabilities),
        }
        for report in workspace.list_reports()
    ]


@app.get("/reports/legacy")
def list_legacy_reports():
    """List invalid local drafts and whether their duplicate IDs can be repaired."""
    return workspace.list_legacy_reports()


@app.get("/reports/{report_id}/export")
def export_report(report_id: str):
    """Download one validated report and its evidence as a portable ZIP bundle."""
    try:
        report, evidence_files = workspace.export_bundle(report_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("draft.json", json.dumps(report.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n")
        for relative_file, contents in sorted(evidence_files.items()):
            archive.writestr(relative_file, contents)
    filename = report_export_filename(report)
    return Response(content=output.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/reports/{report_id}/generate")
def generate_report(report_id: str):
    """Render and download a complete report through the canonical Word template."""
    report, _, contents, _ = finalized_report(report_id)
    filename = report_export_filename(report, ".docx")
    return Response(
        content=contents,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/reports/{report_id}/generate")
def generate_report_to_folder(report_id: str):
    """Render and save a complete report into the shared generated folder."""
    report, _, _, output_path = finalized_report(report_id, save_to_folder=True)
    return {"filename": output_path.name, "path": str(output_path), "folder": str(GENERATED)}


def finalized_report(report_id: str, *, save_to_folder: bool = False) -> tuple[Report, Path, bytes, Path]:
    """Validate and Word-finalize one stored report."""
    try:
        with workspace.locked_report(report_id) as (report, draft_path):
            issues = generation_issues(report)
            if issues:
                raise HTTPException(422, {"message": "Complete the report before generating it", "issues": issues})
            contents = render_report_docx(
                report,
                ROOT / "resources" / "MAIN_TEST.docx",
                draft_path.parent,
                validation_issues=issues,
            )
            contents = update_docx_bytes_with_word(contents)
            output_path = GENERATED / report_export_filename(report, ".docx")
            if save_to_folder:
                GENERATED.mkdir(parents=True, exist_ok=True)
                output_path = unused_export_path(output_path)
                atomic_write_bytes(output_path, contents)
            return report, draft_path.parent, contents, output_path
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    except (ReportGenerationError, RuntimeError) as error:
        raise HTTPException(422, str(error)) from error


def unused_export_path(path: Path) -> Path:
    """Number repeat exports so regenerating never overwrites an earlier report."""
    candidate = path
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        counter += 1
    return candidate


@app.get("/reports/{report_id}")
def open_report(report_id: str):
    """Send a direct report URL to Setup or show the standard missing-report page."""
    report_or_404(report_id)
    return RedirectResponse(f"/reports/{report_id}/setup", status_code=303)


@app.post("/reports/import")
async def import_report(file: UploadFile = File(...)):
    """Validate a JSON draft, a ZIP bundle, or a report this app generated, and save it separately."""
    try:
        contents = await read_upload_limited(file, MAX_BUNDLE_BYTES, "Report bundle")
        if await run_in_threadpool(is_report_docx, contents):
            payload, images, summary = await run_in_threadpool(parse_report_docx, contents)
            evidence_files = {f"evidence/{evidence_id}.png": data for evidence_id, data in images.items()}
            report = await run_in_threadpool(workspace.import_report, payload, evidence_files)
            return {"report_id": report.report_id, "source": "docx", "summary": summary}
        payload, evidence_files = await run_in_threadpool(parse_import, contents)
        report = await run_in_threadpool(workspace.import_report, payload, evidence_files)
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, UnidentifiedImageError, OSError, ValidationError, ValueError) as error:
        raise HTTPException(422, f"Select a valid VulnReport export: {error}") from error
    return {"report_id": report.report_id, "source": "bundle"}


@app.delete("/reports/{report_id}")
def delete_report(report_id: str):
    """Permanently remove one local report and its evidence files."""
    try:
        workspace.delete(report_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    return {"deleted": report_id}


@app.post("/reports/{report_id}/duplicate")
def duplicate_report(report_id: str):
    """Create a separately editable copy of a local report and its evidence."""
    try:
        report = workspace.duplicate(report_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"report_id": report.report_id}


@app.post("/reports/{report_id}/repair")
def repair_report(report_id: str):
    """Repair duplicate fragment IDs in an otherwise valid legacy draft."""
    try:
        report = workspace.repair_duplicate_fragment_ids(report_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Report not found") from error
    except (ValidationError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return {"report_id": report.report_id}


@app.patch("/reports/{report_id}/name")
async def rename_report(report_id: str, request: Request):
    """Rename the application label shown in the report manager."""
    report = await run_in_threadpool(report_or_404, report_id)
    name = (await read_json_object(request)).get("app_name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(422, "Enter an application name")
    name = name.strip()
    if issue := invalid_character_issue("Application name", name, "-:()"):
        raise HTTPException(422, issue)
    report.engagement.app_name = name
    if report.app_id == "unnamed":
        report.app_id = app_id_for(report.engagement)
    await run_in_threadpool(save_if_current, report, expected_revision(request, report.saved_at))
    return {"report_id": report.report_id, "app_name": report.engagement.app_name}


@app.get("/reports/{report_id}/setup", response_class=HTMLResponse)
def setup(request: Request, report_id: str):
    """Render the engagement metadata and scope-target setup page."""
    report = report_or_404(report_id)
    return templates.TemplateResponse(request, "page1_setup.html", {"report": report.model_dump(mode="json", by_alias=True), "library": library.entries})


@app.get("/reports/{report_id}/findings", response_class=HTMLResponse)
def findings(request: Request, report_id: str):
    """Render the findings register with the offline vulnerability library."""
    report = report_or_404(report_id)
    if not setup_is_complete(report):
        return RedirectResponse(f"/reports/{report_id}/setup?incomplete=setup", status_code=303)
    return templates.TemplateResponse(request, "page2_findings.html", {"report": report.model_dump(mode="json", by_alias=True), "library": library.entries})


@app.get("/reports/{report_id}/edit", response_class=HTMLResponse)
def edit(request: Request, report_id: str):
    """Render the content editor with the offline vulnerability library."""
    report = report_or_404(report_id)
    if not setup_is_complete(report):
        return RedirectResponse(f"/reports/{report_id}/setup?incomplete=setup", status_code=303)
    if not report.vulnerabilities or not all(finding_is_complete(vulnerability, report) for vulnerability in report.vulnerabilities):
        return RedirectResponse(f"/reports/{report_id}/findings?incomplete=findings", status_code=303)
    return templates.TemplateResponse(request, "page2_editor.html", {"report": report.model_dump(mode="json", by_alias=True), "library_entries": library.entries})


@app.put("/reports/{report_id}")
async def save_report(report_id: str, request: Request):
    """Validate, provision, and atomically save the browser's current report draft."""
    prior = await run_in_threadpool(report_or_404, report_id)
    payload = await read_json_object(request)
    try:
        client_saved_at = datetime.fromisoformat(payload.get("saved_at", ""))
    except (TypeError, ValueError):
        client_saved_at = None
    if client_saved_at and client_saved_at != prior.saved_at:
        detail = await run_in_threadpool(stale_report_detail, report_id)
        return api_error_response(
            request,
            409,
            detail,
            code="stale_report",
        )
    try:
        removed_references = await run_in_threadpool(reconcile_targets, payload, prior)
    except ValueError as error:
        return api_error_response(request, 422, str(error), code="invalid_scope")
    if removed_references:
        names = ", ".join(removed_references)
        return api_error_response(
            request,
            422,
            f"Restore the removed scope target or give another affected location to: {names}.",
            code="referenced_scope_removed",
        )
    payload["report_id"] = report_id
    payload["app_id"] = prior.app_id
    # After reconcile_targets, so a legacy finding resolves against the targets this save just
    # wrote rather than the ones it replaced.
    normalise_scope_modes(payload)
    try:
        report = await run_in_threadpool(Report.model_validate, payload)
    except ValidationError as error:
        return api_error_response(request, 422, error.errors(include_context=False), code="invalid_report")
    input_issues = await run_in_threadpool(setup_input_issues, report.engagement)
    if input_issues:
        return api_error_response(
            request,
            422,
            {"message": "Correct the invalid Setup fields", "issues": input_issues},
            code="invalid_setup",
        )
    if report.app_id == "unnamed":
        report.app_id = app_id_for(report.engagement)
    await run_in_threadpool(provision_report, report)
    try:
        path = await run_in_threadpool(workspace.save_if_current, report, client_saved_at or prior.saved_at)
    except StaleReportError:
        detail = await run_in_threadpool(stale_report_detail, report_id)
        return api_error_response(
            request,
            409,
            detail,
            code="stale_report",
        )
    response_report = await run_in_threadpool(lambda: report.model_dump(mode="json", by_alias=True))
    return {"saved_at": report.saved_at.isoformat(), "path": str(path), "report": response_report}


@app.get("/library/search")
def search_library(q: str = ""):
    """Return vulnerability-library entries matching a title or tag query."""
    return library.search(q)


@app.post("/reports/{report_id}/library/{library_id}")
def insert_library(request: Request, report_id: str, library_id: str):
    """Copy one library entry into a report as a newly provisioned finding."""
    report = report_or_404(report_id)
    entry = library.get(library_id)
    if entry is None:
        raise HTTPException(404, "Library entry not found")
    # Scope defaults to "all", which would read as a deliberate every-target choice and let the
    # finding past the affected-location gate before the tester has picked anything.
    vulnerability = Vulnerability(uid=f"v_{uuid.uuid4().hex[:8]}", title=entry["title"], likelihood=entry.get("default_likelihood"), impact=entry.get("default_impact"), severity=entry.get("default_severity") or "informational", scope=Scope(mode="custom"), library_ref=LibraryRef(library_id=entry["library_id"], source_id=entry["source_id"], inserted_at=datetime.now().astimezone()), contents=copy.deepcopy(entry.get("contents", [])))
    # This finding *is* the entry, so the Content page must not offer to install what it already
    # holds. Only the sections actually copied are answered; the rest still get their offer.
    vulnerability.content_offer_resolved = {content.type: entry["library_id"] for content in vulnerability.contents}
    assign_fresh_fragment_ids(vulnerability)
    provision(vulnerability)
    report.vulnerabilities.append(vulnerability)
    sync_evidence_image_slots(vulnerability, report)
    variants = applicable_poc_variants(vulnerability, report, entry.get("proof_of_concept"))
    # Several applicable app types is the tester's choice to make on the Content page, not ours.
    if len(variants) == 1:
        steps = (entry.get("proof_of_concept") or {})[variants[0]]
        # The entry is a plain dict, so let Content parse the raw steps back into fragment models.
        apply_poc_variant(vulnerability, Content(type="proof_of_concept", fragments=steps).fragments, variants)
    save_if_current(report, expected_revision(request, report.saved_at))
    return {
        "saved_at": report.saved_at.isoformat(),
        "finding": vulnerability.model_dump(mode="json"),
    }


@app.post("/reports/{report_id}/evidence")
async def upload_evidence(request: Request, report_id: str, file: UploadFile = File(...)):
    """Validate, normalize, store, and register an uploaded evidence image."""
    report = await run_in_threadpool(report_or_404, report_id)
    try:
        source = await read_upload_limited(file, MAX_IMAGE_BYTES, "Image")
        contents, width, height = await run_in_threadpool(normalize_uploaded_image, source)
    except Image.DecompressionBombError as error:
        raise HTTPException(413, "Image exceeds the pixel limit") from error
    except (SyntaxError, UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(400, "Upload a valid image file") from error
    evidence_id, evidence = await run_in_threadpool(
        persist_uploaded_evidence,
        report,
        report_id,
        file.filename,
        contents,
        width,
        height,
        expected_revision(request, report.saved_at),
    )
    return {
        "saved_at": report.saved_at.isoformat(),
        "evidence": {"evidence_id": evidence_id, **evidence.model_dump(mode="json")},
    }


@app.get("/reports/{report_id}/evidence/{evidence_id}")
def get_evidence(report_id: str, evidence_id: str):
    """Safely serve one normalized evidence image belonging to a report."""
    report = report_or_404(report_id)
    evidence = report.evidence.get(evidence_id)
    if evidence is None:
        raise HTTPException(404, "Evidence not found")
    draft_path = workspace.find_path(report_id)
    if draft_path is None:
        raise HTTPException(404, "Report not found")
    evidence_root = (draft_path.parent / "evidence").resolve()
    file_path = (draft_path.parent / evidence.file).resolve()
    if not file_path.is_file() or file_path.parent != evidence_root:
        raise HTTPException(404, "Evidence file not found")
    return FileResponse(file_path, media_type="image/png")


# Authoring tool, deliberately untracked and off by default. Absent in a fresh clone by design.
if os.environ.get("VULNREPORT_LIBRARY_EDITOR") and (Path(__file__).parent / "library_editor.py").is_file():
    from .library_editor import register as register_library_editor

    def _rebind_library() -> None:
        global library
        library = Library.load_or_empty(configured_library)

    register_library_editor(app, configured_library, _rebind_library)
