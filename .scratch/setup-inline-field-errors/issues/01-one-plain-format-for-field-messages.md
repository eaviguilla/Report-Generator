# 01: One plain format for every field message

Status: ready-for-agent

**What to build:** Every message for a Setup refusal or issue, and for a character the Content page's Additional Information fields refuse, follows one format in Python and in JavaScript. A message names its field the way the tester sees it, says what is wrong, then says what to do. A missing value is one instruction. No message holds a code, an escape such as `"\u0007"`, a Unicode number, a spelled-out character name such as "digit zero", or `--`. The wording was agreed on 2026-10-05 against the prototype; see the [spec](../spec.md).

| Result | Message |
|---|---|
| a character the field does not allow | `Application owner cannot have "0". Remove or replace it.` With several: `cannot have "#", "&" or "0". Remove or replace them.` A space where spaces are not allowed: `CI number cannot have spaces. Remove the space.` (`the spaces` when there are several) |
| a hidden character: one Word cannot store, or any character in Unicode categories C or Z other than the plain space | `Line 4 has a hidden character after "api.bank.". Delete it.` The quote holds up to 12 characters before it, led by `...` when cut short. At the very start it reads `at the start`. A tab, a line break and a non-breaking space are named instead: `has a tab after "Bank"`. |
| too long, for a stored value or a scope target (ticket 03 stops the other fields at their limit) | `Line 2 has 537 characters. Shorten it to 500 or fewer.` |
| a username with a space at an end | `Username 2 starts with a space. Delete it.` Also `ends with a space`, and `starts and ends with a space. Delete them.` |
| test dates in the wrong order | `Production start date is after its end date. Change one of them.` |
| a repeated test account | `Test account 4 is the same as test account 1. Remove one of them.` |
| a repeated component | `Component 3 is the same as component 1. Remove one of them.` |
| a missing detail | `Choose a segment.` `Enter the application name.` `Choose a report type.` `Choose the network access.` `Enter the tester's name.` `Enter the report date.` `Enter the Production end date.` (or `start date`, or `start and end dates`) |
| a half-filled test account | `Enter a username for test account 3, or clear its user role.` `Enter a user role for test account 3, or clear its username.` |
| a component with no description | `Enter a description for component 2.` |
| no scope target in a tested environment | `Add a scope target for Production.` |
| Mobile and Thick Client both chosen | `Choose Mobile or Thick Client, not both.` |
| no app type | `Choose at least one app type.` |
| no tested environment | `Choose at least one environment to test.` |
| more than 50 test accounts | `A report can list at most 50 test accounts. Remove some.` |

The last five rows were not in the prototype. They follow the same format.

The field's name is the one beside it on the page: `Application name`, `CI number`, `Production time`, `User role 2`, `Username 2`, `Non-Production name`, `Limitations`, `Line 4` in a Web/API box, `Component 3` and `Description 3` in a component table, `CVSS Score` on the Content page. A scope message shown away from its box, as in a server refusal, the Generate refusal or the import refusal, names the box first: `In the Production Web scope, line 4 has a hidden character after "api.bank.". Delete it.`

- [x] One wording function per language turns a coded result into its message, and every place that words a rule calls it. Python uses `format_rule_message`; `setup_refusal_message`, `setup_issues`, `invalid_character_issue` and `character_issue` route messages through it. JavaScript uses the page-free `vrRules.formatRuleMessage` in `rules.js`; `app.js` keeps no rule wording of its own.
- [x] Some messages need facts the coded results do not carry today: a too-long value's length, which end of a username has the space, the text before a hidden character, which test date is missing, a component's row, and the row a repeated component repeats. Both formatters read those facts from the report. The paired cases cover them, and the existing changed-target and stored-refusal tests cover unchanged saved values.
- [x] A shared case table in `tests/test_rule_cases.py` pairs each result with its message and runs against both wording functions. The regression case failed in both implementations before the fix and passes now.
- [x] Both sides decide what is hidden the same way: Unicode categories C and Z except the plain space, plus the set Word cannot store. Both count the 12 characters before it by code point (`[...value]` in JavaScript), so an emoji is never cut in half.
- [x] Until ticket 02 turns it into a count, the Setup notice shows the new messages one after another.
- [x] The character-name tables (`CHARACTER_NAMES`, `DIGIT_NAMES`, `_character_name`, `characterNames`, `digitNames`, `characterName`) and `portable_names` go if nothing else uses them. Grep `app/`, `tests/` and `scripts/` first; no maintained source, test or script uses them.
- [x] Tests that pin the old words change with them: the `test_app.py` test that pins every `setup_refusal_message` string, and the browser and acceptance tests that assert "contains invalid character", "must be at most", "cannot start or end with a space", "-- remove one" or "Missing:".
- [x] `docs/DATA_MAP.md` §12: the "character-rule message wording" and "setup completeness" rows name the new functions.

## Next steps

1. `/implement`: The wording is agreed, and nothing waits on another ticket.

## Comments

2026-10-05: The browser and Python runtimes disagreed on Unicode categories for some code points, so the page now uses Python-generated C/Z ranges for hidden-character wording. Calling the shared formatter also exposed a date-pair local named `window` that shadowed the browser global; it is now `testWindow`.
