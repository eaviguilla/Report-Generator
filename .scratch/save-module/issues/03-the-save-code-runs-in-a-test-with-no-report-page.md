# 03: The save code runs in a test with no report page

Status: done (2026-10-05)

Blocked by: [02: The save code moves into its own file](02-the-save-code-moves-into-its-own-file.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** A new Python test module runs the save code in a blank Chromium page, with no app server and no report page, as [ADR 0004](../../../docs/adr/0004-the-save-module-calls-the-browser-and-tests-fake-the-browser.md) records. `page.route` serves the page from a made-up address, so its Web Storage is real. The page holds the Save, Undo and Redo buttons and loads the diagnostics script and `save.js`. Tests answer saves with `page.route` and move time with `page.clock`. The first direct tests cover the merge of the server's reply, plus one save from an edit to Saved. `tests/test_rule_cases.py` is the nearest example of a module like this.

- [x] The module starts no app server and opens no report page.
- [x] The clock is installed before the save code loads. No test sleeps; each one waits for a signal or moves the clock.
- [x] Direct tests of `reconcileCanonicalObject`. A value the server changed is adopted, and a value the tester changed while the save was out is kept. An item the server added appears. An item the server removed goes, unless the tester changed it meanwhile. Items with ids merge by id, and a list without ids is replaced only when the tester left it alone. Scope text, `saved_at`, `app_id` and the folder-name hint are skipped.
- [x] One test goes through `vrSave.start`: an edit, the idle time passing on the clock, exactly one save request carrying the edited report, and the Save button reading Saved.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.

Out of scope: replacing page tests, which tickets 04 and 05 do.

## What deviated

The module is `tests/test_save_module.py`. The made-up address is `https://save-module.test`, not plain http: `save.js` calls `crypto.randomUUID`, which a page only has in a secure context. Each test gets its own browser context, so no test sees another's Web Storage, and the clock is paused at a fixed start as well as installed, so a timer fires only when a test moves the clock. The server's reply to a save is built with the server's own `Report` model rather than typed out. The merge cases are one table run as subtests, with two cases beyond the ticket's list: a value the server dropped, and a nested value the server changed beside the tester's edit. Each case and the save test were checked against mutated copies of `save.js` served from a temporary folder, so the file in the workspace never changed: every mutation failed the row it targets. `.github/instructions/tests.instructions.md` now points save-code tests at the module, and its Claude copy was regenerated.
