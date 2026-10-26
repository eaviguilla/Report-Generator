# Import takes a finding's identity from its finding row

> **Status:** done · 2026-10-14 · `2770369`
>
> **From:** [Import refusals name the cause](import-refusals-name-the-cause.md)

> **Stress-test follow-up, 2026-10-14:** Finding-row status recognition now ignores capitals and extra whitespace, matching the finding table, because an edited `CLOSED` row previously reopened the finding.

## Request

> for this part of refusal of import, I want to accept them. make it so that the imported findings will base on the title of the summary table. also am thinking that maybe it refused because the finding's heading still matches the finding summary row title but it does not match exactly when case sensitive. thinking of capital letter differentiations. also for the severity, id, or status differentiation, just make the summary table values be main reference and no need to check the values under the finding header.

Read as: two refusals go away, in retest and editable mode. One is a finding row whose title differs from its finding heading. The other is a Severity, ID or Status in the finding table that differs from the finding row. The importer reads the finding's title, severity, ID and status from the finding row and stops comparing them with the heading and the finding table. The user's "summary table", "finding summary row", "detail table" and "finding header" are the glossary's Findings Summary table, finding row, finding table and finding heading.

## Answers

From a grilling session on 2026-10-14.

- **Q1, pairing a heading with its finding row:** compare titles ignoring capitals and extra spaces, non-breaking spaces included. Pair what is left over by position, the first leftover heading with the first leftover finding row, and so on. Each position pair gets a warning. A pair that differs only in capitals or spaces gets none. Considered and not chosen: refuse anything that does not match by title, and pair by position only.
- **Q2, a leftover:** a finding row with no heading left, or a heading with no finding row left, still refuses, and the message names every leftover. Position pairing happens only when the same number of headings and finding rows are left over. Otherwise nothing pairs by position. Considered and not chosen: import what pairs and drop the rest with a warning, because a heading with no finding row would lose its whole body.
- **Q3, the finding table's values:** the importer stops checking Severity, ID and Status in the finding table. When one differs from the finding row, the import adds one warning per finding that names the values. It never refuses. The comparison ignores capitals and spaces, and covers a Status only when both sides are known statuses, as before.
- **Q4, the app's conclusion sentence:** unchanged. The editable import still refuses a title or status word in that sentence that disagrees with the finding row. The retest import drops the section and is not affected. The Conclusion part of the refusal list may change this later. The refusal's hint is corrected to say "title and status".
- **Q5, sections that do not fit the finding row's status:** unchanged. The import still refuses and lists the sections it expected and found. Accepting would drop the tester's text or guess a status.
- **Q6, term:** finding row, in GLOSSARY.md, added on 2026-10-14. "Summary row" and "finding summary row" are Avoid.
- **Q7, the CVSS table (Asia template only):** the same rule. Its rows pair with finding rows by title ignoring capitals and spaces, then by position with a warning, but only when the same number of CVSS rows and finding rows are left over. Otherwise a leftover CVSS row refuses and a finding row with no CVSS row imports without scores, as today.
- **Other agreed points:** retest and editable behave the same, except for the Q4 check. A finding keeps its finding row's title as printed there, spaces included. A finding table is still recognised by the labels Severity, ID, Status and Location, and its Location row still gives the locations. A finding row with no title or fewer than six cells still does not count, and the leftover refusal says how many such rows it skipped.
- **Facts found:** the app prints a title as typed in the finding row, the heading and the CVSS row, and never changes its capitals, so a difference comes from an edit in Word or from another tool. The app writes the finding rows, the headings and the CVSS rows in one order, by severity and then by title ignoring capitals. The manager shows `summary.warnings` for both modes.
- **Earlier decision reversed:** `docs/plans/status-username-and-na-locations.md` kept the Status check and named this change, making the summary cell authoritative, as the alternative for the user to overrule. This plan takes the alternative.
- **ADR:** none. The change is easy to reverse.
- **Open risk:** position pairing can join a heading to the wrong finding row when a tester both reordered and retitled findings. The warning names every position pair so the tester can check. A finding row whose title was edited also still stops the editable import at the conclusion sentence (Q4).

## Messages

These are the test contract. Keep the meaning if a phrase needs to change, and change its test with it.

- **Position pair:** `The finding heading "X" was paired with the finding row "Y" by position. The finding uses the row's title.`
- **Finding table disagrees:** `"Y": Severity is "Low" in the finding table and "High" in the Findings Summary table. The import uses the Findings Summary table.` It holds one sentence per differing value, and an empty value reads `empty`.
- **Leftovers:** `The finding row "X" has no finding heading left to pair with.` and `The finding heading "Y" has no finding row left to pair with.`, each with a plural form. Then `The importer pairs a finding heading with a finding row by title, ignoring capitals and extra spaces, and then by position, but only when the same number of each is left over.` Then the headings found, the rule that a finding heading is a Report Heading 2 paragraph after the table and before the Appendix, the skipped-rows sentence when it applies, and the other-styles hint.
- **CVSS position pair:** `The CVSS row "X" was paired with the finding row "Y" by position.`
- **CVSS leftover:** `The CVSS table has a row for "X" that no finding row matches.` (several: `rows for "X", "Y"`) followed by the method sentence with "CVSS row" where the one above says "finding heading".
- **Conclusion hint:** `The app writes the first sentence from the finding's title and status. The title is "T", from the finding row, and the status is S.`

## Agreed plan

- [x] 1. Tests first, one slice at a time, each seen failing on the current code: a heading that differs from its finding row only in capitals pairs without a warning in both modes and the finding takes the row's title; a heading in other words pairs by position with the warning; leftovers that differ in number refuse and name every leftover; a finding table that disagrees on Severity, ID or Status imports with the row's values and one warning; CVSS rows pair by capitals, by position with a warning, and refuse when the leftovers are unequal; the leftover refusal names skipped rows; the conclusion refusal names title and status, with a test where only a finding row's capitals changed.
- [x] 2. `app/docx_import.py`: one function pairs a list of titles with the finding rows, by title and then by position, and serves both the headings and the CVSS rows. `_summary_rows` returns the printed title and a comparison key. `_findings` takes the title, severity, ID and status from the finding row, the `differences` refusal becomes a warning, and `typed_titles` goes. The unpaired and CVSS leftover refusals use the wording above.
- [x] 3. `_fragment_change` in `app/docx_import.py`: the conclusion hint.
- [x] 4. Existing tests that pinned the old refusals now pin the new behavior: `test_a_row_and_a_heading_with_different_titles_are_both_named`, `test_a_value_that_differs_between_the_findings_summary_table_and_the_finding_table_names_both`, `test_a_title_listed_more_often_than_it_has_headings_is_counted`, `test_a_title_with_more_headings_than_rows_is_counted`, `test_a_cvss_row_for_another_title_is_named`, `test_a_refusal_through_the_route_names_what_did_not_pair_up`, `test_a_finding_heading_in_another_style_is_named_with_the_style_it_has`, `test_a_long_list_of_titles_with_no_heading_is_cut_after_eight`, and the two conclusion tests that pin the hint.
- [x] 5. Docs: `docs/DATA_MAP.md` (the Status-cells sentence and the Last verified line), `docs/DOCX_TEMPLATE.md` (the CVSS pairing sentence and the paragraph that begins "A refused document says why"), the Word pipeline instruction (add "finding row"), regenerated into `.claude/rules/` with `scripts/sync_ai_rules.py`, and a note in `docs/plans/import-refusals-name-the-cause.md` and one in `docs/plans/status-username-and-na-locations.md`.
- [x] 6. Lint, `graphify update app --force`, `scripts/relevant_tests.py --affected --run`, `/code-review`, then commit. Set this plan to `done` with the commit.

Out of scope: the Description, Recommended Remediation and Conclusion parts of the refusal list, what the importer drops without saying, and ZIP and JSON messages.

## What deviated

The plan held up. These things changed while building and in review.

- **An exact-title pass runs first.** A heading takes the finding row with exactly its title before it considers a row that differs in capitals. Without it, two findings whose titles differ only in capitals could swap identities.
- **`_summary_rows` returns `(rows, skipped)`.** Step 2 said it would return a comparison key. `_pair_with_finding_rows` builds both keys itself, so a row carries only what the report printed.
- **A list of leftovers shows at most eight titles, then a count,** as the earlier refusals do. Q2 said every leftover.
- **The finding table's Status is compared in any capitals,** so `CLOSED` still counts as a known status. A status the app does not know, on either side, adds no finding table warning.
- **A CVSS row with no title is named "(no title)"** in the warning and in the refusal.
- **The CVSS method sentence says "CVSS row"** where the plan said it was the same sentence.
