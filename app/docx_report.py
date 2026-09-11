from __future__ import annotations

import re
from copy import deepcopy
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.parts.hdrftr import FooterPart, HeaderPart
from docx.shared import Mm, Pt, RGBColor
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph
from PIL import Image, ImageOps

from app.models import (
    CodeFragment,
    Content,
    ImageFragment,
    InstanceTitleFragment,
    ListFragment,
    NoteFragment,
    ParagraphFragment,
    Report,
    Run,
    TableFragment,
    Vulnerability,
)
from .docx_captions import add_native_image_captions
from .docx_components import (
    RATING_FONT_COLORS,
    clone_component_elements,
    replace_component_token,
    replace_component_token_runs,
    replace_pattern_across_text_nodes,
)
from .report_service import REPORT_TYPE_LABELS, affected_environments, finding_is_complete, setup_issues

SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational"]
SEVERITY_HEADINGS = {
    "critical": "CRITICAL FINDINGS",
    "high": "HIGH FINDINGS",
    "medium": "MEDIUM FINDINGS",
    "low": "LOW FINDINGS",
    "informational": "INFORMATIONAL FINDINGS",
}
SEVERITY_COLORS = {
    "critical": "BD292E",
    "high": "DF720B",
    "medium": "E7B925",
    "low": "39895A",
    "informational": "7D8CA3",
}
STATUS_LABELS = {
    "open_new": "Open (New)",
    "open_previously_discovered": "Open (Previously Discovered)",
    "resolved": "Resolved",
}
PLAIN_METADATA_TOKENS = {"app-name", "app-owner", "tester-name", "report-name"}
UNRESOLVED_MARKERS = (
    "-vuln",
    "-affected-location",
    "-fragments-here",
    "-step-1-here",
    "-step-2-here",
    "-images-and-caption-here",
    "brief-explanation-here",
)
PLACEHOLDER_TEXT = re.compile(
    r"\(\s*insert[^)]*\)|insert\s+(technology|version|eol\s+date|cves|latest)\s+\w*\s*here|\[value_taken_from",
    re.IGNORECASE,
)
CELL_PLACEHOLDER = re.compile(r"\{\{\s*[^{}]+?\s*\}\}")
SEVERITY_COMPONENT_FILES = {
    "critical": "critical_severity.docx",
    "high": "high_severity.docx",
    "medium": "medium_severity.docx",
    "low": "low_severity.docx",
    "informational": "informatinal_severity.docx",
}
FRAGMENT_COMPONENT_FILES = {
    "paragraph": ("paragraph_fragment.docx", "paragraph-fragment"),
    "numbered_list": ("numbered_fragment.docx", "numbered-list-fragment"),
    "bulleted_list": ("bulleted_fragment.docx", "bullet-list-fragment"),
    "note": ("note_fragment.docx", "note-fragment"),
    "code_block": ("code_fragment.docx", "code-fragment"),
    "instance_title": ("instance_fragment.docx", "instance-fragment"),
    "caption": ("caption_fragment.docx", "caption-fragment"),
}
DEFAULT_IMAGE_FRAGMENT_TEMPLATE = Path(__file__).resolve().parent.parent / "resources" / "fragments" / "image_fragment.docx"
IMAGE_BORDER_RASTER_DPI = 192


class ReportGenerationError(ValueError):
    """Raised when a report cannot be rendered safely into the template."""


def generation_issues(report: Report) -> list[str]:
    """Return report-completeness issues that should block final DOCX output."""
    issues = setup_issues(report)
    if not report.vulnerabilities:
        issues.append("at least one finding")
    for finding in report.vulnerabilities:
        label = finding.title or "Untitled finding"
        if not finding_is_complete(finding, report):
            issues.append(f"{label}: finding details or affected locations are incomplete")
        images = [
            fragment
            for content in finding.contents
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment)
        ]
        for environment in affected_environments(finding, report):
            if not any(image.environment == environment and image.evidence_id for image in images):
                issues.append(f"{label}: {'Production' if environment == 'production' else 'Non-Production'} evidence image required")
        for content in finding.contents:
            for fragment in content.fragments:
                if isinstance(fragment, (ParagraphFragment, NoteFragment)) and not _runs_have_text(fragment.runs):
                    issues.append(f"{label}: {content.type} text is required")
                elif isinstance(fragment, ListFragment) and any(not _runs_have_text(item.runs) for item in fragment.items):
                    issues.append(f"{label}: {content.type} list item text is required")
                elif isinstance(fragment, ImageFragment):
                    missing = []
                    if not fragment.environment:
                        missing.append("environment")
                    if not fragment.evidence_id:
                        missing.append("image")
                    if not fragment.caption.strip():
                        missing.append("caption")
                    if missing:
                        issues.append(f"{label}: {'/'.join(missing)} required for image fragment")
                elif isinstance(fragment, (CodeFragment, InstanceTitleFragment)) and not fragment.text.strip():
                    issues.append(f"{label}: {fragment.type} text is required")
                elif isinstance(fragment, TableFragment):
                    cells = [*fragment.header, *(cell for row in fragment.rows for cell in row)]
                    if not cells or any(not _runs_have_text(cell.runs) for cell in cells):
                        issues.append(f"{label}: every table cell is required")
                if PLACEHOLDER_TEXT.search(_fragment_text(fragment)):
                    issues.append(f"{label}: replace placeholder text in {content.type}")
    return list(dict.fromkeys(issues))


def render_report_docx(
    report: Report,
    template_path: Path,
    report_folder: Path,
    *,
    allow_incomplete: bool = False,
    validation_issues: list[str] | None = None,
) -> bytes:
    """Render a validated report into the supplied canonical DOCX template."""
    if not template_path.is_file():
        raise ReportGenerationError(f"Template not found: {template_path}")
    issues = generation_issues(report) if validation_issues is None else validation_issues
    if issues and not allow_incomplete:
        raise ReportGenerationError("; ".join(issues))

    document = Document(template_path)
    _normalize_page_numbering(document)
    _populate_scope_tables(document, report)
    _populate_summary_table(document, report)
    _replace_metadata(document, report)
    if _has_exact_body_token(document, "findings"):
        _populate_component_findings(
            document,
            report,
            report_folder,
            template_path.parent,
            allow_incomplete,
        )
    else:
        _populate_finding_sections(document, report, report_folder, allow_incomplete)
    add_native_image_captions(document)
    unresolved = _unresolved_placeholders(document)
    if unresolved:
        raise ReportGenerationError(f"Unresolved template placeholders: {', '.join(unresolved)}")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _runs_have_text(runs: list[Run]) -> bool:
    return any(run.text.strip() for run in runs)


def _fragment_text(fragment) -> str:
    if isinstance(fragment, (ParagraphFragment, NoteFragment)):
        return "".join(run.text for run in fragment.runs)
    if isinstance(fragment, ListFragment):
        return " ".join(run.text for item in fragment.items for run in item.runs)
    if isinstance(fragment, TableFragment):
        cells = [*fragment.header, *(cell for row in fragment.rows for cell in row)]
        return " ".join(run.text for cell in cells for run in cell.runs)
    if isinstance(fragment, ImageFragment):
        return fragment.caption
    if isinstance(fragment, (CodeFragment, InstanceTitleFragment)):
        return fragment.text
    return ""


def _display_date(value) -> str:
    return f"{value:%B} {value.day}, {value.year}" if value else "N/A"


def _display_value(value: str | None) -> str:
    return value.strip() if value and value.strip() else "N/A"


def _target_values(report: Report, environment: str, channel: str) -> list[str]:
    return [
        target.value
        for target in sorted(report.scope_targets, key=lambda item: item.order)
        if target.environment == environment and target.channel == channel
    ]


def _metadata(report: Report) -> dict[str, str]:
    engagement = report.engagement
    production = engagement.test_windows.get("production")
    non_production = engagement.test_windows.get("non_production")
    accounts = engagement.test_accounts
    values = {
        "segment": engagement.segment or "N/A",
        "app-name": _display_value(engagement.app_name),
        "report-name": _display_value(engagement.app_name),
        "test-type": REPORT_TYPE_LABELS.get(engagement.report_type or "", "N/A"),
        "app-owner": _display_value(engagement.app_owner),
        "report-date": _display_date(engagement.report_date),
        "tester-name": _display_value(engagement.tester),
        "non-prod-start": _display_date(non_production.start_date if non_production else None),
        "non-prod-end": _display_date(non_production.end_date if non_production else None),
        "non-prod-time": _display_value(non_production.test_time if non_production else None),
        "prod-start": _display_date(production.start_date if production else None),
        "prod-end": _display_date(production.end_date if production else None),
        "prod-time": _display_value(production.test_time if production else None),
        "prod-web": "; ".join(_target_values(report, "production", "web")) or "N/A",
        "non-prod-web": "; ".join(_target_values(report, "non_production", "web")) or "N/A",
        "prod-api": "; ".join(_target_values(report, "production", "api")) or "N/A",
        "non-prod-api": "; ".join(_target_values(report, "non_production", "api")) or "N/A",
        "limitation-set": _display_value(engagement.limitations),
    }
    for index in range(2):
        account = accounts[index] if index < len(accounts) else None
        values[f"role{index + 1}"] = _display_value(account.user_role if account else None)
        values[f"username{index + 1}"] = _display_value(account.username if account else None)
    return values


def _document_roots(document: DocumentType):
    yield document.element
    for part in document.part.package.parts:
        if isinstance(part, (HeaderPart, FooterPart)):
            yield part._element


def _replace_metadata(document: DocumentType, report: Report) -> None:
    for token, value in sorted(_metadata(report).items(), key=lambda item: len(item[0]), reverse=True):
        escaped = re.escape(token)
        patterns = [re.compile(r"\{\{\s*" + escaped + r"\s*\}\}", re.IGNORECASE)]
        if token in PLAIN_METADATA_TOKENS:
            patterns.append(re.compile(r"(?<![\w-])" + escaped + r"(?![\w-])", re.IGNORECASE))
        for root in _document_roots(document):
            for paragraph in root.iter(qn("w:p")):
                for pattern in patterns:
                    replace_pattern_across_text_nodes(paragraph, pattern, value)


def _replace_cell_placeholder(
    cell,
    value: str,
    *,
    font_color: RGBColor | None = None,
    font_size_pt: int | None = None,
) -> None:
    paragraphs = [
        paragraph
        for paragraph in cell._tc.iter(qn("w:p"))
        if CELL_PLACEHOLDER.search("".join(node.text or "" for node in paragraph.iter(qn("w:t"))))
    ]
    if len(paragraphs) != 1:
        raise ReportGenerationError(
            f"Expected exactly one placeholder in summary cell; found {len(paragraphs)}"
        )
    replace_pattern_across_text_nodes(
        paragraphs[0],
        CELL_PLACEHOLDER,
        value,
        font_color,
        font_size_pt,
    )


def _find_table(document: DocumentType, header: str) -> Table:
    for table in document.tables:
        if table.rows and table.rows[0].cells and table.rows[0].cells[0].text.strip().casefold() == header.casefold():
            return table
    raise ReportGenerationError(f"Template table not found: {header}")


def _clear_paragraph(paragraph: Paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def _set_paragraph_runs(paragraph: Paragraph, runs: list[Run] | None = None, text: str | None = None) -> None:
    _clear_paragraph(paragraph)
    if text is not None:
        paragraph.add_run(text)
        return
    for source in runs or []:
        run = paragraph.add_run(source.text)
        run.bold = source.bold
        run.italic = source.italic
        run.underline = source.underline


def _set_cell_lines(cell, lines: list[str], *, label: str | None = None) -> None:
    paragraphs = cell.paragraphs
    first = paragraphs[0]
    paragraph_style = first.style
    for paragraph in paragraphs[1:]:
        cell._tc.remove(paragraph._p)
    _clear_paragraph(first)
    # An added paragraph inherits the style but not the template paragraph's direct
    # formatting, so every line after the first would lose its alignment and indent.
    template_properties = first._p.find(qn("w:pPr"))
    if label:
        first.add_run(label).bold = True
    values = lines or ["N/A"]
    for index, value in enumerate(values):
        if index == 0 and not label:
            paragraph = first
        else:
            paragraph = cell.add_paragraph(style=paragraph_style)
            if template_properties is not None:
                existing = paragraph._p.find(qn("w:pPr"))
                if existing is not None:
                    paragraph._p.remove(existing)
                paragraph._p.insert(0, deepcopy(template_properties))
        paragraph.add_run(value if label is None else f"• {value}")


def _center_plain(cell) -> None:
    """The scope cells use a bullet-list style, so a placeholder needs the plain style to lose its bullet."""
    for paragraph in cell.paragraphs:
        paragraph.style = "Normal"
        properties = paragraph._p.find(qn("w:pPr"))
        if properties is not None:
            for tag in ("w:numPr", "w:ind"):
                for element in properties.findall(qn(tag)):
                    properties.remove(element)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _populate_scope_tables(document: DocumentType, report: Report) -> None:
    engagement = report.engagement
    web = _find_table(document, "URL(s) in Scope")
    _set_cell_lines(web.cell(2, 0), _target_values(report, "production", "web"))
    _set_cell_lines(web.cell(4, 0), _target_values(report, "non_production", "web"))
    api = _find_table(document, "API Routes")
    _set_cell_lines(api.cell(2, 0), _target_values(report, "production", "api"))
    _set_cell_lines(api.cell(4, 0), _target_values(report, "non_production", "api"))
    limitations = _find_table(document, "Limitations")
    limitation_text = _display_value(engagement.limitations)
    _set_cell_lines(limitations.cell(1, 0), [limitation_text])
    if limitation_text.casefold() in {"n/a", "na"}:
        _center_plain(limitations.cell(1, 0))

    accounts = _find_table(document, "User Roles")
    prototype = deepcopy(accounts.rows[1]._tr)
    for row in list(accounts.rows)[1:]:
        accounts._tbl.remove(row._tr)
    for account in engagement.test_accounts or []:
        row_element = deepcopy(prototype)
        accounts._tbl.append(row_element)
        row = _Row(row_element, accounts)
        _set_cell_lines(row.cells[0], [_display_value(account.user_role)])
        _set_cell_lines(row.cells[1], [_display_value(account.username)])
    if len(accounts.rows) == 1:
        row_element = deepcopy(prototype)
        accounts._tbl.append(row_element)
        row = _Row(row_element, accounts)
        _set_cell_lines(row.cells[0], ["N/A"])
        _set_cell_lines(row.cells[1], ["N/A"])


def _populate_summary_table(document: DocumentType, report: Report) -> None:
    table = _find_table(document, "Findings")
    generic_prototype = len(table.rows) == 2 and "{{finding}}" in table.rows[1].cells[0].text.casefold()
    if generic_prototype:
        prototype = deepcopy(table.rows[1]._tr)
        prototypes = {severity: prototype for severity in SEVERITY_ORDER}
    else:
        prototypes = {
            severity: deepcopy(table.rows[index + 1]._tr)
            for index, severity in enumerate(SEVERITY_ORDER)
        }
    for row in list(table.rows)[1:]:
        table._tbl.remove(row._tr)
    for finding in sorted(report.vulnerabilities, key=lambda item: (SEVERITY_ORDER.index(item.severity or "informational"), item.title.casefold())):
        severity = finding.severity or "informational"
        row_element = deepcopy(prototypes[severity])
        table._tbl.append(row_element)
        row = _Row(row_element, table)
        likelihood = finding.likelihood or "informational"
        impact = finding.impact or "informational"
        values = [
            (finding.title, None),
            (likelihood.title(), RATING_FONT_COLORS[likelihood]),
            (impact.title(), RATING_FONT_COLORS[impact]),
            (severity.title(), RATING_FONT_COLORS[severity]),
            (finding.display_id or finding.uid, None),
            (STATUS_LABELS[finding.status], None),
        ]
        for cell, (value, font_color) in zip(row.cells, values):
            _replace_cell_placeholder(
                cell,
                value,
                font_color=font_color,
                font_size_pt=12 if font_color is not None else None,
            )


def _element_text(element) -> str:
    return re.sub(r"\s+", " ", "".join(node.text or "" for node in element.iter(qn("w:t")))).strip()


def _has_exact_body_token(document: DocumentType, token: str) -> bool:
    pattern = re.compile(r"\{\{\s*" + re.escape(token) + r"\s*\}\}", re.IGNORECASE)
    return any(
        element.tag == qn("w:p") and pattern.fullmatch(_element_text(element))
        for element in document.element.body.iterchildren()
    )


def _find_body_element(document: DocumentType, text: str):
    for element in document.element.body.iterchildren():
        if _element_text(element).casefold() == text.casefold():
            return element
    raise ReportGenerationError(f"Template block not found: {text}")


def _normalize_page_numbering(document: DocumentType) -> None:
    body = document.element.body
    document_order = list(body.iter())
    revision_index = document_order.index(_find_body_element(document, "DOCUMENT REVISION HISTORY"))
    section_properties = [
        properties
        for properties in body.iter(qn("w:sectPr"))
        if not any(ancestor.tag == qn("w:sectPrChange") for ancestor in properties.iterancestors())
    ]
    revision_section = next(
        properties
        for properties in section_properties
        if document_order.index(properties) > revision_index
    )
    revision_reached = False
    for properties in section_properties:
        page_numbering = properties.find(qn("w:pgNumType"))
        if properties is revision_section:
            revision_reached = True
            if page_numbering is None:
                page_numbering = OxmlElement("w:pgNumType")
                properties.append(page_numbering)
            page_numbering.set(qn("w:start"), "1")
        elif revision_reached and page_numbering is not None:
            page_numbering.attrib.pop(qn("w:start"), None)
            if not page_numbering.attrib and not len(page_numbering):
                properties.remove(page_numbering)


def _populate_component_findings(
    document: DocumentType,
    report: Report,
    report_folder: Path,
    component_root: Path,
    allow_incomplete: bool,
) -> None:
    body_elements = list(document.element.body.iterchildren())
    anchor_index = _component_anchor_index(body_elements, "findings")
    anchor = body_elements[anchor_index]
    for severity in SEVERITY_ORDER:
        findings = sorted(
            (item for item in report.vulnerabilities if item.severity == severity),
            key=lambda item: item.title.casefold(),
        )
        if not findings:
            continue
        severity_elements = clone_component_elements(
            document,
            component_root / "severity_titles" / SEVERITY_COMPONENT_FILES[severity],
        )
        finding_anchor = _component_anchor_index(severity_elements, "finding_title")
        rendered_findings = []
        for index, finding in enumerate(findings):
            finding_elements = _render_finding_component(
                document,
                finding,
                report,
                report_folder,
                component_root,
                allow_incomplete,
            )
            if index:
                first_paragraph = next(
                    (element for element in finding_elements if element.tag == qn("w:p")),
                    None,
                )
                if first_paragraph is not None:
                    _set_page_break_before(first_paragraph)
            rendered_findings.extend(finding_elements)
        severity_elements = [
            *severity_elements[:finding_anchor],
            *rendered_findings,
            *severity_elements[finding_anchor + 1:],
        ]
        heading = next(
            (element for element in severity_elements if element.tag == qn("w:p")),
            None,
        )
        if heading is not None:
            _set_page_break_before(heading)
        for element in severity_elements:
            anchor.addprevious(element)
    anchor.getparent().remove(anchor)


def _render_finding_component(
    document: DocumentType,
    finding: Vulnerability,
    report: Report,
    report_folder: Path,
    component_root: Path,
    allow_incomplete: bool,
) -> list:
    template_name = "new_finding.docx" if finding.status == "open_new" else "retest_finding.docx"
    elements = clone_component_elements(
        document,
        component_root / "finding_types" / template_name,
    )
    locations = _finding_locations(report, finding)
    values = {
        "finding_title": finding.title,
        "vuln_severity": (finding.severity or "informational").title(),
        "vuln_id": finding.display_id or finding.uid,
        "status": STATUS_LABELS[finding.status],
        "severity-review-tickets": "N/A",
    }
    for token, value in values.items():
        replace_component_token(elements, token, value)
    for token, location_values in (
        ("prod_affected_locations", locations["production"]),
        ("non-prod-affected-locations", locations["non_production"]),
    ):
        replace_component_token_runs(
            elements,
            token,
            [Run(text="\n".join(f"• {value}" for value in location_values) or "N/A")],
        )

    contents = {content.type: content for content in finding.contents}
    anchors = {
        "description-fragments-here": contents.get("description"),
        "recommended-remediation-fragments-here": contents.get("recommended_remediation"),
        "poc-fragments-here": contents.get("proof_of_concept"),
    }
    if finding.status != "open_new":
        anchors.update({
            "prev-poc-fragments-here": contents.get("previous_proof_of_concept"),
            "conclusion-fragments-here": contents.get("in_conclusion"),
        })
    for anchor, content in anchors.items():
        rendered = _render_component_content(
            document,
            content,
            report,
            report_folder,
            component_root,
            allow_incomplete,
        )
        elements = _replace_component_anchor(elements, anchor, rendered)
    return elements


def _render_component_content(
    document: DocumentType,
    content: Content | None,
    report: Report,
    report_folder: Path,
    component_root: Path,
    allow_incomplete: bool,
) -> list:
    if content is None or not content.fragments:
        rendered = _render_text_component(
            document,
            component_root,
            "paragraph",
            [Run(text="N/A")],
        )
    else:
        rendered = []
        for fragment in content.fragments:
            rendered.extend(
                _render_component_fragment(
                    document,
                    fragment,
                    report,
                    report_folder,
                    component_root,
                    allow_incomplete,
                )
            )
    return _trim_trailing_empty_paragraphs(rendered)


def _render_component_fragment(
    document: DocumentType,
    fragment,
    report: Report,
    report_folder: Path,
    component_root: Path,
    allow_incomplete: bool,
) -> list:
    if isinstance(fragment, ParagraphFragment):
        return _render_text_component(document, component_root, "paragraph", fragment.runs)
    if isinstance(fragment, NoteFragment):
        return _render_text_component(document, component_root, "note", fragment.runs)
    if isinstance(fragment, ListFragment):
        component_type = "numbered_list" if fragment.type == "numbered_list" else "bulleted_list"
        filename, token = FRAGMENT_COMPONENT_FILES[component_type]
        numbering_ids: dict[tuple[Path, int], int] = {}
        rendered = []
        for item in fragment.items:
            elements = clone_component_elements(
                document,
                component_root / "fragments" / filename,
                numbering_ids=numbering_ids,
            )
            replace_component_token_runs(elements, token, item.runs)
            rendered.extend(elements)
        return rendered
    if isinstance(fragment, CodeFragment):
        rendered = _render_caption_component(document, component_root, fragment.caption)
        rendered.extend(
            _render_text_component(
                document,
                component_root,
                "code_block",
                [Run(text=fragment.text)],
            )
        )
        return rendered
    if isinstance(fragment, InstanceTitleFragment):
        return _render_text_component(
            document,
            component_root,
            "instance_title",
            [Run(text=fragment.text)],
        )
    if isinstance(fragment, TableFragment):
        return _render_table_component(document, fragment, component_root)
    if isinstance(fragment, ImageFragment):
        return _render_image_component(
            document,
            fragment,
            report,
            report_folder,
            component_root,
            allow_incomplete,
        )
    return []


def _render_text_component(
    document: DocumentType,
    component_root: Path,
    component_type: str,
    runs: list[Run],
) -> list:
    filename, token = FRAGMENT_COMPONENT_FILES[component_type]
    elements = clone_component_elements(document, component_root / "fragments" / filename)
    replace_component_token_runs(elements, token, runs)
    return elements


def _trim_trailing_empty_paragraphs(elements: list) -> list:
    end = len(elements)
    while end and _is_empty_component_paragraph(elements[end - 1]):
        end -= 1
    return elements[:end]


def _is_empty_component_paragraph(element) -> bool:
    return (
        element.tag == qn("w:p")
        and not _element_text(element)
        and not any(True for _ in element.iter(qn("w:drawing")))
        and not any(True for _ in element.iter(qn("w:pict")))
        and not any(True for _ in element.iter(qn("w:br")))
    )


def _render_caption_component(
    document: DocumentType,
    component_root: Path,
    caption: str | None,
) -> list:
    if not caption:
        return []
    return _render_text_component(
        document,
        component_root,
        "caption",
        [Run(text=caption)],
    )


def _render_image_component(
    document: DocumentType,
    fragment: ImageFragment,
    report: Report,
    report_folder: Path,
    component_root: Path,
    allow_incomplete: bool,
) -> list:
    evidence = report.evidence.get(fragment.evidence_id or "")
    if evidence is None:
        if not allow_incomplete:
            raise ReportGenerationError(f"Missing evidence for image fragment {fragment.frag_id}")
        return _render_text_component(
            document,
            component_root,
            "paragraph",
            [Run(text=f"[Evidence image not attached: {_display_value(fragment.caption)}]")],
        )
    path = report_folder / evidence.file
    if not path.is_file():
        raise ReportGenerationError(f"Evidence file not found: {evidence.file}")
    image_elements = _render_text_component(document, component_root, "paragraph", [])
    paragraph_element = next(element for element in image_elements if element.tag == qn("w:p"))
    paragraph = Paragraph(paragraph_element, document._body)
    image_width_mm = min(fragment.width_mm or 155, 155)
    image_template = component_root / "fragments" / "image_fragment.docx"
    picture = paragraph.add_run().add_picture(
        _bordered_image_stream(path, image_width_mm, image_template),
        width=Mm(image_width_mm),
    )
    _apply_image_fragment_format(
        picture,
        paragraph,
        image_template,
    )
    image_elements = _trim_trailing_empty_paragraphs(image_elements)
    return [
        *image_elements,
        *_render_caption_component(document, component_root, _display_value(fragment.caption)),
    ]


def _render_table_component(
    document: DocumentType,
    fragment: TableFragment,
    component_root: Path,
) -> list:
    rendered = _render_caption_component(document, component_root, fragment.caption)
    elements = clone_component_elements(
        document,
        component_root / "fragments" / "table_fragment.docx",
    )
    table_element = next(
        (element for element in elements if element.tag == qn("w:tbl")),
        None,
    )
    if table_element is None:
        raise ReportGenerationError("table_fragment.docx must contain one table")
    source_rows = list(table_element.iterchildren(qn("w:tr")))
    if len(source_rows) != 2:
        raise ReportGenerationError("table_fragment.docx must contain header and body prototype rows")
    source_widths = [
        int(column.get(qn("w:w")))
        for column in table_element.tblGrid.iterchildren(qn("w:gridCol"))
    ]
    if not source_widths:
        raise ReportGenerationError("table_fragment.docx must define a column grid")
    columns = max([len(fragment.header), *(len(row) for row in fragment.rows), 1])
    widths = source_widths if columns == len(source_widths) else _equal_component_widths(sum(source_widths), columns)
    for row in source_rows:
        table_element.remove(row)
    _set_component_table_grid(table_element, widths)
    if fragment.header:
        table_element.append(_resize_component_row(source_rows[0], widths))
    for _ in fragment.rows:
        table_element.append(_resize_component_row(source_rows[1], widths))
    table = Table(table_element, document._body)
    table.autofit = False
    row_offset = 0
    if fragment.header:
        for index, cell in enumerate(table.rows[0].cells):
            runs = fragment.header[index].runs if index < len(fragment.header) else []
            replace_component_token_runs([cell._tc], "table-header-cell", runs)
        row_offset = 1
    for row_index, row in enumerate(table.rows[row_offset:]):
        source_row = fragment.rows[row_index]
        for column_index, cell in enumerate(row.cells):
            runs = source_row[column_index].runs if column_index < len(source_row) else []
            replace_component_token_runs([cell._tc], "table-body-cell", runs)
    rendered.append(table_element)
    return rendered


def _equal_component_widths(total_width: int, columns: int) -> list[int]:
    width, remainder = divmod(total_width, columns)
    return [width + (1 if index < remainder else 0) for index in range(columns)]


def _set_component_table_grid(table, widths: list[int]) -> None:
    grid = table.tblGrid
    for column in list(grid.iterchildren(qn("w:gridCol"))):
        grid.remove(column)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)
    table_width = table.tblPr.find(qn("w:tblW"))
    if table_width is None:
        table_width = OxmlElement("w:tblW")
        table.tblPr.insert(0, table_width)
    table_width.set(qn("w:type"), "dxa")
    table_width.set(qn("w:w"), str(sum(widths)))
    layout = table.tblPr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        table.tblPr.append(layout)
    layout.set(qn("w:type"), "fixed")


def _resize_component_row(source_row, widths: list[int]):
    row = deepcopy(source_row)
    source_cells = list(source_row.iterchildren(qn("w:tc")))
    if not source_cells:
        raise ReportGenerationError("table_fragment.docx contains a prototype row without cells")
    for cell in list(row.iterchildren(qn("w:tc"))):
        row.remove(cell)
    preserve_columns = len(source_cells) == len(widths)
    for index, width in enumerate(widths):
        source_cell = source_cells[index] if preserve_columns else source_cells[min(index, len(source_cells) - 1)]
        cell = deepcopy(source_cell)
        properties = cell.find(qn("w:tcPr"))
        if properties is None:
            properties = OxmlElement("w:tcPr")
            cell.insert(0, properties)
        cell_width = properties.find(qn("w:tcW"))
        if cell_width is None:
            cell_width = OxmlElement("w:tcW")
            properties.insert(0, cell_width)
        cell_width.set(qn("w:type"), "dxa")
        cell_width.set(qn("w:w"), str(width))
        row.append(cell)
    return row


def _replace_component_anchor(elements: list, token: str, replacements: list) -> list:
    index = _component_anchor_index(elements, token)
    return [*elements[:index], *replacements, *elements[index + 1:]]


def _component_anchor_index(elements: list, token: str) -> int:
    pattern = re.compile(r"\{\{\s*" + re.escape(token) + r"\s*\}\}", re.IGNORECASE)
    matches = [
        index
        for index, element in enumerate(elements)
        if element.tag == qn("w:p") and pattern.fullmatch(_element_text(element))
    ]
    if len(matches) != 1:
        raise ReportGenerationError(
            f"Expected exactly one {{{{{token}}}}} component anchor; found {len(matches)}"
        )
    return matches[0]


def _populate_finding_sections(document: DocumentType, report: Report, report_folder: Path, allow_incomplete: bool) -> None:
    body = document.element.body
    severity_headings = {severity: _find_body_element(document, heading) for severity, heading in SEVERITY_HEADINGS.items()}
    appendix = _find_body_element(document, "Appendix: Common Vulnerability Scoring System (CVSS)")
    high_heading = severity_headings["high"]
    medium_heading = severity_headings["medium"]
    prototype = []
    current = high_heading.getnext()
    while current is not medium_heading:
        prototype.append(deepcopy(current))
        current = current.getnext()

    current = severity_headings["critical"]
    while current is not appendix:
        following = current.getnext()
        body.remove(current)
        current = following

    for severity in SEVERITY_ORDER:
        findings = sorted((item for item in report.vulnerabilities if item.severity == severity), key=lambda item: item.title.casefold())
        if not findings:
            continue
        appendix.addprevious(deepcopy(severity_headings[severity]))
        for index, finding in enumerate(findings):
            elements = [deepcopy(element) for element in prototype]
            elements = _populate_finding_block(document, elements, finding, report, report_folder, allow_incomplete)
            if index:
                _set_page_break_before(next(element for element in elements if _paragraph_style(element) == "ReportHeading2"))
            for element in elements:
                appendix.addprevious(element)


def _paragraph_style(element) -> str:
    if element.tag != qn("w:p"):
        return ""
    properties = element.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    return style.get(qn("w:val"), "") if style is not None else ""


def _set_page_break_before(paragraph_element) -> None:
    paragraph_properties = paragraph_element.find(qn("w:pPr"))
    if paragraph_properties is None:
        paragraph_properties = OxmlElement("w:pPr")
        paragraph_element.insert(0, paragraph_properties)
    if paragraph_properties.find(qn("w:pageBreakBefore")) is None:
        paragraph_properties.append(OxmlElement("w:pageBreakBefore"))


def _populate_finding_block(
    document: DocumentType,
    elements: list,
    finding: Vulnerability,
    report: Report,
    report_folder: Path,
    allow_incomplete: bool,
) -> list:
    content = {item.type: item for item in finding.contents}
    if "previous_proof_of_concept" not in content:
        elements = _remove_range(elements, "Previous Proof of Concept:", "Proof of Concept:")
    if "in_conclusion" not in content:
        elements = _remove_range(elements, "In Conclusion:", "Severity Review Ticket (if applicable):")

    title = next(element for element in elements if _paragraph_style(element) == "ReportHeading2")
    _set_paragraph_runs(Paragraph(title, document._body), text=finding.title)
    detail_element = next(element for element in elements if element.tag == qn("w:tbl"))
    detail = Table(detail_element, document._body)
    _set_cell_lines(detail.cell(0, 1), [(finding.severity or "informational").title()])
    _shade_cell(detail.cell(0, 1), SEVERITY_COLORS[finding.severity or "informational"])
    _set_cell_lines(detail.cell(1, 1), [finding.display_id or finding.uid])
    _set_cell_lines(detail.cell(2, 1), [STATUS_LABELS[finding.status]])
    locations = _finding_locations(report, finding)
    _set_cell_lines(detail.cell(3, 1), locations["production"], label="Production Environment:")
    _set_cell_lines(detail.cell(4, 1), locations["non_production"], label="Lower Region Environment:")

    elements = _replace_fragment_anchor(document, elements, "description-fragments-here", content.get("description"), report, report_folder, allow_incomplete)
    elements = _replace_fragment_anchor(document, elements, "recommended-remediation-fragments-here", content.get("recommended_remediation"), report, report_folder, allow_incomplete)
    if "previous_proof_of_concept" in content:
        elements = _replace_fragment_anchor(document, elements, "previous-proof-of-concept-step", content["previous_proof_of_concept"], report, report_folder, allow_incomplete, exclude_images=True)
        elements = _replace_image_anchor(document, elements, "previous-poc-prod-images-and-caption-here", content["previous_proof_of_concept"], "production", report, report_folder, allow_incomplete)
        elements = _replace_image_anchor(document, elements, "previous-poc-non-prod-images-and-caption-here", content["previous_proof_of_concept"], "non_production", report, report_folder, allow_incomplete)
    elements = _replace_fragment_anchor(document, elements, "proof-of-concept-step", content.get("proof_of_concept"), report, report_folder, allow_incomplete, exclude_images=True)
    elements = _replace_image_anchor(document, elements, "prod-images-and-caption-here", content.get("proof_of_concept"), "production", report, report_folder, allow_incomplete)
    elements = _replace_image_anchor(document, elements, "non-prod-images-and-caption-here", content.get("proof_of_concept"), "non_production", report, report_folder, allow_incomplete)
    if "in_conclusion" in content:
        elements = _replace_fragment_anchor(document, elements, "brief-explanation-here", content["in_conclusion"], report, report_folder, allow_incomplete)
    return elements


def _remove_range(elements: list, start_text: str, end_text: str) -> list:
    start = next(index for index, element in enumerate(elements) if _element_text(element).casefold() == start_text.casefold())
    end = next(index for index, element in enumerate(elements) if index > start and _element_text(element).casefold() == end_text.casefold())
    return elements[:start] + elements[end:]


def _finding_locations(report: Report, finding: Vulnerability) -> dict[str, list[str]]:
    values = {"production": [], "non_production": []}
    targets = {target.target_id: target for target in report.scope_targets}
    if finding.scope.mode == "custom":
        for target_id in finding.scope.target_ids:
            target = targets.get(target_id)
            if target:
                values[target.environment].append(finding.scope.location_values.get(target_id, target.value))
        for environment, custom in finding.scope.custom_locations.items():
            values[environment].extend(value for value in custom if value.strip())
    else:
        environments = {
            "all": {"production", "non_production"},
            "all_production": {"production"},
            "all_non_production": {"non_production"},
        }[finding.scope.mode]
        for target in sorted(report.scope_targets, key=lambda item: item.order):
            if target.environment in environments:
                values[target.environment].append(target.value)
    return values


def _shade_cell(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.bold = True


def _replace_fragment_anchor(
    document: DocumentType,
    elements: list,
    marker: str,
    content: Content | None,
    report: Report,
    report_folder: Path,
    allow_incomplete: bool,
    *,
    exclude_images: bool = False,
) -> list:
    indices = [index for index, element in enumerate(elements) if marker in _element_text(element).casefold()]
    if not indices:
        return elements
    anchor = elements[indices[0]]
    fragments = [] if content is None else [fragment for fragment in content.fragments if not exclude_images or not isinstance(fragment, ImageFragment)]
    rendered = []
    for fragment in fragments:
        rendered.extend(_render_fragment(document, anchor, fragment, report, report_folder, allow_incomplete))
    if not rendered:
        rendered.append(_new_paragraph(document, anchor, text="N/A"))
    return [
        *elements[:indices[0]],
        *rendered,
        *(element for index, element in enumerate(elements[indices[0] + 1:], start=indices[0] + 1) if index not in indices),
    ]


def _replace_image_anchor(
    document: DocumentType,
    elements: list,
    marker: str,
    content: Content | None,
    environment: str,
    report: Report,
    report_folder: Path,
    allow_incomplete: bool,
) -> list:
    anchor_index = next((index for index, element in enumerate(elements) if marker in _element_text(element).casefold()), None)
    if anchor_index is None:
        return elements
    images = [] if content is None else [fragment for fragment in content.fragments if isinstance(fragment, ImageFragment) and fragment.environment == environment]
    label_index = next((index for index in range(anchor_index - 1, -1, -1) if _element_text(elements[index]).casefold() in {"prod:", "non-prod:"}), None)
    if not images:
        remove = {anchor_index}
        if label_index is not None:
            remove.add(label_index)
        return [element for index, element in enumerate(elements) if index not in remove]
    if label_index is not None:
        label = Paragraph(elements[label_index], document._body)
        for run in label.runs:
            run.bold = True
    rendered = []
    for image in images:
        rendered.extend(_render_image(document, elements[anchor_index], image, report, report_folder, allow_incomplete))
    return [*elements[:anchor_index], *rendered, *elements[anchor_index + 1:]]


def _render_fragment(document: DocumentType, anchor, fragment, report: Report, report_folder: Path, allow_incomplete: bool) -> list:
    if isinstance(fragment, ParagraphFragment):
        return [
            _new_paragraph(document, anchor, runs=fragment.runs),
            _new_paragraph(document, anchor),
        ]
    if isinstance(fragment, NoteFragment):
        paragraph = _new_paragraph(document, anchor, style="Intense Quote")
        wrapper = Paragraph(paragraph, document._body)
        wrapper.add_run("Note: ").bold = True
        _append_runs(wrapper, fragment.runs)
        return [paragraph]
    if isinstance(fragment, ListFragment):
        rendered = []
        for index, item in enumerate(fragment.items):
            paragraph = _new_paragraph(document, anchor, style="List Paragraph")
            wrapper = Paragraph(paragraph, document._body)
            wrapper.add_run(f"{index + 1}. " if fragment.type == "numbered_list" else "• ").bold = fragment.type == "numbered_list"
            _append_runs(wrapper, item.runs)
            rendered.append(paragraph)
        return rendered
    if isinstance(fragment, InstanceTitleFragment):
        paragraph = _new_paragraph(document, anchor, text=fragment.text, style="Normal")
        for run in Paragraph(paragraph, document._body).runs:
            run.bold = True
        return [paragraph]
    if isinstance(fragment, CodeFragment):
        rendered = []
        if fragment.caption:
            rendered.append(_new_paragraph(document, anchor, text=fragment.caption, style="Caption"))
        paragraph = _new_paragraph(document, anchor, text=fragment.text, style="Normal")
        wrapper = Paragraph(paragraph, document._body)
        for run in wrapper.runs:
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        properties = wrapper._p.get_or_add_pPr()
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "F1F4F8")
        properties.append(shading)
        return [*rendered, paragraph]
    if isinstance(fragment, TableFragment):
        rendered = []
        if fragment.caption:
            rendered.append(_new_paragraph(document, anchor, text=fragment.caption, style="Caption"))
        rows = max(1, len(fragment.rows)) + (1 if fragment.header else 0)
        columns = max([len(fragment.header), *(len(row) for row in fragment.rows), 1])
        table = document.add_table(rows=rows, cols=columns)
        try:
            table.style = "PentestReport"
        except KeyError:
            table.style = "Table Grid"
        document.element.body.remove(table._tbl)
        row_offset = 0
        if fragment.header:
            for index, cell in enumerate(fragment.header):
                _set_cell_runs(table.cell(0, index), cell.runs, bold=True)
            row_offset = 1
        for row_index, source_row in enumerate(fragment.rows):
            for column_index, cell in enumerate(source_row):
                _set_cell_runs(table.cell(row_index + row_offset, column_index), cell.runs)
        rendered.append(table._tbl)
        return rendered
    if isinstance(fragment, ImageFragment):
        return _render_image(document, anchor, fragment, report, report_folder, allow_incomplete)
    return []


def _new_paragraph(document: DocumentType, anchor, *, text: str | None = None, runs: list[Run] | None = None, style: str | None = None):
    paragraph = document.add_paragraph()
    document.element.body.remove(paragraph._p)
    if style:
        paragraph.style = style
    else:
        source_properties = anchor.find(qn("w:pPr"))
        if source_properties is not None:
            current = paragraph._p.find(qn("w:pPr"))
            if current is not None:
                paragraph._p.remove(current)
            paragraph._p.insert(0, deepcopy(source_properties))
    if text is not None:
        paragraph.add_run(text)
    else:
        _append_runs(paragraph, runs or [])
    return paragraph._p


def _append_runs(paragraph: Paragraph, runs: list[Run]) -> None:
    for source in runs:
        run = paragraph.add_run(source.text)
        run.bold = source.bold
        run.italic = source.italic
        run.underline = source.underline


def _set_cell_runs(cell, runs: list[Run], *, bold: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        cell._tc.remove(extra._p)
    _clear_paragraph(paragraph)
    for source in runs:
        run = paragraph.add_run(source.text)
        run.bold = bold or source.bold
        run.italic = source.italic
        run.underline = source.underline


def _render_image(document: DocumentType, anchor, fragment: ImageFragment, report: Report, report_folder: Path, allow_incomplete: bool) -> list:
    evidence = report.evidence.get(fragment.evidence_id or "")
    if evidence is None:
        if not allow_incomplete:
            raise ReportGenerationError(f"Missing evidence for image fragment {fragment.frag_id}")
        return [_new_paragraph(document, anchor, text=f"[Evidence image not attached: {_display_value(fragment.caption)}]", style="Intense Quote")]
    path = report_folder / evidence.file
    if not path.is_file():
        raise ReportGenerationError(f"Evidence file not found: {evidence.file}")
    paragraph_element = _new_paragraph(document, anchor, style="Normal")
    paragraph = Paragraph(paragraph_element, document._body)
    image_width_mm = min(fragment.width_mm or 155, 155)
    picture = paragraph.add_run().add_picture(
        _bordered_image_stream(path, image_width_mm, DEFAULT_IMAGE_FRAGMENT_TEMPLATE),
        width=Mm(image_width_mm),
    )
    _apply_image_fragment_format(picture, paragraph, DEFAULT_IMAGE_FRAGMENT_TEMPLATE)
    caption = _new_paragraph(document, anchor, text=_display_value(fragment.caption), style="Caption")
    Paragraph(caption, document._body).alignment = WD_ALIGN_PARAGRAPH.CENTER
    return [paragraph_element, caption]


def _bordered_image_stream(path: Path, width_mm: float, template_path: Path) -> BytesIO:
    source_line, source_alignment = _cached_image_fragment_format(
        str(template_path.resolve()),
        template_path.stat().st_mtime_ns,
    )
    del source_alignment
    border_width_inches = int(source_line.get("w") or Pt(0.75)) / 914400
    display_width_inches = width_mm / 25.4
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    minimum_width = round(display_width_inches * IMAGE_BORDER_RASTER_DPI)
    if image.width < minimum_width:
        image = image.resize(
            (minimum_width, max(1, round(image.height * minimum_width / image.width))),
            Image.Resampling.LANCZOS,
        )
    border_fraction = border_width_inches / display_width_inches
    border_pixels = max(1, round(image.width * border_fraction / (1 - 2 * border_fraction)))
    bordered = ImageOps.expand(image, border=border_pixels, fill="black")
    stream = BytesIO()
    bordered.save(stream, format="PNG")
    stream.seek(0)
    return stream


def _apply_image_fragment_format(picture, paragraph: Paragraph, template_path: Path) -> None:
    source_line, source_alignment = _cached_image_fragment_format(
        str(template_path.resolve()),
        template_path.stat().st_mtime_ns,
    )
    del source_line
    properties = picture._inline.graphic.graphicData.pic.spPr
    line = properties.find(qn("a:ln"))
    if line is not None:
        properties.remove(line)
    paragraph_properties = paragraph._p.get_or_add_pPr()
    alignment = paragraph_properties.find(qn("w:jc"))
    if alignment is not None:
        paragraph_properties.remove(alignment)
    paragraph_properties.append(deepcopy(source_alignment))


@lru_cache(maxsize=8)
def _cached_image_fragment_format(template_path: str, modified_at: int):
    del modified_at
    document = Document(template_path)
    if len(document.inline_shapes) != 1:
        raise ReportGenerationError("image_fragment.docx must contain exactly one inline image")
    source_picture = document.inline_shapes[0]._inline.graphic.graphicData.pic
    source_line = source_picture.spPr.find(qn("a:ln"))
    source_paragraph = next(
        (paragraph for paragraph in document.paragraphs if any(True for _ in paragraph._p.iter(qn("w:drawing")))),
        None,
    )
    source_alignment = (
        source_paragraph._p.pPr.find(qn("w:jc"))
        if source_paragraph is not None and source_paragraph._p.pPr is not None
        else None
    )
    if source_line is None or source_alignment is None:
        raise ReportGenerationError("image_fragment.docx must define an image border and paragraph alignment")
    return deepcopy(source_line), deepcopy(source_alignment)


def _unresolved_placeholders(document: DocumentType) -> list[str]:
    text = "\n".join(_element_text(root) for root in _document_roots(document))
    unresolved = set(re.findall(r"\{\{.*?\}\}", text))
    lower = text.casefold()
    unresolved.update(marker for marker in UNRESOLVED_MARKERS if marker in lower)
    return sorted(unresolved)