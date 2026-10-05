---
paths:
  - "app/web/**"
  - "tests/test_browser.py"
---
<!-- Generated from .github/instructions/web-client.instructions.md. Edit that file, not this one. -->

# Browser client

- No framework and no build step: edit `app/web/static/*.js` directly. `app.js` is nearly 4,000 lines of page code, and the save code (autosave, save conflicts, recovery copies, undo) is in `save.js`, about 700 more. Find a function with a code search or outline and read it by name or line range, never a whole file.
- A rule that exists in Python and JS changes in pairs (`docs/DATA_MAP.md` §12). Setup rules live in `app/web/static/rules.js` (`vrRules`, page-free, takes the report and the vocabulary) and are guarded by `tests/test_rule_cases.py`, one case table run against both sides; a moved rule gets a case there. The other twins have only the contract tests in `test_browser.py`, or nothing. Do not add a third copy of a twinned rule; call the existing function.
- Fixed lists are not twins. Statuses, severities, segments, report types, network access, app types and their labels, the non-production presets, every field's character rule, the placeholder pattern, the resolved remediation sentence and the report pages' names reach every page in the `#vocabulary` JSON that `_vocabulary.html` writes. Read them from `vocabulary`; never type one into a script or template. A new list goes into `client_vocabulary()` in `app/vocabulary.py`.
- `scope_text` is request-only: it is in PUT bodies and never in responses.
- Every undo and redo ends in a full page load (`restoreHistory`): the page the step was made on, or a reload of the current page when the step was made there or records no page. Restore opens the page its recovery copy records the same way.
- Compare fragments through `sameFragments`: the client drops `false` run flags and the server writes them back, so a raw compare brings a dismissed offer banner back after a save.
- No stylesheet reinstates the browser's `[hidden]` rule, so a control that sets its own `display` needs its own `[hidden]` rule.
- In `tests/test_browser.py` read the harness at the top and one neighbouring test, not the whole file. No fixed sleeps.
