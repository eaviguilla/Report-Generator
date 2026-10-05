# 01: Pages hand the save code their own checks

Status: done (2026-10-05)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** The save code stops asking which page it is on. Today it reads the page's step, calls two functions that `setup()` swaps in at load, and leaves page code to set its scope-decision flag directly. After this ticket, Setup hands the save code one check function, page code holds saves through one call, and the save code sits in one unbroken stretch of `app.js`. The tester sees no change. The work stays inside `app.js`, so that ticket 02 can move the stretch as a plain cut and paste. Review item 06's Answers 4 and 5 describe the interface.

- [x] Setup passes one check function. It runs today's two checks in today's order: no Setup field showing an error, then no finding left without a location. It returns nothing when the save may go, or the Save button's words when the save must wait. `setup()` also runs on Findings, so it passes the check only on Setup. Findings and Content pass none.
- [x] The save code calls the check where it runs the two checks today, and on a Save-button click. It no longer reads the page's step or calls the functions `setup()` swaps in.
- [x] The seven places that set the scope-decision flag call `holdSaves(true)` or `holdSaves(false)` instead.
- [x] Generate calls `hasUnsavedEdits()` in place of reading the three save counters.
- [x] After each successful save the save code calls an `onSaved` function, which updates the engagement name as the save code does today.
- [x] The save code sits in one unbroken stretch. Page code that sits between its parts today, such as the library helpers, the Setup notices and the Generate handler, moves above or below it. Listeners on the same element and event keep their order, and `git diff --color-moved` shows the moved lines as moved.
- [x] Every report-page browser test passes unchanged (`--affected`).
- [x] DATA_MAP §12's paragraph on the Setup gate describes the check function. Only Setup passes one, so the gate still holds a save only on Setup.
- [x] That paragraph also records the one accepted difference. A Save click now runs the whole check, so while a scope rename is being typed or a save is in flight, the button would name a finding left with no location instead of showing today's words. Typing a rename cannot overlap a click on Save, because leaving the field opens the scope dialog first, and a save is in flight for only a moment.

Out of scope: the move to a file of its own (ticket 02), and the Undo hole, which has [its own item](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md).

## What deviated

`setup()` builds Setup's check after the save code has started, so the check cannot exist when the save code is given it. Page code above the stretch holds `let setupSaveCheck`, which `setup()` fills in, and passes `saveCheck`, a function that calls through to it on the Setup step and `null` elsewhere. `setupSaveCheck` is filled in inside `setup()`'s scope-grid block, where `scopeTextStrandedFindings` lives; that block runs only on Setup. `validateSetupInputs` became a constant inside `setup()`. For ticket 02: the stretch runs from `let report = serverReport;` (moved there from the top, so `reportId` now reads `serverReport.report_id`) to the line that offers a recovery copy. The three lines above it, `setupSaveCheck`, `saveCheck` and `onSaved`, are what `vrSave.start` will take. `clone`, `isRecord`, `sameValue` and `activeTextEntry` stay inside the stretch although page code uses them too; ticket 02 decides who owns them. The internal flag keeps its name, `pendingScopeDecision`. A script approved by the user moved the four page blocks, so their lines are byte-identical.
