# Setup messages show next to the field they are about

Status: done

From: [Setup field validation](../../docs/plans/setup-field-validation.md)

## Problem

A Setup field with a bad value shows its message only in the browser's own validation bubble, which disappears, and in the one Setup notice above Next. The field turns red and gets `aria-invalid`, but nothing next to it says what is wrong, and no `aria-describedby` links a message to it. With several bad fields, the tester has to match notice lines to fields by reading. WCAG 2.2 3.3.1 asks for the field to be identified and the error described in text.

The messages are also hard to read, and they do not share a shape. A character Word cannot store reads `contains invalid character: "\u0007" (Unicode U+0007)`, and the notice mixes nouns, sentences and `--`. A value over its character limit gets a refusal the tester could have been spared, because the field could have stopped taking characters.

## Answers

Decided 2026-10-05, after the prototype.

- **Placement: under the field, the prototype's variant A.** An input or a select gets a line under it. A date pair gets one line under its Start, End and Time row, for both dates. A test account row and a component row get a full-width line under the row. A Web/API box gets a list under it, one item per bad line, each starting "Line N". The other two placements, above the field and listed per card, were not chosen.
- **Timing, as variant A showed it.** A refusal shows when the tester leaves the field, then updates as they type, and clears the moment the value is fixed. A refusal of a value already stored when the page opened shows at once. An issue shows after Next, or on arrival from the page gate.
- **Missing details get text too**, not only the red outline.
- **The notice above Next becomes a count**, such as "16 things to fix before Findings. Each one is marked above, and the cursor is on the first." It lists nothing, because each message already sits under its own field.
- **"Just informational" means plain words.** Every message names its field, says what is wrong, then what to do, with no codes, escapes, Unicode numbers or `--`. A missing value is one instruction, such as "Choose a segment." Refusals still hold the save and issues still hold Next, as the Setup field validation plan agreed. Ticket 01 holds the full wording. It applies wherever a rule is worded, including the server's refusals, the Generate refusal and the Content page's Additional Information fields.
- **A field with a character limit stops typing at it and cuts a paste, except a scope target.** A grey note under the field says so, and the note holds neither the save nor Next. Web/API lines and component names are never cut, because a cut URL or component name names a different scope target. They keep the message, and the save waits. A value already over its limit, from an old draft or an import, keeps its message. This reverses the plan's "never shorten a value" for every field but scope targets.

## Prototype

Branch `prototype/setup-inline-field-errors`, commit `0fe2f22`, file `.scratch/setup-inline-field-errors/prototype.html`. It is a static copy of the Setup page that loads the real stylesheets and runs simplified copies of the rules. Open it as a file; `?variant=today|A|B|C` switches the placement. To look at it again, run `git show prototype/setup-inline-field-errors:.scratch/setup-inline-field-errors/prototype.html > .scratch/setup-inline-field-errors/prototype.html`, and delete the file afterwards, because it does not belong on main.

## Tickets

1. [01: One plain format for every field message](issues/01-one-plain-format-for-field-messages.md)
2. [02: Setup messages show under the field they are about](issues/02-setup-messages-show-under-their-field.md), blocked by 01
3. [03: A field stops at its character limit and says so](issues/03-a-field-stops-at-its-character-limit.md), blocked by 02

## Out of scope

- Text under the Content page's Additional Information fields. They keep the browser's bubble, with the new wording.
- Any change to which values are refused or which details are required.
