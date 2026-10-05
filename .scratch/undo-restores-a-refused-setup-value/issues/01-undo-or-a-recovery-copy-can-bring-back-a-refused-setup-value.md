# Undo or a restored recovery copy can bring back a Setup value the server refuses

Status: needs-info
From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

## What happens

The browser checks Setup's fields before a save only while Setup is open. Undo history and recovery copies follow the tester to Findings and Content. An Undo there, or a recovery copy restored there, can put back a Setup value the server refuses. The save then fails with a 422. Back and Next stay blocked, because both save before they leave. The tester gets out by pressing Redo, or by typing the Setup address.

Example: on Setup the tester leaves the application name holding a character the field does not allow, comes back to fix it, and goes on to Findings. One Undo on Findings puts the character back, and every save from then on is refused.

## Expected

Not decided. Two directions came up: refuse the undo on a page that cannot show the field, or apply it and open Setup with the field marked. A restored recovery copy needs the same answer.

## Notes

- DATA_MAP §12 records the cause. Only Setup runs its check before a save, and Undo (`restoreHistory`) and recovery call `save()` directly on every page.
- No test covers it. The Undo tests on Findings and Content undo changes made on those pages.
- Review item 06 moves the save code into `app/web/static/save.js` and lets each page pass its own save check. Building this after that move avoids editing code that is about to move, and any page can then pass the Setup check.

## Next steps

1. `/grill-with-docs`: What Undo and a restored recovery copy should do on Findings and Content with a refused Setup value is not decided.
