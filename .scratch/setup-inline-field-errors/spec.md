# Setup errors show next to the field that has them

Status: needs-info

From: [Setup field validation](../../docs/plans/setup-field-validation.md)

## Problem

A Setup field with a bad value shows its message only in the browser's own validation bubble, which disappears, and in the one Setup notice above Next. The field turns red and gets `aria-invalid`, but nothing next to it says what is wrong, and no `aria-describedby` links a message to it. With several bad fields, the tester has to match notice lines to fields by reading. WCAG 2.2 3.3.1 asks for the field to be identified and the error described in text.

## Open questions

- Where the text sits for each kind of control: a single input, a select, a date pair, an account row, a component row and a multi-line Web/API box.
- When it appears: as the tester types, on leaving the field, or only after Next or Save.
- Whether the Setup notice keeps listing invalid values once each field shows its own, or lists only missing details.
- Whether missing required fields get inline text too, or only the red outline they have today.

## Next steps

1. `/prototype`: The open question is how the inline text looks and behaves across six control shapes; a rough page answers it faster than talking.
2. `/implement`: Build the agreed version in `wireSetupRule` and `validateSetupPage`, with browser tests for the message text and its `aria-describedby` link.
