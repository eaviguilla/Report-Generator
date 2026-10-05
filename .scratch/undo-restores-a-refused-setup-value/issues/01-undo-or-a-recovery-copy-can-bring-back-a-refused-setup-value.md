# Undo or a restored recovery copy can bring back a Setup value the server refuses

Status: done (2026-10-06)
From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)
Blocked by: [The save code moves into its own file](../../save-module/issues/02-the-save-code-moves-into-its-own-file.md)

## What happens

The browser checks Setup's fields before a save only while Setup is open. Undo history and recovery copies follow the tester to Findings and Content. An Undo there, or a recovery copy restored there, can put back a Setup value the server refuses. The save then fails with a 422. Back and Next stay blocked, because both save before they leave. The tester gets out by pressing Redo, or by typing the Setup address.

Example: on Setup the tester leaves the application name holding a character the field does not allow, comes back to fix it, and goes on to Findings. One Undo on Findings puts the character back, and every save from then on is refused.

Content's three Additional Information fields set the same trap. The server refuses a bad character in Severity Review Tickets, CVSS Score or CVSS Vector, stored or not, and an Undo or a restored recovery copy on Setup or Findings can bring one back.

## Expected

Undo, Redo and Restore take the tester to the page where the change was made and point at its field, so a refused value always shows up where the tester can fix it. The Answers below hold the details.

## Notes

- DATA_MAP §12 records the cause. Only Setup runs its check before a save, and Undo (`restoreHistory`) and recovery call `save()` directly on every page.
- No test covers it. The Undo tests on Findings and Content undo changes made on those pages.
- Review item 06 moves the save code into `app/web/static/save.js`. Building this after that move avoids editing code that is about to move. As of commit `2ee0acc`, the pages run the save code in `app.js`, and `save.js` holds a copy that no page starts.

## Answers

Settled with the user on 5 October 2026. "Undo step" and "recovery copy" are defined in `GLOSSARY.md`.

1. **Undo and Redo go to the change.** Undo and Redo work on every page. Each undo step records the page and the field where the tester made it. After the change, the browser opens that page and points at the field, also when it is the current page. A refused value therefore always lands on the page that shows it. This covers Content's Additional Information fields as well as Setup's.
2. **How the page points at the field.** It scrolls the field into view and marks it, the way Content's Go to button marks a target. The cursor stays out of the text box. Once the keyboard plan ships, Ctrl+Z inside a text box runs the browser's own undo, so a second Ctrl+Z there would do nothing. If the field is gone, for example because Undo removed its row, the page scrolls to the section that held it.
3. **Restore goes to the copy's page.** Each recovery copy records the page where its edits were made and the last field changed there. Restore opens that page and points at that field the same way. When that is not the current page, the button names it, for example "Restore on Content".
4. **Order.** This waits until the save code moves into `save.js` (save-module ticket 02), so the Undo code is not edited twice.

Decided without asking, then confirmed with the user:

- A step belongs to the page where the tester made it, even when it also changed data shown on another page. A scope change on Setup that removed a finding's location goes back to Setup.
- The browser still saves the undone report before it opens the page, so the page gate judges the undone state. If the server refuses it, the browser opens the page anyway with the recovery copy, and that page shows the refused value. Setup holds the save and shows the field's message. Content shows the field's message.
- The recovery copy written during an Undo belongs to the step's page.
- Undo steps and copies written before this change record no page. They undo or restore in place, as today. Undo steps live in the tab's session storage, so they go when the tab closes.
- If a page gate sends the tester elsewhere, the report opens where they land, as today.
- A collapsed section that holds the field opens, such as Content's Additional Information.
- The page tells the save code its name when it starts it, so the save code still does not read `root.dataset.step` (review item 06, answer 4).
- Regression tests cover four cases: Undo and Redo of a Setup step from Findings that bring back a refused value, Undo of an Additional Information step from Findings, Restore on Findings of a copy written on Setup, and an Undo that stays on its own page. DATA_MAP §9, §10 and §12 change in the same commit.

Left out:

- A general way out of any refused save. Back and Next still save before they leave. After this change a refused value only shows up on the page that holds it, where the tester can fix it.
- The one refused save the browser sends before it opens the page. The server writes nothing for it.

Built on 5 and 6 October 2026 through the four tickets in `.scratch/undo-and-restore-go-to-the-change/issues/`. The code review's fixes are recorded in tickets 01, 02 and 04.
