# The Word cover prints the chosen network access

Status: ready-for-human

From: [Setup field validation](../../docs/plans/setup-field-validation.md), [Setup network access field](../../docs/plans/setup-network-access.md)

## Problem

None of the four Word templates carries the `{{network}}` token, so every cover reads `Internal`, even when the tester chose External. The code has filled the token since `c599dc6`; only the templates are missing it. Step 6 of `docs/plans/setup-network-access.md` was this edit and was never done. Once Setup field validation makes Network Access an explicit choice, the cover still will not show that choice.

## What to do

The edit is by hand in Word, because the templates are binary and are changed only with the user's approval.

- [ ] In each of `resources/MAIN.docx`, `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx` and `MAIN_THICK_MOBILE_ASIA.docx`, replace the cover value cell reading `Internal` with `{{network}}`. The cover block occurs twice in every template, so that is 8 cells.
- [ ] Leave the third `Internal` alone: it is the Remediation Timelines column header.
- [ ] Run the unresolved-placeholder test in `tests.test_docx` on all four templates, and add one render test asserting a report set to External prints `External` on both cover blocks.
- [ ] Decide whether DOCX import should then read network access from the cover instead of leaving it unset.

If only one of the two cover blocks gets the token, the two blocks disagree, and a later import that reads the cover would see conflicting values for one label.

## Next steps

1. `/implement`: Edit the four templates in Word on Windows, after Setup field validation makes Network Access nullable, so the cover can print `N/A` for an unset value.
