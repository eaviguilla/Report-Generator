"""Generate the Claude Code rules in .claude/rules/ from the Copilot instructions in .github/instructions/.

The .github files are the source. Edit one, then run

    py -3 scripts/sync_ai_rules.py           # rewrite .claude/rules/ (python3 on macOS)
    py -3 scripts/sync_ai_rules.py --check   # list what differs and exit 1; tests/test_ai_rules_sync.py does this

Each `applyTo` glob list becomes a `paths` list and the body is copied unchanged. A comment under the
frontmatter names the source; Claude Code strips it before the rule reaches the model. A rule in
.claude/rules/ without that comment is hand-written and left alone.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(".github/instructions")
RULES = Path(".claude/rules")
SUFFIX = ".instructions.md"
MARK = "<!-- Generated from "
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
APPLY_TO = re.compile(r'^applyTo:\s*"?(.*?)"?\s*$', re.MULTILINE)


def render(name: str, text: str) -> str:
    """The Claude rule for one instruction file. `name` is its file name, for the header comment."""
    match = FRONTMATTER.match(text.replace("\r\n", "\n"))
    found = APPLY_TO.search(match[1]) if match else None
    globs = [glob.strip() for glob in found[1].split(",") if glob.strip()] if found else []
    if not globs:
        raise ValueError(f"{name} needs frontmatter with an applyTo list")
    paths = "".join(f'  - "{glob}"\n' for glob in globs)
    header = f"{MARK}{SOURCES.as_posix()}/{name}. Edit that file, not this one. -->"
    body = match[2].strip("\n")
    return f"---\npaths:\n{paths}---\n{header}\n\n{body}\n"


def expected(root: Path = ROOT) -> dict[Path, str]:
    """Every generated rule the instruction files call for, keyed by its path under `root`."""
    return {
        RULES / f"{source.name[: -len(SUFFIX)]}.md": render(source.name, source.read_text(encoding="utf-8"))
        for source in sorted((root / SOURCES).glob(f"*{SUFFIX}"))
    }


def current(path: Path) -> str | None:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None


def orphans(root: Path, wanted: dict[Path, str]) -> list[Path]:
    """Generated rules whose instruction file is gone."""
    return [
        RULES / found.name
        for found in sorted((root / RULES).glob("*.md"))
        if RULES / found.name not in wanted and MARK in found.read_text(encoding="utf-8")
    ]


def drift(root: Path = ROOT) -> list[str]:
    """What differs between the rules and the instructions; empty when they are in sync."""
    wanted = expected(root)
    problems = []
    for path, text in wanted.items():
        found = current(root / path)
        if found is None:
            problems.append(f"missing {path.as_posix()}")
        elif found != text:
            problems.append(f"out of date {path.as_posix()}")
    problems += [f"orphaned {path.as_posix()}, its instruction file is gone" for path in orphans(root, wanted)]
    return problems


def write(root: Path = ROOT) -> list[str]:
    """Make the rules match the instructions. Returns the paths it wrote or removed."""
    wanted = expected(root)
    touched = []
    (root / RULES).mkdir(parents=True, exist_ok=True)
    for path, text in wanted.items():
        if current(root / path) != text:
            with open(root / path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            touched.append(path.as_posix())
    for path in orphans(root, wanted):
        (root / path).unlink()
        touched.append(path.as_posix())
    return touched


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate .claude/rules/ from .github/instructions/.")
    parser.add_argument("--check", action="store_true", help="list differences and exit 1 instead of writing")
    args = parser.parse_args(argv)
    if args.check:
        problems = drift()
        print("\n".join(problems) if problems else "in sync")
        return 1 if problems else 0
    touched = write()
    print("\n".join(f"wrote {path}" for path in touched) if touched else "already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
