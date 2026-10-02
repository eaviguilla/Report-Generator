# No-findings report: generate a report that has no findings

> **Status:** in progress · 2026-10-02 · built and tested on macOS, not yet committed. The Word
> output still needs a check on Windows, where Word repaginates and numbers the TESTING RESULT
> heading.
>
> **What deviated.**
> - The confirmation is a query parameter, `?confirm_no_findings=true`, on both generate routes,
>   and a refusal carries the code `no_findings_unconfirmed`.
> - The Asia N/A row drops every colour in the row, not only the Severity token's, so nothing in
>   it can print in a rating colour.
> - The Findings-gate contract test changed shape. Its cases now take the report as well as the
>   finding, and it waits for the finding summary rather than a table row, because a report with no
>   findings has no rows.
> - DATA_MAP §12 used to call the readiness test the only contract test. It now names its
>   Findings-gate sibling too.
> - Not addressed: a missing or broken `no_finding.docx` raises `ComponentCompositionError`, which
>   `finalized_report` does not catch, so it reaches the tester as an unexpected error rather than
>   a 422. Every other component file behaves the same way.

## Request

Some applications have had every earlier finding resolved, and the next annual pentest finds nothing
new. The app could save such a report but not generate it. Generate the report anyway, and make the
tester confirm first that it really has no findings. The decisions below came from a grilling
session. No planning agents ran.

## Answers

- **Q1, what it is:** any report with zero findings of any status, whatever its report type. It is
  not a Report Type value and nothing is saved to mark it. GLOSSARY.md defines Finding and
  No-findings report.
- **Q2, the summary row:** one row, "(No vulnerability found)" with the parentheses, then five
  "N/A". Every cell prints in the table's plain 12 pt grey with no rating colour. The Asia Section
  table gets one row of five plain "N/A".
- **Q3, the testing result section:** the user supplies `resources/severity_titles/no_finding.docx`.
  It holds the TESTING RESULT heading and a `{{testing_result}}` tag, and the app fills the tag with
  this paragraph: "The penetration testing activities were completed in accordance with the agreed
  scope and methodology. During the assessment, no vulnerabilities were identified that met the
  criteria for reporting. The security controls evaluated during testing operated effectively and
  no exploitable weaknesses were discovered. While this assessment did not identify any reportable
  findings at the time of testing, this does not constitute a guarantee that the application is free
  from all vulnerabilities. Security remains an ongoing process, and regular testing and monitoring
  are recommended to maintain a strong security posture."
- **Q4:** the three template sentences that mention findings stay as they are.
- **Q5, where:** Findings lets a report with no findings continue to Content, and Generate stays on
  Content. On a report with no findings, Generate opens a dialog first.
- **Q6, import:** both import modes read a no-findings report as a draft with zero findings.
- **Q7:** the file lives in `resources/severity_titles/`, beside the severity files it replaces.
- **Q8, the server check:** the Generate request carries the confirmation and the server refuses a
  report with no findings without it. Nothing is saved. The script gets `--no-findings`, and the
  download address needs the same confirmation.
- **Q9, the dialog:** heading "This report has no findings", body "Generate a report with no
  findings?", buttons "Generate with no findings" and "Cancel". The keyboard starts on Cancel.
- **Q10, wording:** the Findings empty card gains "If testing found nothing, continue to Content to
  generate a report with no findings." Content shows "No findings" and "This report has no findings.
  The Word report will show (No vulnerability found) in the findings table and the testing result
  paragraph in place of the findings sections." Content offers no way to add a finding: findings are
  added on Findings only. The side panel shows "Ready" and "No findings to complete. The report is
  ready to generate." The bounce note becomes "Complete every finding before continuing to
  Content."
- **Q11:** Next keeps working as it does today. It is never greyed out, and with an incomplete
  finding a click keeps the tester on Findings and marks what is missing.
- **Q12:** recorded as `docs/adr/0002-no-findings-report-is-derived-and-confirmed-per-request.md`.

Also agreed: the testing result section starts on a new page like a severity section, the paragraph
takes the formatting of the tag's paragraph in the file, Setup must still be complete, a report
whose findings are all Resolved or Closed stays a normal report, and import summaries stay as they
are.

## Agreed plan

- [x] 1. Word output: `generation_issues` stops requiring a finding. The summary table prints the
  placeholder row, the Asia Section table prints its N/A row, and `no_finding.docx` replaces the
  severity sections with `{{testing_result}}` filled.
- [x] 2. Import: both modes read the placeholder row, and the N/A Section row beside it, as no
  findings.
- [x] 3. Server: `/edit` admits a report with no findings. Both generate routes take
  `confirm_no_findings` and refuse a report with no findings without it.
- [x] 4. Script: `scripts/generate_report.py --no-findings`.
- [x] 5. Browser: the Findings gate, the empty card line, the Content notice and side panel, the
  Generate dialog, and the bounce note.
- [x] 6. Tests: Word output, import, routes, a case in each of the two gate contract tests, and the
  dialog.
- [x] 7. Docs: ADR-0002, GLOSSARY.md, DOCX_TEMPLATE.md, ROUTES.md, DATA_MAP.md.
