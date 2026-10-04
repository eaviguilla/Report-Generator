# One module prints and reads every document convention

Status: needs-triage

Found by the [2 October 2026 review](../report.html#review-2026-10-02-c4), recommendation 4, rated Worth exploring, in-process.

Found again: the [3 October 2026 review](../report.html#review-2026-10-03-c5), recommendation 5, rated Speculative.

## Problem

Each remaining convention is printed in `docx_report.py` and parsed in `docx_import.py` with no shared owner, both files hold a function named `_display_date` that runs in opposite directions, and the writer imports three of its own constants from the reader.

## Solution

One module owns each printed convention as a print and read pair, and the generator and the importer both call it.

## Benefits

- The writer stops importing from the reader.
- One round-trip case per convention.
- Fewer whole-document renders in the importer tests.

## Files

- `app/docx_report.py` · `_display_date` (232), `_environment_label` (828), `SEVERITY_TICKET_PREFIX` (52), the no-findings summary row (530), `"N/A"` 18 times, the import on line 36
- `app/docx_import.py` · `_display_date` (448), `"PROD:"` (389, 689), `TICKET_PREFIX` (98), the no-findings row check (648), `"N/A"` 9 times, `FINDING_HEADING_STYLE`, `INSTANCE_PREFIX`, `NO_FINDINGS_TITLE`
- `tests/test_docx_import.py` · 63 tests, 32 calls to `render_report_docx`

## What shipped and what moved

- Shipped in `37593ea` with review item 01: status labels have one table, `STATUS_LABELS` in `models.py`, which the importer inverts into `STATUS_BY_LABEL`, and the importer's title parser reads segments through `get_args(Segment)`.
- Moved to review item 07: the master-template choice and the Asia checks, which the first review counted as conventions.
- Left: the date, the environment heading, the ticket line, the empty value, the no-findings row, and the three constants the writer imports from the reader.

## Next steps

1. `/triage`: Half of it shipped, and the importer's round-trip tests already catch drift in the rest. Decide whether what is left is worth a module.
2. `/grill-with-docs`: If it goes ahead, settle which conventions the module owns and how each pair is tested without a document render.
