"""Print the unittest targets worth running for the current working-tree changes.

Usage:
    .venv/bin/python scripts/relevant_tests.py            # what changed vs HEAD
    .venv/bin/python scripts/relevant_tests.py --run      # ...and run them

The point is to remove the judgement call. The scope map in .github/copilot-instructions.md
describes the same rules in prose, and prose is easy to skip when a full run feels safer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROWSER = "tests.test_browser"
APP = "tests.test_app"
DOCX = ["tests.test_docx", "tests.test_docx_components", "tests.test_docx_captions", "tests.test_docx_import"]

# Ordered: the first matching prefix wins, so put the specific paths above the general ones.
RULES: list[tuple[str, list[str]]] = [
    ("docs/", []),
    (".github/", []),
    (".claude/", []),
    ("scripts/", []),
    ("app/web/static/", [BROWSER]),
    ("app/web/templates/", [BROWSER]),
    # These four own rules with JavaScript twins, so the browser contract tests are part of the scope.
    ("app/models.py", [APP, BROWSER]),
    ("app/report_service.py", [APP, BROWSER]),
    ("app/workspace.py", [APP, "tests.test_storage"]),
    ("app/storage.py", [APP, "tests.test_storage"]),
    ("app/docx_", DOCX),
    ("resources/", DOCX),
    ("app/main.py", [APP]),
    ("app/", [APP]),
]


def changed_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return sorted({line for line in (out + untracked).splitlines() if line.strip()})


def targets_for(paths: list[str]) -> tuple[list[str], list[str]]:
    targets: set[str] = set()
    unmatched: list[str] = []
    for path in paths:
        if path.startswith("tests/") and path.endswith(".py"):
            targets.add("tests." + Path(path).stem)
            continue
        for prefix, rule_targets in RULES:
            if path.startswith(prefix):
                targets.update(rule_targets)
                break
        else:
            unmatched.append(path)
    return sorted(targets), unmatched


def main() -> int:
    paths = changed_files()
    if not paths:
        print("Tests: none — working tree is clean.")
        return 0
    targets, unmatched = targets_for(paths)

    print(f"Changed ({len(paths)}):")
    for path in paths:
        print(f"  {path}")
    if unmatched:
        print("\nNo rule for these — decide by hand:")
        for path in unmatched:
            print(f"  {path}")
    if not targets:
        print("\nTests: none — nothing changed that a test asserts on.")
        return 0

    print(f"\nTests: {' '.join(targets)}")
    command = [".venv/bin/python", "-m", "unittest", *targets]
    print("  " + " ".join(command))
    if "--run" in sys.argv:
        return subprocess.run(command, cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
