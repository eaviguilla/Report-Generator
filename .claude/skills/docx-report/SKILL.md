---
name: docx-report
description: Conventions for changing .docx report generation, import or templates with python-docx in this repo. Use when modifying the Word pipeline or a Word template.
---
# docx report changes
1. The builders are `app/docx_report.py` (render), `app/docx_components.py` (component documents), `app/docx_captions.py` (caption fields and the Word COM pass) and `app/docx_import.py` (read a finished report back). Templates live in `resources/`: the four `MAIN*.docx` masters, plus `fragments/`, `finding_types/` and `severity_titles/`.
2. Template choice is `main_template_path` only. Content comes from the component documents, so styling comes from the Word files; never hardcode fonts or sizes in code. Replacing a tag keeps the paragraph style and run formatting.
3. A master must contain an exact `{{findings}}` paragraph. Tables are found by their first header cell, never by index.
4. Do not open `.docx` files into context. Verify structure through the tests: `tests/test_docx.py`, `tests/test_docx_components.py`, `tests/test_docx_import.py`, `tests/test_docx_captions.py`. Word's own pass is patched out, so they run on macOS.
5. Anything that changes what is printed also changes what the importer reads back: update `app/docx_import.py` and its round-trip tests in the same change, and record the token or layout in `docs/DOCX_TEMPLATE.md`.
6. Word COM (`pythoncom`, `win32com`) lives only in `app/docx_captions.py` and runs only on Windows with Word; the one real-Word test skips itself elsewhere.
