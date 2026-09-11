from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from app.models import Engagement, FolderHint, Report
from .storage import atomic_write_bytes, atomic_write_json, read_json

INVALID_NAME = re.compile(r'[<>:"/\\|?*]+')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{index}" for index in range(1, 10)), *(f"LPT{index}" for index in range(1, 10))}


class StaleReportError(RuntimeError):
    """Raised when a report changed after a caller loaded its revision."""


def safe_name(value: str, fallback: str) -> str:
    """Convert a user-provided name into a Windows-safe folder-name segment."""
    cleaned = re.sub(r"\s+", "_", INVALID_NAME.sub("", value).strip(". "))[:60]
    reserved_stem = cleaned.split(".", 1)[0].upper()
    return fallback if not cleaned or reserved_stem in RESERVED else cleaned


def app_id_for(engagement: Engagement) -> str:
    """Derive the application folder identity from CI, BSN, or application name."""
    return safe_name(engagement.ci_number or engagement.bsn_number or engagement.app_name, "unnamed")


class Workspace:
    def __init__(self, root: Path, tester: str) -> None:
        """Remember the data root and default tester used for new report drafts."""
        self.apps_root, self.locks_root, self.tester = root / "apps", root / ".locks", tester
        self._report_locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._lock_depths = threading.local()

    def _lock_for(self, report_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._report_locks.setdefault(report_id, threading.RLock())

    @contextmanager
    def _locked(self, report_id: str):
        """Serialize access to one report across threads and app processes."""
        with self._lock_for(report_id):
            depths = getattr(self._lock_depths, "values", None)
            if depths is None:
                depths = self._lock_depths.values = {}
            if depths.get(report_id, 0):
                depths[report_id] += 1
                try:
                    yield
                finally:
                    depths[report_id] -= 1
                return
            self.locks_root.mkdir(parents=True, exist_ok=True)
            lock_name = hashlib.sha256(report_id.encode("utf-8")).hexdigest() + ".lock"
            with (self.locks_root / lock_name).open("a+b") as lock_file:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                depths[report_id] = 1
                try:
                    yield
                finally:
                    depths.pop(report_id, None)
                    lock_file.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def create_report(self) -> Report:
        """Create and persist a new blank report draft."""
        now = datetime.now().astimezone()
        report = Report(report_id=f"r_{uuid.uuid4().hex[:12]}", app_id="unnamed", saved_at=now, engagement=Engagement(tester=self.tester, report_date=now.date()))
        self.save(report)
        return report

    def list_reports(self) -> list[Report]:
        """Load valid drafts for the report-management screen, newest first."""
        reports = []
        for path in self.apps_root.glob("*/*/draft.json"):
            try:
                report_id = read_json(path)["report_id"]
                with self._locked(report_id):
                    reports.append(self.load_path(path))
            except (KeyError, OSError, ValueError):
                continue
        return sorted(reports, key=lambda report: report.saved_at, reverse=True)

    def list_legacy_reports(self) -> list[dict[str, str | bool]]:
        """List invalid drafts without allowing them to interrupt report management."""
        invalid = []
        for path in self.apps_root.glob("*/*/draft.json"):
            try:
                report_id = read_json(path)["report_id"]
                with self._locked(report_id):
                    self.load_path(path)
            except (KeyError, OSError, ValueError, ValidationError) as error:
                try:
                    draft = read_json(path)
                    report_id = draft["report_id"]
                except (KeyError, OSError, ValueError):
                    continue
                reason = "; ".join(item["msg"] for item in error.errors()) if isinstance(error, ValidationError) else str(error)
                invalid.append({"report_id": report_id, "reason": reason, "repairable": "duplicate fragment id:" in reason})
        return invalid

    def delete(self, report_id: str) -> None:
        """Delete one report folder and all evidence belonging to that draft."""
        with self._locked(report_id):
            path = self.find_path(report_id)
            if path is None:
                raise FileNotFoundError(report_id)
            app_folder = path.parent.parent
            shutil.rmtree(path.parent)
            if app_folder.is_dir() and not any(app_folder.iterdir()):
                app_folder.rmdir()

    def import_report(self, payload: dict, evidence_files: dict[str, bytes] | None = None) -> Report:
        """Validate and persist an exported report and its optional evidence files."""
        imported = Report.model_validate(payload)
        files = evidence_files or {}
        expected_files = {evidence.file for evidence in imported.evidence.values()}
        if set(files) != expected_files:
            raise ValueError("Evidence files do not match the report metadata")
        now = datetime.now().astimezone()
        imported.report_id = f"r_{uuid.uuid4().hex[:12]}"
        imported.saved_at = now
        imported.folder_name_hint = FolderHint()
        destination = self.save(imported)
        try:
            for relative_file, contents in files.items():
                atomic_write_bytes(destination.parent / relative_file, contents)
        except Exception:
            shutil.rmtree(destination.parent, ignore_errors=True)
            if destination.parent.parent.is_dir() and not any(destination.parent.parent.iterdir()):
                destination.parent.parent.rmdir()
            raise
        return imported

    def export_bundle(self, report_id: str) -> tuple[Report, dict[str, bytes]]:
        """Read one validated report and all of its evidence under one lock."""
        with self._locked(report_id):
            report = self.load(report_id)
            draft_path = self.find_path(report_id)
            if draft_path is None:
                raise FileNotFoundError(report_id)
            evidence_root = (draft_path.parent / "evidence").resolve()
            files = {}
            for evidence in report.evidence.values():
                file_path = (draft_path.parent / evidence.file).resolve()
                if file_path.parent != evidence_root or not file_path.is_file():
                    raise ValueError(f"Evidence file is missing: {evidence.file}")
                files[evidence.file] = file_path.read_bytes()
            return report, files

    def duplicate(self, report_id: str) -> Report:
        """Copy a report and its evidence into a distinct local draft."""
        with self._locked(report_id):
            source_report, evidence_files = self.export_bundle(report_id)
            duplicated = source_report.model_copy(deep=True)
            duplicated.report_id = f"r_{uuid.uuid4().hex[:12]}"
            duplicated.folder_name_hint = FolderHint()
            destination = self.save(duplicated)
            try:
                for relative_file, contents in evidence_files.items():
                    atomic_write_bytes(destination.parent / relative_file, contents)
            except Exception:
                shutil.rmtree(destination.parent, ignore_errors=True)
                if destination.parent.parent.is_dir() and not any(destination.parent.parent.iterdir()):
                    destination.parent.parent.rmdir()
                raise
            return duplicated

    def repair_duplicate_fragment_ids(self, report_id: str) -> Report:
        """Assign fresh IDs only to repeated fragments in an otherwise valid legacy draft."""
        with self._locked(report_id):
            path = self.find_path(report_id)
            if path is None:
                raise FileNotFoundError(report_id)
            draft = read_json(path)
            fragment_ids: set[str] = set()
            repaired = False
            for vulnerability in draft.get("vulnerabilities", []):
                for content in vulnerability.get("contents", []):
                    for fragment in content.get("fragments", []):
                        fragment_id = fragment.get("frag_id")
                        if not isinstance(fragment_id, str):
                            continue
                        if fragment_id in fragment_ids:
                            fragment["frag_id"] = f"f_{uuid.uuid4().hex[:8]}"
                            repaired = True
                        fragment_ids.add(fragment["frag_id"])
            if not repaired:
                raise ValueError("This draft has no duplicate fragment IDs to repair")
            Report.model_validate(draft)
            atomic_write_json(path, draft)
            return self.load(report_id)

    def find_path(self, report_id: str) -> Path | None:
        """Find a draft by its stored identity rather than by its folder name."""
        for path in self.apps_root.glob("*/*/draft.json"):
            try:
                if read_json(path).get("report_id") == report_id:
                    return path
            except (OSError, ValueError):
                continue
        return None

    def load(self, report_id: str) -> Report:
        """Load a report and repair supported legacy draft shapes when encountered."""
        with self._locked(report_id):
            path = self.find_path(report_id)
            if path is None:
                raise FileNotFoundError(report_id)
            return self.load_path(path)

    @contextmanager
    def locked_report(self, report_id: str) -> Iterator[tuple[Report, Path]]:
        """Yield one report and its stable draft path while holding its lock."""
        with self._locked(report_id):
            path = self.find_path(report_id)
            if path is None:
                raise FileNotFoundError(report_id)
            yield self.load_path(path), path

    def load_path(self, path: Path) -> Report:
        """Load a known draft path and repair supported legacy shapes."""
        draft = read_json(path)
        repaired = False
        engagement = draft.setdefault("engagement", {})
        if "test_type" not in engagement:
            legacy_channels = set(engagement.pop("tested_channels", []))
            engagement["test_type"] = "web_api" if {"web", "api"} <= legacy_channels else "api" if "api" in legacy_channels else "mobile" if "mobile" in legacy_channels else "web"
            repaired = True
        for vulnerability in draft.get("vulnerabilities", []):
            for content in vulnerability.get("contents", []):
                for fragment in content.get("fragments", []):
                    if fragment.get("type") in {"numbered_list", "bulleted_list"} and not fragment.get("items"):
                        fragment["items"] = [{"runs": []}]
                        repaired = True
        if repaired:
            atomic_write_json(path, draft)
        return Report.model_validate(draft)

    def save(self, report: Report) -> Path:
        """Place a report in its application folder and atomically persist its draft."""
        with self._locked(report.report_id):
            return self._save_unlocked(report)

    def save_if_current(self, report: Report, expected_saved_at: datetime) -> Path:
        """Save only when the persisted revision still matches the caller's copy."""
        with self._locked(report.report_id):
            current = self.load(report.report_id)
            if current.saved_at != expected_saved_at:
                raise StaleReportError(report.report_id)
            return self._save_unlocked(report)

    def save_evidence_if_current(
        self,
        report: Report,
        expected_saved_at: datetime,
        relative_file: str,
        contents: bytes,
        evidence_limit: int,
    ) -> Path:
        """Write evidence and report metadata under one report lock."""
        with self._locked(report.report_id):
            current = self.load(report.report_id)
            if current.saved_at != expected_saved_at:
                raise StaleReportError(report.report_id)
            draft_path = self.find_path(report.report_id)
            if draft_path is None:
                raise FileNotFoundError(report.report_id)
            evidence_root = draft_path.parent / "evidence"
            existing_bytes = sum(path.stat().st_size for path in evidence_root.glob("*.png")) if evidence_root.is_dir() else 0
            if existing_bytes + len(contents) > evidence_limit:
                raise ValueError("Report evidence exceeds the configured limit")
            original_file = draft_path.parent / relative_file
            atomic_write_bytes(original_file, contents)
            try:
                saved_path = self._save_unlocked(report)
                return saved_path.parent / relative_file
            except Exception:
                original_file.unlink(missing_ok=True)
                current_path = self.find_path(report.report_id)
                if current_path is not None:
                    (current_path.parent / relative_file).unlink(missing_ok=True)
                raise

    def _save_unlocked(self, report: Report) -> Path:
        app_name = safe_name(report.engagement.app_name, "X")
        first_letter = app_name[0].upper() if app_name[0].isascii() and app_name[0].isalpha() else "X"
        existing = self.find_path(report.report_id)
        desired = self.apps_root / f"{first_letter}_{safe_name(report.app_id, 'unnamed')}" / f"{datetime.now():%Y-%m}_Report_{report.report_id[2:]}" / "draft.json"
        path = existing or desired
        if existing and existing.parent.parent.name == "X_unnamed" and report.app_id != "unnamed":
            desired.parent.parent.mkdir(parents=True, exist_ok=True)
            existing.parent.replace(desired.parent)
            path = desired
        report.folder_name_hint = FolderHint(app_folder=path.parent.parent.name, report_folder=path.parent.name)
        now = datetime.now().astimezone()
        report.saved_at = max(now, report.saved_at + timedelta(microseconds=1))
        atomic_write_json(path, report.model_dump(mode="json", by_alias=True))
        return path
