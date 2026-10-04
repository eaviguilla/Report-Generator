# 04: Setup field refusals are caught by the same rules before the save

Status: done (2026-10-04)

Blocked by: [01: Missing engagement details go through the shared rules on both sides](01-missing-engagement-details-use-the-shared-rules.md)

**What to build:** A Setup field the server would refuse is caught by the same rules in the browser before the save. That covers characters a field does not allow, a username that does not start and end with a letter or number, and test dates in the wrong order. The browser and the server agree on every one, and the tester sees the same message on the field as today.

The rules in this ticket, all refusals: invalid characters in a Setup field (field, plus the environment for a test time and the test account number for a user role or username, and the characters found); invalid username (test account number); test dates out of order (environment).

- [x] The Python Setup function returns these refusals in `setup_input_issues`' field order. `setup_input_issues` and the save refusal return the same strings as today.
- [x] `setupResults` returns the same refusals from the report and the vocabulary's character rules.
- [x] The non-production label is checked only when Non-Production is a tested environment, on both sides.
- [x] The per-field check that runs as the tester types keeps its wiring and its messages. The Next button's Setup check takes these refusals from the rules file.
- [x] Cases cover each field, a username of `N/A`, a username with allowed characters but a bad first or last character, dates in the wrong order in each environment, and Non-Production not tested with a bad label.
- [x] Break one rule on one side and watch a case fail, then restore it.
- [x] `test_setup_inputs_report_character_and_date_errors_before_save` and the refusal test in `test_acceptance.py` pass without changes to what they assert.
- [x] `docs/DATA_MAP.md` §12: the username-shape and test-window rows name the new functions as well as their current twins.

## What deviated

- The codes are `invalid_characters` (context `field`, plus `environment` for `test_time` and `account`, the 1-based test account number, for `user_role` and `username`, then `characters`), `invalid_username` (context `account`) and `test_dates_out_of_order` (context `environment`). The Python function is `report_service.setup_field_refusals`, its JavaScript twin is an internal `fieldRefusals` in `rules.js`, and both feed `setup_results` / `vrRules.setupResults` after the scope refusals.
- One wording function, `setup_refusal_message`, now words every Setup refusal. It replaces ticket 03's `scope_refusal_message`. `setup_input_issues` keeps its signature and words `setup_field_refusals` through it. A new test in `test_app.py` pins all thirteen of its strings, in order, against the code before the change.
- The username's allowed characters moved into `CHARACTER_RULES` as a `username` entry, so the browser reads them from the vocabulary. `USERNAME_PATTERN` stays a twin, in `rules.js` only: the Setup username field now calls `vrRules.usernameRefusal` instead of keeping a third copy of the pattern and an ASCII-only character list.
- That changes one field message. A username with a letter outside ASCII, such as `José`, used to show "contains invalid character é" on the field, while the save said "must start and end with a letter or number". The field now shows the save's message. ASCII usernames show the same message as before.
- `validateSetupPage` refuses Next when `setupResults` returns any refusal. Each field's own wiring still sets the message and the highlight, so `validateSetupInputs` still reveals them. `save()` and the Save button still check the inputs only.
- The ticket-01 case "whitespace-only app name" (`" \t "`) now also expects an invalid-characters refusal for the tab, which the save has always refused.
- `setupResults` checks the missing app name and tester with `vrRules.strip`, the twin of Python's `str.strip` that ticket 03 added, instead of `trim`.
- Not fixed: the browser judges letters and digits by its own Unicode tables and Python by its own. They differ on characters one version has assigned and the other has not (U+088F, for example). Setup has always worked this way.
- The breaking check: dropping the strip of the Non-Production name in `setup_field_refusals` failed "a Non-Production name is checked trimmed" on the Python side only.
