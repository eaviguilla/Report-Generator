# 04: Direct tests for save conflicts and retries

Status: ready-for-agent

Blocked by: [03: The save code runs in a test with no report page](03-the-save-code-runs-in-a-test-with-no-report-page.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** Direct tests, in the module from ticket 03, for save conflicts and for retries. Then each page test that checks only these is replaced by a direct test and deleted, so the suite tests them at the lowest layer that owns them.

Save conflicts:

- [ ] The save-conflict reply comes from the server's own Python code (`main.stale_report_detail`), not typed by hand.
- [ ] A save conflict puts the Save button in its conflict state and keeps a recovery copy. While it stands, nothing more is sent, even when an upload or a library insert asks for a save.
- [ ] "Save my version" sends the report again with the latest revision from the reply. "Load latest" removes the recovery copy and the undo history, and reloads.

Retries:

- [ ] A dropped save or a 5xx retries up to three times, after one, two and four times the idle delay.
- [ ] A refusal, such as a 422, is not retried.
- [ ] An edit or a Save click starts the count again.

Replacing page tests:

- [ ] Each page test considered is listed in this ticket's comments with its verdict. A page test is replaced only when every check in it is about the save code itself: what is sent, the Save button, storage, retries or timing. A page test that also checks page wiring, dialogs, navigation, uploads or the server's own checks stays.
- [ ] Each deleted page test names the direct test that replaces it, and that direct test exists before the page test goes.
- [ ] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.

## Next steps

1. `/implement`: Start once ticket 03 is done. Ticket 05 can run at the same time.
