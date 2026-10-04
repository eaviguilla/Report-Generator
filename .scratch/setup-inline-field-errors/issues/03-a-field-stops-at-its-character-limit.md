# 03: A field stops at its character limit and says so

Status: ready-for-agent

Blocked by: [02: Setup messages show under the field they are about](02-setup-messages-show-under-their-field.md)

**What to build:** Every Setup field with a character limit, except a scope target, stops taking characters at its limit and cuts a paste to fit. A grey note under the field says so. This was decided on 2026-10-05 (see the [spec](../spec.md)) and reverses the Setup field validation plan's "never shorten a value" for these fields.

The fields: Application name, CI number, BSN number, Application owner, Tester, each test time, User role, Username, Limitations, and a component's Description. Read their limits from the served vocabulary (`character_rules`, `scope_limits`) rather than typing them. The typed Non-Production name already stops at 40 (`maxlength` in `app.js`, from `NonProductionLabel` in `app/models.py`) and gets the note too.

Not cut: a Web/API line (500 per line) and a component name (200). A cut URL or component name names a different scope target, so these keep ticket 01's message, and the save waits.

The note:

- Typing at the limit: `Tester holds up to 60 characters.`
- A paste cut to fit: `Tester holds up to 60 characters, so the paste was cut to fit.`
- It is grey, not red. It sits where ticket 02 puts a message, is linked by `aria-describedby`, and is announced politely, because it appears while the tester is in the field. It clears on the next edit and when the tester leaves the field. It holds neither the save nor Next.

- [ ] `maxlength` on each field above, with the note on a blocked keystroke and on a cut paste.
- [ ] A value already over its limit, from an old draft or an import, keeps its message, can still be shortened, and gets no note.
- [ ] The server keeps its length refusal for changed values, because Undo, local draft recovery and other pages can still send one.
- [ ] Check how Chromium counts a line break against a textarea's `maxlength`. The server counts one. If Chromium counts two, Limitations stops early, which is safe; record which in `docs/DATA_MAP.md`.
- [ ] Check that a paste cut by `maxlength` never leaves half an emoji, which the server would refuse as a hidden character. If Chromium can leave one, cut the paste in a `paste` handler instead.
- [ ] Browser tests: typing stops at the limit and the note shows; a paste longer than the room left is cut and the note says so; a Web/API line and a component name go past their limits and show the message; a stored value over its limit shows the message and can be shortened. In headless Chromium, a synthetic `ClipboardEvent("paste")` followed by `document.execCommand("insertText")` drives a paste; the prototype was checked that way.
- [ ] `docs/DATA_MAP.md` §12, the "a Setup field is at most its length" row: replace "No input carries `maxlength`" with the new behaviour.
- [ ] `docs/plans/setup-field-validation.md`, "What deviated": add a dated line under the "No HTML `maxlength`" bullet that points here.

## Next steps

1. `/implement`: Small and decided. Build it once ticket 02 is done.
