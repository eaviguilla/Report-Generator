# 03: Content scrolls to the changed field and marks it

Status: done (2026-10-06)

Blocked by: [02: Setup scrolls to the changed field and marks it](02-setup-scrolls-to-the-changed-field-and-marks-it.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** When Undo, Redo or Restore opens Content, Content shows the step's finding and opens the section that holds the field if it is collapsed, such as Additional Information. Then it points at the field the way its Go to button does. It scrolls the field into view and marks it, and the cursor stays out of the text box. Content names its fields, so the steps and copies from ticket 02 can carry them. A refused Additional Information value then shows on its own field, not only under Still to complete.

- [x] Content names every field a tester changes, together with its finding: the fragments in each section and the Additional Information fields.
- [x] When Undo, Redo or Restore opens Content, Content shows the step's finding, opens the section that holds the field, scrolls the field into view and marks it as Go to does. The cursor stays out of the text box.
- [x] If the field is gone, for example because Undo removed its fragment, Content scrolls to the section that held it.
- [x] An Undo made on Content that reloads Content shows the step's finding and marks the field.
- [x] Ticket 01's Additional Information case also checks that Content shows the finding and marks the field. A new case undoes a change to a finding that Content does not show first.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [x] `docs/DATA_MAP.md` §10 says how Content points at the field.

Out of scope: Findings, which ticket 04 covers.

## What deviated

Content's name for a field is its finding's `uid`, its section's content type and its fragment's `frag_id`; an Additional Information field uses the `{uid}:{key}` id its card already carried for Go to. A control in a section but outside a fragment, such as Add a fragment or a library offer, names the section alone, and Undo then scrolls to that section. Building the case where the field is gone turned up a gap: Delete fragment, Move, Convert and the offer buttons rebuild the pane before the step is recorded, so the focused button was gone and the step named nothing. `render()` now keeps the name of what had focus until the end of that task, and the step takes it. The pointed fragment becomes Go to's target, so the mark survives the pane's rebuilds and the incomplete rings on other fields stay off until the next click, as after Go to. Every section starts open on a page load, so no code opens a collapsed one. The new case for a finding Content does not show first is an Undo on Content of a Description edit, which also covers the Undo that reloads Content. Restore has no browser test of its own: it hands the page its copy's field the same way, and `tests/test_save_module.py` covers that. DATA_MAP §9 also changed, to describe Content's names.

## Next steps

1. `/implement`: Build [ticket 04](04-findings-scrolls-to-the-changed-field-and-marks-it.md); this ticket is done.
