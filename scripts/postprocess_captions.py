from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from docx import Document

from app.docx_captions import add_native_image_captions, update_docx_fields_with_word
from app.storage import atomic_write_bytes


def postprocess_image_captions(input_path: Path, output_path: Path | None = None) -> tuple[Path, int]:
    """Convert image-adjacent caption text into native Word SEQ Figure fields."""
    document = Document(input_path)
    converted = add_native_image_captions(document)
    destination = output_path or input_path.with_name(f"{input_path.stem}-captioned{input_path.suffix}")
    output = BytesIO()
    document.save(output)
    atomic_write_bytes(destination, output.getvalue())
    return destination, converted


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert image-adjacent text into native Word figure captions")
    parser.add_argument("input", type=Path, help="Generated DOCX to post-process")
    parser.add_argument("-o", "--output", type=Path, help="Output DOCX; defaults to <input>-captioned.docx")
    parser.add_argument("--skip-word-update", action="store_true", help="Do not use installed Word to update TOC and field results")
    arguments = parser.parse_args()
    output, converted = postprocess_image_captions(arguments.input, arguments.output)
    if not arguments.skip_word_update:
        update_docx_fields_with_word(output)
    print(f"{output.resolve()} ({converted} captions converted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())