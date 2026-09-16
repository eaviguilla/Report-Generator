from __future__ import annotations

import re
import shutil
import threading
from contextlib import suppress
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .storage import atomic_write_bytes


CAPTION_STYLE_NAMES = ("Figures and Tables", "Caption")
MANUAL_FIGURE_PREFIX = re.compile(r"^\s*Figure\s+\d+\s*[:.\-]?\s*", re.IGNORECASE)
FIGURE_SEQUENCE = re.compile(r"\bSEQ\s+Figure\b", re.IGNORECASE)
# Word stores font size in half-points, so 9pt is 18.
CAPTION_HALF_POINTS = "18"
WORD_AUTOMATION_LOCK = threading.Lock()
WD_MAIN_TEXT_STORY = 1
WD_GO_TO_PAGE = 1
WD_GO_TO_ABSOLUTE = 1
WD_STATISTIC_PAGES = 2
WD_WITHIN_TABLE = 12


def postprocess_image_captions(input_path: Path, output_path: Path | None = None) -> tuple[Path, int]:
    """Convert image-adjacent caption text into native Word SEQ Figure fields."""
    document = Document(input_path)
    converted = add_native_image_captions(document)
    destination = output_path or input_path.with_name(f"{input_path.stem}-captioned{input_path.suffix}")
    output = BytesIO()
    document.save(output)
    atomic_write_bytes(destination, output.getvalue())
    return destination, converted


def update_docx_fields_with_word(input_path: Path, output_path: Path | None = None) -> Path:
    """Use installed Microsoft Word to repaginate and refresh TOCs and fields."""
    destination = output_path or input_path
    if input_path.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, destination)

    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise RuntimeError("Microsoft Word automation requires the existing pywin32 package") from error

    with WORD_AUTOMATION_LOCK:
        pythoncom.CoInitialize()
        word = None
        document = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = 3
            document = word.Documents.Open(
                str(destination.resolve()),
                ReadOnly=False,
                AddToRecentFiles=False,
                ConfirmConversions=False,
            )
            document.Repaginate()
            _update_word_story_fields(document)
            for index in range(1, document.TablesOfContents.Count + 1):
                document.TablesOfContents(index).Update()
            for index in range(1, document.TablesOfFigures.Count + 1):
                document.TablesOfFigures(index).Update()
            document.Repaginate()
            _remove_page_leading_blank_paragraphs(document)
            document.Repaginate()
            for index in range(1, document.TablesOfContents.Count + 1):
                document.TablesOfContents(index).UpdatePageNumbers()
            for index in range(1, document.TablesOfFigures.Count + 1):
                document.TablesOfFigures(index).UpdatePageNumbers()
            document.Save()
        except Exception as error:
            raise RuntimeError(f"Microsoft Word could not update fields in {destination.name}") from error
        finally:
            if document is not None:
                with suppress(Exception):
                    document.Close(False)
            if word is not None:
                with suppress(Exception):
                    word.Quit()
            pythoncom.CoUninitialize()
    return destination


def update_docx_bytes_with_word(contents: bytes) -> bytes:
    """Refresh DOCX fields with Word and return the finalized package bytes."""
    with TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "report.docx"
        path.write_bytes(contents)
        update_docx_fields_with_word(path)
        return path.read_bytes()


def _remove_page_leading_blank_paragraphs(document) -> int:
    """Delete empty body paragraphs that Word places alone at the top of a page."""
    removed = 0
    paragraph_limit = document.StoryRanges(WD_MAIN_TEXT_STORY).Paragraphs.Count
    for _ in range(paragraph_limit):
        document.Repaginate()
        removed_this_pass = 0
        page_count = document.ComputeStatistics(WD_STATISTIC_PAGES)
        for page_number in range(page_count, 1, -1):
            page_start = document.GoTo(
                What=WD_GO_TO_PAGE,
                Which=WD_GO_TO_ABSOLUTE,
                Count=page_number,
            )
            paragraph_range = page_start.Paragraphs(1).Range
            if paragraph_range.Text != "\r" or paragraph_range.Information(WD_WITHIN_TABLE):
                continue
            paragraph_range.Delete()
            removed += 1
            removed_this_pass += 1
        if not removed_this_pass:
            break
    return removed


def add_native_image_captions(document: DocumentType) -> int:
    """Replace eligible caption paragraphs while preserving their paragraph style."""
    caption_style_ids = {
        document.styles[name].style_id
        for name in CAPTION_STYLE_NAMES
        if name in document.styles
    }
    converted = 0
    sequence_number = 0
    paragraphs = list(document.element.body.iter(qn("w:p")))
    index = 0
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        existing_fields = _figure_sequence_count(paragraph)
        if existing_fields:
            sequence_number += existing_fields
            _mark_figure_fields_dirty(paragraph)
            if _is_image_paragraph(paragraph.getprevious()):
                _center_paragraph(paragraph)
            index += 1
            continue
        if not _is_image_paragraph(paragraph):
            index += 1
            continue
        caption = paragraph.getnext()
        if caption is None or caption.tag != qn("w:p"):
            index += 1
            continue
        # Either signal will do, and both still require the paragraph to sit directly under an image:
        # our own generator centres captions and gives them no caption style, while a document that
        # came from elsewhere carries the style but may be left aligned.
        if _has_figure_sequence(caption):
            index += 1
            continue
        if _paragraph_style_id(caption) not in caption_style_ids and not _is_centered(caption):
            index += 1
            continue
        caption_text = _paragraph_text_with_breaks(caption).strip()
        if not caption_text:
            index += 1
            continue
        caption_text = MANUAL_FIGURE_PREFIX.sub("", caption_text)
        sequence_number += 1
        converted += 1
        _center_paragraph(caption)
        _replace_with_native_caption(caption, caption_text, sequence_number)
        index += 2
    mark_all_fields_for_update(document)
    return converted


def mark_all_fields_for_update(document: DocumentType) -> None:
    """Mark cached Word fields dirty and request recalculation when opened."""
    for field in document.element.body.iter(qn("w:fldSimple")):
        field.set(qn("w:dirty"), "true")
    for field in document.element.body.iter(qn("w:fldChar")):
        if field.get(qn("w:fldCharType")) == "begin":
            field.set(qn("w:dirty"), "true")
    _enable_field_updates(document)


def _replace_with_native_caption(paragraph, caption_text: str, number: int) -> None:
    base_properties = next(
        (
            deepcopy(run.find(qn("w:rPr")))
            for run in paragraph.iterchildren(qn("w:r"))
            if run.find(qn("w:rPr")) is not None
        ),
        None,
    )
    base_properties = _caption_run_format(base_properties)
    for child in list(paragraph):
        if child.tag != qn("w:pPr"):
            paragraph.remove(child)

    lines = caption_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    multiline = len(lines) > 1
    if multiline:
        paragraph.append(_proof_error("spellStart"))
    _append_text_run(paragraph, "Figure ", base_properties)
    _append_field_character(paragraph, "begin", base_properties, dirty=True)
    instruction_run = _new_run(base_properties)
    instruction = OxmlElement("w:instrText")
    instruction.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instruction.text = r" SEQ Figure \* ARABIC "
    instruction_run.append(instruction)
    paragraph.append(instruction_run)
    _append_field_character(paragraph, "separate", base_properties)
    _append_text_run(paragraph, str(number), base_properties)
    _append_field_character(paragraph, "end", base_properties)
    # Outside the field, so Word renumbering never rewrites the separator away.
    _append_text_run(paragraph, f". {lines[0]}", base_properties)
    for line in lines[1:]:
        paragraph.append(_proof_error("spellEnd"))
        paragraph.append(_bold_break_run())
        paragraph.append(_proof_error("spellStart"))
        _append_text_run(paragraph, line, base_properties)
    if multiline:
        paragraph.append(_proof_error("spellEnd"))


def _paragraph_text_with_breaks(paragraph) -> str:
    return "".join(
        "\n" if node.tag == qn("w:br") else node.text or ""
        for node in paragraph.iter()
        if node.tag in {qn("w:t"), qn("w:br")}
    )


def _new_run(properties):
    run = OxmlElement("w:r")
    if properties is not None:
        run.append(deepcopy(properties))
    return run


# CT_RPr is an ordered sequence, so a property appended out of turn is invalid XML.
RPR_ORDER = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
    "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
    "specVanish", "oMath",
)


def _set_run_property(properties, tag: str, value: str | None = None) -> None:
    name = tag.split(":")[1]
    element = properties.find(qn(tag))
    if element is None:
        element = OxmlElement(tag)
        position = RPR_ORDER.index(name)
        later = next(
            (
                child
                for child in properties
                if child.tag.split("}")[-1] in RPR_ORDER
                and RPR_ORDER.index(child.tag.split("}")[-1]) > position
            ),
            None,
        )
        if later is None:
            properties.append(element)
        else:
            later.addprevious(element)
    if value is None:
        element.attrib.pop(qn("w:val"), None)
    else:
        element.set(qn("w:val"), value)


def _caption_run_format(properties):
    """Captions print at 9pt italic; the Cs pairs carry it onto complex scripts too."""
    properties = deepcopy(properties) if properties is not None else OxmlElement("w:rPr")
    _set_run_property(properties, "w:i")
    _set_run_property(properties, "w:iCs")
    _set_run_property(properties, "w:sz", CAPTION_HALF_POINTS)
    _set_run_property(properties, "w:szCs", CAPTION_HALF_POINTS)
    return properties

def _append_text_run(paragraph, text: str, properties) -> None:
    run = _new_run(properties)
    node = OxmlElement("w:t")
    if text and (text[0].isspace() or text[-1].isspace()):
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text
    run.append(node)
    paragraph.append(run)


def _append_field_character(paragraph, field_type: str, properties, *, dirty: bool = False) -> None:
    run = _new_run(properties)
    field = OxmlElement("w:fldChar")
    field.set(qn("w:fldCharType"), field_type)
    if dirty:
        field.set(qn("w:dirty"), "true")
    run.append(field)
    paragraph.append(run)


def _bold_break_run():
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    properties.append(OxmlElement("w:b"))
    properties.append(OxmlElement("w:bCs"))
    run.append(properties)
    run.append(OxmlElement("w:br"))
    return run


def _proof_error(error_type: str):
    marker = OxmlElement("w:proofErr")
    marker.set(qn("w:type"), error_type)
    return marker


def _is_centered(paragraph) -> bool:
    properties = paragraph.find(qn("w:pPr"))
    alignment = properties.find(qn("w:jc")) if properties is not None else None
    return alignment is not None and alignment.get(qn("w:val")) == "center"


def _paragraph_style_id(paragraph) -> str | None:
    properties = paragraph.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    return style.get(qn("w:val")) if style is not None else None


def _is_image_paragraph(paragraph) -> bool:
    return bool(
        paragraph is not None
        and (
            any(True for _ in paragraph.iter(qn("w:drawing")))
            or any(True for _ in paragraph.iter(qn("w:pict")))
        )
    )


def center_paragraph(paragraph) -> None:
    properties = paragraph.get_or_add_pPr()
    alignment = properties.find(qn("w:jc"))
    if alignment is None:
        alignment = OxmlElement("w:jc")
        properties.append(alignment)
    alignment.set(qn("w:val"), "center")


def _center_paragraph(paragraph) -> None:
    center_paragraph(paragraph)


def _has_figure_sequence(paragraph) -> bool:
    return bool(_figure_sequence_count(paragraph))


def _figure_sequence_count(paragraph) -> int:
    complex_fields = sum(
        bool(FIGURE_SEQUENCE.search(instruction.text or ""))
        for instruction in paragraph.iter(qn("w:instrText"))
    )
    simple_fields = sum(
        bool(FIGURE_SEQUENCE.search(field.get(qn("w:instr"), "")))
        for field in paragraph.iter(qn("w:fldSimple"))
    )
    return complex_fields + simple_fields


def _mark_figure_fields_dirty(paragraph) -> None:
    for field in paragraph.iter(qn("w:fldSimple")):
        if FIGURE_SEQUENCE.search(field.get(qn("w:instr"), "")):
            field.set(qn("w:dirty"), "true")
    if any(FIGURE_SEQUENCE.search(node.text or "") for node in paragraph.iter(qn("w:instrText"))):
        begin = next(
            (
                node
                for node in paragraph.iter(qn("w:fldChar"))
                if node.get(qn("w:fldCharType")) == "begin"
            ),
            None,
        )
        if begin is not None:
            begin.set(qn("w:dirty"), "true")


def _update_word_story_fields(document) -> None:
    document.Fields.Update()
    for story_type in range(1, 18):
        try:
            story = document.StoryRanges(story_type)
        except Exception:
            continue
        while story is not None:
            story.Fields.Update()
            try:
                story = story.NextStoryRange
            except Exception:
                story = None


def _enable_field_updates(document: DocumentType) -> None:
    settings = document.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")