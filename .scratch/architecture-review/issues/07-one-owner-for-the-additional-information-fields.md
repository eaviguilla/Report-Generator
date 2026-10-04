# One owner for the Additional Information fields

Status: needs-triage

Found by the [3 October 2026 review](../report.html#review-2026-10-03-c4), recommendation 4, rated Worth exploring, in-process.

## Problem

No Python code states which Additional Information fields a finding prints, because the Word documents chosen decide it, `docx_report.py` tests for Asia three different ways, and only `app.js` states the rule, with one six-case browser test as its check.

## Solution

One module states the field rule by segment and status, the generator, readiness, the importer and the browser read it, and a test checks that each Word document carries the tokens the rule promises.

## Benefits

- Asia is decided in one place.
- A new segment edits one table.
- The Word documents are checked against the rule.
- Python tests reach the rule.

## Files

- `app/docx_report.py` · `generation_issues` (101), `main_template_path` (162), `_populate_cvss_table` (617), `_render_finding_component` (766)
- `app/docx_import.py` · reads the table named Section (807)
- `resources/MAIN_ASIA.docx`, `resources/MAIN_THICK_MOBILE_ASIA.docx`, `resources/finding_types/retest_finding.docx`
- `app/web/static/app.js` · `additionalInformationFields` (3495), `cvssIssues` (3603)
- `tests/test_browser.py` · `test_additional_information_shows_only_the_fields_that_apply`

## The rule today

| Segment | Open (New) | Every other status |
|---|---|---|
| Asia | CVSS pair | tickets, CVSS pair |
| JH, GWAM, GDT, GFT | none | tickets |

## Notes

- These are two rows of the twin table in review item 03, "which Additional Information fields a finding shows" and "is this report Asia", so this can be that work's first slice.
- It takes over the master-template choice and the Asia checks from review item 04.
- The template test reads the Word documents and changes none. Changing one needs the user's approval.

## Next steps

1. `/grill-with-docs`: Settle where the rule lives, how the browser gets it, and how a test checks that the Word documents carry its tokens.
