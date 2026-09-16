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
fixture rendered through them never has the extra tables. That is deliberate.

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
component, production rows first. The table has no environment column, so that
ordering is the only thing carrying the distinction to the reader. An empty
component list yields one `N/A` row, mirroring `User Roles` — leaving the
prototype row intact would instead fail the unresolved-placeholder check at the
very end of generation.

## The Section table, in the two `ASIA` templates

Header row `Section | Vulnerability Name | Severity | CVSS Score | CVSS Vector`,
filled by cloned rows in the same order the findings body renders them — the
order is returned by `_populate_component_findings` and consumed, not derived a
second time.

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

**`{{cvss-score}}` and `{{cvss-vector}}` are replaced with an empty string.** The
app does not collect CVSS yet; blank rather than `N/A` so that only the value
changes when it does. `MAIN_ASIA.docx` was unreachable before this, because those
tokens had no source and every unresolved token fails generation.

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
all-or-nothing block to strand.

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
