# 05: Direct tests for recovery copies and held saves

Status: ready-for-agent

Blocked by: [03: The save code runs in a test with no report page](03-the-save-code-runs-in-a-test-with-no-report-page.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** Direct tests, in the module from ticket 03, for recovery copies and for held saves. Held saves are here because the check function and `holdSaves` are the module's new interface. Then each page test that checks only these is replaced by a direct test and deleted.

Recovery copies:

- [ ] An edit writes a recovery copy shortly after, and the save that covers the edit removes it.
- [ ] A copy left behind is offered on the next load. Restore brings it back as the report the page edits, the Save button reads "Recovered changes", and a save follows after the idle delay. Discard removes the copy.
- [ ] A save leaves another tab's copy alone.
- [ ] Web Storage that throws is reported to the tester, and saves to the server still work.

Held saves:

- [ ] A check function that returns words holds the save, sends nothing, and shows the words on the Save button.
- [ ] `holdSaves(true)` holds every save, including the next round of a save already out, until `holdSaves(false)`.

Replacing page tests:

- [ ] Each page test considered is listed in this ticket's comments with its verdict. A page test is replaced only when every check in it is about the save code itself: what is sent, the Save button, storage, retries or timing. A page test that also checks page wiring, dialogs, navigation, uploads or the server's own checks stays.
- [ ] Each deleted page test names the direct test that replaces it, and that direct test exists before the page test goes.
- [ ] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.

## Next steps

1. `/implement`: Tickets 03 and 04 are done: add the tests to `tests/test_save_module.py`, where each test has its own Web Storage, `self.answers` sets how the next saves are answered, and `saveRequests` counts what was sent. `test_unavailable_browser_recovery_storage_is_reported_without_blocking_server_save` was left for this ticket.
