# 02: The save code moves into its own file

Status: done (2026-10-05)

Blocked by: [01: Pages hand the save code their own checks](01-pages-hand-the-save-code-their-own-checks.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** The stretch of save code from ticket 01 moves out of `app.js` into its own file, `save.js`, unchanged. The Setup, Findings and Content pages load it before `app.js`, and it sets `window.vrSave`, the way `rules.js` sets `window.vrRules`. `app.js` starts it once with the server's report, the check function and `onSaved`, and takes today's names from it in one line, so no call site changes. The tester sees no change. Review item 06's Answers 3 and 5 list what moves and what the module returns.

- [x] A script cuts the stretch out of `app.js`, and nobody retypes it. `git diff --color-moved` shows it as moved, with new lines only where the two files join. The script edits files from the terminal, so ask the user before running it.
- [x] `vrSave.start` decides which report the page edits, the server's or a restored recovery copy. It returns that report with today's names (`scheduleSave`, `save`, `setSaveState`, `SAVE_STATES`, `trackMutation`, `waitForMutations`, `markSaveConflict`, `showOperationError`, `applyServerRevision`, `finalizeTextTransaction`) plus `holdSaves` and `hasUnsavedEdits`. `vrSave` also exposes `reconcileCanonicalObject` for tests.
- [x] A helper both files need has one owner. The rule for which element counts as a focused text field stays one function, used by undo's text steps and by the Content page's offer refresh.
- [x] Storage keys and the formats of recovery copies and undo history do not change, so a copy written before the update still restores.
- [x] No report page shows an error at load, and every report-page browser test passes unchanged (`--affected`).
- [x] The test picker, `scripts/relevant_tests.py`, maps `save.js` to every report-page browser test and not to the home page tests, with a case in its own tests.
- [x] The data-layer rules file covers `save.js` beside `app.js`, and its Claude copy is regenerated with the sync script.
- [x] Every doc that places the save code in `app.js` says where it lives now: DATA_MAP's maintenance note and §9, §10 and §13, the browser and test-picker lines of the Copilot instructions, the web-client rules' size note for `app.js`, and both copies of the `invader` agent. A rewritten sentence uses the glossary's "save conflict" and "recovery copy".
- [x] The code graph is refreshed after the change.

Out of scope: renaming anything, and merging the upload and library-insert sequences into one function, which review item 06 leaves for later.

## What deviated

The script moved six helpers that need no page (`clone`, `sameValue`, `isRecord`, `stableItemKey`, `reconcileCanonicalObject`, `activeTextEntry`) to the top of `save.js` byte for byte, so `vrSave` can offer them before `start` runs. The rest sits inside `start`, two spaces deeper. Plain `git diff --color-moved` therefore shows those lines as new; `git diff --color-moved --color-moved-ws=allow-indentation-change` shows everything as moved except the join lines. The user chose this over keeping the old indentation, and the script checked that every cut line reappears unchanged or with exactly two spaces added. `start` takes `root` too, because the `focusout` listener that closes an undo text step sits on `<main>`, and it reads `window.VulnReportDiagnostics` itself, as `app.js` does. `save.js` owns `isRecord` and `activeTextEntry`; `app.js` takes them from `window.vrSave` in a second line beside the `start` call. `clone` and `sameValue` turned out to be used only by the save code. The `loremaster` agent's file table also placed the save code in `app.js`, so both of its copies changed as well.
