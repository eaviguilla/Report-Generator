# 02: Setup scrolls to the changed field and marks it

Status: done (2026-10-06)

Blocked by: [01: Undo, Redo and Restore open the page where the change was made](01-undo-redo-and-restore-open-the-page-where-the-change-was-made.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Setup, Setup scrolls the changed field into view and marks it the way Content's Go to button marks a target. The cursor stays out of the text box. Once the keyboard plan ships, Ctrl+Z inside a text box runs the browser's own undo, so a cursor left there would stop a second Ctrl+Z from reaching the app. To make this work, each new undo step also records the field where the tester made it, and each recovery copy records the last field changed on its page. The page names the field. The save code keeps that name with the step or the copy and hands it back to the page it opens. This ticket builds the recording for every page and teaches Setup to point at the field. Tickets 03 and 04 teach Content and Findings.

- [x] Each new undo step records the field where the tester made it. A step made with no field focused, such as an upload that finishes later, records its page alone, and that page opens without marking anything.
- [x] Each recovery copy records the last field changed on its page. The copy written during an Undo or Redo records the step's field.
- [x] A field's name still finds the field after a reload and a move to another page. Steps and copies with no field open their page and mark nothing.
- [x] When Undo, Redo or Restore opens Setup, Setup scrolls the field into view and marks it the way Go to does, and the mark goes away the way Go to's does when the tester clicks elsewhere. The cursor stays out of the text box. This also happens when the step was made on Setup and Setup reloads.
- [x] If the field is gone, for example because Undo removed its test account or component row, Setup scrolls to the section that held it.
- [x] A page marks only its own fields. If a page gate sends the tester to another page, that page marks nothing.
- [x] Ticket 01's Setup cases also check the mark: Undo and Redo from Findings, Restore on Findings of a copy written on Setup, and an Undo on Setup that stays there. A new case undoes an added test account row and lands on its section.
- [x] Direct tests of the save code cover a step and a copy recording their field, and the field going only to the page it belongs to.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [x] `docs/DATA_MAP.md` §9 and §10 say that steps and copies record their field, and how a page points at it.

Known, by decision: when Setup opens with a refused value, it holds its first autosave, about 5 seconds after the page opens. A held autosave puts the cursor in the first field with an error, and the notice under the page says the cursor is on it. That stays as it is, and `test_held_autosave_shows_every_refusal_on_setup` keeps checking it. The cursor stays out of the text box only until then. A tester who presses Ctrl+Z several times in a row does it well within those 5 seconds.

Out of scope: Content and Findings, which tickets 03 and 04 teach to point at the field.

## What deviated

The page names a field through a `nameField` function it hands `vrSave.start`; the save code calls it on the focused element when it records a step, and stores what comes back without reading it. Setup's name for a field is an object: its section's heading text, its `data-path`, its label, its scope panel and its component row. The heading's own text is used, because Setup appends a live count inside each heading. The opened page learns the field through a new `sessionStorage` key, `vulnreport-changed-field:{reportId}`, which the next page load always removes, and `start` returns it as `changedField` only when the key names this page. Findings and Content pass no `nameField` yet, so their steps record their page alone until tickets 03 and 04. Building the added-account case turned up a bug: Add account meant to put the cursor in the new row, but the row's hidden message row sits after it, so the cursor stayed on the button and the step named no field. Add account now focuses the new row's User role box, and the new test checks that. The field is scrolled to without focus, so it uses the page's smooth scrolling; a section is scrolled to its top, a field to the middle of the view. The review found two more gaps, both fixed with a test. The app type and environment boxes rebuild under the cursor before a step is recorded, so the rebuild now puts focus back on the same box, and the step names it. A restored copy's field was lost when the page wrote the copy again; a page keeps the field of a copy written on itself. The code review found two more, each fixed with a test. When storage refused the changed-field key, Undo, Redo and Restore showed the warning and left the page anyway; now they stay, as for any other storage failure. Remove account, Remove component and the Limitations offer's Use it took the cursor off the field they change before the step was recorded, so the step named nothing; each now names that field, through `keepFieldName`.
