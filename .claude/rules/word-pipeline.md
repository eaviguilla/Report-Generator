---
paths:
  - "app/docx_*.py"
  - "scripts/generate_report.py"
  - "scripts/postprocess_captions.py"
  - "tests/test_docx*.py"
---
<!-- Generated from .github/instructions/word-pipeline.instructions.md. Edit that file, not this one. -->

# Word pipeline

How the pipeline fits together is in `docs/ARCHITECTURE.md` and `docs/DOCX_TEMPLATE.md`; these are the traps.

- Do not modify the binary templates in `resources/` (`MAIN*.docx` and the component documents) without asking, and do not open a `.docx` into context: verify structure through the tests.
- Generate always ends in Word COM automation (`update_docx_bytes_with_word`) and returns 422 on macOS by design. A test that calls `/generate` unpatched is Windows-gated, and a layout change can only be proven on a Windows run.
- Only Word knows where pages break. python-docx cannot see automatic breaks, and `w:lastRenderedPageBreak` markers are stale template residue. Control layout with `keepNext` set from Python (`_keep_with_next`), keyed off the `{{...}}` anchors; do not add it to the binary masters.
- Any `-vuln` (any case) in the finished text, like any other entry of `UNRESOLVED_MARKERS`, aborts generation with a message that names a template placeholder. Free text such as "non-vuln" trips it.
- Status labels have four copies: `STATUS_LABELS` (`docx_report.py`), `STATUS_BY_LABEL` (`docx_import.py`), `statuses` in `app.js` and `labels` in `manager.js`. A new status goes into all four in one change, with its importer round-trip test.
- The default In Conclusion sentence is recognised by `STATUS_CONCLUSION_PATTERN` in `report_service.py`, which has a JS twin. Do not reword it or change its case (`CLOSED` is deliberate): every default sentence already on disk would stop matching.
- A `.docx` is a ZIP. The import route sniffs `word/document.xml` before the bundle branch, and a corrupt DOCX must be a 422, not a 500.
- In a finished document `N/A` means four things (empty section, caption, value, no location), and an imported image is the generated one, re-rasterised with a baked-in border. Recover both deliberately.
- Whatever the generator prints, the importer must read back: change `docx_import.py` and its round-trip tests in the same change, and record any token or layout change in `docs/DOCX_TEMPLATE.md`.
