from __future__ import annotations

import argparse
from pathlib import Path

from app.docx_captions import postprocess_image_captions, update_docx_fields_with_word


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