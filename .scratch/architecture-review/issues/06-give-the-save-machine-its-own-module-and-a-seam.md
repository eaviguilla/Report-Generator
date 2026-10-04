# Give the save machine its own module and a seam

Status: needs-triage

Found by the [3 October 2026 review](../report.html#review-2026-10-03-c3), recommendation 3, rated Worth exploring, ports and adapters.

## Problem

About 700 lines of autosave, conflict handling, local recovery, a three-way merge of the server's reply and undo call fetch, Web Storage, timers and the Save button directly, and `save()` runs Setup's checks through three variables that `setup()` reassigns, so all 26 of its tests load a page.

## Solution

Give the save machine its own file that takes storage, server calls and timers as adapters, and let each page pass in its own save checks.

## Benefits

- Conflict cases run without a page.
- The three-way merge, `reconcileCanonicalObject`, gets direct tests.
- Setup's checks cross the interface instead of being chosen by `root.dataset.step`.
- Locality: saving lives in one file, and `app.js` loses about 700 lines.

## Files

- `app/web/static/app.js` · lines 36 to 110, local drafts and history at load
- `app/web/static/app.js` · lines 172 to 960: `scheduleSave`, `save`, `reconcileCanonicalObject`, `markSaveConflict`, `restoreHistory`, `undo`, `redo`
- `app/web/static/app.js` · `setup()`: `validateSetupInputs`, `strandedByScopeEdit`, `pendingScopeDecision`
- `tests/test_browser.py` · 26 tests of saving, conflicts, recovery and undo
- `docs/DATA_MAP.md` · §9, §10, §12

## Notes

- The page code already uses few of its names: `scheduleSave` 59 times, `save` and `setSaveState` 5 times each, `trackMutation`, `markSaveConflict` and `finalizeTextTransaction` twice each, `waitForMutations` once. None of it touches the history or pending-save state. The module is deep already. What it lacks is a seam.
- DATA_MAP §12 records the cost today. On any page but Setup, undo and local recovery save without the Setup check, so a Setup value the server refuses can block Back and Next.

## Next steps

1. `/grill-with-docs`: Settle the module's interface, how a page passes in its save checks, and which adapters it takes.
2. `/research`: No JavaScript test runner exists in the repo. Review item 03 needs the same answer, so settle it once.
