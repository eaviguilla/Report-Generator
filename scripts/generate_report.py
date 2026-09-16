from __future__ import annotations

import argparse
from pathlib import Path

from app.docx_captions import update_docx_bytes_with_word
from app.docx_report import ReportGenerationError, render_report_docx
from app.main import ROOT, workspace
from app.report_service import report_export_filename
from app.storage import atomic_write_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a VulnReport DOCX from a saved local report")
    parser.add_argument("report_id", help="Stored report ID, for example r_7edb3423a1bc")
    parser.add_argument("-t", "--template", type=Path, default=ROOT / "resources" / "MAIN.docx")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true", help="Render missing evidence as visible placeholders")
    arguments = parser.parse_args()

    try:
        report = workspace.load(arguments.report_id)
        draft_path = workspace.find_path(arguments.report_id)
        if draft_path is None:
            raise FileNotFoundError(arguments.report_id)
        contents = render_report_docx(
            report,
            arguments.template,
            draft_path.parent,
            allow_incomplete=arguments.allow_incomplete,
        )
        contents = update_docx_bytes_with_word(contents)
    except (FileNotFoundError, ReportGenerationError, RuntimeError) as error:
        parser.error(str(error))

    output = arguments.output or Path.cwd() / report_export_filename(report, ".docx")
    atomic_write_bytes(output, contents)
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())