# 04: Findings scrolls to the changed field and marks it

Status: done (2026-10-06)

Blocked by: [02: Setup scrolls to the changed field and marks it](02-setup-scrolls-to-the-changed-field-and-marks-it.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Findings, Findings scrolls the changed field into view and marks it the way Content's Go to button marks a target. The cursor stays out of the text box. A field inside a finding's folded row, such as a location, is shown by unfolding the row first. Findings names its fields, so the steps and copies from ticket 02 can carry them. Setup and Findings share their page code, so this builds on what ticket 02 added for Setup.

- [x] Findings names every field a tester changes, together with its finding: the name, the assessment fields and the locations.
- [x] When Undo, Redo or Restore opens Findings, Findings unfolds the finding's row when the field is inside it, scrolls the field into view and marks it. The cursor stays out of the text box.
- [x] If the field is gone, for example because Undo removed the finding's row, Findings scrolls to the list of findings.
- [x] An Undo made on Findings that reloads Findings marks the field.
- [x] Regression tests cover an Undo on Content of a step made on Findings, which opens Findings and marks the field, and an Undo of an added finding, which lands on the list.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [x] `docs/DATA_MAP.md` §10 says how Findings points at the field.

Out of scope: Content, which ticket 03 covers.

## What deviated

A Findings field's name is its finding's `uid` and one of three keys: its column in the finding's row, the label of a box among its locations, or the environment of a Select all button, whose text changes once pressed. Each row now carries its finding's `uid`, because the rows had nothing to find a finding by. A row button such as Delete names the finding's name column, so an Undo of a deletion marks the restored finding's name. A name or Vuln ID that holds text shows as a button with its box hidden, so the button takes the mark. A location box and Delete rebuild the table before the step is recorded, as Content's buttons do in ticket 03, so the rebuild fallback moved out of Content and both pages share it (`rememberFocusedField`), and the mark code moved out of Setup into `markUntilClickElsewhere`. Add finding now puts the cursor in the new finding's name box before its step is recorded, so the step names the new finding and its Undo lands on the list. Building the Vuln ID case turned up a bug in the save code: `diff` compared arrays by reference, so a save scheduled with nothing changed still recorded a step. The name and Vuln ID boxes schedule one as they lose focus, so every edit there left a second, empty step with no field, and the first Undo did nothing visible. `diff` now compares arrays by content, with a direct test in `tests/test_save_module.py`. DATA_MAP §9 also changed, for the names and the `diff` fix. The library search's Add puts the cursor in the new finding's first location box, and the step names that box. The code review found that when an environment has more than one target, that box is Select all's, which has no label, so Redo found nothing to mark. A location box with no label is now named by its environment, as the Select all button is, with a test.
