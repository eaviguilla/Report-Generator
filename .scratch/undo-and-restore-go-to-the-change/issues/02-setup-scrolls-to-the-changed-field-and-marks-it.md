# 02: Setup scrolls to the changed field and marks it

Status: ready-for-agent

Blocked by: [01: Undo, Redo and Restore open the page where the change was made](01-undo-redo-and-restore-open-the-page-where-the-change-was-made.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Setup, Setup scrolls the changed field into view and marks it the way Content's Go to button marks a target. The cursor stays out of the text box. Once the keyboard plan ships, Ctrl+Z inside a text box runs the browser's own undo, so a cursor left there would stop a second Ctrl+Z from reaching the app. To make this work, each new undo step also records the field where the tester made it, and each recovery copy records the last field changed on its page. The page names the field. The save code keeps that name with the step or the copy and hands it back to the page it opens. This ticket builds the recording for every page and teaches Setup to point at the field. Tickets 03 and 04 teach Content and Findings.

- [ ] Each new undo step records the field where the tester made it. A step made with no field focused, such as an upload that finishes later, records its page alone, and that page opens without marking anything.
- [ ] Each recovery copy records the last field changed on its page. The copy written during an Undo or Redo records the step's field.
- [ ] A field's name still finds the field after a reload and a move to another page. Steps and copies with no field open their page and mark nothing.
- [ ] When Undo, Redo or Restore opens Setup, Setup scrolls the field into view and marks it the way Go to does, and the mark goes away the way Go to's does when the tester clicks elsewhere. The cursor stays out of the text box. This also happens when the step was made on Setup and Setup reloads.
- [ ] If the field is gone, for example because Undo removed its test account or component row, Setup scrolls to the section that held it.
- [ ] A page marks only its own fields. If a page gate sends the tester to another page, that page marks nothing.
- [ ] Ticket 01's Setup cases also check the mark: Undo and Redo from Findings, Restore on Findings of a copy written on Setup, and an Undo on Setup that stays there. A new case undoes an added test account row and lands on its section.
- [ ] Direct tests of the save code cover a step and a copy recording their field, and the field going only to the page it belongs to.
- [ ] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [ ] `docs/DATA_MAP.md` §9 and §10 say that steps and copies record their field, and how a page points at it.

Known, by decision: when Setup opens with a refused value, it holds its first autosave, about 5 seconds after the page opens. A held autosave puts the cursor in the first field with an error, and the notice under the page says the cursor is on it. That stays as it is, and `test_held_autosave_shows_every_refusal_on_setup` keeps checking it. The cursor stays out of the text box only until then. A tester who presses Ctrl+Z several times in a row does it well within those 5 seconds.

Out of scope: Content and Findings, which tickets 03 and 04 teach to point at the field.

## Next steps

1. `/implement`: Ticket 01 is done, so nothing blocks this.
