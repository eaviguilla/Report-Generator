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
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .storage import atomic_write_bytes


CAPTION_STYLE_NAMES = ("Figures and Tables", "Caption")
MANUAL_FIGURE_PREFIX = re.compile(r"^\s*Figure\s+\d+\s*[:.\-]?\s*", re.IGNORECASE)
FIGURE_SEQUENCE = re.compile(r"\bSEQ\s+Figure\b", re.IGNORECASE)
WORD_AUTOMATION_LOCK = threading.Lock()


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
            for index in range(1, document.TablesOfContents.Count + 1):
                document.TablesOfContents(index).UpdatePageNumbers()
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
        if _paragraph_style_id(caption) not in caption_style_ids or _has_figure_sequence(caption):
            index += 1
            continue
        caption_text = "".join(node.text or "" for node in caption.iter(qn("w:t"))).strip()
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
    for child in list(paragraph):
        if child.tag != qn("w:pPr"):
            paragraph.remove(child)

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
    _append_text_run(paragraph, f" {caption_text}", base_properties)


def _new_run(properties):
    run = OxmlElement("w:r")
    if properties is not None:
        run.append(deepcopy(properties))
    return run


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


def _center_paragraph(paragraph) -> None:
    properties = paragraph.get_or_add_pPr()
    alignment = properties.find(qn("w:jc"))
    if alignment is None:
        alignment = OxmlElement("w:jc")
        properties.append(alignment)
    alignment.set(qn("w:val"), "center")


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