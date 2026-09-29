"""Helpers shared by more than one test module. Only code that was copied between modules lives here."""
from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from docx.oxml.ns import qn
from PIL import Image

from app import main
from app.workspace import Workspace


def use_temp_workspace(test: TestCase, tester: str) -> Path:
    """Give one test its own workspace and generated/ folder; both are put back when the test ends."""
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    root = Path(folder.name)
    original = main.workspace
    main.workspace = Workspace(root, tester)
    test.addCleanup(setattr, main, "workspace", original)
    generated = patch.object(main, "GENERATED", root / "generated")
    generated.start()
    test.addCleanup(generated.stop)
    return root


def numbering_details(document, paragraph) -> tuple[str, str | None, int | None]:
    """The numId, nsid and level-0 startOverride behind one list paragraph."""
    numbering = document.part.numbering_part.element
    numbering_id = str(paragraph._p.pPr.numPr.numId.val)
    number = next(element for element in numbering.iterchildren(qn("w:num")) if element.get(qn("w:numId")) == numbering_id)
    abstract_id = number.find(qn("w:abstractNumId")).get(qn("w:val"))
    abstract = next(element for element in numbering.iterchildren(qn("w:abstractNum")) if element.get(qn("w:abstractNumId")) == abstract_id)
    nsid = abstract.find(qn("w:nsid"))
    override = next(
        (level.find(qn("w:startOverride")) for level in number.iterchildren(qn("w:lvlOverride")) if level.get(qn("w:ilvl")) == "0"),
        None,
    )
    return (
        numbering_id,
        nsid.get(qn("w:val")) if nsid is not None else None,
        int(override.get(qn("w:val"))) if override is not None else None,
    )


def png_bytes(width: int = 2, height: int = 2, color: str = "white") -> bytes:
    """A small solid PNG, the stand-in screenshot most tests upload or write as evidence."""
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def off_border_pixels(image) -> list[tuple[int, int]]:
    """Edge pixels of a rendered screenshot that are not the black border the renderer draws."""
    width, height = image.size
    edge = {(x, y) for x in range(width) for y in (0, height - 1)} | {(x, y) for x in (0, width - 1) for y in range(height)}
    return sorted(point for point in edge if image.getpixel(point) != (0, 0, 0))
