# 02: The save code moves into its own file

Status: ready-for-agent

Blocked by: [01: Pages hand the save code their own checks](01-pages-hand-the-save-code-their-own-checks.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** The stretch of save code from ticket 01 moves out of `app.js` into its own file, `save.js`, unchanged. The Setup, Findings and Content pages load it before `app.js`, and it sets `window.vrSave`, the way `rules.js` sets `window.vrRules`. `app.js` starts it once with the server's report, the check function and `onSaved`, and takes today's names from it in one line, so no call site changes. The tester sees no change. Review item 06's Answers 3 and 5 list what moves and what the module returns.

- [ ] A script cuts the stretch out of `app.js`, and nobody retypes it. `git diff --color-moved` shows it as moved, with new lines only where the two files join. The script edits files from the terminal, so ask the user before running it.
- [ ] `vrSave.start` decides which report the page edits, the server's or a restored recovery copy. It returns that report with today's names (`scheduleSave`, `save`, `setSaveState`, `SAVE_STATES`, `trackMutation`, `waitForMutations`, `markSaveConflict`, `showOperationError`, `applyServerRevision`, `finalizeTextTransaction`) plus `holdSaves` and `hasUnsavedEdits`. `vrSave` also exposes `reconcileCanonicalObject` for tests.
- [ ] A helper both files need has one owner. The rule for which element counts as a focused text field stays one function, used by undo's text steps and by the Content page's offer refresh.
- [ ] Storage keys and the formats of recovery copies and undo history do not change, so a copy written before the update still restores.
- [ ] No report page shows an error at load, and every report-page browser test passes unchanged (`--affected`).
- [ ] The test picker, `scripts/relevant_tests.py`, maps `save.js` to every report-page browser test and not to the home page tests, with a case in its own tests.
- [ ] The data-layer rules file covers `save.js` beside `app.js`, and its Claude copy is regenerated with the sync script.
- [ ] Every doc that places the save code in `app.js` says where it lives now: DATA_MAP's maintenance note and §9, §10 and §13, the browser and test-picker lines of the Copilot instructions, the web-client rules' size note for `app.js`, and both copies of the `invader` agent. A rewritten sentence uses the glossary's "save conflict" and "recovery copy".
- [ ] The code graph is refreshed after the change.

Out of scope: renaming anything, and merging the upload and library-insert sequences into one function, which review item 06 leaves for later.

## Next steps

1. `/implement`: Ticket 01 is done, so nothing blocks this. Its "What deviated" paragraph says where the stretch starts and ends.
