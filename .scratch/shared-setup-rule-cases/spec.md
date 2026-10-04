# One set of Setup cases for the Python and JavaScript rules

Status: ready-for-agent

From: [review item 03, twin rules become one interface with two adapters](../architecture-review/issues/03-twin-rules-become-one-interface-with-two-adapters.md). Its `## Answers` section holds the decisions this spec writes down.

## Problem Statement

The Setup page checks a report in the browser, and the server checks it again in Python. The two copies are written by hand and can drift apart. When they disagree, the tester sees one of two failures:

- The browser lets the tester click Next, the save goes through, and the server sends them back to Setup when Findings opens, with no warning on the Setup page.
- The browser lets a save go out that the server refuses, for example a component typed twice in one scope box, and the tester gets a refusal they had no warning of.

No test compares the two copies. The two contract tests that exist cover finding completeness and Word report readiness, and they compare one yes-or-no answer. The browser side also reads the Setup page's text boxes instead of the report, at four places, so its checks cannot be called without a page.

## Solution

Each side gets one function that takes a report and returns the Setup issues and refusals as an ordered list of structured results. The JavaScript function lives in its own file, with no page code, and the Setup page calls it. One table of test cases runs against both functions, and each case states the results it expects. A change to one side that the other side does not copy fails a case, without starting the app.

The tester sees no change: the same checks, the same messages, the same highlighted fields.

## User Stories

1. As a tester, I want the Setup notice to list exactly what the server will hold me back for, so that clicking Next never sends me back to Setup.
2. As a tester, I want the browser to stop a save that the server would refuse, so that I fix the field before the save instead of after a refusal.
3. As a tester, I want the notice to update while I type a scope target, before any save, so that I can see what is still missing.
4. As a tester, I want a component with no description named in the notice, so that I know which row to fix among many.
5. As a tester, I want a component typed twice in one scope box caught before the save, so that its description is not lost.
6. As a tester, I want a character a field does not allow caught on the field itself, so that I see the problem where I typed it.
7. As a tester, I want Mobile and Thick Client together reported as one issue, so that I can deselect one on the page that holds both.
8. As a tester, I want test dates in the wrong order caught before the save, so that the save does not fail.
9. As a tester, I want a tested environment with no scope target reported, so that every tested environment has something to test.
10. As a tester, I want a tested environment with no test dates reported, so that the Word report never prints an empty window.
11. As a tester, I want an untested environment's scope text ignored, so that text I typed and then unticked does not block me.
12. As a tester, I want a blank or `#` component line ignored without moving the descriptions below it, so that each description stays with its component.
13. As a tester, I want the same messages I see today, so that nothing I have learned about the page changes.
14. As a developer, I want one Setup rules function per language, so that I change a Setup rule in two known places.
15. As a developer, I want a case table that fails when only one side changes, so that drift is caught before it ships.
16. As a developer, I want each case to state its expected results, so that a mistake copied to both sides also fails.
17. As a developer, I want the cases to run without the app server, so that they are fast and run in every affected-tests run.
18. As a developer, I want results compared as rule codes with context, not message text, so that wording changes do not break the cases.
19. As a developer, I want the JavaScript rules to take the vocabulary as an argument, so that the cases run with exactly the lists the server serves.
20. As a developer, I want the JavaScript rules file to read no page elements, so that I can call it from a blank page in a test.
21. As a developer, I want the existing Python callers of `setup_issues` to keep their messages, so that the page gates, the Word report readiness check, the import error and the save refusals do not change.
22. As a developer, I want the save check to refuse in the same order it does today, so that the first refusal a tester sees does not change.
23. As a developer, I want the case runner built so that the next slice of rules can add its own table, so that Findings and Word report readiness can follow the same pattern.
24. As a developer, I want `docs/DATA_MAP.md` §12 to name the new functions and the new drift guard, so that the map stays accurate.
25. As an agent reading the repo, I want the instructions that say "the only drift guard is the readiness test" corrected, so that I do not add a third copy of a Setup rule.
26. As an agent, I want each result to say whether it is an issue or a refusal, so that I know whether the save or the page gate owns it.

## Implementation Decisions

### The result shape

- A result is a plain JSON-compatible object: a `kind`, a `code`, and the context the code needs. Both sides build the same objects, so a case compares them for equality.
- `kind` is `issue` or `refusal`, as `GLOSSARY.md` defines them. An issue stops the tester going past Setup. A refusal is what a save of that report would get.
- The list is ordered: refusals first, in the order the save checks them (the scope-text refusals of `reconcile_targets`, then `setup_input_issues` in its field order), then issues, in the order `setup_issues` lists them today.
- Message text is not part of a result. Each side keeps its own formatter from result to message, and the messages stay as they are today.

### The rule codes

The first set, with the context each one carries:

| Kind | Code | Context | Today on the Python side |
|---|---|---|---|
| refusal | no app type | none | `reconcile_targets`, "select at least one app type" |
| refusal | duplicate component | environment, app type, component | `reconcile_targets`, "lists the same component twice" |
| refusal | invalid characters | field; plus the environment for a test time, the test account number for a user role or username, and environment, app type and which box for a scope box | `setup_input_issues`; `reconcile_targets` through `character_issue` |
| refusal | invalid username | test account number | `setup_input_issues`, `USERNAME_PATTERN`: a username with allowed characters that does not start and end with a letter or number |
| refusal | test dates out of order | environment | `setup_input_issues`, `TestWindow.validate_order` |
| issue | missing app name, missing segment, missing report type, missing tester | none | `setup_issues` |
| issue | no tested environment | none | `setup_issues` |
| issue | Mobile and Thick Client together | the app types | `setup_issues` |
| issue | missing test dates | environment | `setup_issues` |
| issue | missing scope target | environment | `setup_issues` |
| issue | missing component description | environment, app type, component | `setup_issues` |

The implementer picks the exact code strings, in snake case. The invalid-characters result also carries the characters found, in the order the message lists them. The non-production label is checked only when Non-Production is a tested environment, as today.

### The Python side

- One new function in the report service takes the report in the shape the browser sends it, including `scope_text`, and returns the ordered results. It needs no stored report: target IDs and stranded findings belong to the scope-survival rule, which is out of scope.
- It turns scope text into targets the way `reconcile_targets` does: pair component and description lines by raw index before cleaning, skip blank and `#` lines, and check characters on component app types only.
- The scope-text checks inside `reconcile_targets` move into a pure helper that lists every refusal. `reconcile_targets` raises the first one, with the same message, so the save is refused exactly as before.
- `setup_issues`, `setup_is_complete` and `setup_input_issues` keep their signatures and return the same strings, formatted from the new results. The page gates, `generation_issues`, the import error, and the save refusals' response bodies do not change.

### The JavaScript side

- A new static file holds the Setup rules. It is a classic script with no build step, and it defines one global object with a `setupResults(report, vocabulary)` function. It reads no page elements and no globals other than its arguments.
- The three report-page templates (Setup, Findings, Content) load it after the vocabulary and before `app.js`.
- `app.js` calls it instead of counting text boxes: in `validateSetupPage`, `updateSetupValidationNotice`, `setupSectionSummary`, the scope box `oninput` handler, and the duplicate-component row check. `missingDescriptionIssues`, `componentExclusionIssue` and the scope character check become calls to it, or go.
- `app.js` keeps the page work: which element a result highlights, focus, scrolling, and the message text. A result's context is enough to find its element.
- The per-field character check that runs as the tester types keeps its current wiring, and reads the same allowed sets from the vocabulary.

## Testing Decisions

- A good test here checks what a function returns for a report, not how it gets there. The cases do not look at the page, the DOM, or message text.
- One new Python test module holds the case table and runs it twice: once against the Python function, and once against the JavaScript function, in a blank Chromium page that loads only the rules file. The test passes the output of `client_vocabulary()` as the vocabulary. There is no app server.
- Each case is a report in the browser's shape and its expected results. Each side is compared with the expected results, not only with the other side, so a mistake copied to both sides fails. Each case runs as a `subTest`.
- The table covers every code at least once, plus the edge cases the code comments name: a blank or `#` component line in the middle of a box; a description against a blank component; an untested environment with scope text; a whitespace-only value; Mobile and Thick Client together; Non-Production not tested with a bad label; and a complete report with no results.
- Every check must be able to fail. Before calling the work done, break one rule on one side and watch a case fail.
- The module launches Chromium once, like the browser harness does, and skips when Playwright is not installed, as `test_browser.py` does.
- The existing tests stay. They are the check that the page is wired to the rules file, and that the messages did not change: the Setup tests in `test_browser.py` (including the one that checks the notice reads the same as `setup_issues`), the `setup_issues` tests in `test_app.py`, and the refusal test in `test_acceptance.py`.
- Prior art: `test_browser_readiness_verdict_matches_server_generation_issues` and `test_browser_findings_gate_matches_server_finding_completeness` for a case table run against both sides; the `setup_issues` tests in `test_app.py` for direct calls.
- `scripts/relevant_tests.py` already sends a change under `app/web/static/` to every report-page browser test, and every `--affected` run includes every Python test module. Check that the new file is not listed under "No rule for these".

## Out of Scope

- Every rule outside Setup: finding completeness, Word report readiness, affected app types, scope survival, image slots, proof-of-concept rules. Each is a later slice of review item 03.
- Rules that change the report, such as installing proof-of-concept steps, and browser-only behaviour such as list paste and the retest Limitations sentence.
- A route that checks a report without saving it. Every JavaScript copy stays (review item 03, answer 7).
- Node.js, or any JavaScript test runner other than Playwright.
- Any change to message text, to which field is highlighted, or to the order the save refuses in.
- Moving `generation_issues` out of the Word report code.
- Serving `USERNAME_PATTERN` through the vocabulary. It stays a twin, and the cases cover it.

## Further Notes

- `docs/DATA_MAP.md` §12 changes in the same work: the Setup rows name the two new functions, the intro paragraph names the case module as their drift guard, and the "the count is taken from the DOM" warning goes. Refresh its "Last verified" line.
- The web-client, data-layer and tests instructions say the readiness test is the only drift guard. Edit them in `.github/instructions/`, then run `scripts/sync_ai_rules.py`.
- The section summary's count of scope lines is a display, not a rule. It can read the rules file's view of the targets, but it is not a case.
- The case runner should not know about Setup in particular, so the next slice adds a table and a function name, not a new runner.

## Next steps

1. `/to-tickets`: The work spans the Python service, `app.js`, three templates, a new test module and the docs, which is more than one session's build.
