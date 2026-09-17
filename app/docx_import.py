"""Read a report this app generated back into a draft.

The generator builds every fragment from a component in ``resources/fragments``, so recognising a
fragment means recognising the component that produced it. Paragraph *styles* cannot do that on
their own: six of the nine components render as ``Normal`` and the two list components share
``List Paragraph``. What separates them is the component's own paragraph properties, which survive
into the finished document.
"""
from __future__ import annotations

import hashlib
import re
import uuid
import zipfile
from datetime import datetime
from io import BytesIO

from docx import Document
from docx.opc.exceptions import OpcError, PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from PIL import Image

from .models import CHANNELS, LEGACY_NON_PRODUCTION_LABELS, NON_PRODUCTION_LABEL_PRESETS

# Taken from the components themselves rather than guessed: see tests/test_docx_import.py, which
# renders one of every fragment type and fails if any of these stops identifying it.
CAPTION_STYLE_ID = "FiguresandTables"
CODE_SHADING_FILL = "F1F4F8"
JUSTIFIED = "both"

FINDING_HEADING_STYLE = "ReportHeading2"
GROUP_HEADING_STYLE = "ReportHeading1"

# Matched on exact text because formatting does not separate them: "In Conclusion:" is bold while
# the others are not. Previous proof of concept is listed first so the longer heading wins --
# "Previous Proof of Concept:" contains "Proof of Concept:", and a substring match would find two
# proof sections in every retest finding and take the earlier one.
SECTION_HEADINGS = (
    ("Description:", "description"),
    ("Recommended Remediation:", "recommended_remediation"),
    ("Previous Proof of Concept:", "previous_proof_of_concept"),
    ("Proof of Concept:", "proof_of_concept"),
    ("In Conclusion:", "in_conclusion"),
)
# Printed by the finding template, never typed by the tester.
BOILERPLATE = {
    "The following demonstrates the vulnerability:",
    "Severity Review Ticket (if applicable):",
}
STATUS_BY_LABEL = {
    "Open (New)": "open_new",
    "Open (Previously Discovered)": "open_previously_discovered",
    "Resolved": "resolved",
}
RETAINED_STATUSES = {"open_new", "open_previously_discovered"}
FIGURE_PREFIX = re.compile(r"^Figure\s+\d+\s*[.:\-]?\s*")
INSTANCE_PREFIX = re.compile(r"^(?:Instance\s+\d+(?:(?:\s*[:.\-])?(?:\s+|$)))+", re.IGNORECASE)
DISPLAY_ID = re.compile(r"^[0-9]{1,5}$")
PRODUCTION_ROW = "Production Environment"


class ReportImportError(ValueError):
    """Raised when a document is not a report this app can read back."""


def _fresh(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _clean(value: str) -> str:
    """Map the document's placeholder for "nothing here" back to nothing."""
    text = " ".join(value.split())
    return "" if text == "N/A" else text


def numbering_formats(document) -> dict[str, str]:
    """Map each ``numId`` to its list format.

    The ids are not stable. Merging the components into the report renumbers them, so a document
    whose bulleted list is ``numId 30`` can come back as ``29`` — reading the id alone silently
    swaps bulleted and numbered lists. Only the resolved format is trustworthy.
    """
    try:
        numbering = document.part.numbering_part.element
    except (AttributeError, KeyError, NotImplementedError):
        return {}
    abstract_formats = {}
    for abstract in numbering.findall(qn("w:abstractNum")):
        level = abstract.find(qn("w:lvl"))
        fmt = level.find(qn("w:numFmt")) if level is not None else None
        if fmt is not None:
            abstract_formats[abstract.get(qn("w:abstractNumId"))] = fmt.get(qn("w:val"))
    formats = {}
    for num in numbering.findall(qn("w:num")):
        reference = num.find(qn("w:abstractNumId"))
        if reference is not None:
            formats[num.get(qn("w:numId"))] = abstract_formats.get(reference.get(qn("w:val")))
    return formats


def _paragraph_mark(paragraph, tag: str) -> bool:
    """Look only at the paragraph mark, which carries the component's formatting.

    Run-level bold and italic belong to the tester, so reading those instead would mistake any
    emphasised sentence for a title or a note.
    """
    properties = paragraph._p.find(qn("w:pPr"))
    run_properties = properties.find(qn("w:rPr")) if properties is not None else None
    return run_properties is not None and run_properties.find(qn(tag)) is not None


def classify_paragraph(paragraph, formats: dict[str, str]) -> str:
    """Name the fragment component that produced one paragraph."""
    if paragraph._p.findall(".//" + qn("a:blip")):
        return "image"
    properties = paragraph._p.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    if style is not None and style.get(qn("w:val")) == CAPTION_STYLE_ID:
        return "caption"
    numbering = properties.find(qn("w:numPr")) if properties is not None else None
    if numbering is not None:
        number_id = numbering.find(qn("w:numId"))
        value = number_id.get(qn("w:val")) if number_id is not None else None
        return "bulleted_list" if formats.get(value) == "bullet" else "numbered_list"
    shading = properties.find(qn("w:shd")) if properties is not None else None
    if shading is not None and (shading.get(qn("w:fill")) or "").upper() == CODE_SHADING_FILL:
        return "code_block"
    alignment = properties.find(qn("w:jc")) if properties is not None else None
    if alignment is not None and alignment.get(qn("w:val")) == JUSTIFIED:
        return "paragraph"
    # The generator's own label, so the text identifies it even though only that label is bold.
    if INSTANCE_PREFIX.match(paragraph.text.strip()):
        return "instance_title"
    if _paragraph_mark(paragraph, "w:b"):
        return "instance_title"
    if _paragraph_mark(paragraph, "w:i"):
        return "note"
    return "paragraph"


def runs_of(paragraph) -> list[dict]:
    """Rebuild a fragment's runs, keeping the emphasis the tester applied.

    A ``w:br`` is a real newline: the generator writes one for every line of a code block, and
    ``paragraph.text`` drops them silently.
    """
    runs = []
    for element in paragraph._p.findall(qn("w:r")):
        properties = element.find(qn("w:rPr"))
        text = ""
        for node in element:
            if node.tag == qn("w:t"):
                text += node.text or ""
            elif node.tag in (qn("w:br"), qn("w:cr")):
                text += "\n"
            elif node.tag == qn("w:tab"):
                text += "\t"
        if not text:
            continue
        run = {"text": text}
        for tag, name in ((qn("w:b"), "bold"), (qn("w:i"), "italic"), (qn("w:u"), "underline")):
            if properties is not None and properties.find(tag) is not None:
                run[name] = True
        runs.append(run)
    return runs


def text_of(paragraph) -> str:
    return "".join(run["text"] for run in runs_of(paragraph))


def section_of(text: str) -> str | None:
    """Name the content section a heading opens, or nothing if it is not a heading."""
    stripped = " ".join(text.split())
    for heading, content_type in SECTION_HEADINGS:
        if stripped == heading:
            return content_type
    return None


def _cell_runs(cell) -> list[dict]:
    runs: list[dict] = []
    for paragraph in cell.paragraphs:
        recovered = runs_of(paragraph)
        if runs and recovered:
            runs.append({"text": "\n"})
        runs.extend(recovered)
    return runs or [{"text": ""}]


def _image_bytes(document, paragraph) -> bytes | None:
    blip = paragraph._p.find(".//" + qn("a:blip"))
    if blip is None:
        return None
    relationship = blip.get(qn("r:embed"))
    if not relationship:
        return None
    return document.part.related_parts[relationship].blob


def _table_fragment(table, caption: str) -> dict:
    rows = [[{"runs": _cell_runs(cell)} for cell in row.cells] for row in table.rows]
    if not rows:
        raise ReportImportError("a table in this report has no rows")
    return {
        "frag_id": _fresh("f"), "type": "table", "caption": _clean(caption) or None,
        "header": rows[0], "rows": rows[1:] or [[{"runs": [{"text": ""}]} for _ in rows[0]]],
    }


def _detect_non_production_label(document) -> str:
    """The evidence heading is the label's only appearance: the scope table rows read
    "Non-Production Environment" from the template, not from what the tester chose."""
    known = {f"{label}:": label for label in (*NON_PRODUCTION_LABEL_PRESETS, *LEGACY_NON_PRODUCTION_LABELS)}
    for paragraph in document.paragraphs:
        if found := known.get(paragraph.text.strip().upper()):
            return found
    return NON_PRODUCTION_LABEL_PRESETS[0]


def _build_fragments(document, elements, formats, non_production_label, evidence):
    """Turn one section's body elements back into fragments.

    Captions sit on either side of what they describe: the generator writes a table's and a code
    block's caption *before* them and an image's *after*, so they are attached by position rather
    than assumed.
    """
    fragments: list[dict] = []
    pending_caption = ""
    labelled_environment = None
    for element in elements:
        if element.tag == qn("w:tbl"):
            table = next(candidate for candidate in document.tables if candidate._tbl is element)
            fragments.append(_table_fragment(table, pending_caption))
            pending_caption = ""
            continue
        if element.tag != qn("w:p"):
            continue
        paragraph = Paragraph(element, document)
        text = text_of(paragraph)
        stripped = " ".join(text.split())
        if stripped in BOILERPLATE:
            continue
        kind = classify_paragraph(paragraph, formats)
        # An image's caption sits directly under it, so position identifies it and the style name does
        # not have to. The generator's "Figure n." lead-in is its own, and never the tester's words.
        if fragments and fragments[-1]["type"] == "image" and not fragments[-1]["caption"] and FIGURE_PREFIX.match(stripped):
            fragments[-1]["caption"] = _clean(FIGURE_PREFIX.sub("", stripped))
            continue
        if kind == "caption":
            caption = FIGURE_PREFIX.sub("", stripped)
            if fragments and fragments[-1]["type"] == "image":
                fragments[-1]["caption"] = _clean(caption)
            else:
                pending_caption = caption
            continue
        if kind == "image":
            data = _image_bytes(document, paragraph)
            if data is None:
                continue
            evidence_id = _fresh("ev")
            evidence[evidence_id] = data
            fragments.append({
                "frag_id": _fresh("f"), "type": "image", "environment": labelled_environment,
                "evidence_id": evidence_id, "caption": "", "width_mm": None,
            })
            continue
        if kind == "instance_title":
            # The environment label and an instance title render from the same component, so the
            # label is only ever recognised by its text.
            if stripped == "PROD:":
                labelled_environment = "production"
                continue
            if stripped == f"{non_production_label.upper()}:":
                labelled_environment = "non_production"
                continue
            if not stripped:
                continue
            # "Instance n:" is the generator's own label, so it is stripped back off on the way in.
            fragments.append({"frag_id": _fresh("f"), "type": "instance_title", "text": INSTANCE_PREFIX.sub("", stripped)})
            continue
        if kind == "code_block":
            if not text.strip():
                continue
            fragments.append({
                "frag_id": _fresh("f"), "type": "code_block",
                "caption": _clean(pending_caption) or None, "text": text,
            })
            pending_caption = ""
            continue
        if kind in ("numbered_list", "bulleted_list"):
            item = {"runs": runs_of(paragraph)}
            if fragments and fragments[-1]["type"] == kind:
                fragments[-1]["items"].append(item)
            else:
                fragments.append({"frag_id": _fresh("f"), "type": kind, "items": [item]})
            continue
        if not text.strip():
            continue
        if kind == "note":
            # The prefix belongs to note_fragment.docx, not to the fragment, so keeping it would
            # render "Note: Note: ..." the next time the report is generated.
            body = re.sub(r"^Note:\s*", "", text)
            fragments.append({"frag_id": _fresh("f"), "type": "note", "runs": [{"text": body}] if body else []})
            continue
        fragments.append({"frag_id": _fresh("f"), "type": "paragraph", "runs": runs_of(paragraph)})
    return fragments


def _find_table(document, header: str):
    for table in document.tables:
        if table.rows and table.rows[0].cells[0].text.strip() == header:
            return table
    return None


def _scope_rows(document, header: str, channel: str) -> list[dict]:
    """Read one scope table, whose rows alternate between an environment name and its values."""
    table = _find_table(document, header)
    targets: list[dict] = []
    if table is None:
        return targets
    environment = None
    for row in table.rows[1:]:
        text = row.cells[0].text.strip()
        if text.endswith("Environment"):
            environment = "production" if text == PRODUCTION_ROW else "non_production"
            continue
        if environment is None:
            continue
        for line in text.splitlines():
            # _wrap_long_value breaks a long target across lines with no marker, so the pieces are
            # rejoined rather than read as separate targets.
            value = _clean(line)
            if value:
                targets.append({
                    "target_id": _fresh("tgt"), "environment": environment, "channel": channel,
                    "value": value, "order": sum(1 for t in targets if t["environment"] == environment),
                })
    return targets


def _summary_rows(document) -> list[dict]:
    table = _find_table(document, "Findings")
    if table is None:
        raise ReportImportError("This document has no findings summary table.")
    rows = []
    for row in table.rows[1:]:
        cells = [cell.text.strip() for cell in row.cells]
        if len(cells) < 6 or not cells[0]:
            continue
        rows.append({
            "title": cells[0], "likelihood": cells[1].lower() or None, "impact": cells[2].lower() or None,
            "severity": cells[3].lower() or "informational", "display_id": cells[4],
            "status": STATUS_BY_LABEL.get(cells[5]),
        })
    return rows


def _detail_locations(table, targets) -> dict:
    """Rebuild a finding's affected locations from its detail table.

    A value that no longer matches a scope target is kept as a typed-in location rather than
    dropped, so nothing the previous test recorded disappears.
    """
    by_value = {(target["environment"], target["value"]): target["target_id"] for target in targets}
    target_ids, custom = [], {}
    for row in table.rows:
        if row.cells[0].text.strip() != "Location":
            continue
        body = row.cells[1].text
        environment = "production" if body.strip().startswith(PRODUCTION_ROW) else "non_production"
        for line in body.splitlines()[1:]:
            value = _clean(line)
            if not value:
                continue
            target_id = by_value.get((environment, value))
            if target_id:
                target_ids.append(target_id)
            else:
                custom.setdefault(environment, {}).setdefault("web", []).append(value)
    return {"mode": "custom", "target_ids": target_ids, "location_values": {}, "custom_locations": custom}


def _empty_proof(scope: dict, targets: list[dict]) -> list[dict]:
    """Build the retest's own proof of concept: somewhere to write and somewhere to paste.

    Stated outright rather than left to `sync_evidence_image_slots`, which measures coverage across
    the whole finding: a carried previous-PoC image would convince it nothing was missing and the
    tester would get no slot at all.
    """
    by_id = {target["target_id"]: target for target in targets}
    environments = []
    for target_id in scope.get("target_ids", []):
        target = by_id.get(target_id)
        if target and target["environment"] not in environments:
            environments.append(target["environment"])
    for environment in scope.get("custom_locations", {}):
        if environment not in environments:
            environments.append(environment)
    fragments = [{"frag_id": _fresh("f"), "type": "numbered_list", "items": [{"runs": []}]}]
    for environment in ("production", "non_production"):
        if environment in environments:
            fragments.append({
                "frag_id": _fresh("f"), "type": "image", "environment": environment,
                "evidence_id": None, "caption": "", "width_mm": None,
            })
    return fragments


def _findings(document, formats, targets, non_production_label, evidence):
    """Walk each finding's body, from its heading to the next one."""
    summary_rows = _summary_rows(document)
    titles = {row["title"] for row in summary_rows}
    body = list(document.element.body.iterchildren())
    starts = []
    for index, element in enumerate(body):
        if element.tag != qn("w:p"):
            continue
        properties = element.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        style_id = style.get(qn("w:val")) if style is not None else ""
        title = " ".join(Paragraph(element, document).text.split())
        if style_id == FINDING_HEADING_STYLE and title in titles:
            starts.append((index, title))

    # Nothing stops two findings sharing a title, so each heading claims the next unclaimed row of
    # that name. Keying the summary by title instead would give both the same finding number.
    unclaimed = list(summary_rows)
    findings, dropped, rewritten = [], [], []
    for position, (index, title) in enumerate(starts):
        stop = len(body)
        for later, _ in starts[position + 1:]:
            stop = later
            break
        for cursor in range(index + 1, stop):
            element = body[cursor]
            if element.tag == qn("w:p"):
                properties = element.find(qn("w:pPr"))
                style = properties.find(qn("w:pStyle")) if properties is not None else None
                if style is not None and style.get(qn("w:val")) == GROUP_HEADING_STYLE:
                    stop = cursor
                    break
        row = next((candidate for candidate in unclaimed if candidate["title"] == title), None)
        if row is None:
            continue
        unclaimed.remove(row)
        if row["status"] not in RETAINED_STATUSES:
            dropped.append(title)
            continue

        detail = None
        sections: dict[str, list] = {}
        current = None
        for element in body[index + 1:stop]:
            if element.tag == qn("w:tbl") and detail is None and current is None:
                detail = next(table for table in document.tables if table._tbl is element)
                continue
            if element.tag == qn("w:p"):
                found = section_of(Paragraph(element, document).text)
                if found:
                    current = found
                    sections.setdefault(current, [])
                    continue
            if current is not None:
                sections[current].append(element)
        for required in ("description", "recommended_remediation", "proof_of_concept"):
            if required not in sections:
                raise ReportImportError(f'"{title}" has no {required.replace("_", " ")} section.')

        # Every retained finding becomes previously discovered: it is the only status that keeps a
        # previous proof of concept, and the recovered steps are exactly that.
        if row["status"] == "open_new":
            rewritten.append(title)
        contents = [
            {"type": "description", "fragments": _build_fragments(document, sections["description"], formats, non_production_label, evidence)},
            {"type": "recommended_remediation", "fragments": _build_fragments(document, sections["recommended_remediation"], formats, non_production_label, evidence)},
            {"type": "previous_proof_of_concept", "fragments": _build_fragments(document, sections["proof_of_concept"], formats, non_production_label, evidence)},
            {"type": "proof_of_concept", "fragments": []},
            {"type": "in_conclusion", "fragments": []},
        ]
        display_id = row["display_id"] if DISPLAY_ID.match(row["display_id"] or "") else None
        scope = _detail_locations(detail, targets) if detail is not None else {"mode": "custom", "target_ids": [], "location_values": {}, "custom_locations": {}}
        contents[3]["fragments"] = _empty_proof(scope, targets)
        findings.append({
            "uid": _fresh("v"), "display_id": display_id, "title": title,
            "likelihood": row["likelihood"], "impact": row["impact"], "severity": row["severity"],
            "status": "open_previously_discovered",
            "scope": scope,
            "contents": contents,
        })
    return findings, dropped, rewritten


def _evidence_records(evidence: dict[str, bytes], uploaded_at: str) -> dict:
    """Describe each extracted image from the bytes themselves.

    The document holds a re-rasterised copy, not the original upload, so the hash and dimensions
    are measured here rather than carried over from whatever the previous report recorded.
    """
    records = {}
    for evidence_id, data in evidence.items():
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        records[evidence_id] = {
            "file": f"evidence/{evidence_id}.png", "original_name": f"{evidence_id}.png",
            "width_px": width, "height_px": height,
            "sha256": hashlib.sha256(data).hexdigest(), "uploaded_at": uploaded_at,
        }
    return records


def parse_report_docx(data: bytes) -> tuple[dict, dict[str, bytes], dict]:
    """Read a generated report into a draft payload, its evidence, and a summary of what changed."""
    try:
        document = Document(BytesIO(data))
    except (PackageNotFoundError, OpcError, zipfile.BadZipFile, KeyError, ValueError) as error:
        raise ReportImportError("This file is not a readable Word document.") from error

    metadata = {}
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) == 2 and cells[0]:
                metadata.setdefault(cells[0], cells[1])

    # The title is the one place the segment and the application name appear as themselves rather
    # than substituted into a sentence: "JH - Northstar Banking - Annual Pentest 2026".
    app_name, segment = "", None
    for paragraph in document.paragraphs[:20]:
        parts = [part.strip() for part in re.split(r"\s[\u2013\u2014-]\s", paragraph.text) if part.strip()]
        if len(parts) >= 3 and parts[0] in ("JH", "GWAM", "Asia"):
            segment, app_name = parts[0], parts[1]
            break

    formats = numbering_formats(document)
    non_production_label = _detect_non_production_label(document)
    targets = _scope_rows(document, "URL(s) in Scope", "web") + _scope_rows(document, "API Routes", "api")
    evidence: dict[str, bytes] = {}
    findings, dropped, rewritten = _findings(document, formats, targets, non_production_label, evidence)

    channels = {target["channel"] for target in targets}
    environments = [
        environment for environment in ("production", "non_production")
        if any(target["environment"] == environment for target in targets)
    ]
    payload = {
        "report_id": "r_placeholder", "app_id": "unnamed",
        "saved_at": datetime.now().astimezone().isoformat(),
        "engagement": {
            "app_name": app_name,
            "app_owner": "",
            "segment": segment,
            "report_type": None,
            "tested_environments": environments or ["production"],
            "tested_channels": [channel for channel in CHANNELS if channel in channels] or ["web"],
            "non_production_label": non_production_label,
            "test_windows": {},
            "report_date": None,
        },
        "scope_targets": targets,
        "vulnerabilities": findings,
        "evidence": _evidence_records(evidence, payload_saved_at := datetime.now().astimezone().isoformat()),
    }
    payload["saved_at"] = payload_saved_at
    summary = {"retained": len(findings), "dropped_resolved": dropped, "statuses_rewritten": rewritten}
    return payload, evidence, summary
