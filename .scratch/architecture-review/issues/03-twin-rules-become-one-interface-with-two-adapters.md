# Twin rules become one interface with two adapters

Status: ready-for-agent

Blocked by: [One set of Setup cases for the Python and JavaScript rules](../../shared-setup-rule-cases/spec.md)

Found by the [2 October 2026 review](../report.html#review-2026-10-02-c3), recommendation 3, rated Worth exploring, in-process.

Found again: the [3 October 2026 review](../report.html#review-2026-10-03-c1), recommendation 1 and its top recommendation, rated Strong.

## Problem

`app.js` returns on its third line unless a report page is loaded, so two page-load tests that compare one yes-or-no answer are the only check that its 38 twin rules agree with Python, and no test compares the app-type, scope-survival and proof-of-concept rows.

## Solution

Move the browser's rules into one file with no DOM that takes the report as an argument, and run it and the Python rules against one shared table of cases that compares the full issue lists.

## Benefits

- Drift fails a shared case.
- Rule cases run without starting the app.
- Locality: one rules module per language.
- Readiness leaves the Word renderer: `generation_issues` moves out of `docx_report.py`.
- Leverage: four pages and the save path call one interface.

## Files

- `app/web/static/app.js` · module-scope rules, lines 1066 to 1486
- `app/web/static/app.js` · `setup()`: `validateSetupPage`, `validateFindingsPage`
- `app/web/static/app.js` · `continuousEditor()`: `updateReadinessPanel`, `fragmentIssues`, `additionalInformationFields`
- `app/report_service.py` · `setup_issues`, `finding_is_complete`, `affected_channels`, `reconcile_targets`, `apply_poc_variant`
- `app/docx_report.py` · `generation_issues`
- `tests/test_browser.py` · `test_browser_readiness_verdict_matches_server_generation_issues`, `test_browser_findings_gate_matches_server_finding_completeness`
- `docs/DATA_MAP.md` · §12

## Notes

- It rose from Worth exploring to Strong because the vocabulary it waited for shipped as review item 01, and 23 of the 34 commits that ever changed `app.js` also changed `report_service.py`, `docx_report.py`, `acceptance.py` or `models.py`. Both report features shipped since 2 October are among them.
- The browser's setup-completeness rule counts scope fields on the page rather than reading the report, at four sites.
- The first shared cases can be the 17 that the readiness contract test already builds.
- DATA_MAP §12 keeps list paste and the retest Limitations sentence client-only by decision. They stay out of this module.
- Open since the first review: keep the JavaScript adapter for every rule, or delete it for some rules and let the page ask the server. Settled by Q7 below.
- Review item 07 covers two rows of the twin table and could be the first slice. Q5 below picks Setup instead.

## Answers

Settled with the user on 4 October 2026. "Issue" is defined in `GLOSSARY.md`.

1. **Which rules the shared cases cover.** Only rules that find issues or refusals. Rules that change the report, such as installing proof-of-concept steps, and browser-only interactions stay out.
2. **What the browser rules file takes.** The browser's copy of the report, including `scope_text`, which holds the scope the tester typed and has not saved. The Next button checks Setup before it saves (`app.js`, the `#next` handler), so a check that reads only the saved report would judge old values. The file reads no page elements; the four Setup sites that count scope text boxes read `scope_text` instead.
3. **What the two sides must agree on.** An ordered list of structured results: a rule code and its context, such as the environment, the app type or the component. Message text is not compared.
4. **How the JavaScript side runs.** Through the Playwright already in `requirements-dev.txt`, loading the rules file in a blank page with no app server. No Node.js.
5. **First slice.** The Setup checks: `setup_issues` and its JavaScript copies `validateSetupPage`, `updateSetupValidationNotice`, `missingDescriptionIssues` and `componentExclusionIssue`.
6. **Setup cases include refusals.** A save does not run `setup_issues`; the server runs it when Findings or Content opens and inside `generation_issues`. A save refuses a component typed twice and characters a field does not allow (`reconcile_targets`, `setup_input_issues`), and the browser blocks those before saving. Both kinds go in the Setup cases, and each result says whether it is an issue or a refusal. The Python side runs `reconcile_targets` and then `setup_issues` on every case.
7. **Every JavaScript copy stays.** Each rule in the shared cases runs while the tester types, so asking the server would need a check-only route and a round trip per change. Moving a rule to the server stays possible later, one rule at a time.
8. **Issue, defined.** Something the tester must fix before going past Setup or Findings, or before building the Word report. Placeholder text is an issue, though the browser marks it `"warning"`, because it turns off Generate on both sides. A library offer is not an issue.

## Next steps

1. `/grill-with-docs`: Once the Setup slice ships, choose the next rules to move and check that its case runner fits them.
