# 01: Undo, Redo and Restore open the page where the change was made

Status: done (2026-10-05)

Blocked by: [The save code moves into its own file](../../save-module/issues/02-the-save-code-moves-into-its-own-file.md)

From: [Undo or a restored recovery copy can bring back a Setup value the server refuses](../../undo-restores-a-refused-setup-value/issues/01-undo-or-a-recovery-copy-can-bring-back-a-refused-setup-value.md)

**What to build:** Undo, Redo and Restore take the tester to the page where the change was made, so a value the server refuses lands on the page that shows it. Each new undo step records the page the tester made it on, and each recovery copy records the page where its edits were made. Undo and Redo still save the undone report first, so the page gate judges the undone state. Then they open the step's page, or reload the page when the step was made there. Restore opens the copy's page, and when that is not the current page its button names it, for example "Restore on Content". A refused Setup value then shows on Setup, which shows the field's message and holds the save. A refused Additional Information value shows on Content, which lists it under Still to complete. Scrolling to the field and marking it come in tickets 02 to 04. The item's Answers hold the decisions.

- [x] The page tells the save code its name when it starts it. The save code still does not work out the page from the page's markup.
- [x] Each new undo step records the page where the tester made it, even when the change also altered data shown on another page. A scope change on Setup that removed a finding's location belongs to Setup.
- [x] Undo and Redo save the undone report, then open the step's page. If the server refuses that save, the page still opens and takes up the recovery copy written during the Undo. When the step's page is the current page, the page reloads as today.
- [x] After an Undo has opened another page, Redo there brings the change back.
- [x] Each recovery copy records the page where its edits were made. The copy written during an Undo or Redo records the step's page.
- [x] Restore opens the copy's page. When that is not the current page, the button names it, for example "Restore on Content". On the copy's own page it still reads "Restore".
- [x] Undo steps and recovery copies written before this change record no page. They undo, redo and restore in place, as today.
- [x] If a page gate sends the tester to another page, the report opens where they land, as today.
- [x] Regression tests cover the item's four cases:
  - Undo and Redo of a Setup step from Findings that bring back a refused value. Setup opens, shows the field's message and holds the save.
  - Undo of an Additional Information step from Findings. Content opens and lists the refused value under Still to complete.
  - Restore on Findings of a copy written on Setup. Setup opens with the copy.
  - An Undo that stays on its own page.
- [x] Direct tests of the save code, with no report page, cover a step and a copy recording their page, the page that Undo, Redo and Restore open, and the Restore button's words.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.
- [x] `docs/DATA_MAP.md` §9, §10 and §12 change in the same commit and say where Undo, Redo and Restore take the tester. §12's sentence that Undo and recovery can still bring back a refused Setup value is replaced. The web-client rule that says every undo and redo ends in a full page reload names the page it loads, and its Claude copy is regenerated with the sync script.

Out of scope:

- Scrolling to the changed field and marking it, which tickets 02 to 04 do.
- A general way out of any refused save. Back and Next still save before they leave.
- The one refused save the browser sends before it opens the page. The server writes nothing for it.

## What deviated

A page's name is the last part of its address: `setup`, `findings`, or `edit` for Content. `app.js` works it out the way it already picks `setup()` or `continuousEditor()`. The three names a tester sees, for the Restore button, come from the vocabulary's `report_pages`, which `app.js` hands `vrSave.start` as `pageNames`; the code review moved them there from the save code. The save code treats a recorded page it does not know as no page. Steps and copies carry the name in a new `page` field, so a step or copy written earlier still loads and works in place. The fourth regression case, an Undo that stays on its own page, is a check added to `test_text_undo_redo_and_interrupted_save_recovery`, beside a direct test of the same thing. The Additional Information case stores the refused value directly, as an import can, rather than typing it on Content first: the server refuses that value stored or not. The direct tests' blank page now opens at a report-page address, so a test reads which page opened from the address. One edge stays open: when a page gate sends an Undo's refused copy to another page and the save fails there too, the next copy records the page the tester landed on, since that page's edits are now its own.
