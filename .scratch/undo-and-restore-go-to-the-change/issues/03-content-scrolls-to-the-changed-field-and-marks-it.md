# 03: Content scrolls to the changed field and marks it

Status: ready-for-agent

Blocked by: [02: Setup scrolls to the changed field and marks it](02-setup-scrolls-to-the-changed-field-and-marks-it.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Content, Content shows the step's finding and opens the section that holds the field if it is collapsed, such as Additional Information. Then it points at the field the way its Go to button does. It scrolls the field into view and marks it, and the cursor stays out of the text box. Content names its fields, so the steps and copies from ticket 02 can carry them. A refused Additional Information value then shows on its own field, not only under Still to complete.

- [ ] Content names every field a tester changes, together with its finding: the fragments in each section and the Additional Information fields.
- [ ] When Undo, Redo or Restore opens Content, Content shows the step's finding, opens the section that holds the field, scrolls the field into view and marks it as Go to does. The cursor stays out of the text box.
- [ ] If the field is gone, for example because Undo removed its fragment, Content scrolls to the section that held it.
- [ ] An Undo made on Content that reloads Content shows the step's finding and marks the field.
- [ ] Ticket 01's Additional Information case also checks that Content shows the finding and marks the field. A new case undoes a change to a finding that Content does not show first.
- [ ] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [ ] `docs/DATA_MAP.md` §10 says how Content points at the field.

Out of scope: Findings, which ticket 04 covers.

## Next steps

1. `/implement`: Build it once ticket 02 is done. Ticket 04 can be built before or after it.
