# 01: Missing engagement details go through the shared rules on both sides

Status: done (2026-10-04)

**What to build:** The first rules end to end. When the tester leaves out an engagement detail, the Setup notice and the Next button get the issue from the new JavaScript rules file, and the server gets the same issue from the new Python function. One case table checks both against the same expected results, without the app server. The tester sees the same messages and highlights as today.

The rules in this ticket, all issues: missing app name, missing segment, missing report type, missing tester, no tested environment, missing test dates for a tested environment, and Mobile and Thick Client together. The spec has the result shape and the order.

- [x] A Python function takes the report in the shape the browser sends, including `scope_text`, and returns these issues as ordered structured results (`kind`, `code`, context).
- [x] `setup_issues` and `setup_is_complete` return the same strings as before, built from those results. The page gates, `generation_issues` and the import error do not change.
- [x] A new JavaScript rules file, a classic script with no build step, defines one global with `setupResults(report, vocabulary)`. It reads no page elements and no globals other than its arguments.
- [x] The Setup, Findings and Content templates load it after the vocabulary and before `app.js`.
- [x] `validateSetupPage` and `updateSetupValidationNotice` take these checks from the rules file. `componentExclusionIssue` is a call to it or is removed. The messages and the highlighted fields do not change.
- [x] A new Python test module launches Chromium once, opens a blank page, loads only the rules file, and passes it the output of `client_vocabulary()`. It skips when Playwright is not installed. The case runner takes a table and a function name, so later tickets add cases, not runners.
- [x] Each case is a report and its expected results, and runs as a `subTest` against both sides. The table covers every code in this ticket, plus a complete report with no results.
- [x] Break one rule on one side and watch a case fail, then restore it.
- [x] The existing Setup browser tests, the `setup_issues` tests in `test_app.py`, and the refusal test in `test_acceptance.py` pass without changes to what they assert.
- [x] `docs/DATA_MAP.md` §12: the setup-completeness and Mobile-and-Thick-Client rows name the two new functions, the intro names the case module as their drift guard, and "Last verified" is refreshed.
- [x] The web-client, data-layer and tests instructions no longer say the readiness test is the only drift guard. They are edited in `.github/instructions/`, and `scripts/sync_ai_rules.py` has been run.
- [x] `scripts/relevant_tests.py` does not list the new file under "No rule for these".

## What deviated

- The codes are `missing_app_name`, `missing_segment`, `missing_report_type`, `missing_tester`, `no_tested_environment`, `mobile_and_thick_client` (context `app_types`) and `missing_test_dates` (context `environment`). The rules file is `app/web/static/rules.js`, its global is `vrRules`, the Python function is `report_service.setup_results`, and the case module is `tests/test_rule_cases.py`.
- The case runner takes the table, the Python function and the JavaScript name, because the two sides name the function in their own style.
- `componentExclusionIssue` stays as the JavaScript formatter: it now takes the result and returns the message.
- `setup_issues` still checks scope targets and component descriptions itself, and places them after each environment's test-dates line so the order of its strings does not change. Ticket 02 moves them into the results.
- `test_browser.py` does not skip without Playwright; it imports it. The new module skips on the `ImportError`.
