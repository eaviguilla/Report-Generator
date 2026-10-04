# One module builds the Word report

Status: needs-triage

Found by the [3 October 2026 review](../report.html#review-2026-10-03-c2), recommendation 2, rated Strong. Dependency category: mock, because Microsoft Word sits behind the seam.

## Problem

The routes share `finalized_report`, but both scripts copy its sequence of gate, confirmation, master template, render, Word pass and file name, so ADR-0002's confirmation rule exists twice, the generate script imports the whole web app to reach the workspace, and tests swap out Word only by patching `main`.

## Solution

One module takes a stored report and the tester's confirmation and returns the finished Word report or why it cannot, with Word behind a seam, and both routes and both scripts call it.

## Benefits

- The confirmation rule is written once.
- The scripts stop importing `app.main`, which loads prefs and the library and builds the web app.
- Two adapters justify the seam: Word on Windows, and a pass-through for tests and the showcase script's `--skip-word`.
- Generation tests run without HTTP.
- Locality: a change to how reports are generated touches one module.

## Files

- `app/main.py` · `finalized_report`, `unused_export_path`, `generate_report`, `generate_report_to_folder`
- `scripts/generate_report.py` · `main`
- `scripts/generate_showcase_reports.py` · `main`, `_verify_report`
- `app/docx_report.py` · `generation_issues`, `main_template_path`, `render_report_docx`
- `app/docx_captions.py` · `update_docx_bytes_with_word`
- `tests/test_app.py`, `tests/test_browser.py` · six patches of `main.update_docx_bytes_with_word`

## Notes

- [ADR-0002](../../../docs/adr/0002-no-findings-report-is-derived-and-confirmed-per-request.md) stands as decided. The confirmation still travels with each request, and every way to generate passes the same check.
- The route holds the report lock through the Word pass. `scripts/generate_report.py` renders without it.

## Next steps

1. `/grill-with-docs`: Settle where the module lives, what it returns when a report cannot be built, and how a caller picks the Word adapter.
2. `/implement`: Small once the shape is agreed: one module, two routes, two scripts and six test patches.
