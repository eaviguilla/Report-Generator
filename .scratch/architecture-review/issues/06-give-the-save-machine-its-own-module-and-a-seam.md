# Give the save machine its own module and a seam

Status: ready-for-agent

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
- `tests/test_browser.py` · about 35 tests that reach saving, conflicts, recovery and undo (26 when reviewed)
- `docs/DATA_MAP.md` · §9, §10, §12

## Notes

- The page code already uses few of its names: `scheduleSave` 59 times, `save` and `setSaveState` 5 times each, `trackMutation`, `markSaveConflict` and `finalizeTextTransaction` twice each, `waitForMutations` once. None of it touches the history or pending-save state. The module is deep already. What it lacks is a seam.
- DATA_MAP §12 records the cost today. On any page but Setup, undo and local recovery save without the Setup check, so a Setup value the server refuses can block Back and Next.

## Answers

Settled with the user on 5 October 2026. "Save conflict" and "recovery copy" are defined in `GLOSSARY.md`.

1. **Behaviour.** The code moves exactly as it works, so the existing browser tests prove the move. The Undo hole in DATA_MAP §12 is its own item: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md).
2. **How tests control the server, storage and time.** The module calls `fetch`, Web Storage and timers directly. Tests serve a blank page from a made-up address, answer saves with `page.route`, move time with `page.clock`, and use the page's real Web Storage. Nothing is passed in for these three. [ADR 0004](../../../docs/adr/0004-the-save-module-calls-the-browser-and-tests-fake-the-browser.md) records why.
3. **What moves.** All of the save part of `app.js` moves into `app/web/static/save.js`: autosave and the Save button, save conflicts, recovery copies, the merge of the server's reply, undo and redo with their buttons and Ctrl+Z, the upload and library-insert queue, the Back button, and the `pageshow`, `pagehide`, `beforeunload` and `visibilitychange` handlers. Undo stays in the same file because the merge moves the point undo starts from, and recovery copies carry undo across reloads. The module finds `#save-button`, `#undo-button`, `#redo-button` and `.back-link` itself and reloads the page itself, as today. It decides which report the page edits, the server's or a restored recovery copy, and hands it to the page. The Setup notices, the Next button and Generate stay in `app.js`.
4. **How a page holds a save.** The page passes one check function when it starts the module. The module calls it before each save and on a Save-button click. It returns nothing when the save may go, or the Save button's words when it must wait. Setup's function runs today's two checks in today's order: no field showing an error, then no finding left without a location. Findings and Content pass none, and the module no longer reads `root.dataset.step`. While a scope dialog is open, the page calls `holdSaves(true)` and then `holdSaves(false)`, in place of the seven assignments to `pendingScopeDecision`.
5. **Names.** Page code keeps today's names and takes them from the module in one line: `const {report, scheduleSave, save, setSaveState, SAVE_STATES, trackMutation, waitForMutations, markSaveConflict, showOperationError, applyServerRevision, finalizeTextTransaction, holdSaves, hasUnsavedEdits} = window.vrSave.start({...})`. `hasUnsavedEdits()` replaces Generate's reads of the three save counters. `save.js` loads before `app.js` and sets `window.vrSave`, the way `rules.js` sets `window.vrRules`. It also exposes `reconcileCanonicalObject`, so tests can call it directly. Merging the upload and library-insert sequences into one `send` function is left for a later change.
6. **Tests, in three steps.** First, move the code with every page test unchanged. Second, add direct tests in a new Python test module beside `tests/test_rule_cases.py`, for the merge, save conflicts, retries and recovery copies. Third, replace each page test that checks only save logic with a direct test, and delete the page version.
7. **The keyboard plan.** `docs/plans/keyboard-save-and-undo.md` was marked done, but none of its code was built. It is reopened as ready-for-agent and blocked by this item, so it is built on the new module.

Decided without asking, then confirmed with the user:

- The page also passes `onSaved`. The module calls it after each successful save, where it calls `updateEngagementName()` today.
- The module still dispatches `reportchange`, and pages keep listening for it.
- Storage keys and the formats of recovery copies and undo history do not change, so copies written before the update still load.
- `scripts/relevant_tests.py` maps `save.js` to every report-page browser test, not to the home page tests.
- Both release builds copy all of `app/`, so neither changes.
- DATA_MAP §9, §10 and §12 change in the same commit as the move.
- The `/research` step is dropped. Review item 03 settled the JavaScript test runner on 4 October: Playwright, a blank page, no Node.js. `tests/test_rule_cases.py` shows how.

## Next steps

1. `/implement`: Build [ticket 02](../../save-module/issues/02-the-save-code-moves-into-its-own-file.md) next; ticket 01 is done. The five tickets in `.scratch/save-module/issues/` carry the work, and the spec was skipped because the Answers above already hold its decisions.
