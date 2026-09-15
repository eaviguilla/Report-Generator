"""Build a clean, user-facing release zip: no git, no dev tooling, no dev data.

Usage:
    .venv/bin/python scripts/package_release.py [name]

Copies only the runtime-required files into a staging folder, zips it, and
writes the result to dist/<name>.zip (dist/ is a build output, gitignored).
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Everything a tester's machine needs to run the app. Anything not listed here
# (tests/, scripts/, docs/, .git, .claude, graphify-out, requirements-dev.txt,
# data/, generated/, ...) is dev-only and left behind.
INCLUDE_FILES = ["run.py", "requirements.txt", "README.md"]
INCLUDE_DIRS = ["app", "resources"]

# Dev-only files that live inside an otherwise-shipped directory.
EXCLUDE_RELATIVE = {
    Path("app/library_editor.py"),
    Path("app/web/templates/library_editor.html"),
    Path("resources/fixtures"),
    Path("resources/report-name.docx"),
}
EXCLUDE_NAMES = {"__pycache__", ".DS_Store"}
EXCLUDE_SUFFIXES = {".pyc"}


def _ignore(directory: str, names: list[str]) -> set[str]:
    current = Path(directory)
    ignored = set()
    for name in names:
        candidate = current / name
        relative = candidate.relative_to(ROOT)
        if name in EXCLUDE_NAMES or candidate.suffix in EXCLUDE_SUFFIXES or relative in EXCLUDE_RELATIVE:
            ignored.add(name)
    return ignored


def build_release(name: str) -> Path:
    staging = DIST / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for filename in INCLUDE_FILES:
        shutil.copy2(ROOT / filename, staging / filename)
    for dirname in INCLUDE_DIRS:
        shutil.copytree(ROOT / dirname, staging / dirname, ignore=_ignore)

    archive = shutil.make_archive(str(DIST / name), "zip", root_dir=DIST, base_dir=name)
    shutil.rmtree(staging)
    return Path(archive)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else f"Report-Generator-{date.today():%Y-%m-%d}"
    DIST.mkdir(exist_ok=True)
    archive = build_release(name)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
