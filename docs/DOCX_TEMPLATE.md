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

## Engagement fields

| Template token | Report value |
|---|---|
| `segment` | Selected segment |
| `app-name`, `report-name` | Application name |
| `test-type` | Annual Pentest, Retest, Deployment Pentest, or New Test |
| `app-owner` | Application owner |
| `report-date` | Report date |
| `tester-name` | Tester |
| `prod-start`, `prod-end`, `prod-time` | Production test window |
| `non-prod-start`, `non-prod-end`, `non-prod-time` | Non-Production test window |

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
very end of generation.

## The Section table, in the two `ASIA` templates

Header row `Section | Vulnerability Name | Severity | CVSS Score | CVSS Vector`,
filled by cloned rows in the same order the findings body renders them — the
order is returned by `_populate_component_findings` and consumed, not derived a
second time.

Every column but the first is a **per-finding** value: `finding.title`,
`finding.severity`, `finding.cvss_score`, `finding.cvss_vector`. The CVSS pair
is held on the finding, not on the engagement, so a report prints as many pairs
as it has findings. A report with **no** findings still gets one cloned row with
all five cells replaced by the empty string, because leaving the prototype
placeholders in place would fail the unresolved-placeholder check at the end of
generation.

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

Reading a finished report back, `parse_report_docx` pairs this table with finding
details by title **and occurrence order**, so duplicate titles retain distinct
rows. Editable mode keeps Resolved rows; retest claims their rows before applying
its intentional Resolved filter. A non-empty editable score or vector must pass
the same Unicode-aware character allowlist as an ordinary save or the entire
import is rejected; it is never silently erased.

## Import contract

`parse_report_docx(data, mode="retest")` supports these four canonical template
structures. Omission of `mode` remains retest-compatible. `editable` creates a
new draft from supported visible document semantics: all known statuses and
their printed sections, engagement metadata, scope, Additional Information, and
reachable evidence. It does not recover hidden source-draft state, original IDs,
or original image upload metadata.

Web/API tables encode channel and environment. Component rows encode their
channel but not their environment: a sole positive environment observation is
used, otherwise the global row defaults to Production and a warning names it.
Unmatched or ambiguous finding locations become selected, covered review
targets, so their text remains visible on Setup and Findings rather than being
discarded on the first save.

Every retained image occurrence receives fresh evidence identity while keeping
its embedded PNG bytes exactly. ZIP member counts and expanded size, media byte
size, selected evidence aggregate, PNG dimensions, and pixel count are bounded
before persistence. Editable width comes only from one proportional, uncropped,
unrotated inline drawing at or below 155 mm; unsupported geometry rejects.
Because the embedded raster is Word-rendered, regeneration may resample it or
add another canonical border, and the import result discloses that limitation.

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

Likelihood, impact, and severity values in the Findings summary table are
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

The summary table is rebuilt from its generic prototype row with one row per
finding. `{{findings}}` is the insertion point for the component hierarchy:

1. A document from `resources/severity_titles/` is inserted for every severity
  that has findings.
2. `{{finding_title}}` in that severity document is replaced by all findings in
  that category.
3. `open_new` findings use `resources/finding_types/new_finding.docx`.
4. `open_previously_discovered` and `resolved` findings use
  `resources/finding_types/retest_finding.docx`.
5. Finding content anchors are replaced by documents from
  `resources/fragments/`.

Detail sections are generated dynamically:

- Empty severity categories are omitted.
- Multiple findings of one severity share one severity-title component.
- Finding title, likelihood, impact, severity, ID, status, and affected locations
  are populated from report data.
- A finding with no Vuln ID leaves that cell blank in both the findings summary
  and the finding's detail table; the internal `uid` is never printed.
- Affected locations render as a real bulleted list cloned from
  `resources/fragments/bulleted_fragment.docx`, forced left-aligned, one bullet
  per location. The bullet glyph comes from the list style, so it is not part of
  the text and is not counted when wrapping.
- Long values are wrapped so a line cannot widen its column: count to the limit,
  walk back to the first character that is not a letter or digit, break after it
  with a `w:br` inside the run, then start counting again. A stretch offering no
  such character is cut at the limit. Characters inside `://` are skipped so a
  long host cannot strand the scheme on a line of its own. Limits live in
  `app/docx_report.py`: `LOCATION_WRAP_CHARACTERS` (74) for affected locations,
  `SCOPE_WRAP_CHARACTERS` (84) for the web and API scope tables.
- Previous Proof of Concept and In Conclusion exist only in retest finding
  components.

## Severity Review Tickets, in the retest finding component

`{{severity-review-tickets}}` lives only in
`resources/finding_types/retest_finding.docx`, so it prints for
`open_previously_discovered` and `resolved` findings and never for `open_new` —
on `new_finding.docx` the replacement is a no-op because there is no such token.
The static label `Severity Review Ticket (if applicable):` is one paragraph, and
the token owns the whole of the paragraph below it.

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
`_ticket_lines` (`app/docx_import.py` L87, L512-L522). That strips a leading key
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
into a single table. Rich-text bold, italic, and underline values are layered
onto the formatting supplied by the fragment document. Numbered lists restart
for each list fragment and increment within that list.

Word decides automatic page breaks itself and never records them in the file, so
the renderer cannot detect one and move things around it. Instead it sets
`w:keepNext` on anything that introduces content: section headings (found by
walking back from their `{{...-fragments-here}}` anchor, never by matching the
heading text, so `SECTION_HEADINGS` in `app/docx_import.py` stays the only place
those strings live), the `PROD:`/`UAT:` evidence labels, instance titles, code
captions, an image that has a caption, and the lead-in paragraph above a table.
Two cases are deliberately uncovered: `Severity Review Ticket (if applicable):`,
which is filled by token replacement and has no anchor to walk back from, and an
uncaptioned code block, which is a run of ordinary paragraphs with no
all-or-nothing block to strand. Now that the ticket value is a tester input, the
first gap is easier to see: a multi-line value is a taller block that can fall
to the next page and leave its label stranded above. Where the break lands is
Word's to decide and nothing in the file records it, so this was left alone
rather than guessed at.

Fragment-template blank paragraphs are preserved between fragments and trimmed
at content-section boundaries. Generated evidence images clone the centered
paragraph alignment from `resources/fragments/image_fragment.docx` and embed
its effective 0.75 pt black border into an in-memory PNG copy so all four edges
render consistently. Source evidence files and static template artwork remain
unchanged.

Images are inserted at their content position, and `caption_fragment.docx`
supplies image, code, and table caption formatting. An environment may contain
any number of images. The final generator rejects missing required environment
evidence.

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
Microsoft Word installed**; see `docs/PLAN.md` § Platform requirements. The
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

`scripts/compose_component_test.py` demonstrates the component architecture:

- `resources/MAIN.docx` supplies the complete report shell.
- Severity components are inserted in Critical, High, Medium, Low,
  Informational order and begin on new pages.
- Finding-type and fragment documents retain their paragraph styles, direct run
  formatting, tables, and list numbering.
- Component paragraph styles must already exist in the main template.
- Evidence images are embedded by the renderer; their captions use the caption
  fragment document.

Run the proof with:

```powershell
py -3 -m scripts.compose_component_test
```

It creates `generated/MAIN-composed.docx` and
`generated/retest-finding-composed.docx`. The first proof populates only the
findings anchor; other metadata placeholders in `MAIN.docx` intentionally
remain unchanged.
