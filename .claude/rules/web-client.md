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
- Every undo and redo ends in a full page load (`restoreHistory`): the page the step was made on, or a reload of the current page when the step was made there or records no page. Restore opens the page its recovery copy records the same way. Undo and Redo first `waitForMutations` (`settleThenStep`) and only then pop a step, because a pending library insert or upload adds its own step when it settles; popping first and then waiting acts on a stale step, and not waiting reloads away from the in-flight POST.
- Compare fragments through `sameFragments`: the client drops `false` run flags and the server writes them back, so a raw compare brings a dismissed offer banner back after a save.
- No stylesheet reinstates the browser's `[hidden]` rule, so a control that sets its own `display` needs its own `[hidden]` rule.
- A save merges the server's copy into the live model (`reconcileCanonicalObject` in `save.js`), and an array of objects with no stable key, such as a table's `header` and `rows`, is replaced by clones. A handler that captured one of those objects when the page was drawn then writes to an orphan: the page says Saved and the next save, Back included, sends the old text. Look the object up by position when the event fires, as `cellInput` does.
- A Setup field's label text is its name: tests find it with `get_by_label(..., exact=True)`, and `setupFieldName` and `headingText` read `firstChild.nodeValue` to name the field in the undo history. The required `*` is therefore CSS (`label.is-required::after`) or a sibling after a heading's text node, never text inside the label.
- To change the report as a page loads without making an Undo step, change `serverReport` before `start()` takes its baseline (Content's arrival sort, `sortFindings`), then call `scheduleAutomaticSave()` (not `scheduleSave()`) right after `start()`, before the page's own code. A change made after `start()` joins the next step, and Undo reloads the page, which makes the change again. `scheduleAutomaticSave` marks the pending save as the app's own, so the `pageshow` handler can still reload stale cached HTML over it; a tester's edit or a recovery copy is never marked.
- In `tests/test_browser.py` read the harness at the top and one neighbouring test, not the whole file. No fixed sleeps.
- **Check a UI change in a real browser before you call it done.** Use the `playwright-cli` skill (`.claude/skills/playwright-cli`) after any change under `app/web/**` or to a page route, and to reproduce a UI bug before you write its test.
  - Start the app with `.venv/bin/python -m scripts.ui_check --report finding` in the background. `--report` takes `none`, `empty`, `setup` or `finding`. It prints `URL` and `REPORT` lines, serves a temporary data folder (never `data/`), and deletes it when you stop it by PID.
  - Run `playwright-cli` from `/tmp`. It writes `.playwright-cli/` (snapshots, logs, possibly credentials) into the current folder, and that folder is not ignored. Give `snapshot` and `screenshot` a `--filename=/tmp/...`.
  - Element refs gain a prefix after a navigation (`e29` becomes `f1e29`). Take a fresh `snapshot --filename=...` and grep it for the ref instead of reusing an old one.
  - It explores and verifies. A lasting regression test still goes in `tests/test_browser.py`.
  - Install without root: `npm install -g --prefix ~/.local @playwright/cli@latest`.
