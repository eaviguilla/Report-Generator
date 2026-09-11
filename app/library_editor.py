"""Disposable vulnerability-library fragment editor.

Edits whatever library the app has loaded, which is the copy under resources/; the pristine
export at the repo root is never touched. Self-contained on purpose: delete this file and the
two `library_editor` lines in app/main.py to remove the tool entirely. Nothing else imports it.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.library import LibraryDocument
from app.models import Severity
from app.storage import atomic_write_json

router = APIRouter(prefix="/library-editor", tags=["library-editor"])

CONTENT_LABELS = {"description": "Description", "recommended_remediation": "Recommended Remediation"}


def _library_path() -> Path:
    from app import main

    return main.configured_library


def _runs_text(runs: list[dict]) -> str:
    return "".join(run.get("text", "") for run in runs or [])


def _fragment_text(fragment: dict) -> str:
    """Flatten one fragment into the plain text a tester edits."""
    kind = fragment.get("type")
    if kind in {"paragraph", "note"}:
        return _runs_text(fragment.get("runs", []))
    if kind.endswith("list"):
        return "\n".join(_runs_text(item.get("runs", [])) for item in fragment.get("items", []))
    if kind == "table":
        rows = [fragment.get("header", []), *fragment.get("rows", [])]
        return "\n".join(" | ".join(_runs_text(cell.get("runs", [])) for cell in row) for row in rows)
    return fragment.get("text", "")


def _apply_text(fragment: dict, text: str) -> None:
    """Write plain text back, keeping the original runs when the text is unchanged."""
    if _fragment_text(fragment) == text:
        return
    kind = fragment.get("type")
    lines = text.split("\n")
    if kind in {"paragraph", "note"}:
        fragment["runs"] = [{"text": text}] if text else []
    elif kind.endswith("list"):
        fragment["items"] = [{"runs": [{"text": line}] if line else []} for line in lines] or [{"runs": []}]
    elif kind == "table":
        grid = [[{"runs": [{"text": cell.strip()}] if cell.strip() else []} for cell in line.split("|")] for line in lines]
        fragment["header"] = grid[0] if grid else [{"runs": []}]
        fragment["rows"] = grid[1:] or [[{"runs": []} for _ in fragment["header"]]]
    else:
        fragment["text"] = text


class FragmentEdit(BaseModel):
    frag_id: str
    text: str


class EntryEdit(BaseModel):
    title: str
    source_id: str = ""
    tags: list[str] = Field(default_factory=list)
    default_likelihood: Severity | None = None
    default_impact: Severity | None = None
    default_severity: Severity | None = None
    requires_tester_input: bool = False
    status: str = "approved"
    fragments: list[FragmentEdit] = Field(default_factory=list)
    removed_frag_ids: list[str] = Field(default_factory=list)


def _entry_issues(entry: dict) -> list[str]:
    """Name everything still unfilled, so gaps are visible without opening each entry."""
    issues = [
        label
        for field, label in (
            ("default_likelihood", "no likelihood"),
            ("default_impact", "no impact"),
            ("default_severity", "no severity"),
            ("tags", "no tags"),
            ("source_id", "no source id"),
            ("status", "no status"),
        )
        if not entry.get(field)
    ]
    filled = {content["type"] for content in entry.get("contents", []) if content.get("fragments")}
    issues += [f"no {label.lower()}" for kind, label in CONTENT_LABELS.items() if kind not in filled]
    blank = sum(1 for content in entry.get("contents", []) for fragment in content.get("fragments", []) if not _fragment_text(fragment).strip())
    if blank:
        issues.append(f"{blank} empty fragment{'s' if blank > 1 else ''}")
    return issues


@router.get("/entries")
def list_entries() -> dict:
    """Return every entry with its editable fields and flattened fragment rows."""
    document = json.loads(_library_path().read_text(encoding="utf-8"))
    entries = []
    for entry in document["entries"]:
        fragments = [
            {
                "frag_id": fragment["frag_id"],
                "type": fragment["type"],
                "content_type": content["type"],
                "content_label": CONTENT_LABELS.get(content["type"], content["type"]),
                "text": _fragment_text(fragment),
            }
            for content in entry.get("contents", [])
            for fragment in content.get("fragments", [])
        ]
        entries.append({
            "library_id": entry["library_id"],
            "title": entry["title"],
            "source_id": entry.get("source_id", ""),
            "tags": entry.get("tags", []),
            "default_likelihood": entry.get("default_likelihood"),
            "default_impact": entry.get("default_impact"),
            "default_severity": entry.get("default_severity"),
            "requires_tester_input": entry.get("requires_tester_input", False),
            "status": entry.get("status", ""),
            "issues": _entry_issues(entry),
            "fragments": fragments,
        })
    return {"path": str(_library_path()), "entries": entries}


@router.put("/entries/{library_id}")
def save_entry(library_id: str, edit: EntryEdit) -> dict:
    """Validate the whole library before replacing it; atomic_write_json keeps the previous copy."""
    path = _library_path()
    document = json.loads(path.read_text(encoding="utf-8"))
    entry = next((item for item in document["entries"] if item["library_id"] == library_id), None)
    if entry is None:
        raise HTTPException(404, f"Unknown library entry: {library_id}")

    if not edit.title.strip():
        raise HTTPException(422, "Title cannot be empty")
    source_id = edit.source_id.strip()
    entry["title"] = edit.title.strip()
    entry["source_id"] = int(source_id) if source_id.lstrip("-").isdigit() else source_id
    entry["tags"] = [tag.strip() for tag in edit.tags if tag.strip()]
    entry["default_likelihood"] = edit.default_likelihood
    entry["default_impact"] = edit.default_impact
    entry["default_severity"] = edit.default_severity
    entry["requires_tester_input"] = edit.requires_tester_input
    entry["status"] = edit.status.strip()

    by_id = {fragment["frag_id"]: fragment for content in entry.get("contents", []) for fragment in content.get("fragments", [])}
    unknown = [item.frag_id for item in edit.fragments if item.frag_id not in by_id] + [frag_id for frag_id in edit.removed_frag_ids if frag_id not in by_id]
    if unknown:
        raise HTTPException(422, f"Unknown fragment IDs: {', '.join(unknown)}")
    for item in edit.fragments:
        _apply_text(by_id[item.frag_id], item.text)
    if edit.removed_frag_ids:
        dropped = set(edit.removed_frag_ids)
        for content in entry.get("contents", []):
            content["fragments"] = [fragment for fragment in content["fragments"] if fragment["frag_id"] not in dropped]

    try:
        LibraryDocument.model_validate(document)
    except Exception as error:
        raise HTTPException(422, f"Edit would make the library invalid: {error}") from error

    backup = path.with_suffix(".bak.json")
    atomic_write_json(path, document)

    from app import main
    from app.library import Library

    main.library = Library(path)
    return {"saved": library_id, "backup": str(backup)}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Library Editor</title>
<style>
:root{color-scheme:light dark;--line:#d1d9e0;--muted:#59636e;--accent:#0969da;--warn:#9a6700;--danger:#cf222e;--bg:#fff;--panel:#f6f8fa;--ink:#1f2328}
@media(prefers-color-scheme:dark){:root{--line:#3d444d;--muted:#9198a1;--accent:#4493f8;--warn:#d29922;--danger:#f85149;--bg:#0d1117;--panel:#151b23;--ink:#f0f6fc}}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);display:grid;grid-template-columns:340px 1fr;height:100vh}
aside{border-right:1px solid var(--line);overflow-y:auto;background:var(--panel)}
main{overflow-y:auto;padding:24px 28px}
h1{font-size:15px;margin:0;padding:14px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel);z-index:1}
h1 small{display:block;font:400 11px/1.5 ui-monospace,Menlo,monospace;color:var(--muted);margin-top:3px;word-break:break-all}
#filter{width:calc(100% - 24px);margin:12px 12px 8px;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.only{display:flex;gap:6px;align-items:center;margin:0 12px 12px;font-size:12px;color:var(--muted)}
.item{padding:9px 16px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px;border-left:3px solid transparent}
.item:hover{background:var(--bg)}
.item.on{background:var(--bg);border-left-color:var(--accent);font-weight:600}
.item small{display:block;color:var(--muted);font-size:11px;font-weight:400}
.item .flags{display:block;color:var(--warn);font-size:11px;font-style:normal;font-weight:400;margin-top:2px}
.fields{display:grid;grid-template-columns:repeat(3,1fr);gap:12px 14px;margin:0 0 24px}
.fields label{display:flex;flex-direction:column;gap:4px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.fields .wide{grid-column:span 3}
.fields .check{flex-direction:row;align-items:center;gap:7px;text-transform:none;letter-spacing:0;font-size:13px;color:var(--ink);align-self:end;padding-bottom:7px}
.fields input,.fields select{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:13px/1.4 system-ui,sans-serif}
.fields .check input{width:auto}
#title{font:600 17px/1.3 system-ui,sans-serif}
.block{margin:0 0 22px}
.block h2{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 8px}
.frag{margin:0 0 12px}
.frag-head{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.frag-head label{flex:1;font-size:11px;color:var(--muted)}
.frag-head .empty{color:var(--warn)}
textarea{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:6px;font:13px/1.6 ui-monospace,Menlo,monospace;background:var(--bg);color:var(--ink);resize:none;overflow:hidden}
textarea:focus,.fields input:focus,.fields select:focus{outline:2px solid var(--accent);outline-offset:1px}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0 14px;display:flex;gap:10px;align-items:center;z-index:2;border-bottom:1px solid var(--line);margin-bottom:18px}
button{padding:7px 14px;border:1px solid var(--line);border-radius:6px;background:#1f883d;color:#fff;font-weight:600;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.rm{padding:2px 8px;font:11px/1.6 system-ui,sans-serif;background:none;color:var(--danger);border-color:var(--line)}
button.rm:hover{background:var(--danger);color:#fff}
#status{font-size:12px;color:var(--muted)}
.hint{font-size:11px;color:var(--muted);margin:-2px 0 14px}
.issues{font-size:12px;color:var(--warn);border:1px solid var(--warn);border-radius:6px;padding:8px 11px;margin:0 0 18px}
</style></head><body>
<aside><h1>Vulnerabilities<small id="where"></small></h1>
<input id="filter" placeholder="Filter by title or tag">
<label class="only"><input type="checkbox" id="only-issues"> Only entries with empty fields <span id="issue-count"></span></label>
<div id="list"></div></aside>
<main><div id="empty" style="color:var(--muted)">Select a vulnerability on the left.</div><div id="editor" hidden>
<div class="bar"><button id="save" disabled>Save entry</button><span id="status"></span></div>
<p class="hint" id="meta"></p>
<p class="issues" id="issues" hidden></p>
<div class="fields">
<label class="wide">Title<input id="title"></label>
<label>Source ID<input id="source_id"></label>
<label>Status<input id="status_field"></label>
<label class="check"><input type="checkbox" id="requires_tester_input"> Requires tester input</label>
<label class="wide">Tags<input id="tags" placeholder="comma separated"></label>
<label>Likelihood<select id="default_likelihood"></select></label>
<label>Impact<select id="default_impact"></select></label>
<label>Severity<select id="default_severity"></select></label>
</div>
<div id="blocks"></div>
</div></main>
<script>
const SEVERITIES = ["critical", "high", "medium", "low", "informational"];
const RATINGS = ["default_likelihood", "default_impact", "default_severity"];
const INPUTS = ["title", "source_id", "status_field", "requires_tester_input", "tags", ...RATINGS];
let data = [], current = null, dirty = false, removed = new Set();
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fit = t => { t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; };
const setDirty = on => { dirty = on; $("save").disabled = !on; $("status").textContent = on ? "Unsaved changes" : ""; };
// Textareas are the only edits that live solely in the DOM, so capture them before any re-render.
const syncText = () => $("blocks").querySelectorAll("textarea").forEach(t => {
  const fragment = current.fragments.find(f => f.frag_id === t.dataset.frag);
  if (fragment) fragment.text = t.value;
});

async function load() {
  const body = await (await fetch("/library-editor/entries")).json();
  data = body.entries;
  $("where").textContent = `editing: ${body.path.split("/").slice(-2).join("/")}`;
  renderList();
}
function renderList() {
  const needle = $("filter").value.toLowerCase().trim();
  const onlyIssues = $("only-issues").checked;
  const flagged = data.filter(e => e.issues.length).length;
  $("issue-count").textContent = `(${flagged} of ${data.length})`;
  const shown = data.filter(e => (!onlyIssues || e.issues.length)
    && (!needle || e.title.toLowerCase().includes(needle) || (e.tags || []).join(" ").toLowerCase().includes(needle)));
  $("list").innerHTML = shown.map(e => `<div class="item${current && e.library_id === current.library_id ? " on" : ""}" data-id="${esc(e.library_id)}">${esc(e.title)}`
    + `<small>${esc(e.library_id)} · ${e.fragments.length} fragments</small>`
    + (e.issues.length ? `<span class="flags">${esc(e.issues.join(" · "))}</span>` : "") + `</div>`).join("");
  $("list").querySelectorAll(".item").forEach(node => node.onclick = () => select(node.dataset.id));
}
function select(id) {
  if (dirty && !confirm("Discard unsaved changes to this entry?")) return;
  current = data.find(e => e.library_id === id);
  removed = new Set();
  setDirty(false);
  $("empty").hidden = true; $("editor").hidden = false;
  $("meta").textContent = `${current.library_id} · ${current.fragments.length} fragments`;
  $("issues").hidden = !current.issues.length;
  $("issues").textContent = `Empty fields: ${current.issues.join(" · ")}`;
  $("title").value = current.title;
  $("source_id").value = current.source_id ?? "";
  $("status_field").value = current.status ?? "";
  $("tags").value = (current.tags || []).join(", ");
  $("requires_tester_input").checked = !!current.requires_tester_input;
  RATINGS.forEach(key => $(key).innerHTML = `<option value="">— not set —</option>`
    + SEVERITIES.map(s => `<option${current[key] === s ? " selected" : ""}>${s}</option>`).join(""));
  INPUTS.forEach(key => { $(key).oninput = $(key).onchange = () => setDirty(true); });
  renderBlocks();
  renderList();
}
function renderBlocks() {
  const groups = [];
  current.fragments.filter(f => !removed.has(f.frag_id)).forEach(f => {
    const group = groups.find(g => g.label === f.content_label) || (groups.push({label: f.content_label, items: []}), groups.at(-1));
    group.items.push(f);
  });
  $("blocks").innerHTML = groups.length ? groups.map(g => `<div class="block"><h2>${esc(g.label)}</h2>` + g.items.map(f => {
    const shape = f.type === "table" ? " — one row per line, cells separated by |" : f.type.endsWith("list") ? " — one item per line" : "";
    return `<div class="frag"><div class="frag-head"><label for="t-${esc(f.frag_id)}">${esc(f.type.replace(/_/g, " "))}${shape}`
      + `${f.text.trim() ? "" : ` <span class="empty">· empty</span>`}</label>`
      + `<button type="button" class="rm" data-rm="${esc(f.frag_id)}">Remove</button></div>`
      + `<textarea id="t-${esc(f.frag_id)}" data-frag="${esc(f.frag_id)}">${esc(f.text)}</textarea></div>`;
  }).join("") + `</div>`).join("") : `<p class="hint">No fragments left. Saving now leaves this entry with no content.</p>`;
  $("blocks").querySelectorAll("textarea").forEach(t => { fit(t); t.oninput = () => { fit(t); setDirty(true); }; });
  $("blocks").querySelectorAll("[data-rm]").forEach(button => button.onclick = () => {
    if (!confirm("Remove this fragment? It is deleted from the library when you save the entry.")) return;
    syncText();
    removed.add(button.dataset.rm);
    setDirty(true);
    renderBlocks();
  });
}
$("filter").oninput = renderList;
$("only-issues").onchange = renderList;
$("save").onclick = async () => {
  syncText();
  $("save").disabled = true; $("status").textContent = "Saving...";
  const res = await fetch(`/library-editor/entries/${current.library_id}`, {
    method: "PUT", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      title: $("title").value,
      source_id: $("source_id").value,
      status: $("status_field").value,
      tags: $("tags").value.split(",").map(tag => tag.trim()).filter(Boolean),
      requires_tester_input: $("requires_tester_input").checked,
      default_likelihood: $("default_likelihood").value || null,
      default_impact: $("default_impact").value || null,
      default_severity: $("default_severity").value || null,
      fragments: current.fragments.filter(f => !removed.has(f.frag_id)).map(f => ({frag_id: f.frag_id, text: f.text})),
      removed_frag_ids: [...removed],
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    $("status").textContent = `Save failed: ${body.detail || res.status}`;
    $("save").disabled = false;
    return;
  }
  const saved = await res.json();
  const id = current.library_id;
  setDirty(false);
  await load();
  select(id);
  $("status").textContent = `Saved. Previous copy: ${saved.backup.split("/").pop()}`;
};
addEventListener("beforeunload", e => { if (dirty) e.preventDefault(); });
load();
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
def editor_page() -> HTMLResponse:
    """Serve the standalone editor page."""
    return HTMLResponse(PAGE)
