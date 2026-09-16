"""
Local-only vulnerability library editor. Deliberately untracked: it writes the file the app
validates at import, so it never ships. Enable with VULNREPORT_LIBRARY_EDITOR=1 and open
/library-editor. Nothing in tracked code links to it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .library import Library, LibraryDocument

# Only the fragment types the proof-of-concept section already accepts on the Content page.
STEP_TYPE = "numbered_list"


def _document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _steps_to_fragments(lines: list[str], prefix: str) -> list[dict]:
    """One step per line, matching how the Content page renders a numbered list."""
    items = [{"runs": [{"text": line}]} for line in lines if line.strip()]
    return [{"frag_id": f"{prefix}-poc", "type": STEP_TYPE, "items": items}] if items else []


def _fragments_to_steps(fragments: list[dict]) -> list[str]:
    lines = []
    for fragment in fragments:
        for item in fragment.get("items", []):
            lines.append("".join(run.get("text", "") for run in item.get("runs", [])))
    return lines


def register(app, library_path: Path, rebind) -> None:
    """Mount the editor. `rebind` swaps the app's live Library for a freshly loaded one."""

    @app.get("/library-editor", response_class=HTMLResponse)
    def library_editor_page(request: Request):
        document = _document(library_path)
        entries = [
            {
                "library_id": entry["library_id"],
                "title": entry["title"],
                "tags": entry.get("tags", []),
                "default_likelihood": entry.get("default_likelihood"),
                "default_impact": entry.get("default_impact"),
                "default_severity": entry.get("default_severity"),
                "requires_tester_input": entry.get("requires_tester_input", False),
                "status": entry.get("status", "approved"),
                "proof_of_concept": {
                    variant: _fragments_to_steps(fragments)
                    for variant, fragments in (entry.get("proof_of_concept") or {}).items()
                },
            }
            for entry in document["entries"]
        ]
        template = (Path(__file__).parent / "web" / "templates" / "library_editor.html").read_text(encoding="utf-8")
        return HTMLResponse(template.replace("__ENTRIES__", json.dumps(entries)))

    @app.put("/library-editor/entries/{library_id}")
    async def save_entry(library_id: str, request: Request):
        payload = await request.json()
        document = _document(library_path)
        index = next((position for position, entry in enumerate(document["entries"]) if entry["library_id"] == library_id), None)
        if index is None:
            raise HTTPException(404, "Library entry not found")

        entry = document["entries"][index]
        # library_id is the key every saved draft's library_ref points at, so it is never editable.
        for field in ("title", "status"):
            if field in payload:
                entry[field] = payload[field]
        for field in ("default_likelihood", "default_impact", "default_severity"):
            if field in payload:
                entry[field] = payload[field] or None
        if "tags" in payload:
            entry["tags"] = [tag.strip() for tag in payload["tags"] if tag.strip()]
        if "requires_tester_input" in payload:
            entry["requires_tester_input"] = bool(payload["requires_tester_input"])
        if "proof_of_concept" in payload:
            variants = {}
            for variant, lines in payload["proof_of_concept"].items():
                fragments = _steps_to_fragments(lines, f"{library_id}-{variant}")
                if fragments:
                    variants[variant] = fragments
            # Drop the key when nothing is left, so clearing every box restores the original shape.
            if variants:
                entry["proof_of_concept"] = variants
            else:
                entry.pop("proof_of_concept", None)

        document["entry_count"] = len(document["entries"])
        _write_validated(document, library_path, rebind)
        return {"saved": library_id}

    @app.post("/library-editor/entries")
    async def create_entry(request: Request):
        payload = await request.json()
        library_id = (payload.get("library_id") or "").strip()
        if not library_id:
            raise HTTPException(422, "library_id is required")
        document = _document(library_path)
        if any(entry["library_id"] == library_id for entry in document["entries"]):
            raise HTTPException(422, f"{library_id} already exists")
        document["entries"].append({
            "library_id": library_id,
            "source_id": payload.get("source_id") or library_id,
            "title": (payload.get("title") or "").strip() or library_id,
            "tags": [],
            "default_likelihood": None,
            "default_impact": None,
            "default_severity": None,
            "requires_tester_input": False,
            "status": "approved",
            "contents": [],
            "proof_of_concept": {},
        })
        document["entries"].sort(key=lambda entry: entry["title"].casefold())
        document["entry_count"] = len(document["entries"])
        _write_validated(document, library_path, rebind)
        return {"created": library_id}


def _write_validated(document: dict, library_path: Path, rebind) -> None:
    """Validate the exact bytes that will land on disk, then promote them atomically."""
    try:
        LibraryDocument.model_validate(document)
    except ValueError as error:
        raise HTTPException(422, f"Library would not load: {error}") from error

    payload = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{library_path.name}.", suffix=".tmp", dir=library_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        # The boot path, run against the real bytes, so a file that would not start the app never replaces the good one.
        Library(temporary)
        os.replace(temporary, library_path)
    except ValueError as error:
        raise HTTPException(422, f"Library would not load: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    rebind()
