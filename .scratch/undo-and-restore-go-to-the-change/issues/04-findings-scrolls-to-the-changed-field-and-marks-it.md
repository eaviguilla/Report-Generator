# 04: Findings scrolls to the changed field and marks it

Status: ready-for-agent

Blocked by: [02: Setup scrolls to the changed field and marks it](02-setup-scrolls-to-the-changed-field-and-marks-it.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Findings, Findings scrolls the changed field into view and marks it the way Content's Go to button marks a target. The cursor stays out of the text box. A field inside a finding's folded row, such as a location, is shown by unfolding the row first. Findings names its fields, so the steps and copies from ticket 02 can carry them. Setup and Findings share their page code, so this builds on what ticket 02 added for Setup.

- [ ] Findings names every field a tester changes, together with its finding: the name, the assessment fields and the locations.
- [ ] When Undo, Redo or Restore opens Findings, Findings unfolds the finding's row when the field is inside it, scrolls the field into view and marks it. The cursor stays out of the text box.
- [ ] If the field is gone, for example because Undo removed the finding's row, Findings scrolls to the list of findings.
- [ ] An Undo made on Findings that reloads Findings marks the field.
- [ ] Regression tests cover an Undo on Content of a step made on Findings, which opens Findings and marks the field, and an Undo of an added finding, which lands on the list.
- [ ] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [ ] `docs/DATA_MAP.md` §10 says how Findings points at the field.

Out of scope: Content, which ticket 03 covers.

## Next steps

1. `/implement`: Tickets 02 and 03 are done, so nothing blocks this. It is the last of the four.
