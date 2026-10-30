# DOCX Template Contract

`app/docx_report.py` renders into one of four canonical Word templates under
`resources/`. The renderer preserves their styles, sections, headers, footers,
numbering, and static content while replacing the fields below.

## Template selection

`main_template_path(report, resources)` is the sole owner of the choice, and it
switches on two independent axes. Its `.parent` is also the component fragment
root, so every branch must stay inside `resources/`.

| | not Asia | `segment == "Asia"` |
|---|---|---|
| no component app type | `MAIN.docx` | `MAIN_ASIA.docx` |
| Mobile or Thick Client covered | `MAIN_THICK_MOBILE.docx` | `MAIN_THICK_MOBILE_ASIA.docx` |

**Asia is a boolean, not one value among several**, so `JH`, `GWAM`, `GDT` and
`GFT` all land in the *not Asia* column — the last two by decision rather than by
omission. No `MAIN_GDT.docx` or `MAIN_GFT.docx` was authored and none is wanted:
the whole document cost of either segment is one printed string, the segment at
the start of the report name that `report_name_for` builds, so such
a report carries no Section table and demands no CVSS pair. The decision lives in
the tests rather than in a branch — `test_main_template_path_selects_on_both_axes`
covers ten rows, and
`test_every_shipped_template_renders_without_unresolved_placeholders` renders the
same ten, so both are proved to render with nothing unresolved. Giving either
its own masters later means two Word-authored files and a per-segment suffix
lookup in place of the boolean.

Each template is a superset of the one above and left of it. The component pair
adds a Component/Description table; the Asia pair adds a Section table. Tables
are resolved by their first header cell, never by index, so a template may carry
a table the others do not without disturbing anything.

The scripts under `scripts/` hard-code `MAIN.docx` and bypass this function, so a
fixture rendered through them never has the extra tables. That is deliberate. It
also means a scripted fixture never prints a collected CVSS value, because the
Section table is the only place either one is printed.

## Render path

`render_report_docx` has one implementation of the findings body. The template
must contain an exact `{{findings}}` body token; without it the render is
rejected rather than falling back to a second renderer:

```python
if not _has_exact_body_token(document, "findings"):
    raise ReportGenerationError(f"Template has no {{findings}} anchor paragraph: {template_path}")
_populate_component_findings(...)
```

A legacy inline renderer used to handle templates with no `{{findings}}` token.
It was removed: `resources/MAIN.docx` carries the token, so the fallback
could not run in production, yet every fragment rule had to be written twice and
had already drifted. `resources/fixtures/report-name.docx` is retained only as
the rejection test's fixture.

The findings body is composed from `resources/severity_titles/`,
`resources/finding_types/` and `resources/fragments/`. A severity section is
inserted for each severity that has findings, severity is rendered as a font
colour on the rating text (see [Tag formatting](#tag-formatting)), and fragments
are rendered by `_render_component_fragment`.

### Text a tester types

Text from the report reaches the document through `replace_pattern_across_text_nodes`,
`_replace_pattern_with_runs` and `_add_wrapped_run`, and each passes it through `user_text` in
`app/docx_components.py`. `user_text` drops the characters XML 1.0 cannot hold, because lxml
refuses them and a pasted escape character used to fail Generate with an error that named
nothing. It also slips a private mark, U+E000 followed by `m`, inside each pair of braces and
each entry of `UNRESOLVED_MARKERS`.

`_unresolved_placeholders` looks for template text that was never replaced once the findings
are in. The marks keep a typed `{{7*7}}`, a typed component token such as `{{table-body-cell}}`
and a word such as `non-vulnerable` from counting. It reads one paragraph at a time and counts a
line break as a space, so text that sits side by side only because of how the document is built
never joins into one string. `_restore_user_text` takes every mark out after the check. A U+E000
the tester typed is written as U+E000 followed by `s`, so the text prints exactly as typed. Text
from a template that nothing replaced still stops generation with `Unresolved template
placeholders`. Any new code that writes report text into the document has to go through
`user_text`, or the check reads that text as the template's own.

A replacement carries on searching after the text it has just written. A value that spells its
own token, such as a table cell reading `{{table-body-cell}}`, is therefore written once. It used
to match again for ever.

## Engagement fields

| Template token | Report value |
|---|---|
| `segment` | Selected segment |
| `app-name` | Application name |
| `report-name` | The report name: the tester's own for a segment in `REPORT_NAME_SEGMENTS`, otherwise built by `report_name_for` |
| `test-type` | Annual Pentest, Retest, Deployment Pentest, or New Test |
| `app-owner` | Application owner |
| `report-date` | Report date, printed `Month D, YYYY` with a year padded to four digits, which the importer's `%Y` needs for years below 1000 |
| `tester-name` | Tester |
| `prod-start`, `prod-end`, `prod-time` | Production test window |
| `non-prod-start`, `non-prod-end`, `non-prod-time` | Non-Production test window |
| `network` | `Internal` or `External`, from `Engagement.network`; `N/A` while the tester has not chosen |

**`{{report-name}}` is the whole report name, and each master holds it in three paragraphs.** The cover
title in `word/document.xml` and the lines in `word/footer5.xml` and `word/footer8.xml` hold only that
token. For a segment in `REPORT_NAME_SEGMENTS` (`GWAM`) it is the name the tester typed on Setup, as typed.
For every other segment `report_name_for` builds `segment - application name - report type year`, joined
with en dashes, the year being the Report Date's, always four digits (`0099`), because the importer strips exactly four. `{{app-name}}` is the application name alone: the cover
table's Application cell, and the sentences, headings, captions and scope text around it.

Before 2026-10-22 the cover read `{{segment}} - {{app-name}} - {{test-type}} 2026`, with a plain `2026`,
and the footers `{{segment}} - {{report-name}} - {{test-type}}` with no year, and `report-name` then held the
application name. Every segment's cover now prints the Report Date's year, and its footers print the year
too, with the cover's dashes.

The token is braced-only and is replaced after every other token. Its value is free text, so a pass that
matched `report-name` or `app-name` as bare words would either rewrite the name or never finish:
`replace_pattern_across_text_nodes` searches its own output again. Four tests hold this in place.
`test_each_master_prints_its_report_name_from_one_token_on_the_cover_and_in_both_footers` pins the three
paragraphs, `test_the_report_name_prints_on_the_cover_and_in_both_footers_while_the_application_name_stays_put`
renders every segment on every master, `test_a_report_name_holding_a_token_word_prints_as_typed` guards the
order, and `test_no_shipped_document_spells_report_name_without_braces` checks the masters and components.
`resources/report-name.docx`, which both release scripts ship and nothing renders, still holds the old footer line.

**`{{network}}` is braced-only, and sits in the cover's `Application Type` cell.** All four shipped
templates carry it since `7e42186`, in **8 cells, not 4**: the cover block occurs twice in every template
(a text box and its fallback), and both must hold the token or import refuses the document for
conflicting values. Generation refuses an unset value, so `N/A` never reaches a generated cover. DOCX
import reads the cell back through `_network_access`; anything but `Internal` or `External` leaves
`network` unset with `NETWORK_IMPORT_WARNING`. Reports generated before `7e42186` print a hardcoded
`Internal` there, which imports as `Internal` whatever the engagement was.

It is deliberately **not** in `PLAIN_METADATA_TOKENS`. That set matches bare, unbraced text, and the
lowercase word `network` already appears three times in body prose ("…must reside on the same
network…"), so a plain token would rewrite a sentence in every report. For the same reason nothing
find-and-replaces the literal `Internal`: it remains once per template, as a column header in the
Remediation Timelines table beside `External`, and a document-wide replacement would rewrite that
policy row to `External | External`. `test_both_cover_blocks_print_the_chosen_network_access_on_every_template`
pins both cover cells and that header.

Tokens may be wrapped in `{{...}}` or appear as plain text where the template
already uses that form. Split Word runs are supported.

## Component scope, in the two `THICK_MOBILE` templates

| Template token | Report value |
|---|---|
| `mobile-thick`, `thick-mobile` | `Mobile` or `Thick Client` |
| `binaries`, `binaries-description` | The prototype row of the `Component` table |

The two templates spell the caption token in opposite orders, so `_metadata`
always supplies both keys; `_replace_metadata` no-ops on the one that is absent,
which is also why the other two templates are unaffected by them.

The `Component` table is filled by cloning its single data row once per
component, production rows first. The table has no environment column or row
count boundary, so a finished DOCX cannot prove which environment owns a row. An empty
component list yields one `N/A` row, mirroring `User Roles` — leaving the
prototype row intact would instead fail the unresolved-placeholder check at the
very end of generation. `User Roles` leaves out a test account whose role and
username are both blank (a leftover from Add); the draft keeps the row, so an
import cannot bring it back.

## The Section table, in the two `ASIA` templates

Header row `Section | Vulnerability Name | Severity | CVSS Score | CVSS Vector`,
filled by cloned rows in the same order the findings body renders them — the
order is returned by `_populate_component_findings` and consumed, not derived a
second time.

Every column but the first is a **per-finding** value: `finding.title`,
`finding.severity`, `finding.cvss_score`, `finding.cvss_vector`. The CVSS pair
is held on the finding, not on the engagement, so a report prints as many pairs
as it has findings. A report with **no** findings gets one cloned row reading
`N/A` in all five cells, with every colour removed so the Severity cell does not
keep the prototype's. Leaving the prototype placeholders in place would fail the
unresolved-placeholder check at the end of generation, and the importer reads
this row back as no findings (see
[A report with no findings](#a-report-with-no-findings)).

`render_report_docx` finds this table before the findings go in and hands it to
`_populate_cvss_table`. A table a tester puts in a finding can be headed `Section`, and the Asia
masters keep the real one after the findings, so a lookup made afterwards found the tester's
table first. The importer's `_find_table` skips every table inside the findings, which run from
the first finding heading after the Findings table to the Appendix, for the same reason. That
also keeps a tester's table headed `Component` from being taken for the Component table that
two of the four templates lack.

**`{{section-number}}` becomes a Word `REF` field, never a number counted in
Python.** `_populate_component_findings` bookmarks each finding-title paragraph
as `vuln_<uid>`, and the Section cell holds ` REF vuln_<uid> \w \h `. Word
resolves it against the heading's own numbering, so the two cannot disagree, and
it keeps working if the heading styles are ever re-levelled. `\w` rather than
`\r` because the reference sits in a different section, where a relative number
is short. The existing `mark_all_fields_for_update` pass marks the field dirty
and sets `updateFields`, so the Word finalization step bakes the value in.

With the template as it stands, a finding title is `ReportHeading2` under a
`ReportHeading1` severity heading, and the severity headings begin at section 7 —
so the first Critical finding reads **7.1**, not `6.2.1`.

**`{{cvss-score}}` and `{{cvss-vector}}` carry the tester's values.**
`_populate_cvss_table` writes `finding.cvss_score` into cell 3 and
`finding.cvss_vector` into cell 4 (`app/docx_report.py` L627-L628). Both were an
empty string until the app started collecting them; blank rather than `N/A` was
chosen so that only the value would have to change, and only the value did.
`MAIN_ASIA.docx` was unreachable before either form existed, because those tokens
had no source and every unresolved token fails generation.

An empty field still prints an empty cell, so the token itself never blocks a
render. Requiring a value is `generation_issues`' job, and only when the segment
is Asia (`app/docx_report.py` L112-L116) — a field the tester cannot see must
never block their report.

Reading a finished report back, `parse_report_docx` pairs this table's rows with the
finding rows of the Findings Summary table by title, ignoring capitals and extra
spaces, so duplicate titles pair in order. What is left pairs by position when as
many CVSS rows as finding rows are left, and each position pair adds a warning. A
finding row with no CVSS row imports without scores, and a CVSS row that no finding
row matches refuses the import. Editable mode keeps Resolved and Closed rows; retest
pairs their rows before applying its intentional Resolved and Closed filter. A non-empty editable
score or vector must pass the same Unicode-aware character allowlist as an
ordinary save or the entire import is refused; it is never silently erased.

## Import contract

`parse_report_docx(data, mode="retest")` supports these four canonical template
structures. Omission of `mode` remains retest-compatible. `editable` creates a
new draft from supported visible document semantics: all known statuses and
their printed sections, engagement metadata, scope, Additional Information, and
reachable evidence. It does not recover hidden source-draft state, original IDs,
or original image upload metadata.

Status recognition ignores capitals and extra whitespace in both the finding
row and the finding table. `CLOSED` has the same meaning as `Closed`.

Status round-trips on the printed label. `STATUS_BY_LABEL` is the inverse of
`STATUS_LABELS` in `app/models.py`, so it carries all five,
including `"Closed": "closed"` — without it a generated Closed report imports as
`open_previously_discovered` through `FALLBACK_STATUS`, which succeeds with one
warning and is therefore easy to miss. A retest drops Closed findings exactly as
it drops Resolved ones and names them in the same `dropped_resolved` list;
editable mode keeps Closed as written and is the way back to a dropped finding.
The cover title is read against the segment set the model holds (`get_args(Segment)`), so
there is no list of its own to drift. Segment, application name and report type are
assigned from one match, so a title that does not start with a segment loses all three
together and raises nothing at import time;
`test_every_segment_the_model_allows_parses_back_out_of_a_title` in
`tests/test_docx_import.py` pins every segment.

A segment in `REPORT_NAME_SEGMENTS` prints its typed name as that title, so its title is read
differently. An Editable copy takes the title paragraph as printed for `report_name`, and the
application name from the cover's Application cell (`APPLICATION_COVER_LABEL`, read through
`_labelled_value`), falling back to the title's middle parts when the cell is empty. The cell is
looked up only in `_cover_texts`, the paragraphs inside the cover's text boxes (`w:txbxContent`, a
box and its fallback copy in all four masters), never in the whole body, because a finding's list
item or table cell can read "Application" followed by a value and would otherwise conflict with the
cover. The value is read with `free_text=True`, so it goes through `_visible_value` (edges trimmed, `N/A` read as empty) and keeps
the spaces inside it as typed; the other labelled values collapse runs of spaces. Two cover copies that disagree still refuse the import. A label owns the line after it, so an application named exactly `Application` is that label's value and is not read as a second label whose value is the next cell (`Application Type`). The Application Type cell is still read
from the whole body. A Retest import takes the application name from the cell and leaves `report_name`
empty, because the old name carries the old test's type and year. In an Editable copy, a title that
ends in a word that is not a report type gives a warning and an empty report type instead of the
"Unknown report type" refusal, because a free-text name can end in anything. A name that does not
start with a segment cannot be read at all, so the tester picks the segment and types it again.
Other segments import as before. `ReportNameImportTests` in `tests/test_docx_import.py` pins each case.

Web/API tables encode channel and environment. Component rows encode their
channel but not their environment: a sole positive environment observation is
used, otherwise the global row defaults to Production and a warning names it.
Unmatched or ambiguous finding locations become selected, covered review
targets, so their text remains visible on Setup and Findings rather than being
discarded on the first save.

A refused document says why. A finding takes its title, severity, ID and status
from its finding row in the Findings Summary table, so the importer pairs each
finding heading, a `ReportHeading2` paragraph between that table and the Appendix,
with a finding row before it reads any finding. A heading takes the row with
exactly its title first, then a row whose title is equal ignoring capitals and
extra spaces. What is left pairs by position when as many headings as finding
rows are left, and each position pair adds a warning. Otherwise nothing pairs
by position, and the refusal names the leftover finding rows and headings (the
first eight of each, then a count), the headings it did find, and any rows it
skipped for lacking a title or six cells. A heading in one of Word's own heading styles (`Heading2`) is
listed with its style. A finding keeps its finding row's title as printed there,
because the default In Conclusion sentence carries it that way.

Each finding then needs a finding table (the labels Severity, ID, Status and
Location in its first column, before its first section) and the sections its
status prints, in order. A finding table whose Severity, ID or Status differs from
the finding row (ignoring capitals, and ignoring a Status the app does not know)
never refuses the import: it keeps the finding row's values and adds one warning.
A missing or repeated section, and an invalid
ID, CVSS value or ticket, are each named with the finding and what was found. A
fragment that cannot be read is named with its section too. The wording is in
`app/docx_import.py`, pinned by tests in `tests/test_docx_import.py`. The checks
in `finalize_editable_import` name the finding, the section and what the app
would change (`first_change`).

An unlabelled table before Description is refused rather than discarded. So are
unattached captions, a repeated non-empty image caption, a caption separated from
its table or code block by prose, text beside a picture in one paragraph, pictures
inside text-only table cells, merged cells, and body-level Word content controls. A table cell
that holds a nested table, a content control, a tracked insertion, a symbol character, list
numbering or text the read would miss (inside a simple field, for example) is refused too, as is
a row that starts or ends partway across the grid. Deleted text in a tracked deletion is not
visible, so it does not count. A table whose first row is not a header cannot be told from one
that is, so it comes back with its first row as the header. The refusal
names the finding and section where applicable. The tester can rearrange the Word
content and retry; no partial draft is created.
An unexpected non-Appendix group heading after the last finding is also refused,
because treating it as a boundary would silently truncate that finding.

Visible hyperlink text imports as ordinary text with its bold, italic and
underline settings, not as a clickable link. Explicit formatting-off values,
paragraph-mark formatting-off values, and Word's `numId=0` numbering-off value
remain off. A header-only table keeps zero data rows, and empty cell paragraphs
retain their line breaks. Severity review ticket
metadata is read after In Conclusion begins; the same label in another section
remains authored text.

Every retained image occurrence receives fresh evidence identity while keeping
its embedded PNG bytes exactly. ZIP member counts and expanded size, media byte
size, selected evidence aggregate, PNG dimensions, and pixel count are bounded
before persistence. Editable width comes only from one proportional, uncropped,
unrotated inline drawing at or below 155 mm; unsupported geometry rejects.
The embedded raster is the copy this renderer produced, so it already carries
the canonical border in its pixels. Regeneration recognises that border and
embeds the picture unchanged, and the editable import result says the images
are rendered Word copies rather than the original files.

## Tag formatting

Replacing a main-template value tag preserves its paragraph style and run
formatting, including font family, size, bold, italic, and underline. Only the
font color may change for likelihood, impact, and severity rating tags.

Preferred rating tags are `{{likelihood-rating}}`, `{{impact-rating}}`, and
`{{severity-rating}}`. `{{vuln_severity}}` and `{{rating}}` are also supported.
Rating names and tags are matched case-insensitively.

| Rating | Font color |
|---|---|
| Critical | `RGBColor(192, 0, 0)` / `C00000` |
| High | `RGBColor(237, 125, 49)` / `ED7D31` |
| Medium | `RGBColor(255, 192, 0)` / `FFC000` |
| Low | `RGBColor(112, 173, 71)` / `70AD47` |
| Informational | `RGBColor(81, 81, 81)` / `515151` |

Likelihood, impact, and severity values in the Findings Summary table are
always rendered at `12 pt`.

Non-rating tags and unrecognized rating values retain the color defined by the
template.

## Scope fields

| Template token | Report value |
|---|---|
| `prod-web`, `non-prod-web` | Web scope targets by environment |
| `prod-api`, `non-prod-api` | API scope targets by environment |
| `role1`, `username1`, `role2`, `username2` | Compatibility placeholders; the account table is rebuilt for all accounts |
| `limitation-set` | Testing limitations |

## Findings

The Findings Summary table is rebuilt from its generic prototype row with one
row per finding. `{{findings}}` is the insertion point for the component hierarchy:

1. A document from `resources/severity_titles/` is inserted for every severity
  that has findings.
2. `{{finding_title}}` in that severity document is replaced by all findings in
  that category.
3. `open_new` findings use `resources/finding_types/new_finding.docx`.
4. `open_previously_discovered`, `open_resolved_on_non_prod`, `resolved` and
  `closed` findings use `resources/finding_types/retest_finding.docx`.
5. Finding content anchors are replaced by documents from
  `resources/fragments/`.

`Closed` prints exactly what `Resolved` prints — the same five sections through
the same component. No third finding component was authored and none is needed,
because the selection is `new_finding.docx` if `open_new` else
`retest_finding.docx`, and the importer's `expected_sections` reaches the same
five-section shape from its own `!= "open_new"` test. Neither side carries a
`closed` arm, deliberately: adding one to either would make every Closed report
this app writes a report it cannot read back. `STATUS_LABELS` in
`app/models.py` is the whole of the status contract on the way out — both
call sites are bare subscripts, and the status cell is neither recoloured nor
resized, so a fifth label was all the document needed.

Each finding's heading, table and sections are generated dynamically:

- Empty severity categories are omitted.
- Multiple findings of one severity share one severity-title component.
- Finding title, likelihood, impact, severity, ID, status, and affected locations
  are populated from report data.
- A finding with no Vuln ID leaves that cell blank in both the Findings Summary
  table and the finding table; the internal `uid` is never printed.
- Affected locations render as a real bulleted list cloned from
  `resources/fragments/bulleted_fragment.docx`, forced left-aligned, one bullet
  per location. The bullet glyph comes from the list style, so it is not part of
  the text and is not counted when wrapping. An environment the finding does not
  affect prints a single `N/A` **through the same bullet path**, so the two
  environment cells read alike; Limitations deliberately goes the other way and
  strips its bullet.
- Long values are wrapped so a line cannot widen its column: count to the limit,
  walk back to the first character that is not a letter or digit, break after it
  with a `w:br` inside the run, then start counting again. A stretch offering no
  such character is cut at the limit. Characters inside `://` are skipped so a
  long host cannot strand the scheme on a line of its own. Limits live in
  `app/docx_report.py`: `LOCATION_WRAP_CHARACTERS` (74) for affected locations,
  `SCOPE_WRAP_CHARACTERS` (84) for the web and API scope tables.
- Previous Proof of Concept and In Conclusion exist only in retest finding
  components.

## A report with no findings

A report with no findings of any status prints a fixed layout instead of the
findings body. The decisions are in `docs/plans/no-findings-report.md` and
`docs/adr/0002-no-findings-report-is-derived-and-confirmed-per-request.md`.

- The Findings Summary table gets one row: `NO_FINDINGS_TITLE`
  (`(No vulnerability found)`, in `app/docx_import.py`), then `N/A` for
  Likelihood, Impact, Severity, ID and Status. No cell is coloured. The three
  rating cells are set to 12 pt like any rating, because their prototype token
  run is 10 pt.
- `resources/severity_titles/no_finding.docx` takes the place of every severity
  section at `{{findings}}`. It holds the TESTING RESULT heading in Report
  Heading 1, so the heading is numbered and listed in the table of contents like
  a severity heading, and a paragraph holding `{{testing_result}}`.
  `_populate_component_findings` fills that tag with `TESTING_RESULT_PARAGRAPH`
  and gives the first paragraph a page break before it, as it does a severity
  section. The paragraph's look comes from the file; the code supplies only the
  words.
- The Asia Section table gets its one `N/A` row.
- The three template sentences that mention findings (the executive summary's
  pointer to the Findings Summary, the CVSS appendix pointer, and the Findings
  Summary introduction) print unchanged.

`no_finding.docx` is authored in Word by the user. Like every component it may
use only styles the four masters define and may hold no relationship in its
body. It must carry no tag except `{{testing_result}}`, because metadata tags
such as `{{app-name}}` are replaced before the findings body is inserted and
would be left unresolved.

`generation_issues` no longer asks for a finding. Generating a report with no
findings instead needs the tester's confirmation on the request (see
`docs/ROUTES.md`).

Reading it back, `_summary_rows` returns no rows when the table's only row is
the placeholder, and `_findings` drops the Section table's lone all-`N/A` row
when the summary held none, so both import modes produce a draft with zero
findings. The TESTING RESULT heading is a Report Heading 1 that does not start
with "Appendix:", so the body scan passes over it.

## Severity Review Tickets, in the retest finding component

`{{severity-review-tickets}}` lives only in
`resources/finding_types/retest_finding.docx`, so it prints for
`open_previously_discovered`, `open_resolved_on_non_prod`, `resolved` and
`closed` findings and never for `open_new` —
on `new_finding.docx` the replacement is a no-op because there is no such token.
The static label `Severity Review Ticket (if applicable):` is one paragraph, and
the token owns the whole of the paragraph below it. The label carries
`w:keepNext`, so Word moves it to the page where its value starts (see the
page-break note under Fragment anchors). The renderer finds the label by walking
up from the token, so the two must stay in adjacent paragraphs. A blank
paragraph between them stops the walk, and
`test_the_severity_review_ticket_label_is_kept_on_the_page_with_its_value` fails.

It is written with `replace_component_token_runs` rather than the plain string
path (`app/docx_report.py` L772-L776), because only `_set_run_text` turns a
newline into a real `w:br`. Each stored line therefore becomes one printed line
inside that single paragraph, not a paragraph of its own.

The draft stores **bare digits**, one per line; the prefix belongs to the
document. Every printed line is written as `SEVERITY_TICKET_PREFIX` + the stored
line — `GRIMPEN-` (`app/docx_report.py` L54) — so `1234` prints as
`GRIMPEN-1234`. Blank stored lines are dropped, and a value that is empty once
stripped prints the literal `N/A`, unprefixed.

Reading a finished report back, the importer matches on the label string rather
than a position, then reads the following paragraph run by run —
`paragraph.text` would silently drop the `w:br` lines — and normalises it with
`_parsed_ticket_lines` in `app/docx_import.py`. That strips a leading key
of any tracker rather than `GRIMPEN-` alone, splits on newlines, commas and
semicolons, and keeps only the pieces that are wholly decimal. A piece such as
`GRIMPEN-3523 (closed 2024)` is dropped whole rather than mined for the digits
inside it, because a fabricated ticket reference reads as plausibly as a real
one and nothing downstream would catch it.

## Fragment anchors

| Anchor | Rendered content |
|---|---|
| `description-fragments-here` | All Description fragments |
| `recommended-remediation-fragments-here` | All remediation fragments |
| `prev-poc-fragments-here` | Previous PoC fragments in retest findings |
| `poc-fragments-here` | Current PoC fragments |
| `conclusion-fragments-here` | In Conclusion fragments in retest findings |

Each fragment is emitted as a distinct paragraph, list, table, note, code block,
or image/caption pair using its corresponding document under
`resources/fragments/`. A table fragment is the exception: only the `w:tbl`
element of `table_fragment.docx` is used and every paragraph in it is discarded,
so the renderer appends one empty paragraph after each table. Without it two
consecutive table fragments become adjacent `w:tbl` siblings, which Word merges
into a single table. A list is cloned once per item and has no blank of its own,
so the renderer also appends one empty paragraph after the last item of every
numbered or bulleted list. The importer drops it with every other empty
paragraph, and a list that ends a content section loses it with the other
trailing blanks. Rich-text bold, italic, and underline values are layered
onto the formatting supplied by the fragment document. Numbered lists restart
for each list fragment and increment within that list.

Every row of a table fragment gets `w:cantSplit`, and a header row also gets `w:tblHeader`, from
`_keep_row_whole`. `table_fragment.docx` sets neither and the binary templates are not edited. A
table with no header row repeats nothing. Word has not been checked on this yet: render a table of
30 rows and 8 columns on Windows and look at its second page.

Word decides automatic page breaks itself and never records them in the file, so
the renderer cannot detect one and move things around it. Instead it sets
`w:keepNext` on anything that introduces content: section headings (found by
walking back from their `{{...-fragments-here}}` anchor, never by matching the
heading text, so `SECTION_HEADINGS` in `app/docx_import.py` stays the only place
those strings live), the `Severity Review Ticket (if applicable):` label (found
the same way, by walking back from the `{{severity-review-tickets}}` token under
it before the token is replaced), the `PROD:`/`UAT:` evidence labels, instance
titles, code captions, an image that has a caption, and the lead-in paragraph
above a table. On the ticket label, `w:keepNext` keeps the label on the page where
its value starts, whether the value is `N/A` or a list of tickets. An Open (New)
finding has no label, because only `retest_finding.docx` carries the token. Two
cases are not covered. An uncaptioned code block is a run of ordinary paragraphs
with no all-or-nothing block to strand. A long list of tickets can still split
across two pages, because its paragraph has no `w:keepLines` and `w:keepNext`
only ties the label to the first lines of the value.

Fragment-template blank paragraphs are preserved between fragments and trimmed
at content-section boundaries. The exception is a code block in a proof-of-concept
section (`poc-fragments-here` and `prev-poc-fragments-here`): the spacer a
paragraph, list or note leaves behind comes off when an uncaptioned code block
follows, so the code sits directly under the step that introduces it, and the
blank the caption component ships with comes off between a caption and its code.
The blank above a caption stays. Two code blocks in a row never had a spacer, and
a code block in a Description or a Remediation keeps the one it has. The importer
tells a code block by its shading, not by a blank above it, so it reads the tight
layout back unchanged (`test_a_code_block_directly_under_its_steps_is_still_read_as_code`).
Generated evidence images clone the centered
paragraph alignment from `resources/fragments/image_fragment.docx` and embed
its effective 0.75 pt black border into an in-memory PNG copy so all four edges
render consistently. Source evidence files and static template artwork remain
unchanged.

A picture that already carries a border gets no second one. `_has_border` in
`app/docx_report.py` treats an image as bordered when, on all four sides, its
outermost line of pixels is dark: at least 98% of the line at 64 or less out of
255 in every colour channel (`IMAGE_BORDER_DARK_LEVEL`, `IMAGE_BORDER_DARK_SHARE`).
Such a picture is embedded as it is, with no resizing and no new border. This
covers pictures carried into Previous Proof of Concept by a retest import, images
brought back by an editable import, and pictures copied out of an earlier report.
A border shrunk to about 40% of its size is still found, blurred or not. The test
cannot tell a border from a dark edge, so a dark-mode screenshot or a solid black
image also goes in without one. A report generated before this check keeps any
double border it already has.

Images are inserted at their content position, and `caption_fragment.docx`
supplies image, code, and table caption formatting. An environment may contain
any number of images. The final generator rejects missing required environment
evidence.

In Proof of Concept and Previous Proof of Concept, an environment label
(`PROD:`, or the non-production label in capitals such as `UAT:`) prints above
an image whose environment differs from the last label printed, and again
after an instance title even when the environment is the same, so Prod, UAT,
Prod, Prod, UAT prints `PROD:`, `UAT:`, `PROD:`, `UAT:`. Nothing else between
images, such as steps or notes, prints a new label. The label renders from the
instance-title component, and the importer tells it apart by its text alone:
it sets the environment of the images after it and adds no fragment, so a
repeated label, whether from this generator or from a report written before
it, imports cleanly.

The generator prints images in their stored order and reorders nothing. The
order arrives production first, because in each instance of Proof of Concept
the app keeps production evidence ahead of non-production evidence when it
saves (`production_images_first`, `docs/DATA_MAP.md`). So the first label there
is `PROD:` whenever the instance holds production evidence. Previous Proof of
Concept prints as the earlier engagement wrote it.

Run `py -3 -m scripts.compose_component_test` to generate
`generated/image-caption-test.docx`, an isolated proof containing one embedded
image followed immediately by a `Figures and Tables` caption.

Native Word captions can be added as a post-processing step:

```powershell
py -3 -m scripts.postprocess_captions generated-report.docx -o captioned-report.docx
```

The processor converts caption-styled text immediately below body images into
`SEQ Figure \* ARABIC` fields, preserves the paragraph style, stores visible
cached numbering, explicitly centers every image caption, and is idempotent. By
default, it uses the already-installed
Microsoft Word automation interface to repaginate the document, rebuild the
Table of Contents, update TOC page numbers, and refresh all caption fields.
Pass `--skip-word-update` only when Word automation is unavailable; the DOCX
will then request field updates when opened in Word. Images not followed by a
`Caption` or `Figures and Tables` paragraph are ignored.

Normal app and CLI report generation automatically creates native image-caption
fields and runs the same Word finalization step. There is no `--skip-word-update`
equivalent on those paths, so **generating a report requires Windows with
Microsoft Word installed**; see `docs/ARCHITECTURE.md` § Platform requirements. The
existing methodology image in `MAIN.docx` is Figure 1, so generated evidence
captions continue at Figure 2 in document order.

`generated/native-image-caption-test.docx` is the three-image native-caption
proof. Its captions display Figure 1 through Figure 3 and contain genuine Word
sequence fields.

## Commands

Generate a final report:

```powershell
py -3 -m scripts.generate_report <report_id>
```

Generate a layout preview with visible placeholders for missing evidence:

```powershell
py -3 -m scripts.generate_report <report_id> --allow-incomplete
```

The Content page also exposes **Generate Report** when all review issues are
resolved.

## Component composition

`scripts/compose_component_test.py` builds two image-caption proofs from the caption
fragment document (`clone_component_elements`, which the renderer also uses):

- Finding-type and fragment documents retain their paragraph styles, direct run
  formatting, tables, and list numbering when cloned into a report.
- Component paragraph styles must already exist in the main template.
- Evidence images are embedded by the renderer; their captions use the caption
  fragment document.

Run the proofs with:

```powershell
py -3 -m scripts.compose_component_test
```

It creates `generated/image-caption-test.docx` and
`generated/native-image-caption-test.docx`.
