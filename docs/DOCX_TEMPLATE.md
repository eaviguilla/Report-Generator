# DOCX Template Contract

`resources/MAIN_TEST.docx` is the canonical Word template used by
`app/docx_report.py`.
The renderer preserves its styles, sections, headers, footers, numbering, and
static content while replacing the fields below.

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
`resources/fragments/`. Rich-text bold, italic, and underline values are layered
onto the formatting supplied by the fragment document. Numbered lists restart
for each list fragment and increment within that list.

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
fields and runs the same Word finalization step. The existing methodology image
in `MAIN_TEST.docx` is Figure 1, so generated evidence captions continue at
Figure 2 in document order.

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

- `resources/MAIN_TEST.docx` supplies the complete report shell.
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

It creates `generated/MAIN_TEST-composed.docx` and
`generated/retest-finding-composed.docx`. The first proof populates only the
findings anchor; other metadata placeholders in `MAIN_TEST.docx` intentionally
remain unchanged.
