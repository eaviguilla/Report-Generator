"""
VulnReport -- build-time converter: SharePoint HTML  ->  fragment JSON.

The vuln DB stores Description and Recommended Remediation as HTML blobs
(SharePoint "enhanced rich text" columns). The app must never parse HTML at
runtime, so this tool runs OFFLINE whenever the library is refreshed and emits
library/vuln_library.json containing ready-made fragments.

    python -m scripts.html_to_fragments vulnerabilities.json -o vuln_library.json

The source HTML is NOT well formed. Measured on the 51-entry export:
  * 4 entries have an unclosed <ul>
  * 9 entries have table rows that begin with <td> and no opening <tr>
  * 2 entries use <li> where </li> was intended
A strict parser silently discards that content. This parser recovers instead,
and reports every recovery so the source data can be fixed at leisure.

Stdlib only -- html.parser. No bs4, no lxml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.4"

# Text that must never reach a client deliverable.
PLACEHOLDER_RE = re.compile(
    r"\(\s*insert[^)]*\)|insert\s+(technology|version|eol\s+date|cves|latest)\s+"
    r"\w*\s*here|\[value_taken_from",
    re.I,
)

# A remediation/description note looks like:  <p><b><i>Note:</i></b> body</p>
NOTE_PREFIX_RE = re.compile(r"^\s*note\s*:\s*", re.I)

SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "informational": "informational",
    "info": "informational",
}


# =============================================================================
# RUNS  --  inline formatting, the storage form for all rich text
# =============================================================================

def _merge(runs: list[dict]) -> list[dict]:
    """Collapse adjacent runs that share formatting, drop empties."""
    out: list[dict] = []
    for r in runs:
        if not r["text"]:
            continue
        if out and out[-1].get("bold") == r.get("bold") \
                and out[-1].get("italic") == r.get("italic") \
                and out[-1].get("underline") == r.get("underline"):
            out[-1]["text"] += r["text"]
        else:
            out.append(dict(r))
    for r in out:
        for k in ("bold", "italic", "underline"):
            if not r.get(k):
                r.pop(k, None)
    if out:
        out[0]["text"] = out[0]["text"].lstrip()
        out[-1]["text"] = out[-1]["text"].rstrip()
    return [r for r in out if r["text"]]


def runs_text(runs: list[dict]) -> str:
    """Flatten rich-text runs into plain text for matching and diagnostics."""
    return "".join(r["text"] for r in runs)


# =============================================================================
# PARSER
# =============================================================================

class FragmentParser(HTMLParser):
    """Lenient HTML -> block fragment converter."""

    BLOCK_OPEN = {"p", "ul", "ol", "table", "tr", "li", "td", "th", "div"}

    def __init__(self, prefix: str) -> None:
        """Initialize the tolerant HTML parser and its fragment buffers."""
        super().__init__(convert_charrefs=True)
        self.prefix = prefix
        self.frags: list[dict] = []
        self.warnings: list[str] = []

        self._n = 0
        self._runs: list[dict] = []          # inline buffer
        self._bold = 0
        self._italic = 0
        self._underline = 0

        self._list: list[list[dict]] | None = None   # items, each a run list
        self._list_ordered = False
        self._in_li = False

        self._table: list[list[list[dict]]] | None = None
        self._table_header: list[list[dict]] | None = None
        self._row: list[list[dict]] | None = None
        self._in_cell = False
        self._cell_is_header = False

    # -- ids ---------------------------------------------------------------
    def _fid(self) -> str:
        """Return the next converter-local fragment identifier."""
        self._n += 1
        return f"{self.prefix}{self._n}"

    # -- inline ------------------------------------------------------------
    def handle_data(self, data: str) -> None:
        """Normalize text nodes and add them to the current inline run buffer."""
        if not data:
            return
        text = data.replace("\xa0", " ")
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        if not text.strip() and not self._runs:
            return
        self._runs.append({
            "text": text,
            "bold": bool(self._bold),
            "italic": bool(self._italic),
            "underline": bool(self._underline),
        })

    def _take_runs(self) -> list[dict]:
        """Return normalized buffered runs and clear the inline buffer."""
        runs, self._runs = _merge(self._runs), []
        return runs

    # -- emit --------------------------------------------------------------
    def _emit_paragraph(self) -> None:
        """Turn buffered inline content into a paragraph or recognized note."""
        runs = self._take_runs()
        if not runs:
            return
        # <p><b><i>Note:</i></b> body</p>  ->  note fragment
        if runs[0].get("bold") and NOTE_PREFIX_RE.match(runs[0]["text"]):
            body = list(runs)
            head = NOTE_PREFIX_RE.sub("", body[0]["text"]).strip()
            if head:
                body[0] = {**body[0], "text": head}
                body[0].pop("bold", None)
                body[0].pop("italic", None)
            else:
                body = body[1:]
            body = _merge(body)
            if body:
                self.frags.append({"frag_id": self._fid(), "type": "note",
                                   "runs": body})
                return
        self.frags.append({"frag_id": self._fid(), "type": "paragraph",
                           "runs": runs})

    def _close_list(self) -> None:
        """Finish the current HTML list and append its fragment when non-empty."""
        if self._list is None:
            return
        if self._in_li:
            item = self._take_runs()
            if item:
                self._list.append(item)
            self._in_li = False
        items = [i for i in self._list if i]
        if items:
            self.frags.append({
                "frag_id": self._fid(),
                "type": "numbered_list" if self._list_ordered else "bulleted_list",
                "items": [{"runs": i} for i in items],
            })
        self._list = None

    def _close_row(self) -> None:
        """Finish the active table row and classify it as header or body data."""
        if self._row is None:
            return
        if self._in_cell:
            self._row.append(self._take_runs())
            self._in_cell = False
        if self._row:
            if self._cell_is_header and self._table_header is None:
                self._table_header = self._row
            else:
                assert self._table is not None
                self._table.append(self._row)
        self._row = None
        self._cell_is_header = False

    def _close_table(self) -> None:
        """Normalize table width and append the completed table fragment."""
        self._close_row()
        if self._table is None:
            return
        header = self._table_header or []
        rows = self._table
        width = max([len(header)] + [len(r) for r in rows]) if (header or rows) else 0
        if width:
            header = (header + [[] for _ in range(width)])[:width]
            rows = [(r + [[] for _ in range(width)])[:width] for r in rows]
            self.frags.append({
                "frag_id": self._fid(), "type": "table", "caption": None,
                "header": [{"runs": c} for c in header],
                "rows": [[{"runs": c} for c in r] for r in rows],
            })
        self._table = None
        self._table_header = None

    def _flush_all(self) -> None:
        """Finish whichever block structure is still active in the parser."""
        if self._table is not None:
            self._close_table()
        elif self._list is not None:
            self._close_list()
        else:
            self._emit_paragraph()

    # -- tags --------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        """Handle formatting and block opening tags, recovering malformed structures."""
        tag = tag.lower()
        if tag in ("b", "strong"):
            self._bold += 1
        elif tag in ("i", "em"):
            self._italic += 1
        elif tag == "u":
            self._underline += 1
        elif tag == "br":
            if self._list is None and self._table is None:
                self._emit_paragraph()
        elif tag in ("p", "div"):
            if self._list is None and self._table is None:
                self._emit_paragraph()
        elif tag in ("ul", "ol"):
            self._emit_paragraph()
            if self._list is not None:
                self.warnings.append("nested/unclosed <ul> recovered")
                self._close_list()
            self._list = []
            self._list_ordered = tag == "ol"
            self._in_li = False
        elif tag == "li":
            if self._list is None:                       # <li> outside a list
                self.warnings.append("<li> outside <ul> recovered")
                self._list, self._list_ordered = [], False
            if self._in_li:                              # previous <li> unclosed
                item = self._take_runs()
                if item:
                    self._list.append(item)
            self._runs = []
            self._in_li = True
        elif tag == "table":
            self._emit_paragraph()
            self._close_list()
            self._table, self._table_header, self._row = [], None, None
        elif tag == "tr":
            if self._table is None:
                self.warnings.append("<tr> outside <table> recovered")
                self._table, self._table_header = [], None
            self._close_row()
            self._row = []
        elif tag in ("td", "th"):
            if self._table is None:
                self.warnings.append("cell outside <table> recovered")
                self._table, self._table_header = [], None
            if self._row is None:                        # missing <tr>
                self.warnings.append("table row missing <tr> recovered")
                self._row = []
            if self._in_cell:
                self._row.append(self._take_runs())
            self._runs = []
            self._in_cell = True
            if tag == "th":
                self._cell_is_header = True

    def handle_endtag(self, tag: str) -> None:
        """Handle formatting and block closing tags for the current parser state."""
        tag = tag.lower()
        if tag in ("b", "strong"):
            self._bold = max(0, self._bold - 1)
        elif tag in ("i", "em"):
            self._italic = max(0, self._italic - 1)
        elif tag == "u":
            self._underline = max(0, self._underline - 1)
        elif tag in ("p", "div"):
            if self._list is None and self._table is None:
                self._emit_paragraph()
        elif tag == "li":
            if self._list is not None:
                item = self._take_runs()
                if item:
                    self._list.append(item)
                self._in_li = False
        elif tag in ("ul", "ol"):
            self._close_list()
        elif tag in ("td", "th"):
            if self._row is not None:
                self._row.append(self._take_runs())
                self._in_cell = False
        elif tag == "tr":
            self._close_row()
        elif tag == "table":
            self._close_table()

    def close(self) -> None:                              # type: ignore[override]
        """Flush incomplete input structures when HTML input ends."""
        super().close()
        if self._table is not None:
            self.warnings.append("unclosed <table> recovered at end of input")
            self._close_table()
        if self._list is not None:
            self.warnings.append("unclosed <ul> recovered at end of input")
            self._close_list()
        self._emit_paragraph()


def html_to_fragments(html: str, prefix: str) -> tuple[list[dict], list[str]]:
    """Convert one HTML field into fragments and a list of recovery warnings."""
    p = FragmentParser(prefix)
    p.feed(html or "")
    p.close()
    return p.frags, p.warnings


# =============================================================================
# LIBRARY BUILD
# =============================================================================

TAG_RULES: list[tuple[str, re.Pattern]] = [
    ("mobile", re.compile(r"jailbreak|root detection|mobile application|android|ios", re.I)),
    ("ai_llm", re.compile(r"\bAI\b|LLM|prompt|internal rules", re.I)),
    ("api", re.compile(r"\bAPI\b|CORS|HTTP method|OPTIONS", re.I)),
    ("headers", re.compile(r"header|CSP|HSTS|X-Frame|Referrer|Permissions-Policy|Pragma", re.I)),
    ("session", re.compile(r"session|cookie|token|logout|concurrent", re.I)),
    ("injection", re.compile(r"injection|XSS|SQL|HTML Injection", re.I)),
    ("authn", re.compile(r"authentication|MFA|autocomplete", re.I)),
    ("authz", re.compile(r"authoriz|direct object|access control", re.I)),
    ("upload", re.compile(r"file upload|malicious file", re.I)),
    ("crypto", re.compile(r"SSL|TLS|cipher|encryption", re.I)),
    ("disclosure", re.compile(r"disclos|information leak|verbose error|exposed", re.I)),
    ("components", re.compile(r"EOL|vulnerable technology|deprecated", re.I)),
]


def tags_for(name: str) -> list[str]:
    """Infer searchable library tags from a vulnerability title."""
    return sorted({t for t, rx in TAG_RULES if rx.search(name)}) or ["general"]


def build(src: Path, out: Path) -> dict[str, Any]:
    """Convert an exported vulnerability list into the runtime library JSON file."""
    raw = json.loads(src.read_text(encoding="utf-8"))
    rows = raw["findings"] if isinstance(raw, dict) else raw

    entries: list[dict] = []
    report: list[str] = []
    stats = {"placeholders": 0, "recovered": 0, "tables": 0, "notes": 0}

    for row in rows:
        lid = f"VDB-{int(row['id']):03d}"
        name = (row.get("vulnerability_name") or "").strip()
        if not name:
            report.append(f"{lid}: skipped, no vulnerability_name")
            continue

        desc, w1 = html_to_fragments(row.get("description", ""), f"{lid}-d")
        rem, w2 = html_to_fragments(row.get("remediation", ""), f"{lid}-r")

        for w in w1 + w2:
            report.append(f"{lid}: RECOVERED - {w}")
            stats["recovered"] += 1

        blob = " ".join(
            runs_text(f["runs"]) if "runs" in f else
            " ".join(runs_text(i["runs"]) for i in f.get("items", []))
            for f in desc + rem
        )
        has_ph = bool(PLACEHOLDER_RE.search(blob)) or bool(
            PLACEHOLDER_RE.search(row.get("description", "") + row.get("remediation", "")))
        if has_ph:
            stats["placeholders"] += 1
        stats["tables"] += sum(1 for f in desc + rem if f["type"] == "table")
        stats["notes"] += sum(1 for f in desc + rem if f["type"] == "note")

        sev = SEVERITY_MAP.get((row.get("severity") or "").strip().lower())
        lik = SEVERITY_MAP.get((row.get("likelihood") or "").strip().lower())
        imp = SEVERITY_MAP.get((row.get("impact") or "").strip().lower())

        entries.append({
            "library_id": lid,
            "source_id": row["id"],
            "title": name,
            "tags": tags_for(name),
            "default_likelihood": lik,
            "default_impact": imp,
            "default_severity": sev,
            "requires_tester_input": has_ph,
            "status": "approved",
            "contents": [
                {"type": "description", "fragments": desc},
                {"type": "recommended_remediation", "fragments": rem},
            ],
        })

    entries.sort(key=lambda e: e["title"].casefold())
    lib = {
        "schema_version": SCHEMA_VERSION,
        "source": src.name,
        "entry_count": len(entries),
        "_README": [
            "Vulnerability library for VulnReport. Generated by scripts.html_to_fragments",
            "from the SharePoint List export. DO NOT hand-edit -- edit the List and",
            "re-run the converter.",
            "",
            "Fragments are pre-converted. The app performs NO HTML parsing at runtime.",
            "",
            "requires_tester_input=true means the entry contains placeholder text that",
            "MUST be replaced before the report is complete. The review panel flags",
            "those fragments until the tester has edited them.",
            "",
            "Rich text is stored as runs: [{text, bold?, italic?, underline?}].",
        ],
        "entries": entries,
    }
    out.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"lib": lib, "report": report, "stats": stats}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default="vuln_library.json")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    r = build(Path(a.source), Path(a.out))
    lib, stats = r["lib"], r["stats"]
    print(f"entries          {lib['entry_count']}")
    print(f"tables           {stats['tables']}")
    print(f"note fragments   {stats['notes']}")
    print(f"needs input      {stats['placeholders']}")
    print(f"HTML recoveries  {stats['recovered']}")
    print(f"written          {a.out}")
    if a.report:
        print()
        for line in r["report"]:
            print("  " + line)
