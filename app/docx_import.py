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
from PIL import Image, UnidentifiedImageError

from .models import CHANNELS, COMPONENT_CHANNELS, LEGACY_NON_PRODUCTION_LABELS, NON_PRODUCTION_LABEL_PRESETS
from .report_service import REPORT_TYPE_LABELS, RESOLVED_REMEDIATION, content_types_for_status

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
SEVERITY_TICKET_LABEL = "Severity Review Ticket (if applicable):"
BOILERPLATE = {
    "The following demonstrates the vulnerability:",
    SEVERITY_TICKET_LABEL,
}
STATUS_BY_LABEL = {
    "Open (New)": "open_new",
    "Open (Previously Discovered)": "open_previously_discovered",
    "Open (Resolved on Non-Prod)": "open_resolved_on_non_prod",
    "Resolved": "resolved",
    "Closed": "closed",
}
LABEL_BY_STATUS = {status: label for label, status in STATUS_BY_LABEL.items()}
# A label this app does not know falls back to this rather than refusing the document, so a report
# written by an older version or edited by hand still imports.
FALLBACK_STATUS = "open_previously_discovered"
IMPORT_MODES = {"editable", "retest"}
REPORT_TYPE_BY_LABEL = {label: value for value, label in REPORT_TYPE_LABELS.items()}
FIGURE_PREFIX = re.compile(r"^Figure\s+\d+\s*[.:\-]?\s*")
INSTANCE_PREFIX = re.compile(r"^(?:Instance\s+\d+(?:(?:\s*[:.\-])?(?:\s+|$)))+", re.IGNORECASE)
DISPLAY_ID = re.compile(r"^[0-9]{1,5}$")
PRODUCTION_ROW = "Production Environment"
MAX_IMAGE_WIDTH_MM = 155
# The cover prints a hardcoded word today, so reading it back would return Internal for every
# report, including the External ones. Warn instead of recovering.
NETWORK_IMPORT_WARNING = "Network access was not read from the DOCX; it defaults to Internal -- change it in Setup if this engagement was External."


class ReportImportError(ValueError):
    """Raised when a document is not a report this app can read back."""


class ReportImportLimitError(ReportImportError):
    """Raised when a document exceeds an import resource limit."""


def _fresh(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _clean(value: str) -> str:
    """Map the document's placeholder for "nothing here" back to nothing."""
    text = " ".join(value.split())
    return "" if text == "N/A" else text


def _visible_value(value: str) -> str:
    """Strip field edges while preserving visible whitespace inside user-authored values."""
    text = value.strip()
    return "" if text == "N/A" else text


# Whatever a previous report wrote: prefixed or bare, one per line or comma-separated on one.
TICKET_SEPARATORS = re.compile(r"[\r\n,;]+")
TICKET_PREFIX = re.compile(r"^[A-Za-z]+-")
def _valid_cvss_score(value: str) -> bool:
    """Twin of the save rule: decimal digits and periods only."""
    return bool(value) and all(character.isdecimal() or character == "." for character in value)


def _valid_cvss_vector(value: str) -> bool:
    """Twin of the save rule: letters, decimal digits, periods, slashes and colons only."""
    return bool(value) and all(character.isalpha() or character.isdecimal() or character in "./:" for character in value)


def _parsed_ticket_lines(text: str) -> tuple[str, list[str]]:
    """Normalise a printed ticket list back to the bare digits the draft stores.

    A piece that is not wholly digits once its key is removed is dropped rather than mined for the
    digits inside it: "GRIMPEN-3523 (closed 2024)" must not yield 2024 as a second ticket, because a
    fabricated reference reads as plausibly as a real one and nothing downstream would catch it.
    """
    tickets, invalid = [], []
    for piece in TICKET_SEPARATORS.split(text):
        source = _visible_value(piece)
        if not source:
            continue
        candidate = TICKET_PREFIX.sub("", source)
        # isdecimal, not isdigit: the twin of the save rule's allow_numbers, so no value survives
        # here that would 422 on the next save.
        if candidate.isdecimal():
            tickets.append(candidate)
        else:
            invalid.append(source)
    return "\n".join(tickets), invalid


def _ticket_lines(text: str) -> str:
    return _parsed_ticket_lines(text)[0]


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


def _paragraph_number_id(paragraph) -> str | None:
    properties = paragraph._p.find(qn("w:pPr"))
    numbering = properties.find(qn("w:numPr")) if properties is not None else None
    number_id = numbering.find(qn("w:numId")) if numbering is not None else None
    return number_id.get(qn("w:val")) if number_id is not None else None


def _strip_run_prefix(runs: list[dict], pattern: re.Pattern) -> list[dict]:
    """Remove generated lead-in text without flattening the remaining formatting."""
    match = pattern.match("".join(run["text"] for run in runs))
    remaining = match.end() if match else 0
    stripped = []
    for run in runs:
        item = dict(run)
        if remaining:
            consumed = min(remaining, len(item["text"]))
            item["text"] = item["text"][consumed:]
            remaining -= consumed
        if item["text"]:
            stripped.append(item)
    return stripped


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
    blips = paragraph._p.findall(".//" + qn("a:blip"))
    if len(blips) != 1:
        raise ReportImportError("An evidence image does not have exactly one image relationship.")
    blip = blips[0]
    relationship = blip.get(qn("r:embed"))
    if not relationship:
        raise ReportImportError("An evidence image has no readable relationship.")
    try:
        return document.part.related_parts[relationship].blob
    except KeyError as error:
        raise ReportImportError("An evidence image relationship cannot be resolved.") from error


def _image_width_mm(paragraph, data: bytes) -> float:
    inline = paragraph._p.findall(".//" + qn("wp:inline"))
    if len(inline) != 1 or paragraph._p.findall(".//" + qn("wp:anchor")):
        raise ReportImportError("Editable import supports one inline image per evidence paragraph.")
    extent = inline[0].find(qn("wp:extent"))
    try:
        width, height = int(extent.get("cx")), int(extent.get("cy"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ReportImportError("An evidence image has invalid display dimensions.") from error
    if width <= 0 or height <= 0:
        raise ReportImportError("An evidence image has invalid display dimensions.")
    if width > MAX_IMAGE_WIDTH_MM * 36_000:
        raise ReportImportError(f"Editable import supports evidence widths up to {MAX_IMAGE_WIDTH_MM} mm.")
    transform = inline[0].find(".//" + qn("a:xfrm"))
    if transform is not None and any(transform.get(name) not in (None, "0", "false") for name in ("rot", "flipH", "flipV")):
        raise ReportImportError("Rotated or flipped evidence images are not supported for editable import.")
    source_rectangle = inline[0].find(".//" + qn("a:srcRect"))
    if source_rectangle is not None and any(int(value or 0) for value in source_rectangle.attrib.values()):
        raise ReportImportError("Cropped evidence images are not supported for editable import.")
    try:
        with Image.open(BytesIO(data)) as image:
            pixel_width, pixel_height = image.size
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ReportImportError("A generated report contains an unreadable evidence image.") from error
    if abs(width * pixel_height - height * pixel_width) / max(width * pixel_height, height * pixel_width) > 0.01:
        raise ReportImportError("Distorted evidence images are not supported for editable import.")
    return round(width / 36_000, 2)


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
    return ""


def _build_fragments(document, elements, formats, non_production_label, evidence, mode):
    """Turn one section's body elements back into fragments.

    Captions sit on either side of what they describe: the generator writes a table's and a code
    block's caption *before* them and an image's *after*, so they are attached by position rather
    than assumed.
    """
    fragments: list[dict] = []
    pending_caption = ""
    labelled_environment = None
    active_list_id = None
    last_numbered_id = None
    for element in elements:
        if element.tag == qn("w:tbl"):
            table = next(candidate for candidate in document.tables if candidate._tbl is element)
            fragments.append(_table_fragment(table, pending_caption))
            pending_caption = ""
            active_list_id = None
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
            evidence_id = _fresh("ev")
            evidence[evidence_id] = data
            fragments.append({
                "frag_id": _fresh("f"), "type": "image", "environment": labelled_environment,
                "evidence_id": evidence_id, "caption": "",
                "width_mm": _image_width_mm(paragraph, data) if mode == "editable" else None,
            })
            active_list_id = None
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
            active_list_id = None
            continue
        if kind == "code_block":
            if not text.strip():
                continue
            fragments.append({
                "frag_id": _fresh("f"), "type": "code_block",
                "caption": _clean(pending_caption) or None, "text": text,
            })
            pending_caption = ""
            active_list_id = None
            continue
        if kind in ("numbered_list", "bulleted_list"):
            number_id = _paragraph_number_id(paragraph)
            item = {"runs": runs_of(paragraph)}
            if fragments and fragments[-1]["type"] == kind and active_list_id == number_id:
                fragments[-1]["items"].append(item)
            else:
                fragment = {"frag_id": _fresh("f"), "type": kind, "items": [item]}
                if kind == "numbered_list" and number_id and number_id == last_numbered_id:
                    fragment["continue_numbering"] = True
                fragments.append(fragment)
            active_list_id = number_id
            if kind == "numbered_list":
                last_numbered_id = number_id
            continue
        active_list_id = None
        if not text.strip():
            continue
        if kind == "note":
            # The prefix belongs to note_fragment.docx, not to the fragment, so keeping it would
            # render "Note: Note: ..." the next time the report is generated.
            fragments.append({
                "frag_id": _fresh("f"),
                "type": "note",
                "runs": _strip_run_prefix(runs_of(paragraph), re.compile(r"^Note:\s*")),
            })
            continue
        fragments.append({"frag_id": _fresh("f"), "type": "paragraph", "runs": runs_of(paragraph)})
    return fragments


def _find_table(document, header: str):
    for table in document.tables:
        if table.rows and table.rows[0].cells and table.rows[0].cells[0].text.strip() == header:
            return table
    return None


def _display_date(value: str, label: str) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%B %d, %Y").date().isoformat()
    except ValueError as error:
        raise ReportImportError(f"{label} is not a supported report date: {cleaned}") from error


def _document_texts(document) -> list[str]:
    """Include paragraphs nested in cover-page shapes, which python-docx omits."""
    return [
        "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
        for paragraph in document.element.body.iter(qn("w:p"))
    ]


def _labelled_value(texts: list[str], label: str) -> str:
    values = {
        _clean(texts[index + 1])
        for index, text in enumerate(texts[:-1])
        if text == label and _clean(texts[index + 1])
    }
    if len(values) > 1:
        raise ReportImportError(f'The document contains conflicting values for "{label}".')
    return next(iter(values), "")


def _revision_metadata(document) -> tuple[str | None, str]:
    texts = [text for text in _document_texts(document) if text]
    headings = ["Version", "Modification", "Date", "Author"]
    for index in range(len(texts) - 7):
        if texts[index:index + 4] == headings:
            return _display_date(texts[index + 6], "Report date"), _clean(texts[index + 7])
    return None, ""


def _test_windows(document) -> dict[str, dict]:
    table = _find_table(document, "Environment")
    if table is None:
        return {}
    windows = {}
    for row in table.rows[1:]:
        cells = [cell.text.strip() for cell in row.cells]
        if len(cells) < 4:
            continue
        environment = "production" if cells[0] == "Production" else "non_production" if cells[0] in {"Lower Region", "Non-Production"} else None
        if environment is None:
            continue
        start_date = _display_date(cells[1], f"{cells[0]} start date")
        end_date = _display_date(cells[2], f"{cells[0]} end date")
        test_time = _clean(cells[3])
        if start_date or end_date or test_time:
            windows[environment] = {
                "start_date": start_date,
                "end_date": end_date,
                "test_time": test_time or "Anytime",
            }
    return windows


def _test_accounts(document) -> list[dict]:
    table = _find_table(document, "User Roles")
    if table is None:
        return [{"user_role": "N/A", "username": "N/A"}]
    accounts = []
    for row in table.rows[1:]:
        role, username = (_visible_value(cell.text) for cell in row.cells[:2])
        if role or username:
            accounts.append({"user_role": role or "N/A", "username": username or "N/A"})
    return accounts or [{"user_role": "N/A", "username": "N/A"}]


def _limitations(document) -> str:
    table = _find_table(document, "Limitations")
    if table is None or len(table.rows) < 2:
        return "N/A"
    if not table.rows[1].cells:
        raise ReportImportError("The limitations table has an invalid Limitations row.")
    cell = table.rows[1].cells[0]
    return _visible_value("\n".join(text_of(paragraph) for paragraph in cell.paragraphs)) or "N/A"


def _component_rows(document, observed_environments: list[str], warnings: list[str]) -> list[dict]:
    table = _find_table(document, "Component")
    if table is None:
        return []
    texts = _document_texts(document)
    channels = [
        channel
        for channel, marker in (("mobile", "Mobile Application Binary"), ("thick_client", "Thick Client Application Binary"))
        if any(marker in text for text in texts)
    ]
    values = []
    for row in table.rows[1:]:
        if len(row.cells) < 2:
            raise ReportImportError("The component scope table has an invalid Component row.")
        value = _visible_value("".join(text_of(paragraph).replace("\n", "") for paragraph in row.cells[0].paragraphs))
        description = _visible_value("\n".join(text_of(paragraph) for paragraph in row.cells[1].paragraphs))
        if value:
            values.append((value, description))
    if not values:
        return []
    if len(channels) != 1:
        raise ReportImportError("The component report does not identify exactly one supported app type.")
    environment = observed_environments[0] if len(observed_environments) == 1 else "production"
    targets = []
    for order, (value, description) in enumerate(values):
        targets.append({
            "target_id": _fresh("tgt"),
            "environment": environment,
            "channel": channels[0],
            "value": value,
            "description": description,
            "order": order,
        })
        if len(observed_environments) != 1:
            warnings.append(
                f'Review the environment for component "{value}"; the DOCX does not encode the boundary, so it was assigned to Production.'
            )
    return targets


def _editable_engagement(
    document,
    app_name,
    segment,
    report_type,
    targets,
    non_production_label,
    windows,
    evidence_environments,
    warnings,
):
    texts = _document_texts(document)
    report_date, tester = _revision_metadata(document)
    channels = [channel for channel in CHANNELS if any(target["channel"] == channel for target in targets)]
    if not channels:
        channels = ["web"]
        warnings.append("No app type was visible in the DOCX; review the default Web selection.")
    environments = [
        environment for environment in ("production", "non_production")
        if environment in windows or environment in evidence_environments
        or any(target["environment"] == environment for target in targets)
    ]
    if not environments:
        environments = ["production"]
        warnings.append("No tested environment was visible in the DOCX; review the default Production selection.")
    if "non_production" in environments and not non_production_label:
        warnings.append("The non-production label was not visible in the DOCX; review the default NON-PROD label.")
    return {
        "app_name": app_name,
        "app_owner": _labelled_value(texts, "Delivered To"),
        "segment": segment,
        "report_type": report_type,
        "tested_environments": environments,
        "tested_channels": channels,
        "non_production_label": non_production_label or NON_PRODUCTION_LABEL_PRESETS[0],
        "test_windows": windows,
        "test_accounts": _test_accounts(document),
        "limitations": _limitations(document),
        "tester": tester,
        "report_date": report_date,
    }


def _scope_rows(document, header: str, channel: str) -> list[dict]:
    """Read one scope table, whose rows alternate between an environment name and its values."""
    table = _find_table(document, header)
    targets: list[dict] = []
    if table is None:
        return targets
    environment = None
    for row in table.rows[1:]:
        if not row.cells:
            raise ReportImportError(f"The scope table has an invalid {header} row.")
        text = row.cells[0].text.strip()
        if text.endswith("Environment"):
            environment = "production" if text == PRODUCTION_ROW else "non_production"
            continue
        if environment is None:
            continue
        for paragraph in row.cells[0].paragraphs:
            # The renderer inserts visual line breaks inside one paragraph when a target wraps.
            value = _visible_value(text_of(paragraph).replace("\n", ""))
            if value:
                targets.append({
                    "target_id": _fresh("tgt"), "environment": environment, "channel": channel,
                    "value": value, "description": "",
                    "order": sum(1 for t in targets if t["environment"] == environment),
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
            "status": STATUS_BY_LABEL.get(cells[5], FALLBACK_STATUS), "status_label": cells[5],
        })
    return rows


def _is_finding_detail_table(table) -> bool:
    if any(
        row.cells and row.cells[0].text.strip() == "Location" and len(row.cells) < 2
        for row in table.rows
    ):
        raise ReportImportError("A finding detail table has an invalid Location row.")
    labels = [row.cells[0].text.strip() for row in table.rows if row.cells]
    return all(label in labels for label in ("Severity", "ID", "Status", "Location"))


def _observed_environments(document, windows: dict, targets: list[dict]) -> list[str]:
    observed = set(windows) | {target["environment"] for target in targets}
    for table in document.tables:
        if not _is_finding_detail_table(table):
            continue
        for row in table.rows:
            if not row.cells or row.cells[0].text.strip() != "Location":
                continue
            paragraphs = [text_of(paragraph).strip() for paragraph in row.cells[1].paragraphs]
            if not any(_visible_value(value) for value in paragraphs[1:]):
                continue
            heading = paragraphs[0] if paragraphs else ""
            if heading.startswith(PRODUCTION_ROW):
                observed.add("production")
            elif heading.endswith("Environment:"):
                observed.add("non_production")
    evidence_labels = {paragraph.text.strip().upper() for paragraph in document.paragraphs}
    if "PROD:" in evidence_labels:
        observed.add("production")
    if any(f"{label}:" in evidence_labels for label in (*NON_PRODUCTION_LABEL_PRESETS, *LEGACY_NON_PRODUCTION_LABELS)):
        observed.add("non_production")
    return [environment for environment in ("production", "non_production") if environment in observed]


def _detail_locations(table, targets, warnings, title) -> dict:
    """Rebuild a finding's affected locations from its detail table.

    Ambiguous values become ordinary selected targets. That keeps them visible on Setup and
    Findings and lets the normal first-save reconciliation preserve their IDs.
    """
    target_ids = []
    for row in table.rows:
        if not row.cells or row.cells[0].text.strip() != "Location":
            continue
        paragraphs = ["".join(text_of(paragraph).splitlines()).strip() for paragraph in row.cells[1].paragraphs]
        heading = paragraphs[0] if paragraphs else ""
        if heading.startswith(PRODUCTION_ROW):
            environment = "production"
        elif heading.endswith("Environment:"):
            environment = "non_production"
        else:
            raise ReportImportError(f'"{title}" has an unsupported location heading.')
        for paragraph in paragraphs[1:]:
            value = _visible_value(paragraph)
            if not value:
                continue
            matches = [
                target for target in targets
                if target["environment"] == environment and target["value"] == value
            ]
            if matches:
                target = min(matches, key=lambda item: CHANNELS.index(item["channel"]))
                if len(matches) > 1:
                    warnings.append(
                        f'{title}: review the app type for "{value}"; it appears in more than one scope table and was assigned to {target["channel"].replace("_", " ")}.'
                    )
            else:
                covered = {target["channel"] for target in targets}
                channel = next((candidate for candidate in CHANNELS if candidate in covered), "web")
                target = {
                    "target_id": _fresh("tgt"),
                    "environment": environment,
                    "channel": channel,
                    "value": value,
                    "description": "",
                    "order": sum(
                        1 for candidate in targets
                        if candidate["environment"] == environment and candidate["channel"] == channel
                    ),
                }
                targets.append(target)
                warnings.append(
                    f'{title}: review the app type for "{value}"; it was added to {channel.replace("_", " ")} scope.'
                )
            if target["target_id"] not in target_ids:
                target_ids.append(target["target_id"])
    return {"mode": "custom", "target_ids": target_ids, "location_values": {}, "custom_locations": {}}


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


def _findings(document, formats, targets, non_production_label, evidence, mode, warnings):
    """Walk each finding's body, from its heading to the next one."""
    summary_rows = _summary_rows(document)
    # Named rather than refused: the tester can see which findings were assumed and correct them.
    for row in summary_rows:
        if row["status_label"] not in STATUS_BY_LABEL:
            warnings.append(
                f'"{row["title"]}" had an unrecognised status '
                f'({row["status_label"] or "blank"}) and was imported as {LABEL_BY_STATUS[FALLBACK_STATUS]}.'
            )
    body = list(document.element.body.iterchildren())
    summary_table = _find_table(document, "Findings")
    summary_index = body.index(summary_table._tbl)
    starts = []
    for index, element in enumerate(body[summary_index + 1:], start=summary_index + 1):
        if element.tag != qn("w:p"):
            continue
        properties = element.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        style_id = style.get(qn("w:val")) if style is not None else ""
        title = " ".join(Paragraph(element, document).text.split())
        if style_id == GROUP_HEADING_STYLE and title.startswith("Appendix:"):
            break
        if style_id == FINDING_HEADING_STYLE:
            starts.append((index, title))

    # Nothing stops two findings sharing a title, so each heading claims the next unclaimed row of
    # that name. Keying the summary by title instead would give both the same finding number.
    unclaimed = list(summary_rows)
    # Absent from three of the four templates, so a missing table is normal and never an error.
    cvss_table = _find_table(document, "Section")
    if cvss_table is not None and any(len(row.cells) < 5 for row in cvss_table.rows[1:]):
        raise ReportImportError("The CVSS table has an invalid Section row.")
    unclaimed_cvss = list(cvss_table.rows[1:]) if cvss_table is not None else []
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
            raise ReportImportError(f'Finding detail "{title}" has no matching summary row.')
        unclaimed.remove(row)
        # Claimed before the Resolved drop, so a dropped finding consumes its own row rather than
        # leaving it for the next title to match. Never by index: the table carries a row per
        # rendered finding while this function omits every Resolved one.
        cvss_row = next((candidate for candidate in unclaimed_cvss if _clean(candidate.cells[1].text) == title), None)
        if cvss_row is not None:
            unclaimed_cvss.remove(cvss_row)
        cvss_score, cvss_vector = "", ""
        if cvss_row is not None:
            score, vector = _visible_value(cvss_row.cells[3].text), _visible_value(cvss_row.cells[4].text)
            if mode == "editable" and score and not _valid_cvss_score(score):
                raise ReportImportError(f'"{title}" has an invalid CVSS score.')
            if mode == "editable" and vector and not _valid_cvss_vector(vector):
                raise ReportImportError(f'"{title}" has an invalid CVSS vector.')
            cvss_score = score if _valid_cvss_score(score) else ""
            cvss_vector = vector if _valid_cvss_vector(vector) else ""

        detail = None
        sections: dict[str, list] = {}
        current = None
        section_order = []
        tickets = ""
        awaiting_tickets = False
        for element in body[index + 1:stop]:
            if element.tag == qn("w:tbl") and current is None:
                table = next(table for table in document.tables if table._tbl is element)
                if _is_finding_detail_table(table):
                    if detail is not None:
                        raise ReportImportError(f'"{title}" has more than one finding detail table.')
                    detail = table
                continue
            if element.tag == qn("w:p"):
                paragraph = Paragraph(element, document)
                found = section_of(paragraph.text)
                if found:
                    if found in sections:
                        raise ReportImportError(f'"{title}" has more than one {found.replace("_", " ")} section.')
                    current = found
                    section_order.append(found)
                    awaiting_tickets = False
                    sections.setdefault(current, [])
                    continue
                # The label and its value both stop here, or they reach in_conclusion as fragments.
                if " ".join(paragraph.text.split()) == SEVERITY_TICKET_LABEL:
                    awaiting_tickets = True
                    continue
                if awaiting_tickets:
                    # runs_of, not paragraph.text: the value's lines are w:br, which text drops.
                    value = "".join(run["text"] for run in runs_of(paragraph))
                    if not value.strip():
                        continue
                    tickets, invalid_tickets = _parsed_ticket_lines(value)
                    if mode == "editable" and invalid_tickets:
                        raise ReportImportError(f'"{title}" has an invalid severity review ticket.')
                    awaiting_tickets = False
                    continue
            if current is not None:
                sections[current].append(element)
        expected_sections = ["description", "recommended_remediation", "proof_of_concept"]
        if row["status"] != "open_new":
            expected_sections = [
                "description", "recommended_remediation", "previous_proof_of_concept",
                "proof_of_concept", "in_conclusion",
            ]
        # A status this app assumed tells us nothing about the shape, so either is accepted and the
        # document decides. Without this the structure check refuses before the status ever matters.
        if row["status_label"] not in STATUS_BY_LABEL and section_order == [
            "description", "recommended_remediation", "proof_of_concept",
        ]:
            expected_sections = section_order
        if section_order != expected_sections:
            raise ReportImportError(
                f'"{title}" does not have the expected section structure for '
                f'{row["status_label"] or LABEL_BY_STATUS[row["status"]]}.'
            )
        if detail is None:
            raise ReportImportError(f'"{title}" has no finding detail table.')
        detail_values = {
            cells[0]: cells[1]
            for table_row in detail.rows
            if len(cells := [cell.text.strip() for cell in table_row.cells]) >= 2
        }
        repeated = {
            "Severity": row["severity"].title(),
            "ID": row["display_id"],
        }
        if any(_clean(detail_values.get(label, "")) != _clean(value) for label, value in repeated.items()):
            raise ReportImportError(f'"{title}" summary and detail values do not match.')
        # Compared only when both cells name a status this app knows. Either one unrecognised means
        # the status was assumed, so there is nothing to disagree about and the document still
        # imports. Two known labels that differ is a real inconsistency, and still refuses.
        detail_status_label = _clean(detail_values.get("Status", ""))
        if (
            row["status_label"] in STATUS_BY_LABEL
            and detail_status_label in STATUS_BY_LABEL
            and STATUS_BY_LABEL[detail_status_label] != row["status"]
        ):
            raise ReportImportError(f'"{title}" summary and detail values do not match.')

        local_evidence: dict[str, bytes] = {}
        source_contents = [
            {
                "type": content_type,
                "fragments": _build_fragments(
                    document,
                    sections[content_type],
                    formats,
                    non_production_label,
                    local_evidence,
                    mode,
                ),
            }
            for content_type in expected_sections
        ]
        working_targets = list(targets)
        local_warnings = []
        scope = _detail_locations(detail, working_targets, local_warnings, title)

        if mode == "retest" and row["status"] in ("resolved", "closed"):
            dropped.append(title)
            continue

        if mode == "editable":
            # Provisioning will rebuild this finding to the shape its status implies, and the
            # projection check refuses the import if what we hand over differs -- in order, not just
            # in membership. Only a fallback finding can be short here.
            by_type = {content["type"]: content for content in source_contents}
            source_contents = [
                by_type.get(content_type, {"type": content_type, "fragments": []})
                for content_type in content_types_for_status(row["status"])
            ]
            contents = source_contents
            status = row["status"]
            if status == "resolved":
                remediation = next(content for content in contents if content["type"] == "recommended_remediation")
                fragments = remediation["fragments"]
                text = "".join(
                    run["text"]
                    for fragment in fragments if fragment["type"] == "paragraph"
                    for run in fragment["runs"]
                )
                if len(fragments) != 1 or fragments[0]["type"] != "paragraph" or text != RESOLVED_REMEDIATION:
                    raise ReportImportError(f'"{title}" has edited remediation while Resolved.')
                fragments[0]["generated"] = "resolved_remediation"
        else:
            # A retest keeps last year's status, because the distinction it carries is exactly what
            # this year re-tests. Only Open (New) is meaningless on a retest and becomes previously
            # discovered; Resolved and Closed never reach here at all.
            if row["status"] == "open_new":
                rewritten.append(title)
            source_by_type = {content["type"]: content for content in source_contents}
            contents = [
                source_by_type["description"],
                source_by_type["recommended_remediation"],
                {"type": "previous_proof_of_concept", "fragments": source_by_type["proof_of_concept"]["fragments"]},
                {"type": "proof_of_concept", "fragments": []},
                {"type": "in_conclusion", "fragments": []},
            ]
            status = "open_previously_discovered" if row["status"] == "open_new" else row["status"]
        targets[:] = working_targets
        warnings.extend(local_warnings)
        used_evidence = {
            fragment["evidence_id"]
            for content in contents
            for fragment in content["fragments"]
            if fragment["type"] == "image" and fragment["evidence_id"]
        }
        evidence.update({evidence_id: local_evidence[evidence_id] for evidence_id in used_evidence})
        if mode == "editable" and row["display_id"] and not DISPLAY_ID.match(row["display_id"]):
            raise ReportImportError(f'"{title}" has an invalid finding ID.')
        display_id = row["display_id"] if DISPLAY_ID.match(row["display_id"] or "") else None
        if mode == "retest":
            contents[3]["fragments"] = _empty_proof(scope, targets)
        findings.append({
            "uid": _fresh("v"), "display_id": display_id, "title": title,
            "likelihood": row["likelihood"], "impact": row["impact"], "severity": row["severity"],
            "status": status,
            "scope": scope,
            "severity_review_tickets": tickets,
            "cvss_score": cvss_score,
            "cvss_vector": cvss_vector,
            "contents": contents,
        })
    if unclaimed:
        raise ReportImportError("The findings summary and detail sections do not match.")
    if unclaimed_cvss:
        raise ReportImportError("The CVSS table and finding detail sections do not match.")
    return findings, dropped, rewritten


def _evidence_records(
    evidence: dict[str, bytes],
    uploaded_at: str,
    *,
    max_image_bytes: int,
    max_image_pixels: int,
    max_total_bytes: int,
) -> dict:
    """Describe each extracted image from the bytes themselves.

    The document holds a re-rasterised copy, not the original upload, so the hash and dimensions
    are measured here rather than carried over from whatever the previous report recorded.
    """
    records = {}
    total_bytes = 0
    for evidence_id, data in evidence.items():
        if len(data) > max_image_bytes:
            raise ReportImportLimitError("An evidence image exceeds the configured byte limit.")
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise ReportImportLimitError("Imported evidence exceeds the configured report limit.")
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format != "PNG":
                    raise ReportImportError("Generated report evidence must be PNG.")
                width, height = image.size
                if width * height > max_image_pixels:
                    raise ReportImportLimitError("An evidence image exceeds the configured pixel limit.")
                image.verify()
        except Image.DecompressionBombError as error:
            raise ReportImportLimitError("An evidence image exceeds the configured pixel limit.") from error
        except (UnidentifiedImageError, OSError) as error:
            raise ReportImportError("A generated report contains an unreadable evidence image.") from error
        records[evidence_id] = {
            "file": f"evidence/{evidence_id}.png", "original_name": f"{evidence_id}.png",
            "width_px": width, "height_px": height,
            "sha256": hashlib.sha256(data).hexdigest(), "uploaded_at": uploaded_at,
        }
    return records


def parse_report_docx(
    data: bytes,
    mode: str = "retest",
    *,
    max_package_bytes: int = 100 * 1024 * 1024,
    max_files: int = 1000,
    max_uncompressed_bytes: int = 250 * 1024 * 1024,
    max_image_bytes: int = 20 * 1024 * 1024,
    max_image_pixels: int = 40_000_000,
    max_evidence_bytes: int = 250 * 1024 * 1024,
) -> tuple[dict, dict[str, bytes], dict]:
    """Read a generated report into a draft payload, its evidence, and a summary of what changed."""
    if mode not in IMPORT_MODES:
        raise ReportImportError(f"Unknown DOCX import mode: {mode}")
    if len(data) > max_package_bytes:
        raise ReportImportLimitError("The Word document exceeds the configured upload limit.")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            names = [info.filename for info in infos]
            media_infos = [info for info in infos if info.filename.startswith("word/media/")]
            if len(infos) > max_files:
                raise ReportImportLimitError("The Word document contains too many files.")
            if len(names) != len(set(names)):
                raise ReportImportError("The Word document contains duplicate paths.")
            if any(info.flag_bits & 1 for info in infos):
                raise ReportImportError("Encrypted Word documents are not supported.")
            if sum(info.file_size for info in infos) > max_uncompressed_bytes:
                raise ReportImportLimitError("The expanded Word document exceeds the configured limit.")
            if any(info.file_size > max_image_bytes for info in media_infos):
                raise ReportImportLimitError("An embedded media file exceeds the configured byte limit.")
            if sum(info.file_size for info in media_infos) > max_evidence_bytes:
                raise ReportImportLimitError("Embedded media exceeds the configured report limit.")
    except zipfile.BadZipFile as error:
        raise ReportImportError("This file is not a readable Word document.") from error
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
    app_name, segment, report_type = "", None, None
    for paragraph in document.paragraphs[:20]:
        parts = [part.strip() for part in re.split(r"\s[\u2013\u2014-]\s", paragraph.text) if part.strip()]
        if len(parts) >= 3 and parts[0] in ("JH", "GWAM", "Asia", "GDT"):
            segment, app_name = parts[0], " - ".join(parts[1:-1])
            label = re.sub(r"\s+\d{4}$", "", parts[-1])
            report_type = REPORT_TYPE_BY_LABEL.get(label)
            if mode == "editable" and report_type is None:
                raise ReportImportError(f"Unknown report type: {label}")
            break

    formats = numbering_formats(document)
    detected_non_production_label = _detect_non_production_label(document)
    non_production_label = detected_non_production_label or NON_PRODUCTION_LABEL_PRESETS[0]
    windows = _test_windows(document) if mode == "editable" else {}
    warnings: list[str] = []
    targets = _scope_rows(document, "URL(s) in Scope", "web") + _scope_rows(document, "API Routes", "api")
    targets += _component_rows(document, _observed_environments(document, windows, targets), warnings)
    evidence: dict[str, bytes] = {}
    findings, dropped, rewritten = _findings(document, formats, targets, non_production_label, evidence, mode, warnings)
    evidence_environments = {
        fragment["environment"]
        for finding in findings
        for content in finding["contents"]
        for fragment in content["fragments"]
        if fragment["type"] == "image" and fragment["environment"]
    }

    channels = {target["channel"] for target in targets}
    environments = [
        environment for environment in ("production", "non_production")
        if any(target["environment"] == environment for target in targets)
    ]
    engagement = {
        "app_name": app_name,
        "app_owner": "",
        "segment": segment,
        "report_type": None,
        "tested_environments": environments or ["production"],
        "tested_channels": [channel for channel in CHANNELS if channel in channels] or ["web"],
        "non_production_label": non_production_label,
        "test_windows": {},
        "report_date": None,
    }
    if mode == "editable":
        engagement = _editable_engagement(
            document, app_name, segment, report_type, targets, detected_non_production_label,
            windows, evidence_environments, warnings,
        )
    # After the branch, so the default retest path warns too. The cover prints a hardcoded word
    # today, so reading it back would return Internal for every report including External ones.
    warnings.append(NETWORK_IMPORT_WARNING)
    payload = {
        "report_id": "r_placeholder", "app_id": "unnamed",
        "saved_at": datetime.now().astimezone().isoformat(),
        "engagement": engagement,
        "scope_targets": targets,
        "vulnerabilities": findings,
        "evidence": _evidence_records(
            evidence,
            payload_saved_at := datetime.now().astimezone().isoformat(),
            max_image_bytes=max_image_bytes,
            max_image_pixels=max_image_pixels,
            max_total_bytes=max_evidence_bytes,
        ),
    }
    payload["saved_at"] = payload_saved_at
    referenced_evidence = {
        fragment["evidence_id"]
        for finding in findings
        for content in finding["contents"]
        for fragment in content["fragments"]
        if fragment["type"] == "image" and fragment["evidence_id"]
    }
    if referenced_evidence != set(payload["evidence"]) or referenced_evidence != set(evidence):
        raise ReportImportError("Imported evidence ownership is inconsistent.")
    summary = {
        "retained": len(findings),
        # Holds Closed findings too. Kept under this name because a half-landed rename fails
        # silently: the manager reads `summary.dropped_resolved || []` and the notice just vanishes.
        "dropped_resolved": dropped,
        "statuses_rewritten": rewritten,
    }
    if mode == "editable":
        summary.update({
            "status_counts": {
                status: sum(1 for finding in findings if finding["status"] == status)
                for status in STATUS_BY_LABEL.values()
            },
            "sections_imported": sum(len(finding["contents"]) for finding in findings),
            "evidence_imported": len(evidence),
            "restored_engagement": [
                "application", "owner", "segment", "report type", "report date", "tester",
                "test windows", "accounts", "limitations", "scope",
            ],
            "warnings": warnings + ([
            "Imported images are rendered Word copies and may be resampled or receive another border when regenerated."
            ] if evidence else []),
        })
    elif warnings:
        summary["warnings"] = warnings
    return payload, evidence, summary
