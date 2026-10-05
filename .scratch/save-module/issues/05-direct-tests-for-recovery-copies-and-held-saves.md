# 05: Direct tests for recovery copies and held saves

Status: done (2026-10-05)

Blocked by: [03: The save code runs in a test with no report page](03-the-save-code-runs-in-a-test-with-no-report-page.md)

From: [Give the save machine its own module and a seam](../../architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

**What to build:** Direct tests, in the module from ticket 03, for recovery copies and for held saves. Held saves are here because the check function and `holdSaves` are the module's new interface. Then each page test that checks only these is replaced by a direct test and deleted.

Recovery copies:

- [x] An edit writes a recovery copy shortly after, and the save that covers the edit removes it.
- [x] A copy left behind is offered on the next load. Restore brings it back as the report the page edits, the Save button reads "Recovered changes", and a save follows after the idle delay. Discard removes the copy.
- [x] A save leaves another tab's copy alone.
- [x] Web Storage that throws is reported to the tester, and saves to the server still work.

Held saves:

- [x] A check function that returns words holds the save, sends nothing, and shows the words on the Save button.
- [x] `holdSaves(true)` holds every save, including the next round of a save already out, until `holdSaves(false)`.

Replacing page tests:

- [x] Each page test considered is listed in this ticket's comments with its verdict. A page test is replaced only when every check in it is about the save code itself: what is sent, the Save button, storage, retries or timing. A page test that also checks page wiring, dialogs, navigation, uploads or the server's own checks stays.
- [x] Each deleted page test names the direct test that replaces it, and that direct test exists before the page test goes.
- [x] Each new test fails when its behaviour is broken once by hand, and `--affected` passes.

## What deviated

No bug turned up, so `save.js` is unchanged. The tests go beyond the list in three places. When Web Storage refuses Restore or Discard, the copy stays and the tester is told, which a page test checked and a direct test now does. Web Storage that throws is tested for `localStorage` and for `sessionStorage`. Discard is tested for a copy of the saved revision and for a copy of an older one, which get different messages. The blank page's start now always passes a check function that returns `window.heldBy`, so a test holds saves by setting it. The two-tab test opens a real second tab in the same browser, which shares `localStorage` but not `sessionStorage`, and reads each tab's id from its copy. Each new test was checked against a `save.js` copy broken for it, 22 mutations served from a temporary folder, and every one failed. Two of the first mutations survived because they were incomplete, and were redone. One moved only the read of the tab id, so each tab still made its own id. The other removed one of three places that bring the storage warning back after a save.

## Comments

Page tests considered, with their verdicts:

- `test_unavailable_browser_recovery_storage_is_reported_without_blocking_server_save`: **deleted**. It checked the storage warning, a failed save and its retry, the value sent and the warning coming back. All of that is save code. That the server stores a save it accepts is checked by every page test that saves. Replaced by `test_web_storage_that_throws_is_reported_and_saves_still_reach_the_server`.
- `test_recovery_actions_report_late_storage_failures_without_losing_the_draft`: **deleted**. It checked that Restore and Discard, refused by Web Storage, show the warning and keep the copy. All of that is save code. Replaced by `test_restore_or_discard_that_storage_refuses_keeps_the_copy_and_says_so`.
- `test_saving_one_tab_keeps_the_other_tabs_recovery_snapshot`: **deleted**. It checked that two tabs get different ids and that a save removes only its own tab's copies. All of that is save code. Replaced by `test_a_save_leaves_another_tabs_copy_alone`, which also covers the copy under the older key format.
- `test_stale_local_draft_does_not_replace_newer_backend_report`: stays. It checks that the Setup field shows the server's value, which is page wiring. Its message and Discard are also in `test_discard_removes_the_copy_left_behind`.
- `test_later_page_save_does_not_erase_an_unresolved_recovery_draft`: stays. It goes from Setup to Findings with Back and Forward and accepts the leave-page dialog.
- `test_text_undo_redo_and_interrupted_save_recovery`: stays. It checks undo's reload and the restored value in a Setup field.
- `test_undo_does_not_reload_or_lose_changes_when_recovery_write_fails`: stays. It checks the URL and the field after undo, and undo is outside this ticket.
- `test_server_normalization_reaches_the_live_browser_draft`: stays. It checks what the server's normalization puts in the copy.
- The restore tests for odd recovered shapes (`test_a_cached_draft_written_before_the_two_box_scope_still_accepts_typing`, `test_a_recovered_non_string_component_pair_is_normalized_before_save`, `test_a_recovered_non_object_scope_environment_accepts_valid_component_rows`, `test_a_recovered_non_object_test_window_accepts_valid_dates`, `test_a_recovered_non_array_account_list_does_not_break_setup`, `test_recovered_scalar_coverage_values_render_component_scope`, `test_recovered_non_array_scope_targets_fall_back_to_the_server_targets`, `test_recovered_non_array_findings_fall_back_to_the_server_findings`, `test_recovery_restore_preserves_an_empty_supporting_tile`): stay. Each checks how the page draws or saves a restored report.
- `test_an_over_length_setup_field_shows_the_server_message_and_holds_the_save` and `test_held_autosave_shows_every_refusal_on_setup`: stay. They check Setup's field messages and its check function, which are page code.
- `test_custom_location_removal_cannot_autosave_before_its_evidence_decision`: stays. It checks the Findings dialog that holds saves.
