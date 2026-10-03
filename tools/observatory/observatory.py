#!/usr/bin/env python3
"""Build the observatory, a star map of this repo's work items, and open it in the browser.

    python3 tools/observatory/observatory.py      (macOS and Linux)
    py -3 tools\\observatory\\observatory.py      (Windows)
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import time
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

SCRIPT = Path(__file__).resolve()
HERE = SCRIPT.parent
REPO = HERE.parent.parent
TEMPLATE = HERE / "page.html"
OUTPUT = HERE / "observatory.html"
DATA_MARK = "/*OBSERVATORY_DATA*/null"
# mattpocock/skills was installed at this commit; items that already existed then get no star.
CUTOFF = "663d12d"

STATUSES = ("needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "in-progress", "done", "wontfix")
FINISHED = ("done", "wontfix")
# Status words from before the seven, still written in plans and wayfinder tickets.
OLD_WORDS = {
    "planning": "needs-info",
    "agreed": "ready-for-agent",
    "in progress": "in-progress",
    "shipped": "done",
    "superseded": "wontfix",
    "abandoned": "wontfix",
    "claimed": "in-progress",
    "resolved": "done",
}
AGENT_TICKET_TYPES = ("research",)
PATTERNS = (".scratch/*/map.md", ".scratch/*/spec.md", ".scratch/*/issues/*.md", "docs/plans/*.md", "docs/adr/*.md", ".out-of-scope/*.md")
DESCRIPTION_SECTIONS = {
    "ticket": ("question",),
    "map": ("destination",),
    "spec": ("problem statement", "summary"),
    "plan": ("request",),
    "issue": ("what to build", "what happens"),
    "review": ("problem", "what to build"),
}
TYPE_WORDS = {"plan": "Plan", "spec": "Spec", "map": "Map"}
HEADER_KEYS = {"status", "type", "blocked by", "map", "from", "merged into", "what to build"}

FIELD = re.compile(r"^\s*(?:>\s*)?(?:\*\*)?(?P<key>[A-Za-z][A-Za-z ]*?)(?::\*\*|\*\*:|:)\s*(?P<value>.*)$")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
STEP = re.compile(r"^\s*\d+[.)]\s+`?/(?P<skill>[A-Za-z0-9][\w:-]*)`?\s*[:\u2014-]\s*(?P<reason>.+)$")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
NOT_PROSE = re.compile(r"^\s*(?:#|>|\||<!--|---|```)")


@dataclass
class Item:
    path: str
    kind: str
    lines: list[str]
    num: str | None = None
    title: str = ""
    short: str = ""
    status: str | None = None
    word: str | None = None
    came_from: dict[str, str] = field(default_factory=dict)
    blocked_by: list[str] = field(default_factory=list)
    merged_into: str | None = None
    warnings: list[str] = field(default_factory=list)


def node_type(rel: str, repo: Path) -> str | None:
    parts = rel.split("/")
    if len(parts) == 2 and parts[0] == ".out-of-scope" and parts[1].endswith(".md"):
        return "out-of-scope"
    if parts[:2] == ["docs", "plans"] and len(parts) == 3:
        return "plan"
    if parts[:2] == ["docs", "adr"] and len(parts) == 3 and re.match(r"\d{4}-", parts[2]):
        return "adr"
    if parts[0] != ".scratch":
        return None
    if len(parts) == 3 and parts[2] in ("map.md", "spec.md"):
        return parts[2][:-3]
    if len(parts) == 4 and parts[2] == "issues" and re.match(r"\d{2}-", parts[3]):
        if parts[1] == "architecture-review":
            return "review"
        return "ticket" if (repo / ".scratch" / parts[1] / "map.md").is_file() else "issue"
    return None


def paths_at_cutoff(repo: Path) -> set[str] | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--name-only", CUTOFF],
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {p.decode("utf-8", "replace") for p in done.stdout.split(b"\0") if p}


def read_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if lines and lines[0].strip() == "---":
        for k in range(1, len(lines)):
            if lines[k].strip() == "---":
                return lines[k + 1:]
    return lines


def head(lines: list[str]) -> list[str]:
    for k, line in enumerate(lines):
        if line.startswith("## "):
            return lines[:k]
    return lines


def header_value(lines: list[str], key: str) -> str | None:
    for line in head(lines):
        m = FIELD.match(line)
        if m and m["key"].strip().lower() == key:
            return m["value"].strip()
    return None


def plain(text: str) -> str:
    text = LINK.sub(r"\1", text)
    text = re.sub(r"\*\*|__|`", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def title_of(lines: list[str], rel: str) -> str:
    for line in lines:
        if line.startswith("# "):
            return plain(re.sub(r"^\d+:\s*", "", line[2:]))
    return rel.rsplit("/", 1)[-1][:-3]


def number_of(rel: str, kind: str) -> str | None:
    name = rel.rsplit("/", 1)[-1]
    if kind in ("ticket", "issue", "review"):
        return name[:2]
    return name[:4] if kind == "adr" else None


def short_label(kind: str, num: str | None, title: str) -> str:
    text = title.split(": ", 1)[0] if kind == "plan" else title
    text = clip(text, 30)
    if kind in ("ticket", "issue"):
        return f"{num} · {text}"
    if kind == "review":
        return f"Review {int(num)} · {text}"
    if kind == "adr":
        return f"ADR {num} · {text}"
    if kind == "out-of-scope":
        return f"Out-of-scope idea · {text}"
    return f"{TYPE_WORDS[kind]} · {text}"


def status_word(value: str) -> str:
    word = re.split(r"\s+·\s+|\s+-\s+|[,;(.]", value, maxsplit=1)[0]
    return word.replace("*", "").replace("`", "").strip().lower()


def official_status(word: str | None, ticket_type: str | None, merged: bool) -> tuple[str, str | None]:
    if merged:
        return "wontfix", None
    if word is None:
        return "needs-triage", "It has no Status: line, so it shows as needs triage."
    if word in STATUSES:
        return word, None
    if word == "open":
        return ("ready-for-agent" if ticket_type in AGENT_TICKET_TYPES else "ready-for-human"), None
    if word in OLD_WORDS:
        return OLD_WORDS[word], None
    return "needs-triage", f'Its status "{word}" is not one of the seven, so it shows as needs triage.'


def section(lines: list[str], name: str) -> list[str]:
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower() == name
            continue
        if inside:
            out.append(line)
    return out


def blocks(lines: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def is_header_line(line: str) -> bool:
    m = FIELD.match(line)
    return bool(m) and m["key"].strip().lower() in HEADER_KEYS


def list_items(block: list[str]) -> list[str]:
    items: list[str] = []
    for line in block:
        if LIST_ITEM.match(line):
            items.append(LIST_ITEM.sub("", line).strip())
        elif items:
            items[-1] += " " + line.strip()
    return [plain(i) for i in items]


def first_paragraph(lines: list[str]) -> str:
    prose = [b for b in blocks(lines) if not NOT_PROSE.match(b[0]) and not all(is_header_line(x) for x in b)]
    if not prose:
        return ""
    first = prose[0]
    if LIST_ITEM.match(first[0]):
        return list_items(first)[0]
    text = plain(" ".join(x.strip() for x in first))
    # A paragraph that introduces a list reads better with the list.
    if text.endswith(":") and len(prose) > 1 and LIST_ITEM.match(prose[1][0]):
        text += " " + " ".join(list_items(prose[1]))
    return text


def description(lines: list[str], kind: str) -> str:
    for name in DESCRIPTION_SECTIONS.get(kind, ()):
        text = first_paragraph(section(lines, name)) or plain(header_value(lines, name) or "")
        if text:
            return clip(text, 420)
    return clip(first_paragraph(head(lines)) or first_paragraph(lines), 420)


def next_steps(lines: list[str]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for line in section(lines, "next steps"):
        m = STEP.match(line)
        if m:
            steps.append({"skill": m["skill"], "reason": plain(m["reason"])})
        elif steps and line[:1] in (" ", "\t") and line.strip():
            steps[-1]["reason"] = plain(steps[-1]["reason"] + " " + line)
    return steps


def link_paths(value: str, rel: str) -> list[str]:
    out = []
    for _text, href in LINK.findall(value):
        target = unquote(href.split("#", 1)[0])
        if target and not re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            out.append(posixpath.normpath(posixpath.join(posixpath.dirname(rel), target)))
    return out


def blocked_paths(value: str, item: Item, siblings: dict[str, str]) -> list[str]:
    targets = link_paths(value, item.path)
    rest = LINK.sub("", value).replace("**", "").strip()
    if re.match(r"none\b", rest, re.I):
        return targets
    for part in re.split(r",|;|\band\b", rest):
        part = part.strip().strip(".").strip()
        if not part:
            continue
        m = re.match(r"#?(\d{1,3})\b", part)
        found = siblings.get("num:" + m[1].zfill(2)) if m else siblings.get("title:" + part.lower())
        if found:
            targets.append(found)
        else:
            item.warnings.append(f'Blocked by: names "{part}", which is not a ticket in this folder.')
    return targets


def checked(targets: list[str], key: str, item: Item, items: dict[str, Item], repo: Path) -> list[str]:
    good = []
    for target in targets:
        if target in items and target != item.path and (key == "From" or items[target].kind != "out-of-scope"):
            good.append(target)
        elif (repo / target).exists():
            item.warnings.append(f"{key}: names {target}, which is not a work item or decision record.")
        else:
            item.warnings.append(f"{key}: names {target}, which does not exist.")
    return good


def folder_parent(item: Item, items: dict[str, Item]) -> str | None:
    if item.kind not in ("ticket", "issue", "review"):
        return None
    slug = item.path.split("/")[1]
    for parent in (f".scratch/{slug}/spec.md", f".scratch/{slug}/map.md", f"docs/plans/{slug}.md"):
        if parent in items:
            return parent
    return None


def work_item_paths(repo: Path) -> set[Path]:
    return {p for pattern in PATTERNS for p in repo.glob(pattern)}


def read_items(repo: Path) -> dict[str, Item]:
    found = {p.relative_to(repo).as_posix() for p in work_item_paths(repo)}
    items = {}
    for rel in sorted(found):
        kind = node_type(rel, repo)
        if kind:
            items[rel] = Item(rel, kind, read_lines(repo / rel))
    for item in items.values():
        item.num = number_of(item.path, item.kind)
        item.title = title_of(item.lines, item.path)
        item.short = short_label(item.kind, item.num, item.title)
    return items


def link_items(items: dict[str, Item], repo: Path) -> None:
    folders: dict[str, dict[str, str]] = {}
    for item in items.values():
        if item.num and item.kind in ("ticket", "issue", "review"):
            index = folders.setdefault(posixpath.dirname(item.path), {})
            index["num:" + item.num] = item.path
            index["title:" + item.title.lower()] = item.path
    for item in items.values():
        parent = folder_parent(item, items)
        if parent:
            item.came_from[parent] = "folder"
        for target in checked(link_paths(header_value(item.lines, "from") or "", item.path), "From", item, items, repo):
            item.came_from.setdefault(target, "From: line")
        blocked = header_value(item.lines, "blocked by")
        if blocked:
            siblings = folders.get(posixpath.dirname(item.path), {})
            item.blocked_by = checked(blocked_paths(blocked, item, siblings), "Blocked by", item, items, repo)
        merged = checked(link_paths(header_value(item.lines, "merged into") or "", item.path), "Merged into", item, items, repo)
        item.merged_into = merged[0] if merged else None
        if item.kind not in ("adr", "out-of-scope"):
            raw = header_value(item.lines, "status")
            word = status_word(raw) if raw else None
            item.status, warning = official_status(word, (header_value(item.lines, "type") or "").lower(), bool(item.merged_into))
            item.word = word if word and word != item.status else None
            if warning:
                item.warnings.append(warning)


def ref(item: Item) -> str:
    if item.kind in ("ticket", "issue"):
        return f"{item.kind} {item.num}"
    if item.kind == "review":
        return f"review item {int(item.num)}"
    return item.short


def is_open(item: Item) -> bool:
    return item.kind not in ("adr", "out-of-scope") and item.status not in FINISHED


def context(item: Item, items: dict[str, Item], shown: set[str]) -> list[dict]:
    out = []
    for target, via in item.came_from.items():
        if items[target].kind == "out-of-scope":
            why = "This idea was turned down before."
        else:
            why = f"It came from this, by {'its folder' if via == 'folder' else 'a From: line'}."
        out.append((target, why))
    for target in item.blocked_by:
        out.append((target, f"Blocked by this, which is {'still open' if is_open(items[target]) else 'finished'}."))
    for other in items.values():
        if other.merged_into == item.path:
            out.append((other.path, "Merged into this item."))
    seen, rows = set(), []
    for target, why in out:
        if target in seen:
            continue
        seen.add(target)
        if target not in shown:
            if items[target].kind != "out-of-scope":
                why += f" It is older than {CUTOFF}, so it has no star."
        rows.append({"path": target, "title": items[target].title, "why": why, "shown": target in shown})
    return rows


def build(repo: Path, existing: set[str] | None) -> dict:
    items = read_items(repo)
    link_items(items, repo)
    shown = {rel for rel in items if existing is None or rel not in existing}
    linked_out_of_scope = {
        target
        for item in items.values()
        if is_open(item)
        for target in item.came_from
        if items[target].kind == "out-of-scope"
    }
    shown = {rel for rel in shown if items[rel].kind != "out-of-scope" or rel in linked_out_of_scope}
    out = []
    for rel in sorted(shown):
        item = items[rel]
        waits = [items[t] for t in item.blocked_by if is_open(items[t])]
        merged = items.get(item.merged_into) if item.merged_into else None
        out.append({
            "id": rel,
            "path": rel,
            "type": item.kind,
            "num": item.num,
            "title": item.title,
            "short": item.short,
            "status": item.status,
            "word": item.word,
            "desc": description(item.lines, item.kind),
            "next": next_steps(item.lines) if item.kind != "adr" else [],
            "from": [t for t in item.came_from if t in shown],
            "blockedBy": [t for t in item.blocked_by if t in shown],
            "mergedInto": item.merged_into if item.merged_into in shown else None,
            "context": context(item, items, shown),
            "waitsFor": [{"path": w.path, "ref": ref(w), "title": w.title} for w in waits],
            "mergedRef": {"path": merged.path, "ref": ref(merged), "title": merged.title, "shown": merged.path in shown} if merged else None,
            "warnings": item.warnings,
        })
    return {
        "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cutoff": CUTOFF,
        "cutoffKnown": existing is not None,
        "items": out,
    }


def render(template: str, data: dict) -> str:
    if DATA_MARK not in template:
        raise SystemExit(f"{TEMPLATE.name} has no {DATA_MARK} mark.")
    # "<" escaped, so no text in a work item can close the script tag.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace(DATA_MARK, payload, 1)


def write_page(path: Path, text: str) -> None:
    # Replaced in one step, so a reload never sees half a page.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def snapshot(repo: Path, extra: Iterable[Path]) -> dict[str, int]:
    found = work_item_paths(repo) | set(extra)
    out = {}
    for p in found:
        try:
            out[p.as_posix()] = p.stat().st_mtime_ns
        except OSError:
            pass
    return out


def watch(look: Callable[[], dict], rebuild: Callable[[], None], wait: Callable[[], None], rounds: int | None = None) -> None:
    last, dirty, looked = look(), False, 0
    while rounds is None or looked < rounds:
        looked += 1
        wait()
        now = look()
        if now != last:
            last, dirty = now, True
        elif dirty:
            dirty = False
            rebuild()


def rebuild_once() -> None:
    # A fresh interpreter builds with the current code, and its crash cannot stop the watcher.
    result = subprocess.run([sys.executable, str(SCRIPT), "--no-open"], cwd=REPO)
    if result.returncode:
        print(f"{datetime.now():%H:%M:%S} Rebuild failed; the page keeps its last good build.", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the observatory page from this repo's work items and open it.")
    parser.add_argument("--no-open", action="store_true", help="write the page without opening it")
    parser.add_argument("--watch", action="store_true", help="rebuild the page whenever a work item or this tool changes, until stopped")
    args = parser.parse_args(argv)
    if args.watch:
        print("Watching the work items. Reload the page to see a rebuild; Ctrl+C stops.")
        try:
            rebuild_once()
            watch(lambda: snapshot(REPO, (SCRIPT, TEMPLATE)), rebuild_once, lambda: time.sleep(0.5))
        except KeyboardInterrupt:
            pass
        return 0
    existing = paths_at_cutoff(REPO)
    if existing is None:
        print(f"git could not list the files at {CUTOFF}, so every item gets a star.", file=sys.stderr)
    data = build(REPO, existing)
    write_page(OUTPUT, render(TEMPLATE.read_text(encoding="utf-8"), data))
    warnings = [(i["path"], w) for i in data["items"] for w in i["warnings"]]
    print(f"Observatory: {len(data['items'])} items, {len(warnings)} warnings.")
    for path, warning in warnings:
        print(f"  {path}: {warning}")
    print(f"Wrote {OUTPUT.relative_to(REPO).as_posix()}")
    if not args.no_open:
        webbrowser.open(OUTPUT.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
