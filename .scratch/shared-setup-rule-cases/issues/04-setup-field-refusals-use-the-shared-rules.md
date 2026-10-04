# 04: Setup field refusals are caught by the same rules before the save

Status: ready-for-agent

Blocked by: [01: Missing engagement details go through the shared rules on both sides](01-missing-engagement-details-use-the-shared-rules.md)

**What to build:** A Setup field the server would refuse is caught by the same rules in the browser before the save. That covers characters a field does not allow, a username that does not start and end with a letter or number, and test dates in the wrong order. The browser and the server agree on every one, and the tester sees the same message on the field as today.

The rules in this ticket, all refusals: invalid characters in a Setup field (field, plus the environment for a test time and the test account number for a user role or username, and the characters found); invalid username (test account number); test dates out of order (environment).

- [ ] The Python Setup function returns these refusals in `setup_input_issues`' field order. `setup_input_issues` and the save refusal return the same strings as today.
- [ ] `setupResults` returns the same refusals from the report and the vocabulary's character rules.
- [ ] The non-production label is checked only when Non-Production is a tested environment, on both sides.
- [ ] The per-field check that runs as the tester types keeps its wiring and its messages. The Next button's Setup check takes these refusals from the rules file.
- [ ] Cases cover each field, a username of `N/A`, a username with allowed characters but a bad first or last character, dates in the wrong order in each environment, and Non-Production not tested with a bad label.
- [ ] Break one rule on one side and watch a case fail, then restore it.
- [ ] `test_setup_inputs_report_character_and_date_errors_before_save` and the refusal test in `test_acceptance.py` pass without changes to what they assert.
- [ ] `docs/DATA_MAP.md` §12: the username-shape and test-window rows name the new functions as well as their current twins.

## Next steps

1. `/implement`: The fields, their order and their messages are fixed by today's `setup_input_issues`.
