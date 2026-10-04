# 02: Setup messages show under the field they are about

Status: ready-for-agent

Blocked by: [01: One plain format for every field message](01-one-plain-format-for-field-messages.md)

**What to build:** The prototype's variant A. Each Setup message from ticket 01 appears as text under the field it is about, and the field's `aria-describedby` points at that text. A tester and a screen reader both learn what is wrong without the browser's bubble, which meets WCAG 2.2 3.3.1. The prototype is on branch `prototype/setup-inline-field-errors`; the [spec](../spec.md) says how to open it.

Where the text goes:

| Control | Text |
|---|---|
| an input or a select | a line under it |
| Limitations | a line under the box |
| a date pair | one line under the Start, End and Time row for the date order and the missing dates, linked from both date inputs. The Time box has its own line under it. |
| a test account row | a full-width line under the row, spanning the table |
| a component row | a full-width line under the row, spanning the table |
| a Web/API box | a list under the box, one item per bad line, each starting "Line N" |

When it shows:

- A refusal shows when the tester leaves the field. From then on it updates as they type, and it clears the moment the value is fixed. A new refusal in a field that shows no text waits until the tester leaves.
- A refusal of a value already stored when the page opened, from an import or an old draft, shows at once, as its red outline does today.
- An issue shows after Next, or on arrival from the page gate (`?incomplete=setup`), and clears as each field is filled.
- A save held on Setup shows the text for every field that holds it. Today `save()` also holds the save for a field the tester is still typing in, so without this the reason would be hidden.
- Next shows refusals and issues together. Today `validateSetupPage` returns at the first refusal, so missing details show only after every bad value is fixed.

- [ ] Placement and timing as above, for every Setup field, including rows added later and the typed Non-Production name.
- [ ] The text sits outside the field's `<label>`. Each Setup field is wrapped by its label today, so text inside the label would become part of the field's spoken name. Each field keeps the accessible name it has today.
- [ ] The notice above Next shows one count and lists nothing: "16 things to fix before Findings. Each one is marked above, and the cursor is on the first." With one: "1 thing to fix before Findings. It is marked above, and the cursor is on it." Arriving from the page gate shows the same count.
- [ ] Next and a held save put the cursor in the first field with text, in page order. The browser's bubble (`reportValidity`) no longer opens.
- [ ] A repeated component outlines and describes only the later row. Today both rows are outlined.
- [ ] Browser tests, one per control shape: the text appears at the right moment, the field's `aria-describedby` names an element that holds it, `aria-invalid` is set, and both clear when the value is fixed. Also cover the count, the arrival from the page gate, a held save, and a field's accessible name staying the same.
- [ ] `docs/DATA_MAP.md` §12, the "setup completeness" row: how `validateSetupPage` and the notice now read the results.

Out of scope: the Content page's Additional Information fields keep the browser's bubble.

## Next steps

1. `/implement`: Placement, timing and the notice are decided. Build it once ticket 01 is done.
