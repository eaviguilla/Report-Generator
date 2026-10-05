# 04: Direct tests for save conflicts and retries

Status: done (2026-10-05)

Blocked by: [03: The save code runs in a test with no report page](03-the-save-code-runs-in-a-test-with-no-report-page.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** Direct tests, in the module from ticket 03, for save conflicts and for retries. Then each page test that checks only these is replaced by a direct test and deleted, so the suite tests them at the lowest layer that owns them.

Save conflicts:

- [x] The save-conflict reply comes from the server's own Python code (`main.stale_report_detail`), not typed by hand.
- [x] A save conflict puts the Save button in its conflict state and keeps a recovery copy. While it stands, nothing more is sent, even when an upload or a library insert asks for a save.
- [x] "Save my version" sends the report again with the latest revision from the reply. "Load latest" removes the recovery copy and the undo history, and reloads.

Retries:

- [x] A dropped save or a 5xx retries up to three times, after one, two and four times the idle delay.
- [x] A refusal, such as a 422, is not retried.
- [x] An edit or a Save click starts the count again.

Replacing page tests:

- [x] Each page test considered is listed in this ticket's comments with its verdict. A page test is replaced only when every check in it is about the save code itself: what is sent, the Save button, storage, retries or timing. A page test that also checks page wiring, dialogs, navigation, uploads or the server's own checks stays.
- [x] Each deleted page test names the direct test that replaces it, and that direct test exists before the page test goes.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.

## What deviated

"Load latest" did not work: during a conflict the save code still counts the edit as unsaved, so the `pagehide` handler wrote the recovery copy back while the page reloaded, and the next load offered the discarded version again. The direct test found it; `save.js` now clears the unsaved mark in "Load latest" before reloading, and DATA_MAP §5 says so. The conflict reply is the server's whole answer, not only `stale_report_detail`: the test passes that detail through `main.http_exception_handler`, so the body, the diagnostic and the `X-VulnReport-Error` header are the server's. The blank page counts save requests as they are sent, because reading the Save button's "Saving..." raced with the answer. Each new test was checked against a `save.js` copy broken for it (16 mutations, served from a temporary folder); every one failed.

## Comments

Page tests considered, with their verdicts:

- `test_transient_autosave_failure_retries_without_another_edit`: **deleted**. It checked the number of saves sent, that the retried save carried the edit, and that the failure notice went away: all save code. Replaced by `test_a_retry_that_succeeds_saves_the_edit_and_clears_the_failure`, with the timing in `test_a_failed_save_retries_three_times_after_one_two_and_four_idle_delays`.
- `test_stale_save_keeps_local_recovery_until_confirmed`: **deleted**. It checked the conflict notice, the recovery copy, the resend after "Save my version" and a later save: all save code. The server's half, the 409 and its `latest_saved_at`, is `test_app.test_save_rejects_stale_writes_and_removed_scope_references`. Replaced by `test_a_save_conflict_shows_resolve_conflict_and_keeps_a_recovery_copy` and `test_save_my_version_sends_the_report_again_with_the_latest_revision`. A real two-tab conflict through the server still runs in the two page tests below that stay.
- `test_two_tabs_racing_the_first_save_after_editable_import_conflict_correctly`: stays. It checks the revision the import route writes, which is the server's.
- `test_upload_attempt_during_conflict_keeps_the_resolution_state`: stays. It checks the upload wiring, including that the file input is emptied so the same screenshot can be chosen again.
- `test_supporting_tile_survives_conflict_resolution_before_upload`: stays. It checks the evidence tile on the Content page and the upload after the conflict.
- `test_previous_saves_before_library_replacement_and_next_navigation`: stays. A failed save holding Previous is navigation.
- `test_text_undo_redo_and_interrupted_save_recovery`: stays. It checks undo's reload and the recovery offer on a real page; recovery copies are ticket 05's.
- `test_unavailable_browser_recovery_storage_is_reported_without_blocking_server_save`: left to ticket 05. Its retry is incidental to the storage warning it checks.
- `test_a_failed_second_import_request_after_mode_choice_can_be_retried`: not save code; it retries an import request on the home page.
