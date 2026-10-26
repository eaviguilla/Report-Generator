# Import refusals name the cause

> **Status:** done · 2026-10-14 · `65ac9a9`
>
> **Superseded in part, 2026-10-14.** The refusals for a heading and a finding row with different titles, for a title listed more often than it has headings, and for a finding table that disagrees with the finding row no longer hold, and neither does the answer that titles pair by a collapsed copy. A finding now takes its title, severity, ID and status from its finding row. A heading pairs with a row by equal title, then by title ignoring capitals and spaces, then by position ([Import takes a finding's identity from its finding row](import-uses-the-finding-row-as-the-reference.md)). Still true: a leftover refuses and is named, a list shows at most eight titles, and a finding keeps its title as printed, now the row's.

> **Stress-test follow-up, 2026-10-14:** Unsupported tables before Description, caption arrangements, mixed picture/text content, merged cells, body-level content controls and unexpected final group headings now refuse instead of silently losing or changing authored work; supported text, cell line breaks and formatting-off values are preserved.

## Request

> When refusing an import, can we know the exact reason and why the import was rejected? For example, summary and detail sections do not match, but we do not have detail sections. We have description and recommended remediation, and we have no summary section. Can we correct the terms that we are using in the output of import errors? I am having errors when I am trying to input a valid report, and I would like to debug that by knowing exactly what the error of the import is.

Read as: the old refusals said which rule failed but not which finding, row or heading, and they used "summary" and "detail" for things the report calls the Findings Summary table, a finding heading, a finding table and a section. "The findings summary and detail sections do not match." meant that a row of the Findings Summary table had no finding heading with the same title. Nothing in the message said which row.

## Answers

From a grilling session.

- **Q1, terms:** Findings Summary table (and its rows), finding heading, finding table, and section, for Description, Recommended Remediation, Previous Proof of Concept, Proof of Concept and In Conclusion. Messages and docs say "refused". The prefix "This Word report can't be imported:" stays, and function names stay. The terms are in GLOSSARY.md.
- **Q2, message shape:** one paragraph that names the finding, the part, what the importer expected and what it found. The rule for a finding heading (a Report Heading 2 paragraph) appears only in heading and section refusals.
- **Q3, how many problems:** the importer still stops at the first check that fails, and that check lists everything it found. A list shows at most 8 titles, then "and N more".
- **Q4, scope:** the messages in `app/docx_import.py` and the editable import's checks in `app/main.py`. Not included: ZIP and JSON messages, and what the importer drops without saying (text above the first section heading, formatting other than bold, italic and underline).
- **Q5, two valid reports were refused:** a title with a double or non-breaking space (the heading was read with its spaces collapsed and the Findings Summary row was not), and an In Conclusion section that holds the app's sentence and more text in one run (provisioning splits the run and the guard took the split for an edit). Both are fixed test first, in commits of their own, before the wording.
- **The conclusion fix:** the guard in `app/main.py` joins neighbouring runs that differ only in text, so `provision` and its JavaScript twin do not change.
- **Titles:** paired by a copy with their spaces collapsed, and stored as printed. The first plan stored the collapsed copy. Review showed that the default In Conclusion sentence carries the title as typed, so a finding with a double, non-breaking or trailing space in its title was still refused by the editable import's guard.
- **ADR:** none. The wording is easy to change.

## Agreed plan

- [x] 1. A title with extra spaces: test seen failing, then `_summary_rows` collapses the row title (59c58dd).
- [x] 2. A conclusion that continues after the app's sentence: test seen failing, then `_with_merged_runs` in the guard, with a companion test that a real disagreement is still refused (484fe2d).
- [x] 3. The Findings Summary rows and the finding headings are paired before any finding is read. Every title with no partner is named, with the headings found and the style a restyled heading has.
- [x] 4. A missing Findings Summary table, a missing or repeated section (expected and found lists), a value that differs between the row and the finding table, a missing or repeated finding table, and CVSS rows that no heading claims.
- [x] 5. The invalid ID, CVSS score and vector, ticket, location heading, Location row, Section row, Resolved remediation, cover value and report type refusals carry the finding and the value found. A fragment that cannot be read names its section.
- [x] 6. The editable import's checks name the finding, the section and what would change (`first_change`), and the stranded scope check names the findings.
- [x] 7. Code review, then fixes with their tests: the finding keeps its title as printed; a title listed more often than it has headings is counted; a lost bold or italic names the words; the component refusal counts the markers it found; the CVSS Section row names its finding; the Location row check runs inside the finding's own check; every branch of `first_change` and the cap of eight titles have a test.
- [x] 8. Docs: GLOSSARY.md (Refusal, Findings Summary table, Finding heading, Finding table, Section), `docs/DOCX_TEMPLATE.md`, `docs/ROUTES.md`, `docs/DATA_MAP.md`, and the Word pipeline instruction regenerated into `.claude/rules/`.
- [x] 9. Commits: `59c58dd` (title spacing), `484fe2d` (conclusion guard) and `65ac9a9` (the wording, the title kept as printed, docs).

Tests: `RefusalMessageTests` and a route test in `tests/test_docx_import.py`, plus the existing tests that pinned the old phrases, now pinning the new ones.

## What deviated

`first_change` lives in `app/docx_import.py`, not `app/main.py`, so `main.py` calls two public functions and imports nothing private. A finding keeps its title as printed, where the plan said collapsed (see Answers). The Location row check moved from the document-level scan into the finding's own check, so it always names the finding, and a short Location row in a table that is not a finding table is no longer refused. Left as they were: the Limitations, Component row and scope-row refusals and "a table in this report has no rows" (each fires on a table row that lost its cells, and tests pin their phrases), the other evidence-image refusals (they only gained the section prefix), and the check that provisioning reaches a stable state, which only fails when provisioning itself is wrong and could be reached in a test only by patching it. A Findings Summary row with fewer than six cells is still skipped without a word, as before, so a refusal about its heading does not say the row is damaged. The hint about other styles lists headings whose style id starts with "Heading", Word's built-in heading styles, rather than every paragraph that has a row's title.
