# One module accepts every draft on the write path

Status: done

Found by the [2 October 2026 review](../report.html#review-2026-10-02-c2), recommendation 2, rated Strong, local-substitutable.

## Problem

The write path ran as ten ordered steps inside `save_report`, `finalize_editable_import` repeated seven of them by hand, and `rename_report` checked names against `-:()` while Setup allows `-:;.()`, so a rename refused `Portal v1.2; EU`.

## Solution

One module takes the stored report and an incoming draft and returns the report to save or a named refusal, and every mutating route calls it and only maps refusals to status codes.

## Benefits

- Save rules are testable without HTTP.
- Editable import reuses the save rules.
- Rename gets Setup's app-name rule.
- Locality: one place defines saving.

## Files

- `app/main.py` · `save_report`, `finalize_editable_import`, `rename_report`, `insert_library`
- `app/report_service.py` · `reconcile_targets`, `setup_input_issues`, `finding_input_issues`, `provision`
- `app/models.py` · `normalise_scope_modes`
- `app/workspace.py` · `save_if_current`
- `tests/test_app.py`

## Outcome

The rename fix came first, in `a2b2eac`. The module was built through the plan [Report acceptance](../../../docs/plans/report-acceptance.md) as `app/acceptance.py`, in `af37291`. Four entry paths still skip acceptance: bundle import, retest DOCX import, library insert and rename. They are filed in `.scratch/report-acceptance/issues/`.
