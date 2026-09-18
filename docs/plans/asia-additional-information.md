# Asia segment: Additional Information content

> **Status:** in progress · 2026-09-18 · all ten steps written, suites green, not yet committed

## Request

> When asia segment is selected, add another content in the contents page named Additional Information. In this, one will be Severity Change, which is, one value per line, then CVSS Score where the only allowed are numbers and period(only one line). CVSS Vector which is another text box, only one line which allows letters and these symbols /: only. Make sure the UI design for all contents are in sync.
>
> the Severity Review Tickets value will be generated to the tagging of {{severity-review-tickets}}.
> this will only be visible to Open (Previously Discovered) and to Resolved findings.
> these are in the /resources/finding_types/retest_finding.docx
> this will be empty and is not required to have an input before generating. also, if it is empty, then the default value will be N/A
> also, the Severity Review Tickets field will be visible to all segments
>
> then, the CVSS Score and CVSS Vector fields will be visible only to Asia segments.
> these will be filling the {{cvss-score}} and {{cvss-vector}} respectively. they are in the bottom most part table of the MAIN_ASIA.docx or MAIN_THICK_MOBILE_ASIA.docx
>
> So if the new Additional information content will not be visible if the segment is not Asia or the finding is Open (New). Then refer to text above for the rulings of the visibility of each field. Ask me any questions for better output and plan and implementation.

## Coordinator notes before Round 1

**Size: large.** A new content type is a schema change to `ContentType`, the visibility rules depend on
two axes, the character allowlists will need twins in both Python and JavaScript, and three Word
templates are involved. Both rounds.

**The document side is already wired.** Found before dispatching any agent:

| Token | Today | Where |
|---|---|---|
| `{{severity-review-tickets}}` | hardcoded to the literal `"N/A"` | `app/docx_report.py` L764 |
| `{{cvss-score}}` | replaced with an empty string | `_populate_cvss_table`, L607 |
| `{{cvss-vector}}` | replaced with an empty string | same |

The source comment reads *"CVSS score and vector are tester inputs the app does not collect yet.
Blank rather than…"*, and `docs/plans/thick-client-app-type.md` states the intent plainly: *"When the
CVSS fields are added later, only the value changes."*

So this change is mostly about **collecting** three values and **gating their visibility**. The
token replacement already exists and only needs its source swapped from a constant to a field.

**A contradiction in the request blocked Round 1** and was settled by the owner before it ran; see
*Answers*. The request called the Severity Review Tickets field *"visible to all segments"* while
also hiding the whole section outside Asia, which cannot both hold if the field lives in that
section.

## Round 1 - Oracle: how it works today

Everything below was read out of source on 2026-09-18. Where `docs/DATA_MAP.md` and the code
disagree it is called out; nothing here is taken from a plan document.

### 1. The content model

`ContentType` is a closed five-member `Literal`, declared once at
[app/models.py](app/models.py#L34): `description`, `recommended_remediation`,
`previous_proof_of_concept`, `proof_of_concept`, `in_conclusion`.

`Content` is two fields and nothing else — [app/models.py](app/models.py#L140-L142):

```python
class Content(BaseModel):
    type: ContentType
    fragments: list[Fragment] = Field(default_factory=list)
```

Contents hang off a finding as a plain list, [app/models.py](app/models.py#L224):
`contents: list[Content] = Field(default_factory=list)` on `Vulnerability`
([app/models.py](app/models.py#L199)). There is no back-pointer from a `Content` or a
`Vulnerability` to the `Report`; anything that needs the engagement must be handed the report.

A **fragment** is one of seven discriminated models, unioned at
[app/models.py](app/models.py#L137) with `Field(discriminator="type")`:

| Fragment | Payload key that identifies it | Declared at |
|---|---|---|
| `ParagraphFragment` (`paragraph`) | `runs: list[Run]`, plus a legacy `generated` marker | [L79](app/models.py#L79) |
| `ListFragment` (`numbered_list`, `bulleted_list`) | `items: list[ListItem]`, `min_length=1`, plus `continue_numbering` | [L90](app/models.py#L90) |
| `TableFragment` (`table`) | `header`, `rows`, `caption` | [L98](app/models.py#L98) |
| `NoteFragment` (`note`) | `runs` | [L105](app/models.py#L105) |
| `ImageFragment` (`image`) | `environment`, `evidence_id`, `caption`, `width_mm` | [L111](app/models.py#L111) |
| `CodeFragment` (`code_block`) | `text`, `caption` | [L119](app/models.py#L119) |
| `InstanceTitleFragment` (`instance_title`) | `text` | [L131](app/models.py#L131) |

`Run` is `{text, bold, italic, underline}` ([L74](app/models.py#L74)). So there are exactly three
text shapes a new field could reuse: rich `runs`, a list of `items`, or a plain `text` string.

**Which fragment types may appear in which section is not constrained in Python at all.**
`Content.fragments` is a bare `list[Fragment]`. The restriction exists only in the browser, as the
`allowed` map at [app/web/static/app.js](app/web/static/app.js#L119), which drives the Add menu.

**Ordering.** Two different guarantees, and they are not the same one:

- **Section order is derived, not stored.** `provision` rewrites `vulnerability.contents` on every
  PUT to `content_types_for_status(status)` order, with carried sections appended after —
  [app/report_service.py](app/report_service.py#L211). Whatever order the browser submits is
  discarded. The JavaScript twin does the same at
  [app/web/static/app.js](app/web/static/app.js#L1055).
- **Fragment order inside a section is the tester's**, mutated by move up/down and drag-drop in
  `renderFragment` ([app/web/static/app.js](app/web/static/app.js#L3049)). The one exception is
  `ensure_proof_steps`, which inserts a `numbered_list` at index 0
  ([app/report_service.py](app/report_service.py#L165)).
- **The editor does not render in `contents` order.** `pairUp` lifts description/remediation and
  the two proofs into `.content-row` pairs first, then appends whatever is left in list order —
  [app/web/static/app.js](app/web/static/app.js#L4003-L4013). A new section not named in a pair
  falls to the bottom, full width.

`Report.validate_references` enforces that `contents[].type` values are unique within one finding
([app/models.py](app/models.py#L384-L386)) and that `frag_id` is unique **across the whole report**
([L390-L393](app/models.py#L390)). It enforces nothing about which sections a status requires.

### 2. Who decides which sections a finding has

Both deciding functions are **status-only**. Neither can see the engagement, and therefore neither
can see the segment:

```python
def content_types_for_status(status: str) -> list[str]:      # report_service.py L172
def provision(vulnerability: Vulnerability) -> None:          # report_service.py L202
```

[app/report_service.py](app/report_service.py#L172) returns three sections for `open_new` and all
five for everything else. [app/report_service.py](app/report_service.py#L202) takes the
`Vulnerability` alone.

The only place holding both the finding and the report is `provision_report`
([app/main.py](app/main.py#L261)), which loops the findings and calls `provision(vulnerability)`
then `sync_evidence_image_slots(vulnerability, report)`. **`sync_evidence_image_slots` is the
existing precedent for a report-aware provisioning pass** — it already has the signature
`(vulnerability, report)` ([app/report_service.py](app/report_service.py#L357)).

**Carry-work, the rule added after the data-loss bug** —
[app/report_service.py](app/report_service.py#L206-L211):

```python
carried = [content for content in vulnerability.contents
           if content.type not in types and content.type != "in_conclusion" and content_has_work(content)]
vulnerability.contents = [existing.get(t, Content(type=t)) for t in types] + carried
```

So a section the new status does not print is **kept out of sight** rather than deleted, provided
`content_has_work` ([L179](app/report_service.py#L179)) says it holds something. That predicate
deliberately ignores boilerplate this app wrote itself (`generated` markers, the default conclusion
sentence). `in_conclusion` is the single exception and is dropped outright. A carried section is
invisible everywhere: the editor filters to printed types
([app/web/static/app.js](app/web/static/app.js#L3998)), `generation_issues` skips it
([app/docx_report.py](app/docx_report.py#L112-L114)), and `_render_finding_component` has no anchor
for it.

**Consequence for this change:** a section that becomes inapplicable (segment moves off Asia) is
*already* preserved by this machinery **if and only if** the deciding function stops returning it
*and* the section holds work. A section holding only empty fields is silently dropped on the next
save. That is a real behaviour, not a hypothetical.

**Seed fragments** are a dict keyed by content type,
[app/report_service.py](app/report_service.py#L212-L218), applied only to an **empty** section
([L220](app/report_service.py#L220)). The guard is `content.type not in required_fragments`, so an
unlisted sixth type is skipped without raising. The JavaScript twin
([app/web/static/app.js](app/web/static/app.js#L1058-L1061)) guards the same way with
`!required[content.type]`.

**One bare `next()` worth knowing about:** [app/report_service.py](app/report_service.py#L233)
reads `remediation = next(content for content in vulnerability.contents if content.type ==
"recommended_remediation")` with no default. It raises `StopIteration` if that section is ever
absent. The conclusion lookup two lines below uses `next(..., None)` instead. Any new code that
looks a section up must use the second form.

**Where `provision` runs — and where it does not.** Python: `main.save_report` via
`provision_report` ([app/main.py](app/main.py#L697)) and `main.insert_library`
([app/main.py](app/main.py#L719)). JavaScript: the Findings status `onchange`
([app/web/static/app.js](app/web/static/app.js#L2590)) and new-finding creation
([L3646](app/web/static/app.js#L3646)). It does **not** run on load, on `import_report`, or on
editor boot. A draft therefore gains a newly-required section only on its next PUT.

### 3. Segment

`Segment = Literal["JH", "GWAM", "Asia"]` at [app/models.py](app/models.py#L32); stored in exactly
one place, `Engagement.segment: Segment | None = None` at [app/models.py](app/models.py#L232).
It is nullable, and a blank segment is a `setup_issues` line
([app/report_service.py](app/report_service.py#L655-L656)) that redirects Findings and Editor back
to Setup.

**Reaching it from a finding:** there is no path. `Vulnerability` carries no report reference, so
every consumer needs `report.engagement.segment` passed in. On the client this is free — `report`
is a module-scope object the whole script closes over — which makes the two sides asymmetric: the
JavaScript `provision(vulnerability)` could read the segment today without a signature change, the
Python one could not.

**What already branches on segment:**

| Reader | Effect | Where |
|---|---|---|
| `main_template_path` | `asia = report.engagement.segment == "Asia"`; picks one of four templates on two axes | [app/docx_report.py](app/docx_report.py#L152-L158) |
| `_metadata` | fills the `{{segment}}` token, `or "N/A"` | [app/docx_report.py](app/docx_report.py#L265) |
| `_populate_cvss_table` | **indirectly** — it looks for a table named `Section`, which only the Asia templates carry, and returns early if absent | [app/docx_report.py](app/docx_report.py#L607-L612) |
| `report_export_filename` | first component of the export filename, fallback `Unassigned` | [app/report_service.py](app/report_service.py#L158) |
| `setup_issues` | blocks navigation when unset | [app/report_service.py](app/report_service.py#L655) |
| `parse_report_docx` | reads the segment back out of the title line on import | [app/docx_import.py](app/docx_import.py#L528-L535) |
| client | engagement-name display, the Setup missing-fields list, the navigation metadata check | [app.js L30](app/web/static/app.js#L30), [L622](app/web/static/app.js#L622), [L2702](app/web/static/app.js#L2702) |

Note that the template axis and the CVSS table axis are **independent implementations of the same
rule**: one compares the string, the other infers it from the template's contents.

**Does a segment change re-provision anything today? No.** The control is a plain
`<select data-path="engagement.segment">` in [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7),
wired by the generic `[data-path]` handler at
[app/web/static/app.js](app/web/static/app.js#L1575-L1580), which does
`report[section][field] = input.value || null` and `scheduleSave()`. No confirmation, no purge, no
recomputation of any finding. Changing segment today only changes which template generation picks.

**The app-type precedent, which is the one the request's phrasing invites.** Unticking an app type
runs `dropChannelEverywhere` ([app/web/static/app.js](app/web/static/app.js#L1801)), which computes
the affected findings with `findingsStrandedBy` ([L1684](app/web/static/app.js#L1684)), asks with a
`vrDialog` confirmation, then **deletes** — `dropTargetsEverywhere`
([L1754](app/web/static/app.js#L1754)) removes the targets and strips them from every finding's
scope. The server-side half is the survivor loop inside `reconcile_targets`
([app/report_service.py](app/report_service.py#L542)), which drops dangling `target_ids` rather
than refusing the save.

But that is not the only precedent, and the two point in opposite directions:

- **Purge, with a confirmation** — the app-type/scope path above.
- **Keep, and never repair** — `sync_evidence_image_slots` removes a slot only when it is both
  unreachable *and* empty; an uploaded screenshot is never deleted and never relabelled
  ([app/report_service.py](app/report_service.py#L357)). The same instinct governs
  `non_production_label`, where widening the field to free text deliberately shipped **no**
  `load_path` repair (DATA_MAP §6).
- **Carry out of sight** — `provision`'s `carried` list, §2 above.

The planner should treat "what happens to Asia data when the segment stops being Asia" as an open
choice between these three, not as settled.

### 4. How a content section renders in the editor

**There is no section markup in the template.** [app/web/templates/page2_editor.html](app/web/templates/page2_editor.html)
is a single-line document supplying only `<main id="editor" data-report=… data-library=…>`,
`<aside id="finding-nav">`, `<div id="finding-editor">` and the review panel. Searching it for
`content-block`, `content-toggle` or `fragment` returns nothing. Every section is built in
JavaScript, which means the whole of this change's UI lives in `app.js` and the stylesheets.

`buildContentBlock(content)` — [app/web/static/app.js](app/web/static/app.js#L3930-L3995) — is the
one builder. Its chrome, in order:

1. `div.content-block`, plus `is-expanded` when open, carrying `dataset.contentType`.
2. `button.content-toggle` with `aria-expanded`, whose innerHTML is exactly
   `<span>{name}</span><span class="content-flag" aria-hidden="true" hidden></span><small>N fragment(s)</small>`
   ([L3939](app/web/static/app.js#L3939)). Its `onclick` measures the block's offset inside the
   pane, re-renders, then restores that offset twice (once synchronously, once in a
   `requestAnimationFrame`) because autosizing children grow a frame later.
3. **Collapsed blocks return here** — a collapsed section renders the toggle and nothing else.
4. Expanded: `contentOffersFor(finding, content)` banner nodes, appended as **direct children**.
5. Then either a `p.content-locked` notice (the resolved-remediation special case, and it also
   suppresses the Add menu) or the fragment cards, with consecutive `image` fragments grouped into
   one `renderEvidenceSet`.
6. Then `select.add-fragment`, whose options come from `allowed[content.type]`
   ([L3962](app/web/static/app.js#L3962)).

Three module-scope maps are keyed by `ContentType` and all three must be fed for a section to work:
`contentNames` ([L118](app/web/static/app.js#L118)) — the heading text, which prints `undefined` if
missing; `allowed` ([L119](app/web/static/app.js#L119)) — **a missing key throws a `TypeError` in
`appendFragmentMenu`**; `requiresFragment` ([L121](app/web/static/app.js#L121)) — the never-empty
set.

`renderFragment` ([L3049](app/web/static/app.js#L3049)) gives every fragment
`article.fragment[data-fragment-id][tabindex=-1]` containing `div.fragment-head` with, in DOM order:
`button.fragment-drag-handle`, `span.tag`, an optional `select.fragment-convert`,
`button.fragment-move-up`, `button.fragment-move-down`, `button.danger.fragment-delete`. The rich
toolbar and the list `label.list-continue` are **moved into** that head after `.tag`
([L3135](app/web/static/app.js#L3135), [L3166](app/web/static/app.js#L3166)).

**The fragment body is chosen by which payload key is present, not by `type`** —
`if (fragment.runs) … else if (fragment.items) … else if (fragment.type === "table")`
([L3132](app/web/static/app.js#L3132)). DATA_MAP §12 records this as load-bearing.

Textarea behaviour and autosize, precisely:

- Rich text (`rich()`, [L979](app/web/static/app.js#L979)) is a `div.rich[contenteditable]` with
  `role="textbox" aria-multiline="true"`, an optional `.toolbar`, and the placeholder carried as
  `data-placeholder` + `aria-label`. Autosize is `style.height = "auto"` then `= scrollHeight`,
  re-run on `input`, on paste (inside a `requestAnimationFrame`), on `document.fonts.ready`, and on
  every width change via `observeWidth`. The placeholder is painted by CSS `.rich:empty::before`
  ([taste.css L2654](app/web/static/taste.css#L2654)).
- Lists ([L3144](app/web/static/app.js#L3144)) are `div.list-text-editor` wrapping
  `div.list-gutter`, `textarea.list-textarea` and `div.list-line-measure`, with
  `placeholder="One item per line"`, `rows=1`, and autosize `Math.max(34, scrollHeight)` driven by
  `oninput` and a `ResizeObserver`.
- Table cells ([L3246](app/web/static/app.js#L3246)) use `textarea.table-cell-input`, `rows=1`, and
  size the whole row to the tallest cell.
- Setup is the only page with plain `<input>` fields; every Content-page text body is either a
  contenteditable `.rich` or a `<textarea>`. **There is no single-line text control on the Content
  page today.**

**What "in sync" means concretely.** The section styling is *positional*, keyed to `.content-block`
and its immediate children, and it is duplicated across two stylesheets that both load (taste.css
last, so it wins):

| Selector | taste.css | overrides.css |
|---|---|---|
| `.content-block` — `display:grid`, `align-content:start`, `overflow:clip`, 1px border, `--radius-sm`, `--surface-raised` | [L1344](app/web/static/taste.css#L1344), [L3055](app/web/static/taste.css#L3055) | [L240](app/web/static/overrides.css#L240) |
| `.content-block > .content-toggle` — full width, bottom border, `--canvas-deep` | [L1355](app/web/static/taste.css#L1355), [L3063](app/web/static/taste.css#L3063) | [L241](app/web/static/overrides.css#L241) |
| `.content-block > *:not(.content-toggle)` — `margin-inline: 13px`, the inset that sets every child's width | [L1367](app/web/static/taste.css#L1367) | — |
| `.content-block > .content-toggle + *` — `margin-top: 11px` | [L1371](app/web/static/taste.css#L1371) | — |
| `.content-block > :last-child` — `margin-bottom: 12px` | [L1375](app/web/static/taste.css#L1375) | — |
| `.content-block > .add-fragment` — `width:auto` because the margins already set the width | [L1380](app/web/static/taste.css#L1380) | [L266](app/web/static/overrides.css#L266) |
| `.content-row` — 2-column grid, `gap:13px`, collapsing to one column under a 900px **container** query on `.finding-card` | [L1564](app/web/static/taste.css#L1564), [L3039](app/web/static/taste.css#L3039) | — |
| `.content-flag` — the red "N to fill in" pill, `margin-inline:auto`; `[hidden]` re-declared because nothing else reinstates it | [L3081](app/web/static/taste.css#L3081) | — |
| `.fragment`, `.fragment-head` — head children all sized to a 20px square and revealed only on `:hover`/`:focus-within` | [L1614](app/web/static/taste.css#L1614), [L1627](app/web/static/taste.css#L1627), [L2551-L2640](app/web/static/taste.css#L2551) | [L246-L248](app/web/static/overrides.css#L246) |
| `.rich`, `.list-textarea` | [L439](app/web/static/taste.css#L439), [L517](app/web/static/taste.css#L517), [L1548](app/web/static/taste.css#L1548) | [L260](app/web/static/overrides.css#L260), [L264](app/web/static/overrides.css#L264) |

So "in sync" has an exact meaning here: a new section is in sync if it is a `div.content-block`
carrying `data-content-type`, headed by a `button.content-toggle` with the same three-child
innerHTML, whose remaining children are **direct** children (any wrapper element loses the
`margin-inline`, the heading gap and the last-child gap in one stroke), and whose text inputs use
the existing `.rich` / `.list-textarea` / `.table-cell-input` classes so they pick up the
hover/focus rules at [taste.css L1548-L1561](app/web/static/taste.css#L1548). DATA_MAP §12 already
records why a wrapper was rejected for the offer banners: *"There is no wrapper element ... a
permanent slot would cost every section its heading gap."*

Two further couplings a new block inherits automatically by carrying `data-content-type`:
`updateReadinessPanel` walks `pane.querySelectorAll("[data-content-type]")` to set the
`.content-flag` count ([L3481-L3487](app/web/static/app.js#L3481)), and `refreshContentOffers`
walks `.content-block.is-expanded` to rebuild banners
([L3617-L3630](app/web/static/app.js#L3617)).

### 5. Validation

**Python.** [app/report_service.py](app/report_service.py#L58):

```python
def invalid_character_issue(label: str, value: str, symbols: str, *,
                            allow_numbers: bool = True, allow_spaces: bool = True,
                            allow_line_breaks: bool = False) -> str | None
```

The allowlist is expressed as **a string of extra symbols**, and the real test is in
`_invalid_characters` ([L34-L56](app/report_service.py#L34)):

```python
if not (character.isalpha()
        or (allow_numbers and character.isdecimal())
        or character in symbols
        or character in spacing)
```

**Letters are allowed unconditionally.** `character.isalpha()` sits outside every flag, and there is
no `allow_letters` parameter. That means **"digits and period only" cannot be expressed with this
helper as it stands** — a CVSS Score rule needs either a new keyword argument or a separate check.
It also means both allowlists are Unicode-wide (`isalpha`/`isdecimal`), which is why the JavaScript
twins use `\p{L}` and `\p{Nd}` rather than `A-Za-z0-9`.

Single-line is enforced by the **default** `allow_line_breaks=False`: `\r` and `\n` simply fall
through as invalid characters and are named from `CHARACTER_NAMES`
([L22-L32](app/report_service.py#L22)) in the message. Only Limitations opts into line breaks
([L138](app/report_service.py#L138)). There is no separate length or line-count check anywhere.

Where it runs: `setup_input_issues(engagement)` ([L112](app/report_service.py#L112)) — **engagement
fields only** — and once inside `reconcile_targets` for component scope
([L604](app/report_service.py#L604)). **Nothing inside `contents` is character-validated anywhere
in the app.** The enforcement point is `save_report`, which returns 422 `invalid_setup`
([app/main.py](app/main.py#L687-L694)); it runs at save, never at load.

**JavaScript.** [app/web/static/app.js](app/web/static/app.js#L1445):

```js
const characterRule = (label, allowed) => {
  const invalidCharacters = value => [...new Set([...value].filter(c => !allowed.test(c)))];
  return {label, invalidCharacters, valid: value => !invalidCharacters(value).length};
};
```

Here the allowlist is **a regex matched against one character at a time**, e.g.
`characterRule("Limitations", /^[\p{L}\p{Nd} /,.;:()&'"\-\r\n]$/u)`. Line breaks are allowed by
listing `\r\n` in the class — the mirror of `allow_line_breaks=True`. `setupRules`
([L1462-L1475](app/web/static/app.js#L1462)) maps field name to rule; `wireSetupRule`
([L1488](app/web/static/app.js#L1488)) attaches it, calling `setCustomValidity`, setting
`aria-invalid` and the `.validation-error` class on `input` and `change`.

The two stay in step **by hand, with one drift guard**. Message parity needs three mirrored pieces:
`characterNames` ([L1439](app/web/static/app.js#L1439)) mirroring `CHARACTER_NAMES`,
`invalidCharacterMessage` ([L1444](app/web/static/app.js#L1444)) mirroring the Python f-string, and
`digitNames` ([L1442](app/web/static/app.js#L1442)) existing only because Python's
`unicodedata.name("3")` yields `DIGIT THREE`. DATA_MAP §12 names
`tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save` as the one
test asserting the browser's `validationMessage` is byte-identical to the server's issue string.

**The blocker nobody has hit yet:** `characterRule`, `setupRules`, `characterNames`,
`characterName`, `invalidCharacterMessage`, `wireSetupRule` and `showRuleState` are **all declared
inside `function setup()`**, which spans [L1432](app/web/static/app.js#L1432) to
[L3344](app/web/static/app.js#L3344). `continuousEditor()` begins at
[L3345](app/web/static/app.js#L3345), and the bottom of the file dispatches
`root.id === "setup" ? setup() : continuousEditor()`. **None of the character-rule machinery is
reachable from the Content page today.** Validating a Content-page field means hoisting that block
to module scope first — a real refactor of a function the Setup page's validation depends on.

### 6. Completeness and gating

Three independent gates, all server-owned at the route level:

1. **Setup** — `setup_issues` / `setup_is_complete`
   ([app/report_service.py](app/report_service.py#L649), [L682](app/report_service.py#L682)).
   `/findings` and `/edit` both `303` back to Setup when it fails
   ([app/main.py](app/main.py#L633), [L642](app/main.py#L642)).
2. **Findings** — `finding_is_complete(vulnerability, report)`
   ([app/report_service.py](app/report_service.py#L707)) is title, likelihood, impact, severity,
   status and `scope_has_location`. **It does not look at `contents` at all.** `/edit` redirects to
   `/findings` if any finding fails ([app/main.py](app/main.py#L644)).
3. **Generation** — `generation_issues(report)`
   ([app/docx_report.py](app/docx_report.py#L94)) is the only gate that reads content. It is
   re-run by the generate route ([app/main.py](app/main.py#L515)) and by `render_report_docx`
   itself.

Inside `generation_issues`, the section filter is
[app/docx_report.py](app/docx_report.py#L110-L114):

```python
printed = set(content_types_for_status(finding.status))
for content in finding.contents:
    if content.type not in printed:
        continue
```

so **a section no status prints is already exempt from every completeness judgement**. That is the
cheapest route to "never blocks generation" and it already exists.

What is *not* exempt: within a printed section, the per-fragment rules at
[L124-L145](app/docx_report.py#L124) fire on an empty paragraph or note (`text is required`), a
blank list item, an image missing environment/evidence/caption, empty code text, any blank table
cell, and any placeholder text. `requiresFragment` — `{description, recommended_remediation,
in_conclusion}` at [L116](app/docx_report.py#L116) — additionally demands at least one fragment.

**So the "never required" guarantee cannot be met by putting empty fragments into a printed
section.** A blank paragraph in a printed section is a generation error today. The options the
source leaves open are: keep the section out of `content_types_for_status`'s return; carry the
values somewhere other than `contents`; or add an explicit exemption in **both**
`generation_issues` and the client's `fragmentIssues`.

The client twin is `updateReadinessPanel` / `fragmentIssues`
([app/web/static/app.js](app/web/static/app.js#L3369-L3430)). It applies the same `printed` filter
at [L3384](app/web/static/app.js#L3384). Its output drives three things at once: the
`#issue-count` badge and its `data-state`, the per-section `.content-flag` counts, and
**`#generate-report`'s `disabled`** ([L3489-L3493](app/web/static/app.js#L3489)). Library offers
are deliberately listed as `level:"warning"` and **not counted**, precisely so the badge and the
Generate button cannot disagree with the server — that is the existing pattern for
"visible but never blocking".

Navigation between pages is gated by the routes, not by JavaScript; the browser's own
`validateSetupPage` / `validateFindingsPage` only pre-empt the redirect.

### 7. Reading contents at generation time

`_render_finding_component` ([app/docx_report.py](app/docx_report.py#L745)) is where a finding's
contents become document content. Three distinct mechanisms live side by side there:

**a. Scalar tokens.** A flat dict at [L759-L765](app/docx_report.py#L759):

```python
values = {"finding_title": …, "vuln_severity": …, "vuln_id": …, "status": …,
          "severity-review-tickets": "N/A"}
for token, value in values.items():
    replace_component_token(elements, token, value)
```

`replace_component_token` ([app/docx_components.py](app/docx_components.py#L72)) is a regex replace
that **silently no-ops when the token is absent**. That is why `severity-review-tickets` can be
supplied for every finding while only `retest_finding.docx` carries the token — the `new_finding.docx`
path just does nothing with it. Corroborating evidence that the label is printed today:
`docx_import.BOILERPLATE` ([app/docx_import.py](app/docx_import.py#L47-L50)) contains the literal
`"Severity Review Ticket (if applicable):"`, and `_build_fragments` drops that paragraph on import
([L243-L244](app/docx_import.py#L243)). Confirming the template itself is the Scribe's job.

**b. Section anchors.** [L774-L784](app/docx_report.py#L774):

```python
contents = {content.type: content for content in finding.contents}
anchors = {"description-fragments-here": contents.get("description"), …}
if finding.status != "open_new":
    anchors.update({"prev-poc-fragments-here": …, "conclusion-fragments-here": …})
```

**A section that may be absent is already handled, twice over:** `contents.get(...)` yields `None`,
and `_render_component_content` accepts `Content | None`. The `status != "open_new"` branch is the
existing precedent for "this anchor only exists in some templates".

**c. The Asia CVSS table.** `{{cvss-score}}` and `{{cvss-vector}}` are **not** finding-template
tokens. They are cells 3 and 4 of the Asia-only table named `Section`, filled by
`_populate_cvss_table` ([app/docx_report.py](app/docx_report.py#L607)) from the
`list[tuple[Vulnerability, str]]` that `_populate_component_findings` returns. Today both are set
to the empty string at [L622-L623](app/docx_report.py#L622), under the comment *"CVSS score and
vector are tester inputs the app does not collect yet."* The function **already holds the
`Vulnerability`**, so reading a value off the finding is a one-line change there. `_optional_table`
returning `None` ([L610-L612](app/docx_report.py#L610)) is what makes this Asia-only without ever
consulting `engagement.segment`.

Two constraints on that table: `_replace_cell_placeholder` raises
`ReportGenerationError` unless the cell contains **exactly one** `{{…}}` paragraph
([app/docx_report.py](app/docx_report.py#L325-L327)), and `_unresolved_placeholders`
([L1480](app/docx_report.py#L1480)) raises if any `{{…}}` survives anywhere in the document,
including headers and footers. So a token added to a template must be filled on every path that
uses that template.

### 8. What this adds to `docs/DATA_MAP.md` §12

New rows, each needing a Python owner and a JavaScript twin:

| Rule | Why it must be twinned |
|---|---|
| CVSS Score allowlist | the browser must block what the server 422s, or the save fails with no preceding message |
| CVSS Vector allowlist | same |
| Severity Review Tickets line cleaning, if it gets any | compare the existing `location_lines` / `locationLines` row |
| Field visibility by segment × status | `provision` decides what exists, `buildContentBlock` decides what shows; they cannot disagree |
| Section visibility derived from field visibility | the *Answers* section makes this one rule; it will still have two implementations |

Existing rows this change modifies rather than adds:

- **"status to section list"** (`content_types_for_status` ↔ `contentTypesForStatus`) gains a second
  axis. The JavaScript twin is called from four places — `provision`, the readiness panel, the
  editor's section render, and the status `onchange` — so a signature change touches all four.
- **"a printed section that must never be empty"** (`generation_issues`'s set ↔ `requiresFragment`)
  needs the new section named as exempt on both sides, or it will block generation.
- **"generation readiness"** (`generation_issues` ↔ `updateReadinessPanel`/`fragmentIssues`) — this
  is the pair the only contract test covers,
  `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`.
- Python's `required_fragments` ↔ the JavaScript `required` seeding dict.

DATA_MAP §6 will also need the new `ContentType` member recorded, and §7 the changed `provision`
behaviour.

### 9. Where a sixth `ContentType` member bites

I checked every site that writes the five names out. Ordered by severity:

1. **`docx_import._findings` builds `contents` as a literal five-element list and then indexes it
   positionally.** [app/docx_import.py](app/docx_import.py#L476-L485): the list is built with
   `proof_of_concept` third, and then `contents[3]["fragments"] = _empty_proof(scope, targets)`.
   **Appending a sixth entry is safe; inserting one anywhere before index 3 silently writes the
   fresh proof-of-concept fragments into the wrong section**, with no error. This is the only
   positional assumption about content order in the codebase.
2. **`docx_import.SECTION_HEADINGS`** ([app/docx_import.py](app/docx_import.py#L39-L45)) is an
   ordered tuple matched on exact paragraph text, with a comment at
   [L35-L38](app/docx_import.py#L35) explaining that `Previous Proof of Concept:` must precede
   `Proof of Concept:` or the substring match finds the wrong one. If the new section prints a
   heading in the document, it needs a row here or its content is absorbed into whichever section
   precedes it. If it prints *inside an existing table* (which the CVSS pair does), the importer
   never sees it at all and the values are lost on a retest round trip. Also note
   [L468-L470](app/docx_import.py#L468): import **raises** `ReportImportError` when
   `description`, `recommended_remediation` or `proof_of_concept` is missing — that hard-coded
   triple is the closest thing to an exhaustive check on the import path.
3. **`allowed[content.type]`** ([app/web/static/app.js](app/web/static/app.js#L119), read at
   [L3962](app/web/static/app.js#L3962)) — a missing key throws `TypeError: Cannot read properties
   of undefined (reading 'map')` and kills the render. `contentNames`
   ([L118](app/web/static/app.js#L118)) fails more softly, printing `undefined` as the heading.
4. **`report_service.provision`'s bare `next()`** for `recommended_remediation`
   ([app/report_service.py](app/report_service.py#L233)) — unaffected by an added type, but it is
   the pattern to avoid copying.
5. **The readiness panel's section order array** — `order` at
   [app/web/static/app.js](app/web/static/app.js#L3455) is a hardcoded five-element list used for
   ranking; an unknown type gets rank `-1` and sorts **above** everything else.
   `typeByLabel` ([L3474](app/web/static/app.js#L3474)) is derived from `contentNames`, so it
   follows automatically.
6. **Stored drafts are safe.** `ContentType` is a `Literal`, so widening it is permissive: every
   draft on disk still validates, and `Content` is only ever constructed from data.
   `content_offer_resolved` and `content_offer_dismissed` are typed `dict[ContentType, StableId]`
   ([app/models.py](app/models.py#L216), [L219](app/models.py#L219)) and widen with it, so no
   migration is needed. `validate_references`'s per-finding uniqueness check
   ([L384](app/models.py#L384)) is set-based and needs nothing.
   **The one-way door:** once any draft stores a section with the new type, removing the member
   from the `Literal` makes that draft unloadable — the same shape as the
   `non_production_label` widening recorded in DATA_MAP §6.
7. **Nothing back-fills existing drafts.** `provision` never runs on load or on import (§2), so a
   report saved before this change gains the new section on its **next PUT** and not before. Any
   code reading the new section must use `next(..., None)` or `.get(...)`.
8. **No exhaustive check exists that would fail loudly.** `generation_issues`, `provision`'s
   `required_fragments`, and `_render_finding_component`'s `anchors` all skip unknown types
   silently. There is no `match`/`assert_never` anywhere. That cuts both ways: nothing breaks, and
   nothing tells you a site was missed.
9. **Tests.** None asserts the exact five-member set. The closest are
   `tests/test_browser.py` L3483, which iterates every `.content-block` on the page and toggles it
   (so a new section is exercised automatically), L3354 and `tests/test_app.py` L1239-L1240, which
   assert `in_conclusion` is absent after a status change.

### Map drift

None found. Every §6, §7 and §12 claim I checked against source held: `content_types_for_status` is
still the single owner, the carry-work rule and the `in_conclusion` exception read as documented,
`provision` runs only from PUT and library insert, and the `requiresFragment` triple is correct.
`docs/DATA_MAP.md` is unchanged by this report.

Two things §12 does not yet say, which are facts rather than corrections, and which the planner
needs:

- The character-rule helpers are scoped inside `function setup()` and are unreachable from the
  Content page.
- `invalid_character_issue` allows letters unconditionally and has no flag to disallow them.

## Round 1 - Scribe: the document side

Read out of `app/`, `tests/` and `docs/` on 2026-09-18. The `.docx` files cannot be opened on this
machine, so every claim about a template's own contents is backed by one of three things, named
where it is used: **a test that passes today**, **the fact that generation succeeds today** (any
`{{…}}` left in a rendered document fails the render, so a token's absence is provable), or the text
conversions under `graphify-out/converted/`, which are derived artifacts and the weakest evidence of
the three. Nothing here is taken from a plan document.

### 1. `{{severity-review-tickets}}` today

**The mechanism.** [app/docx_report.py](app/docx_report.py#L759-L767), inside
`_render_finding_component` ([L745](app/docx_report.py#L745)):

```python
values = {"finding_title": …, "vuln_severity": …, "vuln_id": …, "status": …,
          "severity-review-tickets": "N/A"}          # L764
for token, value in values.items():
    replace_component_token(elements, token, value)
```

`replace_component_token` ([app/docx_components.py](app/docx_components.py#L72)) delegates to
`_replace_token` ([L390](app/docx_components.py#L390)), which compiles
`\{\{\s*severity-review-tickets\s*\}\}` case-insensitively and hands every paragraph in the cloned
component to `replace_pattern_across_text_nodes` ([L402](app/docx_components.py#L402)). That
function walks the paragraph's `w:t` nodes, finds the match **across split runs**, and writes

```python
nodes[start_index].text = prefix + replacement + (suffix if start_index == end_index else "")   # L428
```

— the value goes into the **existing text node of the run the token was authored in**. No run is
created, no paragraph is created, and nothing is removed. It searches every element it is given and
silently does nothing where the token is absent, which is why the same `values` loop runs for
`new_finding.docx` without effect.

**Where the token sits: its own paragraph, immediately below the label paragraph.** Document order
in `resources/finding_types/retest_finding.docx`, from
[graphify-out/converted/retest_finding_7b5835eb.md](graphify-out/converted/retest_finding_7b5835eb.md):

```
In Conclusion:
{{conclusion-fragments-here}}

Severity Review Ticket (if applicable):
{{severity-review-tickets}}
```

It is the **last paragraph of the finding component**. Two tests make this more than a conversion
artifact:

- [tests/test_docx.py](tests/test_docx.py#L830) does
  `next(item for item in document.paragraphs if item.text.strip() == "Severity Review Ticket (if applicable):")`
  on a *rendered* retest finding. python-docx's `Paragraph.text` concatenates every run, rendering
  `w:br` as `\n`, so if the token shared the label's paragraph — inline **or** separated by a soft
  break — that paragraph's text would read `…(if applicable): N/A` or `…(if applicable):\nN/A` and
  the `next()` would raise `StopIteration`. It passes, so **the label owns its paragraph and the
  token owns the next one**.
- [tests/test_docx.py](tests/test_docx.py#L247-L263) counts blank paragraphs above that same label
  and asserts at most one, so there is a single blank between `{{conclusion-fragments-here}}` and
  the label, and none between the label and the token.

This matters more than anything else in section 2: **the premise of the request's hard case does not
hold.** The anchor is not inline in a sentence, so the destructive option (replacing the whole
paragraph) is available as well as the safe one.

**Corroborating that the label prints today:** `docx_import.BOILERPLATE`
([app/docx_import.py](app/docx_import.py#L47-L50)) carries the literal string, and the token has no
`-fragments-here` anchor, which is why it is the named scope-out in the `keepNext` work
([app/docx_report.py](app/docx_report.py#L1348), [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L206)).

**The token exists in exactly one component.** `severity-review-tickets` does not appear in
`new_finding.docx` (no match in the conversions; corroborated by
[docs/plans/import-docx-as-retest-draft.md](docs/plans/import-docx-as-retest-draft.md#L158)), and it
cannot appear in any main template: the `values` loop only touches finding-component elements, so a
copy in `MAIN*.docx` would survive to `_unresolved_placeholders` and fail every render.

### 2. Multi-line output at that anchor — the part that matters

**What the pipeline does with `\n` on the path this token uses today: nothing, and the newline is
not a line break.** `replace_pattern_across_text_nodes` writes the string verbatim into one `w:t`
node ([L428](app/docx_components.py#L428)). There is no `\n` → `w:br` conversion anywhere on that
path. `_preserve_text_spaces` ([app/docx_components.py](app/docx_components.py#L647-L650)) only sets
`xml:space="preserve"` when the value *begins or ends* with whitespace, so an interior newline is not
even protected from XML whitespace normalisation. In WordprocessingML a line break inside a paragraph
comes from a `<w:br/>` element or from a paragraph boundary, and from nothing else — so the character
does not render as a line break. **Whether Word shows it as a single space or drops it entirely is
Word's whitespace normalisation, and only Word settles that**; either way it is a flattened single
line, not the requested one-value-per-line.

**The conversion exists, on a different function.** `_set_run_text`
([app/docx_components.py](app/docx_components.py#L548-L559)) normalises `\r\n` and `\r` to `\n`,
splits, and appends a real `<w:br/>` between segments. It is reached only from
`_replace_pattern_with_runs` ([L478](app/docx_components.py#L478)), i.e. only from the **runs**
variants of token replacement — not from `replace_component_token`.

**This is already proven in production.** `_replace_token_with_bullets`
([app/docx_report.py](app/docx_report.py#L696)) feeds
`[Run(text="\n".join(_wrap_long_value(value, LOCATION_WRAP_CHARACTERS)))]` to
`replace_component_token_runs`, and [tests/test_docx.py](tests/test_docx.py#L484) asserts *"a long
location should break once"* by counting `w:br` in the rendered paragraph — with
[tests/test_docx.py](tests/test_docx.py#L243) asserting zero breaks for a short one. The mechanism is
exercised in both directions by tests that run on macOS.

**The options, in order of cost:**

| | Mechanism | Result in Word | Notes |
|---|---|---|---|
| **A** | Drop the key from the `values` dict and call `replace_component_token_runs(elements, "severity-review-tickets", [Run(text="\n".join(lines))])` | one paragraph, real `<w:br/>` between lines | Smallest change. Same silent no-op on `new_finding.docx`: `_replace_pattern_with_runs` returns immediately when the pattern does not match. Formatting inherited — see §6. |
| **B** | One paragraph per line, by `deepcopy`-ing the token's paragraph and removing the original, the shape `_replace_token_with_bullets` uses | one paragraph per value | **Only possible because the token owns its paragraph** — that function deletes the whole paragraph containing the token, which inline would destroy the label. Costs more code and changes vertical rhythm (paragraph spacing per line instead of a break). Cloning `bulleted_fragment.docx` instead would print bullet glyphs, which nobody asked for. |
| **C** | `replace_component_token_runs_with_proofed_breaks` ([app/docx_components.py](app/docx_components.py#L85)) | as A, plus `spellEnd`/break/`spellStart` proofing surgery | **Dead code.** It and `restore_proofed_fragment_breaks` ([L98](app/docx_components.py#L98)) are imported nowhere, called nowhere, and covered by no test. Reviving it needs a reason; A does not require it. |

**Recommendation: A.** And note the answer does not change if the anchor were inline after all — the
`w:br` elements land inside the run that replaces the token, so the label would stay on line 1 with
the remaining values hanging beneath it in the same paragraph. It is **B** that inline would make
impossible.

**A caveat the planner must carry:** the same "no `\n` handling" applies to
`_replace_cell_placeholder` (§3), which goes through `replace_pattern_across_text_nodes` too. **No
table cell in this pipeline can render a line break**, which is consistent with CVSS Score and Vector
being single-line by rule, but means that rule is load-bearing rather than cosmetic.

### 3. `_populate_cvss_table` — per finding, confirmed

[app/docx_report.py](app/docx_report.py#L607-L627), called once from `render_report_docx` at
[L193](app/docx_report.py#L193), after the findings body (so the headings exist to bookmark) and
before `add_native_image_captions` (so its mark-every-field-dirty sweep reaches the `REF` fields this
writes).

```python
table = _optional_table(document, "Section")      # L610
if table is None:
    return                                        # L611-612  <- the Asia gate
prototype = _strip_data_rows(table)               # L613
for finding, bookmark in rendered or []:          # L614
    row = _append_prototype_row(table, prototype) # L615
    severity = finding.severity or "informational"
    _reference_field(row.cells[0].paragraphs[0], bookmark)                    # L617
    _replace_cell_placeholder(row.cells[1], finding.title)                    # L618
    _replace_cell_placeholder(row.cells[2], severity.title(), font_color=…)   # L619
    _replace_cell_placeholder(row.cells[3], "")                               # L622
    _replace_cell_placeholder(row.cells[4], "")                               # L623
if not rendered:                                  # L624-627
    _append_prototype_row(table, prototype)
    for index in range(5):
        _replace_cell_placeholder(table.rows[1].cells[index], "")
```

- **Finding the table.** `_optional_table` ([L345](app/docx_report.py#L345)) wraps `_find_table`
  ([L338](app/docx_report.py#L338)), which scans `document.tables` for the one whose **first header
  cell** casefolds to `section`. Never by index. Absent → `None` → early return. That is the whole
  Asia gate: the function never reads `engagement.segment`, so it stays a function of the template it
  was handed — which is what lets `scripts/` render anything through `MAIN.docx` safely.
- **Cloning.** `_strip_data_rows` ([L366](app/docx_report.py#L366)) `deepcopy`s `table.rows[1]._tr`
  as the prototype and deletes every row after the header. `_append_prototype_row`
  ([L356](app/docx_report.py#L356)) `deepcopy`s that prototype per finding and appends the `w:tr`.
  Its docstring names the alternative that was rejected: stacking values as paragraphs in one cell
  misaligns every row below the first that wraps.
- **Order.** `rendered` is the `list[tuple[Vulnerability, str]]` returned by
  `_populate_component_findings` ([L630](app/docx_report.py#L630)) — severity order, then title
  casefold — consumed rather than re-derived, and pinned by
  `tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`
  ([tests/test_docx.py](tests/test_docx.py#L1101)).

**Columns, in order, with the exact cells:**

| Index | Header | Prototype token | Filled with |
|---|---|---|---|
| `row.cells[0]` | Section | `{{section-number}}` | a Word `REF vuln_<uid> \w \h` field, marked dirty |
| `row.cells[1]` | Vulnerability Name | `{{finding}}` | `finding.title` |
| `row.cells[2]` | Severity | `{{rating}}` | `severity.title()`, recoloured from `RATING_FONT_COLORS` |
| `row.cells[3]` | CVSS Score | `{{cvss-score}}` | `""` today |
| `row.cells[4]` | CVSS Vector | `{{cvss-vector}}` | `""` today |

Header row and prototype row confirmed by
[graphify-out/converted/MAIN_ASIA_b33945bd.md](graphify-out/converted/MAIN_ASIA_b33945bd.md#L185-L187)
and, independently, by the test above asserting `cells[1]`, `cells[2]`, `cells[3]` and `cells[4]` by
index on a real render.

**Answer to the question that decides the schema: yes, per finding.** One row per finding, and the
loop **already holds the `Vulnerability`** — `for finding, bookmark in rendered`. Reading
`finding.cvss_score` / `finding.cvss_vector` there is a two-line change with no signature change and
no report lookup. A report-level field would have to print the same value on every row, which the
table's shape contradicts. **The two new CVSS fields belong on the finding.**

### 4. Where the three tokens appear across the four templates

| Token | `MAIN.docx` | `MAIN_THICK_MOBILE.docx` | `MAIN_ASIA.docx` | `MAIN_THICK_MOBILE_ASIA.docx` |
|---|---|---|---|---|
| `{{cvss-score}}` | absent | absent | once, prototype row of the `Section` table | once, prototype row of the `Section` table |
| `{{cvss-vector}}` | absent | absent | once, same row | once, same row |
| `{{severity-review-tickets}}` | absent | absent | absent | absent (it lives in `retest_finding.docx`) |

**Neither CVSS token appears anywhere else in the two Asia templates — not in a second table, not in
a header or footer — and neither appears at all in the two non-Asia templates. This is provable, not
inferred.** `_unresolved_placeholders` ([app/docx_report.py](app/docx_report.py#L1480-L1485)) scans
`_document_roots` — the body **plus every header and footer part** — for any `{{…}}` and aborts the
render. `_populate_cvss_table` touches nothing but that one table's cloned rows, and
`_replace_metadata` has no CVSS key. So a second copy anywhere in an Asia template would fail every
Asia render; a copy in a non-Asia template would fail every non-Asia render, since the `Section`
table is absent there and the function returns at L612 without writing anything. Asia and non-Asia
renders both succeed today
([tests/test_docx.py](tests/test_docx.py#L1101), [tests/test_docx.py](tests/test_docx.py#L1020)), so
no such copy exists.

**Nothing in the plan needs to handle a non-Asia template carrying these tokens.** The counterpart
risk is the live one: `main_template_path` ([app/docx_report.py](app/docx_report.py#L152-L158))
selects the Asia template from `segment == "Asia"`, while `_populate_cvss_table` selects itself from
the table's presence. Those are two independent implementations of one rule. They agree today, and a
collected CVSS value simply never prints when the chosen template has no `Section` table — including
every fixture rendered through `scripts/`, which hard-code `MAIN.docx`
([docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L23-L24)).

Note also that the words *CVSS Score* appear in a **second, static** table in all four templates
(`Severity | CVSS Score | Impact | Exploitability`, the severity-band reference in the Appendix). It
holds no tokens and is matched by nothing, but `_find_table` keys on the first header cell — `Severity`
versus `Section` — so the two cannot be confused.

### 5. Empty values, and what `_unresolved_placeholders` does

**The existing reasoning still holds, and it is about the token being *consumed*, not about the value
being non-empty.** `_replace_cell_placeholder` ([app/docx_report.py](app/docx_report.py#L313-L328))
requires **exactly one** `{{…}}`-bearing paragraph in the cell and raises
`ReportGenerationError("Expected exactly one placeholder in summary cell; found N")` otherwise; the
replacement it then performs erases the token whether the value is `""` or `"9.8"`. So writing an
empty string is a complete discharge of the obligation.

**What happens if a token is left unreplaced.** `_unresolved_placeholders`
([app/docx_report.py](app/docx_report.py#L1480-L1485)) runs as the **last** step of
`render_report_docx` ([L195-L197](app/docx_report.py#L195)), after captions, over body, headers and
footers. It collects every `{{…}}` by regex plus any of the seven `UNRESOLVED_MARKERS`
([L54-L62](app/docx_report.py#L54)) and raises
`ReportGenerationError(f"Unresolved template placeholders: {…}")`. The whole generation fails; there
is no partial document. `docs/DOCX_TEMPLATE.md` records that this is precisely why `MAIN_ASIA.docx`
was unreachable before the empty-string writes existed
([docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L104-L107)).

**What an empty Severity Review Tickets should write: the literal `N/A`, and that keeps generation
succeeding.** Technically either works — with option A,
`_replace_pattern_with_runs` filters to `source_runs = [r for r in replacement_runs if r.text]`
([L506](app/docx_components.py#L506)), so an all-empty run list erases the token and leaves an empty
paragraph, which satisfies the unresolved check. But `N/A` is what the document prints today
unconditionally, it matches `_display_value` ([app/docx_report.py](app/docx_report.py#L226-L227)) and
`_replace_token_with_bullets`'s own empty branch ([L705-L707](app/docx_report.py#L705)), and it
avoids a stray blank paragraph that the Word pass may then delete (§6). Pass `[Run(text="N/A")]`.

**One new failure mode the planner must close.** `_unresolved_placeholders` scans the *rendered*
document, so it sees tester input as well as template text. A Severity Review Tickets value
containing `{{` … `}}` — a pasted ticket template, say — would abort generation with a message about
"template placeholders" that names the tester's own text. The CVSS pair is safe by construction
(digits/`.` and letters/`/`/`:` allow no braces); **Severity Review Tickets has no proposed allowlist
and is the one exposed field.** Note also that the seven `UNRESOLVED_MARKERS` are substring matches —
a value containing `-vuln` or `-fragments-here` would trip the same check.

### 6. Formatting inheritance, and whether a long value disturbs layout

**CVSS cells.** `_replace_cell_placeholder` passes `font_color=None` and `font_size_pt=None` for
cells 3 and 4, so `replace_pattern_across_text_nodes` writes into the prototype row's own `w:t` node
and **overrides nothing**: font, size, bold and colour are whatever the template author gave that
cell in Word. (Cell 2 is the contrast — it forces the severity colour; the findings summary table
additionally forces 12 pt.) Column widths come from the template's `tblGrid`, which the renderer
never touches, so a long CVSS v3.1 vector (~44 characters) wraps inside its column and grows the row
height. **The app applies no wrapping here** — `_wrap_long_value`
([app/docx_report.py](app/docx_report.py#L379)) is used only for affected locations and the scope
tables, never for these cells. How a full vector actually breaks in that column is a Word layout
question and only Word settles it.

**The tickets paragraph.** Today the value inherits the run containing the token in
`retest_finding.docx`, exactly as above. Under option A, `_replace_pattern_with_runs` takes
`base_run = deepcopy(start_run)` ([L502](app/docx_components.py#L502)) and builds every generated run
from that copy, then layers `_apply_run_formatting` ([L653](app/docx_components.py#L653)) on top.
**That function is additive — it can add bold/italic/underline but never remove them** (which is why
`_unbold_runs_after_first` exists at [app/docx_report.py](app/docx_report.py#L852)). Passing plain
`Run(text=…)` with no flags therefore reproduces the template's own formatting exactly. Neither path
touches `w:pPr`, so paragraph style, alignment and spacing are untouched either way.

**Layout risk of a longer value is low and bounded.** The tickets paragraph is the **last** paragraph
of the finding component, and everything that follows it starts on a fresh page already: every
finding after the first in a severity group gets `pageBreakBefore`
([app/docx_report.py](app/docx_report.py#L671-L677)), as does every severity heading
([L684-L689](app/docx_report.py#L684)). So a taller tickets paragraph cannot shove a later finding's
title around — it can only push **itself** further down, and at worst onto a following page. The one
real consequence: the label carries **no** `w:keepNext` — deliberately, because it has no
`-fragments-here` anchor to walk back from, and that scope-out is pinned by an assertion in
[tests/test_docx.py](tests/test_docx.py#L828-L831). A multi-line value makes that gap more visible,
because Word may now split a list of tickets from the label that introduces it. Whether it does, for
any given report, is a pagination question only Word can answer. If the planner wants it closed, it
is a change to that test plus a `keepNext` on the label — not free, and out of this plan's stated
scope.

**The Word pass does not touch any of this.** `update_docx_fields_with_word`
([app/docx_captions.py](app/docx_captions.py#L45-L97)) repaginates, refreshes fields and tables of
contents/figures, and then runs `_remove_page_leading_blank_paragraphs`
([app/docx_captions.py](app/docx_captions.py#L174-L196)), which deletes **empty** body paragraphs
Word has left alone at the top of a page and skips anything inside a table. A tickets paragraph
holding `N/A` or any text is never a candidate; an *empty* one could be deleted if it happened to
land at a page top — one more reason to write `N/A` rather than nothing.

### 7. Reading it back: both values are lost on import

Not asked, but it is the other half of my territory and it constrains the plan. **Neither value
survives a retest round trip today, and nothing in this change makes it survive.**

- **The CVSS table is never read.** `docx_import._summary_rows`
  ([app/docx_import.py](app/docx_import.py#L344-L358)) reads only the table whose first header cell is
  `Findings`. The `Section` table is not opened by any importer code.
- **The tickets value is collected and then discarded.** The section walker in `_findings`
  ([app/docx_import.py](app/docx_import.py#L455-L470)) switches sections only on a `SECTION_HEADINGS`
  match ([L39-L45](app/docx_import.py#L39)); `Severity Review Ticket (if applicable):` is not one, so
  the label and its value land in `sections["in_conclusion"]`. `_findings` then builds contents from
  `description`, `recommended_remediation` and the document's `proof_of_concept` only, with
  `in_conclusion` hard-coded to `[]` ([L476-L485](app/docx_import.py#L476)). The `BOILERPLATE` entry
  for the label ([L47-L50](app/docx_import.py#L47)) is inert on this path, since `_build_fragments` is
  never called for that section.

Consequence: an imported retest draft starts with all three fields empty, and the delivered document
is not a recoverable source for them. That is probably correct behaviour for tickets (a retest gets
new ones) but it should be a decision, not a discovery. If the planner *wants* tickets to round-trip,
it needs a `SECTION_HEADINGS` row and a consumer — and note the trap the Oracle flagged: `contents`
is built as a positional five-element list and indexed as `contents[3]`
([L485](app/docx_import.py#L485)), so a new entry may only be **appended**.

### 8. `docs/DOCX_TEMPLATE.md` — what goes wrong and what is missing

| Location | Today | Why it breaks |
|---|---|---|
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L104-L107) | "**`{{cvss-score}}` and `{{cvss-vector}}` are replaced with an empty string.** The app does not collect CVSS yet; blank rather than `N/A` so that only the value changes when it does." | Directly contradicted. Becomes: per-finding tester input, collected only when the segment is Asia, written per row; still blank when not supplied — unless the planner decides otherwise, see below. |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L84-L90) | The Section table's columns and row order | Needs the value source named per column, and the statement that the CVSS columns are per finding, not per report. |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L161-L162) | "Finding title, likelihood, impact, severity, ID, status, and affected locations are populated from report data." | **`severity-review-tickets` is documented nowhere in this file** — it appears only as the `keepNext` scope-out at [L206](docs/DOCX_TEMPLATE.md#L206). It needs a row of its own: which component carries it, that it is its own paragraph below the label, that it renders one value per line via `w:br`, and that empty prints `N/A`. |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L201-L210) | The `keepNext` scope-out for the ticket label | Still accurate, but worth one sentence recording that the value is now multi-line, so the uncovered case can strand a list from its label. |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L23-L24) | "The scripts under `scripts/` hard-code `MAIN.docx`" | Still true; worth noting that collected CVSS values therefore never appear in scripted fixtures. |

I have not edited that file — it should change in the same commit as the code, not ahead of it.

### 9. Tests that this change will move

All three run on macOS.

- **`tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`**
  ([tests/test_docx.py](tests/test_docx.py#L1117-L1118)) asserts
  `{row.cells[3].text} | {row.cells[4].text} == {""}` under the comment *"CVSS is a tester input the
  app does not collect yet."* This assertion must change, and it is the natural place to pin the new
  per-finding behaviour.
- **`tests/test_docx.py::test_section_headings_are_kept_on_the_page_with_the_content_below_them`**
  ([tests/test_docx.py](tests/test_docx.py#L828-L831)) finds the ticket label by exact paragraph text
  and asserts it has no `keepNext`. It keeps passing under option A — but it is the test that breaks
  loudly if anyone makes the token share the label's paragraph, so it is worth knowing it is there.
- **`tests/test_docx_components.py`** ([tests/test_docx_components.py](tests/test_docx_components.py#L67))
  and **`scripts/compose_component_test.py`** ([scripts/compose_component_test.py](scripts/compose_component_test.py#L51))
  both pass `"severity-review-tickets": "N/A"` through `compose_docx_components`, which uses
  `_replace_token` — the **string** path. If the production call moves to
  `replace_component_token_runs`, these two keep exercising the old mechanism, and
  `compose_docx_components` raises `ComponentCompositionError` on any token it is not given
  ([app/docx_components.py](app/docx_components.py#L143-L147)). Neither is a blocker; both are places
  the two mechanisms will quietly differ.

### 10. What only Word can settle

- Whether a multi-line tickets value splits across a page boundary away from its label, for any
  particular report. The label carries no `keepNext` by design, and Word never records automatic page
  breaks in the file, so nothing in this repository can predict it. Rendering a real report on a
  Windows machine is the only answer.
- How a full CVSS v3.1 vector wraps inside the `CVSS Vector` column, and how much the row grows.
- What Word does with the literal `\n` that the current string path would write (space, or nothing).
  Irrelevant if option A is taken, since that path stops being used for this token.

## Round 1 - Planner: proposal and open questions

### Understanding

The app must collect three per-finding values it does not collect today — Severity Review Tickets,
CVSS Score and CVSS Vector — show them on the Content page under a heading called *Additional
Information* whose visibility is derived from which fields are visible, and hand them to token
replacements that already exist. Both reports agree the document side is finished apart from where
the value comes from: `{{severity-review-tickets}}` is a constant, and `{{cvss-score}}` /
`{{cvss-vector}}` are empty strings written into a table whose loop **already holds the
`Vulnerability`**. Nothing is required, so generation must succeed with all three blank.

**The proposal in one line: the three values are scalar fields on `Vulnerability`, not a sixth
`ContentType`, and the Additional Information block is editor chrome with no `Content` behind it.**
That single decision dissolves constraints 3, 4 and 7 rather than mitigating them, because
`provision`, `content_types_for_status`, `generation_issues`, `fragmentIssues`, `allowed`,
`requiresFragment` and `docx_import` all read `contents` and only `contents`. A value that never
enters `contents` is invisible to every one of them, and there is nothing to exempt, nothing to
re-provision and nothing to twin.

### Blast radius

| File | What changes |
|---|---|
| [app/models.py](app/models.py#L199) | three defaulted `str` fields on `Vulnerability`. `ContentType` is **not** touched |
| [app/docx_report.py](app/docx_report.py#L764) | `severity-review-tickets` leaves the `values` dict for `replace_component_token_runs` |
| [app/docx_report.py](app/docx_report.py#L622) | `_populate_cvss_table` reads `finding.cvss_score` / `finding.cvss_vector` off the finding it already has |
| [app/web/static/app.js](app/web/static/app.js#L1432) | six character-rule helpers hoisted out of `setup()` to module scope |
| [app/web/static/app.js](app/web/static/app.js#L3930) | new `additionalInformationFields(finding)` and its block builder; appended after `printedContents`; `expandedContentTypes` seed at [L3770](app/web/static/app.js#L3770) gains the pseudo-type |
| [app/web/static/taste.css](app/web/static/taste.css#L1344) | one field-row rule; the new input class joined to `.evidence-caption`'s selector lists |
| [app/web/static/overrides.css](app/web/static/overrides.css#L271) | the same input class joined to the `.evidence-caption` rule there, or its inset is lost |
| [tests/test_docx.py](tests/test_docx.py#L1117) | the "both CVSS cells are empty" assertion; new tickets line-break and `N/A` tests |
| [tests/test_browser.py](tests/test_browser.py#L3462) | new visibility-matrix test; the Setup parity test must still pass after the hoist |
| [tests/test_app.py](tests/test_app.py) | a pre-change draft still loads, with the three fields defaulted |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §6 the three fields; §12 the visibility rule and why it needs no Python twin |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L104) | the five rows the Scribe listed in its §8 |

**Deliberately unchanged:** [app/report_service.py](app/report_service.py) (unless OQ3 is answered
*server-side*), [app/main.py](app/main.py), [app/docx_import.py](app/docx_import.py),
[app/storage.py](app/storage.py), [app/workspace.py](app/workspace.py). No new route, no new
signature, no migration.

### The three fields on the model

```python
# Tester inputs the document prints, not sections of it: fixed, typed, and never required.
# Defaulted so every draft written before this change still validates unchanged.
severity_review_tickets: str = ""
cvss_score: str = ""
cvss_vector: str = ""
```

Three shape decisions, each with its reason:

- **`cvss_score` is a `str`, not a `float`.** Autosave fires while the tester is still typing, so
  `9.` has to be storable; a float would reject it, and would reformat `9.0`. The request describes a
  character rule ("numbers and period"), not a numeric range, so a string is the honest type. It also
  makes the empty case free — `""` is exactly what `_replace_cell_placeholder` writes today.
- **`severity_review_tickets` is one `str` with newlines, not `list[str]`.** The control is a
  textarea whose value is a string; `engagement.limitations` is the precedent for storing raw
  multi-line text. A list would need a normaliser on both sides to agree on what a blank line means.
  Line cleaning — strip each line, drop blanks — happens **only** at render time in
  [app/docx_report.py](app/docx_report.py), one owner, no JavaScript twin, and the tester's text is
  never rewritten under their caret.
- **All three default to `""`, never `None`.** No `| None` means no third state to reason about, and
  `""` already means "print nothing" on both output paths.

### The nine constraints, answered

**1 — `invalid_character_issue` allows letters unconditionally.** Under my recommendation (OQ3) the
Python side is not asked to express the CVSS rules at all, so the drift cannot start. If the owner
chooses server-side validation, the correct fix is a single keyword argument on
[app/report_service.py](app/report_service.py#L34): `allow_letters: bool = True`, added to the
predicate as `(allow_letters and character.isalpha())`. Defaulted `True`, so every existing caller's
output is byte-identical, and the message stays in one place — which is what the parity test at
`tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save` actually
pins. A separate ad-hoc regex check would create a second message format and break that guarantee.
The two sides then express the same allowlist the way every other pair in this app already does:
Python takes symbols plus flags, JavaScript takes a per-character regex class, with each naming the
other in a comment.

**2 — `characterRule` is trapped inside `setup()`.** Hoist six declarations to module scope, beside
`rich()` at [app/web/static/app.js](app/web/static/app.js#L979): `characterNames`, `digitNames`,
`characterName`, `invalidCharacterMessage`, `characterRule`, `showRuleState`. Leave `setupRules`,
`usernameCharacters`, `componentScopeRule`, `wireSetupRule` and `validateSetupInputs` inside
`setup()` — `wireSetupRule` stamps `data-setup-validated`, which the Setup page's own
`validateSetupInputs` queries, and the Content page must not inherit that. This is a pure move:
`setup()` keeps closing over the same names. The Content page then gets its own three-line wiring
that calls `setCustomValidity` and `showRuleState` without the Setup marker.

**3 — the deciding functions cannot see the engagement.** They no longer need to. Visibility is a
render-time question answered in `buildContentBlock`'s neighbourhood, where `report` is already in
scope and the finding is in hand; `provision(vulnerability)` keeps its signature on both sides, and
`provision_report` is untouched. The `sync_evidence_image_slots(vulnerability, report)` precedent
stays available if Round 2 finds a server-side need, but this design has none.

**4 — "never blocks generation".** This is the constraint that decides the whole design, and the
scalar shape satisfies it structurally rather than by exemption. `generation_issues` iterates
`finding.contents` ([app/docx_report.py](app/docx_report.py#L110-L114)) and its twin `fragmentIssues`
filters the same list ([app/web/static/app.js](app/web/static/app.js#L3384)); a field that is not a
fragment in a `Content` is never reached by either. No new entry in `requiresFragment`, no new
exemption, no risk of the badge and the Generate button disagreeing. **Invariant to assert: a finding
with all three fields empty produces zero issues and leaves `#generate-report` enabled.**

**5 — what happens to data when the segment moves off Asia.** Of the three precedents, **keep and
never repair** — the `sync_evidence_image_slots` / `non_production_label` instinct. Justification
against what the owner would expect: purging exists in the app-type path because a dropped scope
target leaves *dangling `target_ids`* that `validate_references` would reject, so something has to
give; a CVSS string references nothing and dangles nothing, so the cost that justifies a confirmation
dialog is absent. A tester who changes the segment dropdown by mistake and changes it back expects to
find their `9.8` still there, and they will. While the segment is not Asia the value prints nowhere —
`_optional_table` returns `None` and `_populate_cvss_table` returns early
([app/docx_report.py](app/docx_report.py#L610-L612)) — so keeping it cannot leak into a document.
"Carry out of sight" is not actually a third option here: it is a property of `provision`'s `carried`
list, which only exists inside `contents`, and its predicate `content_has_work` would govern whether
a tester's typed CVSS value survived. Note the trap that avoids: as a `Content`, a section holding
only empty fields is **silently dropped on the next save**. The same keep-and-hide rule covers
tickets when a status change makes it invisible.

**6 — positional chrome on `.content-block > *`.** The new block is a real `div.content-block`
carrying `data-content-type="additional_information"`, headed by a `button.content-toggle` with the
same three-child innerHTML, and **every field row is a direct child**. Three details the reports
imply but do not state, which I verified in source and which will bite silently otherwise:
- `.content-block` has **no `gap`** ([app/web/static/taste.css](app/web/static/taste.css#L1344-L1352));
  the spacing between children comes from the child, `.fragment` carrying `margin-bottom: 8px`
  ([taste.css L1614](app/web/static/taste.css#L1614)). A new field row needs its own bottom margin or
  the rows will touch.
- `expandedContentTypes` is seeded from `finding.contents.map(content => content.type)`
  ([app/web/static/app.js](app/web/static/app.js#L3770)), so a pseudo-type is **not** in it and the
  block would render collapsed while every real section is open. The seed needs the pseudo-type.
- The Content page **does** already have a single-line `<input>`: `input.evidence-caption`
  ([app/web/static/app.js](app/web/static/app.js#L2905)), styled in *both* stylesheets
  ([taste.css L1796](app/web/static/taste.css#L1796),
  [overrides.css L271](app/web/static/overrides.css#L271)). That is the control to mirror, and
  mirroring it means touching both files — which is exactly the duplication hazard the Oracle named.

Two couplings the block inherits for free by carrying `data-content-type`, both verified safe:
`updateReadinessPanel` finds no entry for it in `typeByLabel` and leaves its `.content-flag` hidden
([app/web/static/app.js](app/web/static/app.js#L3481-L3487)), and `refreshContentOffers` returns
early on `if (!content)` when no `Content` matches the dataset value
([L3620-L3622](app/web/static/app.js#L3620)). The browser test that toggles **every** `.content-block`
on the page ([tests/test_browser.py](tests/test_browser.py#L3483)) will exercise the new block
automatically wherever its fixture makes it visible, which is a reason to give it a working toggle
rather than a static heading.

**7 — `allowed[content.type]` and `contents[3]`.** Both disappear. No sixth `ContentType` means
`allowed`, `contentNames`, `requiresFragment`, the readiness `order` array
([app/web/static/app.js](app/web/static/app.js#L3455)), `required_fragments`,
`SECTION_HEADINGS` and the positional list at
[app/docx_import.py](app/docx_import.py#L476-L485) are all untouched, and there is no one-way
`Literal` door to walk through.

**8 — switching to `replace_component_token_runs`.** Take the Scribe's option A: drop the
`severity-review-tickets` key from the `values` dict and call
`replace_component_token_runs(elements, "severity-review-tickets", [Run(text=…)])` after the loop,
with `"\n".join(lines)` where `lines` is the value's non-blank stripped lines, falling back to
`[Run(text="N/A")]` when there are none. `_set_run_text`
([app/docx_components.py](app/docx_components.py#L548-L559)) turns each `\n` into a real `<w:br/>`,
which `tests/test_docx.py::test_affected_locations_wrap` already exercises in both directions. The
test that must change is
`tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`
([tests/test_docx.py](tests/test_docx.py#L1117-L1118)) — it asserts `cells[3]` and `cells[4]` are
empty under a comment that this change makes false, and it is the right place to pin the new
per-finding behaviour. Two call sites keep exercising the retired string path and are left alone:
[tests/test_docx_components.py](tests/test_docx_components.py#L67) and
[scripts/compose_component_test.py](scripts/compose_component_test.py#L51) both pass the token
through `compose_docx_components`, which raises on any token it is not given — removing it there
would break them for no gain.

**9 — a tickets value that aborts generation.** Worse than the reports found, and this is my one
genuinely new risk. `_unresolved_placeholders` ([app/docx_report.py](app/docx_report.py#L1480-L1485))
casefolds the whole rendered document and treats seven **bare substrings** as failures, including
`-vuln`. A ticket reference like `SEC-VULN-1234` contains `-vuln` and would abort the render with
*"Unresolved template placeholders: -vuln"*. **No character allowlist can close this**, because
letters and hyphens are precisely what a ticket ID is made of. `{{` and `}}` are the same class of
problem and are closable by an allowlist; the markers are not. See OQ4.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | `clear` | No new mutation path. The three values ride the existing full `PUT /reports/{id}` body, which already carries `saved_at`. Nothing new needs the `X-Report-Saved-At` header. |
| Lost update | `clear` | No new `Workspace` method and no new read-then-write. `save_report`'s existing `save_if_current` under `_locked` covers these fields like every other. |
| Orphan reference | `clear` | The values are opaque strings referencing no `frag_id`, `evidence_id` or `target_id`. This is the fact that makes keep-and-hide safe where the app-type purge was not. |
| Silent stranding | **RISK (accepted)** | A stored CVSS value stops printing when the segment leaves Asia; a stored tickets value stops printing when the status becomes Open (New). Both are silent and both are deliberate — the value is preserved, only its visibility is lost, mirroring an uploaded screenshot in an unreachable evidence slot. The alternative, deleting on a dropdown change, is the worse failure. |
| Schema break | `clear` | Three defaulted `str` fields widen `Vulnerability` permissively. Every `draft.json` on disk still validates, `validate_references` has nothing new to check, and no `load_path` repair is needed. |
| Request/response asymmetry | `clear` **conditional on step 1 landing first** | The fields are declared on the model, so they round-trip. This only holds if the model change ships before the client writes them — otherwise Pydantic's ignore behaviour drops them on the first save and the tester watches their typing vanish on reload. That ordering is the whole reason step 1 is step 1. |
| Rule drift | **RISK (managed)** | The visibility rule has no Python twin, and that is defensible rather than sloppy: the status axis is already enforced by which component is cloned (`{{severity-review-tickets}}` exists only in `retest_finding.docx`) and the segment axis by the `Section` table's presence. The document therefore agrees with the UI *by construction*. But that agreement is implicit and will drift the moment someone adds the token to `new_finding.docx`, so it must be written into DATA_MAP §12 as a rule, not left as a coincidence. The character allowlists are JavaScript-only under OQ3's recommendation, which is asymmetric in the safe direction — the browser blocks more than the server rejects, never less. |
| Navigation trap | `clear` | No field is required (settled in *Answers*), so no gate gains a condition and no page can bounce. |
| Derived-state fight | `clear`, and this is the design's main dividend | `provision` rewrites `vulnerability.contents` wholesale on every PUT and touches no other field on `Vulnerability`. Scalars are outside its reach. Had these been fragments in a `Content`, `provision_report` would have rewritten them on every save and `content_has_work` would have decided whether they survived. |
| Backup exhaustion | `clear` | The fields ride the existing debounced `scheduleSave`; no field triggers its own PUT, so the single `draft.bak.json` is not consumed any faster than today. |
| **New: reserved-substring abort** | **RISK, unclosed** | A tickets value containing `-vuln` or `{{` aborts generation with a message naming the tester's own text. See constraint 9 and OQ4. |

### Plan

- [ ] **Step 1 — Three defaulted fields on `Vulnerability`.**
  [app/models.py](app/models.py#L199): `severity_review_tickets`, `cvss_score`, `cvss_vector`, each
  `str = ""`. Nothing else in this step.
  *Test:* `tests/test_app.py` — load a `draft.json` fixture written without the keys and assert all
  three read `""`, then round-trip a report carrying values through `PUT /reports/{id}` and assert
  the response returns them.
  *Invariant:* no existing draft fails validation, and the server returns every field the client
  sends.

- [ ] **Step 2 — CVSS values reach the Asia table.**
  [app/docx_report.py](app/docx_report.py#L622-L623): `_replace_cell_placeholder(row.cells[3],
  finding.cvss_score)` and `cells[4], finding.cvss_vector`, replacing the two `""` literals and the
  comment above them.
  *Test:* rewrite `tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`
  ([tests/test_docx.py](tests/test_docx.py#L1117)) to assert the stored values land in those cells,
  and keep one finding with both blank asserting the cells render empty.
  *Invariant:* a non-Asia render is byte-identical — `_optional_table` still returns `None` and the
  function still returns before touching anything.

- [ ] **Step 3 — Tickets print one value per line.**
  [app/docx_report.py](app/docx_report.py#L764): remove the key from `values`, add a
  `replace_component_token_runs` call with the cleaned lines joined by `\n`, falling back to `N/A`.
  *Test:* `tests/test_docx.py` — a retest finding with two ticket lines renders one paragraph
  containing exactly one `w:br` (count them as
  `tests/test_docx.py::test_affected_locations_wrap` does); an empty value renders `N/A`; an
  Open (New) finding renders unchanged.
  *Invariant:*
  `test_section_headings_are_kept_on_the_page_with_the_content_below_them`
  ([tests/test_docx.py](tests/test_docx.py#L828)) still finds the label paragraph by exact text —
  the value must never merge into the label's paragraph.

- [ ] **Step 4 — Hoist the character-rule helpers to module scope.**
  [app/web/static/app.js](app/web/static/app.js#L1439-L1450): move `characterNames`, `digitNames`,
  `characterName`, `invalidCharacterMessage`, `characterRule` and `showRuleState` above
  `function setup()`. Move only; change no behaviour.
  *Test:* `tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save`
  must still pass unchanged — it is the one test asserting the browser's `validationMessage` is
  byte-identical to the server's issue string.
  *Invariant:* Setup validation is unaltered in message, timing and `data-setup-validated` marking.

- [ ] **Step 5 — The Additional Information block.**
  [app/web/static/app.js](app/web/static/app.js#L3930): `additionalInformationFields(finding)`
  returning the visible descriptors from `report.engagement.segment` and `finding.status` per the
  *Answers* matrix; a builder producing `div.content-block[data-content-type="additional_information"]`
  with the standard toggle and **direct-child** field rows; appended to `box` after the
  `printedContents.forEach` loop, and only when the descriptor list is non-empty; the
  `expandedContentTypes` seed at [L3770](app/web/static/app.js#L3770) gains the pseudo-type. Each
  field writes straight to the finding and calls `scheduleSave()`, exactly as
  `input.evidence-caption` does at [L2910](app/web/static/app.js#L2910). CVSS Score and Vector carry
  `characterRule` validation wired to `setCustomValidity` + `showRuleState`.
  *Test:* `tests/test_browser.py` — the five visible cells and the one hidden cell of the *Answers*
  matrix; a typed value survives a reload; and with all three fields empty `#issue-count` reads
  `Ready` and `#generate-report` is enabled.
  *Invariant:* `updateReadinessPanel` and `refreshContentOffers` both tolerate a `[data-content-type]`
  block with no backing `Content`, and the Generate button never disables because of this section.

- [ ] **Step 6 — Styling in sync.**
  [app/web/static/taste.css](app/web/static/taste.css#L1344): a field-row rule carrying
  `margin-bottom: 8px` to match `.fragment`, and the new input class added to `.evidence-caption`'s
  selector lists; the same class added at
  [app/web/static/overrides.css](app/web/static/overrides.css#L271).
  *Test:* none — CSS is exempt under the repo's scope map. Verification is a screenshot of the new
  block beside an existing section with the computed `margin-inline`, `margin-top` and
  `margin-bottom` of each direct child read out of the page and diffed numerically, per the visual
  rule in `.github/copilot-instructions.md`.
  *Invariant:* every direct child of the block reports `margin-inline: 13px`, the first reports
  `margin-top: 11px`, and the last reports `margin-bottom: 12px`.

- [ ] **Step 7 — Documentation, in the same change.**
  [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 gains the three fields and §12 gains the visibility rule
  with the note that its document-side enforcement is what makes a Python twin unnecessary;
  [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) takes the five rows from the Scribe's §8; this plan
  file's status line moves to `shipped` with the deviations paragraph.
  *Test:* none.
  *Invariant:* no claim in either document contradicts the code shipped in steps 1–6.

**Why this order.** Step 1 alone is inert. Steps 2 and 3 are observable with every value still empty,
so they can be verified against the document before any UI exists. Step 4 is a pure move that must
land before step 5 can use it. Step 5 is the first step that writes a value, and by then the field
exists on the model — so there is no window in which the browser sends a key the server drops.

### What I would not do

**I would not make Additional Information a sixth `ContentType`.** It is the tempting shortcut,
because `buildContentBlock` already exists and would give the section for free. It would cost:
`content_types_for_status` gaining a second axis and therefore `provision(vulnerability, report)` on
both sides plus its four JavaScript call sites; entries in `allowed`, `contentNames`,
`requiresFragment`, `required_fragments` and the readiness `order` array; a matched exemption in
`generation_issues` **and** `fragmentIssues` or the section blocks generation the moment it is empty;
a row in `docx_import.SECTION_HEADINGS` and care around the positional `contents[3]`; and a one-way
`Literal` door that makes any later retreat unloadable for drafts already on disk. Worst of all, it
would put the tester's typed CVSS value under `provision`'s carry rule, where a section holding only
empty fields is **silently dropped on the next save** — a data-loss path invented to solve a layout
problem.

**I would not purge the CVSS values when the segment leaves Asia.** The app-type purge exists because
dangling `target_ids` break `validate_references`; a string breaks nothing, prints nowhere while the
template has no `Section` table, and a confirmation dialog on a dropdown the tester may have
mis-clicked buys a risk it does not remove.

**I would not store `cvss_score` as a number.** Autosave runs mid-keystroke; `9.` must survive the
trip.

**I would not add a server-side `generation_issues` entry for the reserved-substring problem without
twinning it.** A server-only gate is exactly the drift the existing design spends effort avoiding:
the badge would read `Ready`, the Generate button would be enabled, and the click would fail.

### Open questions

**1. The CVSS Vector allowlist as requested rejects every real CVSS vector.** The request says
"letters and these symbols `/:` only". A CVSS v3.1 vector reads
`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` — it contains the digits `3` and `1` and a period. A
v4.0 vector begins `CVSS:4.0/…` and has the same problem. Under the rule as written the tester
literally cannot type a valid vector into the field. Options: **(a)** implement it exactly as stated,
letters plus `/` and `:`, and accept that the standard prefix is untypable; **(b)** widen to letters,
digits, `.`, `/` and `:` — a superset that accepts both vector versions while still rejecting spaces,
braces, hyphens and everything else. **Recommendation: (b).** It rejects nothing the request wanted
rejected, and it is the difference between a field that works and one that does not. Absent an
answer I will build (b), because (a) ships a field nobody can use.

**2. What should happen to a typed CVSS value when the segment moves away from Asia and back?**
Three precedents exist in this codebase and they point in different directions: purge with a
confirmation dialog (what unticking an app type does to scope targets), keep and never repair (what
changing coverage does to an uploaded screenshot), and carry out of sight (what a status change does
to a content section). Options: **(a)** keep the value, hide the field, and show it again with the
value intact if the segment returns — nothing is ever deleted, and the value prints nowhere in the
meantime because a non-Asia template has no `Section` table; **(b)** prompt and delete on the segment
change, matching the app-type dialog; **(c)** clear silently. **Recommendation: (a).** A CVSS string
references nothing, so it cannot dangle and cannot fail validation — the pressure that justifies (b)
elsewhere is absent here, and a tester who mis-clicks a dropdown and corrects it should find their
work where they left it. The same rule would cover a tickets value when a status change hides it.
Absent an answer I will build (a).

**3. Should the server reject bad characters in these fields, or only the browser?** Every character
rule in the app today exists twice: Python 422s the save and JavaScript blocks the input, kept in
step by hand and pinned by one parity test. These fields are the first content-side values with a
character rule, and nothing inside `contents` is character-validated anywhere today. Options:
**(a)** browser-only — the rule lives in one place, no new 422 path, no new parity test, and
`invalid_character_issue` needs no `allow_letters` parameter; a hand-crafted `PUT` could store any
string, which would print into a Word cell but cannot corrupt a draft or break a load. **(b)** mirror
it in Python — a new per-finding issues function called from `save_report`, the `allow_letters`
keyword argument, and a mirrored message plus a contract test, matching how Setup behaves.
**Recommendation: (a).** The asymmetry runs in the safe direction: the browser blocks more than the
server rejects, never less, so there is no save that the client permits and the server refuses.
Absent an answer I will build (a) and leave `invalid_character_issue` untouched.

**4. A ticket reference containing `-vuln` aborts generation, and no allowlist can prevent it.**
`_unresolved_placeholders` casefolds the entire rendered document and fails on seven bare substrings,
one of which is `-vuln` ([app/docx_report.py](app/docx_report.py#L54-L62),
[L1480-L1485](app/docx_report.py#L1480)). A reference like `SEC-VULN-1234` — plausible for a
vulnerability ticket — would abort the whole render with *"Unresolved template placeholders:
-vuln"*, naming the tester's own text as a template fault. `{{` and `}}` are the same class of
failure. Options: **(a)** a browser-side rule on the tickets field that refuses `{{`, `}}` and the
seven reserved substrings with a message saying so, blocking the value before it is ever saved, and
no server change; **(b)** a `generation_issues` entry with its `fragmentIssues` twin, so the Generate
button disables and the review panel names the field — correct but it touches the one pair a contract
test covers; **(c)** leave it, and accept that a tester with an unlucky ticket ID gets an
incomprehensible failure with no route to a fix. **Recommendation: (a).** It is the only option that
costs one rule in one place, and the existing abort remains the backstop for a value that arrives by
another route. Absent an answer I will build (a).

**5. Should the tickets value survive a `.docx` import round trip?** The Scribe established that
neither value survives today: the `Section` table is never read by the importer, and the ticket label
and its value fall into `in_conclusion`, which `_findings` hard-codes to `[]`. So an imported retest
draft starts with all three fields empty. Options: **(a)** accept that — a retest round raises new
tickets, and the delivered document is not treated as a source of truth for any of the three;
**(b)** add a `SECTION_HEADINGS` row and a consumer so the tickets value is read back, remembering
that `contents` is built as a positional five-element list and may only be **appended** to.
**Recommendation: (a),** and record it in DATA_MAP as a decision rather than leaving it as something
the next person rediscovers. Absent an answer I will build (a) and add nothing to the importer.

## Round 2 - Scribe: the import round trip

Read out of `app/docx_import.py`, `app/docx_report.py`, `app/docx_captions.py`, `tests/`, the pinned
`python-docx==1.2.0` source in `.venv`, and the text conversions under `graphify-out/converted/` on
2026-09-18. No `.docx` was opened — this machine cannot — so every claim about a template's own
contents is backed by a test that passes today, by the fact that generation succeeds today, or is
named as an inference where it is one.

**Verdict: feasible, and no part of it needs Word.** The whole round trip is exercisable on macOS,
because `render_report_docx` → `parse_report_docx` never touches the automation path. The CVSS half
is straightforward: one header lookup and a title match, in a file that already does both. The
tickets half is also straightforward *mechanically* — line breaks survive intact — but it rests on
matching a literal caption string, and it needs a test fixture that does not exist anywhere in the
suite today.

### 1. The importer is template-agnostic; the extra Asia table is inert

**Nothing in the importer counts tables or indexes into `document.tables`.** Every table it wants is
resolved by its first header cell, and the one exception is resolved by object identity:

| Table | How it is found | Where |
|---|---|---|
| Findings summary | first header cell `== "Findings"` | [app/docx_import.py](app/docx_import.py#L344-L347) |
| `URL(s) in Scope`, `API Routes` | first header cell, same helper | [L318-L323](app/docx_import.py#L318) |
| a finding's detail table | `table._tbl is element` while walking the body | [L457-L459](app/docx_import.py#L457) |

`_find_table` ([L311-L315](app/docx_import.py#L311)) scans `document.tables` for a header match and
returns `None` when there is none. Index access happens only *inside* a table already found —
`table.rows[1:]`, `row.cells[0]`, `cells[5]` — never `document.tables[n]`. **So there is no fixed
table count or table index anywhere on the import path, and the Asia templates' extra table changes
nothing.**

Two further paths that see every table and are still unaffected:

- `parse_report_docx` walks all tables collecting two-cell rows into `metadata`
  ([L521-L526](app/docx_import.py#L521)). The Section table's rows carry five cells, so it
  contributes nothing — and `metadata` is **never read again**. It is assigned at L521 and dead from
  there on. Out of scope here, worth one line in DATA_MAP or a follow-up.
- `_findings` builds its `starts` list from body-level paragraphs only
  ([L418-L426](app/docx_import.py#L418)); paragraphs inside table cells are not body children, so the
  finding titles printed in the Section table cannot produce a phantom finding.

**Where the Section table sits, and the one way this could already be wrong.** It is the last table
of `MAIN_ASIA.docx`, inside the *Appendix: Common Vulnerability Scoring System (CVSS)* section, which
follows the `{{findings}}` anchor
([converted MAIN_ASIA L92-93](graphify-out/converted/MAIN_ASIA_b33945bd.md#L92),
[L185-L187](graphify-out/converted/MAIN_ASIA_b33945bd.md#L185)). The **last** finding's body range
runs from its heading to the next `ReportHeading1`, or to the end of the body if there is none
([app/docx_import.py](app/docx_import.py#L432-L444)). So everything depends on the appendix heading
carrying `ReportHeading1`: if it does not, the appendix is already folded into the last finding, and
`_build_fragments` turns every `w:tbl` it is handed into a table fragment
([L233-L237](app/docx_import.py#L233)) and every non-empty paragraph into a paragraph fragment — the
Section table would arrive today as a stray table in the last finding's previous proof of concept.

**Evidence that it does carry `ReportHeading1`:** `MAIN.docx` has the same appendix after
`{{findings}}` ([converted MAIN L92-93](graphify-out/converted/MAIN_17ec8f65.md#L92)), and
`test_a_generated_report_reads_back_into_a_valid_draft` asserts the only finding's previous proof of
concept is **exactly** five fragments ([tests/test_docx_import.py](tests/test_docx_import.py#L222-L226)).
An overrun would add the appendix paragraphs and its severity-band table to that list. The test
passes and is not one of the two known macOS failures. **This is an inference from a passing test
plus a derived conversion, not an observation**; opening the template is the only direct proof.

Either way the instruction to the planner is the same: **read the Section table by header lookup,
never by walking a finding's body.** One asymmetry to carry across: `docx_import._find_table`
compares `== header` **case-sensitively** ([L313](app/docx_import.py#L313)) while
`docx_report._find_table` casefolds ([app/docx_report.py](app/docx_report.py#L338-L343)), so the new
lookup must spell it `"Section"`, exactly as the template header row does.

### 2. Finding the tickets paragraph: a literal caption string, and the paragraph after it

Once rendered there is no token and no distinguishing style. The value paragraph is an ordinary
paragraph of `retest_finding.docx`
([converted L23-24](graphify-out/converted/retest_finding_7b5835eb.md#L23)); `classify_paragraph`
([app/docx_import.py](app/docx_import.py#L113-L140)) would call it `paragraph` like any body text.
**So yes — it is matched on a literal caption string, and there is no alternative anchor.**

The mitigation is that the literal is already in the source, once:
`BOILERPLATE` ([L47-L50](app/docx_import.py#L47)) holds `"Severity Review Ticket (if applicable):"`
and is matched against `" ".join(text.split())` at [L242-L244](app/docx_import.py#L242). The plan
should lift that string to a named constant that `BOILERPLATE` is then built from, rather than
introduce a second copy that can drift from the first.

**The importer's paragraph walk does give a reliable position once the label is found.** The label
owns its own paragraph and the value owns the very next one — established in Round 1 §1 and pinned by
[tests/test_docx.py](tests/test_docx.py#L828-L831), which locates the label by exact paragraph text
and would raise `StopIteration` if the value shared it. So the anchor is *"the literal label, then the
next `w:p` in the same finding range"*: one fact about the template that a test already protects, and
one string that a test does not.

**Put the branch in `_findings`'s element loop** ([L456-L467](app/docx_import.py#L456)), not in
`_build_fragments`:

- For a retest finding the label falls after `In Conclusion:`, so `current == "in_conclusion"` — and
  `_findings` hard-codes `in_conclusion` to `[]` ([L481](app/docx_import.py#L481)), so
  `_build_fragments` is never called for that section. The value is collected into `sections` and
  then silently dropped. A reader placed in `_build_fragments` would never run.
- A branch in the loop is also independent of where the label sits relative to the section headings,
  which a template edit could change.
- Capture the label **and** its value with `continue`, so neither is appended to `sections[current]`.
  The label is already dropped by `BOILERPLATE` inside `_build_fragments`
  ([L243-L244](app/docx_import.py#L243)) but the **value is not** — if anyone later builds
  `in_conclusion` from the document, an uncaptured value would come back as a stray paragraph in the
  conclusion.

**Two facts about which findings can carry a value at all:**

- `new_finding.docx` has neither the label nor an `In Conclusion:` heading
  ([converted new_finding](graphify-out/converted/new_finding_3568c9e0.md#L1-L22)), so an Open (New)
  finding yields `""`. Correct, and free.
- **A Resolved finding is dropped before any of this runs** ([L449-L451](app/docx_import.py#L449)),
  so a ticket value on a Resolved finding never round-trips. Every imported finding is rewritten to
  `open_previously_discovered` ([L489](app/docx_import.py#L489)), which is a status where the field is
  *visible* per the Answers matrix — so a recovered value is shown rather than stranded. Record the
  Resolved exclusion as a decision; it is otherwise a discovery.

### 3. Line breaks survive; `_clean` is what destroys them

`runs_of` converts `w:br` and `w:cr` to `"\n"` itself
([app/docx_import.py](app/docx_import.py#L155-L156)) and `text_of` joins the runs
([L169-L170](app/docx_import.py#L169)). A three-ticket value written by option A lands as one run
holding `w:t`/`w:br`/`w:t`/`w:br`/`w:t` (`_set_run_text`,
[app/docx_components.py](app/docx_components.py#L548-L559)), so `text_of` returns
`"1234\n5678\n9012"` — **the separate lines are recovered, not joined and not lost.**

**`_clean` is the trap** ([L71-L74](app/docx_import.py#L71)): `" ".join(value.split())` flattens every
break to a single space, so cleaning the whole value turns three tickets into `"1234 5678 9012"`.
Clean per line and rejoin:

```python
lines = [cleaned for line in text_of(paragraph).split("\n") if (cleaned := _clean(line))]
tickets = "\n".join(lines)
```

That is the same shape `_scope_rows` uses on a wrapped cell
([L332-L336](app/docx_import.py#L332)) — except that there the pieces are deliberately rejoined
*without* a separator, because `_wrap_long_value` broke one value across lines. Here each line is its
own ticket, so the `\n` is kept. The filter is what makes an all-`N/A` value read as `""` rather than
as a blank line (§5).

Two smaller notes on the same mechanism:

- `runs_of` reads **direct-child** runs only (`paragraph._p.findall(qn("w:r"))`,
  [L149](app/docx_import.py#L149)) while token replacement searches `w:t` **descendants**
  ([app/docx_components.py](app/docx_components.py#L478-L519)). If the token's run were nested in the
  template — a hyperlink, a tracked insertion, a smart tag — generation would still succeed and the
  import would read back empty. Asserting the recovered string equals the written one catches this
  immediately; nothing else would.
- `runs_of`'s docstring says *"``paragraph.text`` drops them silently"*
  ([L145-L146](app/docx_import.py#L145)). Against the pinned `python-docx==1.2.0` that is no longer
  true: `CT_Br.__str__` returns `"\n"` for a `textWrapping` break and `CT_R.text` includes it. Both
  readers work; the comment is stale, and anyone reasoning from it will reach the wrong conclusion
  about which one to use.

### 4. Matching a Section row back to its finding

The row is `Section | Vulnerability Name | Severity | CVSS Score | CVSS Vector`, filled per finding
at [app/docx_report.py](app/docx_report.py#L607-L627).

**Cell 0 is useless as a key, in both of the two states it can be in.** `_reference_field`
([app/docx_report.py](app/docx_report.py#L584-L604)) writes begin / `instrText` / separate / end with
**no result run**, so before Word the cell holds no `w:t` at all and python-docx yields `""` —
`CT_R.text` reads only `w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab`, and `w:instrText` is
not in that list. After the Windows pass, `flatten_section_number_fields`
([app/docx_captions.py](app/docx_captions.py#L108), [L115-L141](app/docx_captions.py#L115)) replaces
the computed field with plain text: the heading's own list label minus its trailing period, e.g.
`7.1`. So a delivered document yields a section number and a document rendered without Word yields an
empty string; neither identifies a finding, and a stale one would be actively wrong.
`tests/test_docx.py::test_a_computed_section_number_loses_its_trailing_period`
([tests/test_docx.py](tests/test_docx.py#L1076-L1099)) states both states outright.

**Cell 1 is the key, and it is exactly the string the importer already matches on.**
`test_asia_section_rows_follow_the_rendered_finding_order`
([tests/test_docx.py](tests/test_docx.py#L1101-L1118)) asserts
`[row.cells[1].text for row in table.rows[1:]] == headings`, where `headings` are the bookmarked
`ReportHeading2` paragraphs — the same paragraphs `_findings` collects into `starts`
([app/docx_import.py](app/docx_import.py#L418-L426)). Cell 2 (severity, title-cased) can corroborate
but cannot separate two same-titled findings of the same severity.

**Do not pair by row index.** The table carries a row for every *rendered* finding, while the
importer's output list omits every Resolved one ([L449-L451](app/docx_import.py#L449)) and every
heading that claims no summary row ([L445-L447](app/docx_import.py#L445)). One Resolved finding
shifts every row after it.

**Use the mechanism the file already has for duplicate titles.** Claim Section rows by title, in
document order, at the same point the summary row is claimed — `unclaimed` /
`next((candidate for candidate in unclaimed ...))` at [L445-L451](app/docx_import.py#L445) — and
claim **before** the status drop, so a Resolved finding consumes its own row and the alignment holds.
Normalise both sides with `" ".join(cell.text.split())` to match the heading normalisation at
[L424](app/docx_import.py#L424); `_summary_rows` uses a bare `.strip()`
([L350](app/docx_import.py#L350)), a pre-existing inconsistency that bites any title containing a
double space.

### 5. Empty cells and the literal `N/A`

| What the document holds today | What the importer must produce |
|---|---|
| tickets paragraph reading `N/A` ([app/docx_report.py](app/docx_report.py#L764)) | `""` |
| tickets paragraph with three lines | `"1234\n5678\n9012"` |
| CVSS cells written `""` ([L622-L623](app/docx_report.py#L622)) | `""` |
| **no Section table at all** — every non-Asia document | `""` for both, and no exception |

- `_clean` already maps exactly the string `N/A` to nothing ([L71-L74](app/docx_import.py#L71)), so
  cleaning **per line** plus dropping empties gives `""` for an old document rather than a field
  holding the text `N/A`. Without the empty-line filter the same value imports as a field containing
  one blank line, which is the failure the owner named.
- Put the CVSS cells through `_clean` too rather than `.strip()`. It costs nothing and it means that
  if the generator is ever changed to write `N/A` into an empty CVSS cell, the importer does not
  start importing that text as a score.
- **The absent-table branch must be tolerant, not fatal.** `_summary_rows` *raises* when its table is
  missing ([L346-L347](app/docx_import.py#L346)) because a document with no findings table is not a
  report. The Section table's absence is the normal case for three of the four templates, so the new
  lookup must follow `_scope_rows` ([L322-L323](app/docx_import.py#L322)): `None` → return nothing and
  carry on.
- Net effect, stated plainly: **importing any report generated before this change yields three empty
  fields** — no `N/A` text, no stray blank line.

### 6. The `contents[3]` hazard is avoided entirely

Confirmed. The three values become keys in the dict built at
[L486-L492](app/docx_import.py#L486), beside `uid`, `title` and `scope`. The `contents` literal
([L476-L482](app/docx_import.py#L476)) keeps exactly five entries in exactly the order that
`contents[3]["fragments"] = _empty_proof(scope, targets)` ([L485](app/docx_import.py#L485)) depends
on: nothing inserted, nothing appended, nothing reordered. `SECTION_HEADINGS`
([L39-L45](app/docx_import.py#L39)) gains no row and the required triple at
[L468-L470](app/docx_import.py#L468) is untouched.

**The ticket label must not become a `SECTION_HEADINGS` entry.** That tuple is consumed by
`section_of` ([L173-L180](app/docx_import.py#L173)), whose return value is used directly as a content
type key — adding a row would invent a sixth section in the importer alone, which is the very thing
the plan's shape avoids.

One ordering constraint, the same one that governs the client: `parse_report_docx` returns a payload
that `Report.model_validate` must accept ([tests/test_docx_import.py](tests/test_docx_import.py#L236)),
so the three model fields must land before the importer writes them.

### 7. Tests

**Nothing in `tests/test_docx_import.py` breaks.** Its assertions are engagement fields, section-to-
fragment-type lists and evidence records; three new keys on the finding dict disturb none of them,
and `Report.model_validate` accepts them once the model carries them. The only existing test this
change forces is the one the plan already moves,
`tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`
([tests/test_docx.py](tests/test_docx.py#L1117-L1118)).

**The fixture, and whether it is generation-clean.** The import suite builds one report:
`FragmentRecognitionTests._report` ([tests/test_docx_import.py](tests/test_docx_import.py#L55-L98)),
rendered through `TEMPLATE = resources/MAIN.docx` ([L46](tests/test_docx_import.py#L46)) — reused by
`ImportRouteTests._docx` as well. **It is generation-clean by construction**: every test calls
`render_report_docx` with no `allow_incomplete`, which raises on any issue
([app/docx_report.py](app/docx_report.py#L174-L175)), so the suite could not run otherwise. For this
change it is the wrong shape twice over — segment `JH`
([tests/test_docx_import.py](tests/test_docx_import.py#L64)), so no Section table, and status
`open_new` ([L74](tests/test_docx_import.py#L74)), so the document is built from `new_finding.docx`
and carries no ticket paragraph at all.

**No test anywhere feeds a retest-rendered document to `parse_report_docx`.** All five call sites use
that one fixture. So the retest component has never been through the importer, and the tickets half of
this round trip needs a fixture that does not exist.

What a proving test has to assert:

- **Tickets, values.** A new generation-clean fixture with `status="open_previously_discovered"`,
  carrying description, recommended remediation, previous proof of concept, a proof of concept with a
  numbered list and a production image with `evidence_id` *and* caption, and a **non-default**
  `in_conclusion` paragraph — otherwise `generation_issues`
  ([app/docx_report.py](app/docx_report.py#L116-L123)) blocks the render. Render, parse, assert
  `severity_review_tickets == "1234\n5678\n9012"` **exactly**: the breaks are the assertion, not the
  presence of the digits.
  `tests/test_docx.py::_layout_document` ([tests/test_docx.py](tests/test_docx.py#L763)) is the
  closest existing retest fixture and is **not** reusable — it renders `allow_incomplete=True`, which
  substitutes placeholder paragraphs for missing images, the reason
  [docs/plans/import-docx-as-retest-draft.md](docs/plans/import-docx-as-retest-draft.md#L736) ruled it
  out for import fixtures.
- **Tickets, empty.** A second finding with no value renders `N/A` and must import as `""`.
- **CVSS.** An Asia render in the shape of `_asia_multi_finding_document`
  ([tests/test_docx.py](tests/test_docx.py#L1031-L1046)), which already renders three findings through
  `main_template_path`, with **a different score and vector per finding** and **at least one Resolved
  finding in the set**. Assert each retained finding's values by title. Identical values across
  findings would pass with a broken matcher; the Resolved finding is what proves the match is not
  positional.
- **Non-Asia.** The existing `MAIN.docx` fixture imports with all three fields `""` and no exception —
  the regression that keeps the absent Section table tolerant, and the one that proves an old report
  yields empty fields rather than `N/A`.

One consequence of the *Answers* worth stating: once empty CVSS blocks generation on Asia reports,
**an Asia fixture must carry both values or the render raises**, so no test can produce a fresh Asia
document with empty CVSS cells. The "old document" case is therefore only testable through a non-Asia
render or a hand-edited document.

Scope line for the repo's test rule: `tests.test_docx_import`, plus `tests.test_docx` for the Asia and
retest renders.

### 8. What only Word can settle

Very little, and none of it blocks the plan.

- Whether the appendix heading is `ReportHeading1` (§1) is an inference from a passing test plus a
  derived conversion. Opening `MAIN.docx` or `MAIN_ASIA.docx` in Word settles it. If it turns out not
  to be, the Asia import already has a bug independent of this change.
- A delivered document's Section cell 0 holds whatever Word computed; the importer ignores it, so
  nothing here depends on that value.
- Everything else in the round trip — the breaks, the cell text, the table lookup, the title match —
  is decided in this repository and testable on macOS.

## Round 2 - Oracle: verdict on the proposal

Everything below was read out of source on 2026-09-18, after the *Answers* were settled. Where this
round contradicts an earlier round of this same document it is called out; nothing here is taken
from a plan.

**Verdict: the shape survives, but the argument the planner gave for it does not.** Three scalar
fields on `Vulnerability` are still the smaller change, and the *Answers* widen the margin rather
than narrowing it — because a sixth `ContentType` would now need the required-check written *and* an
exemption carved out of machinery the scalar shape never touches. What must be retracted is the
justification: "that single decision dissolves constraints 3, 4 and 7" is now true of 3 and 7 only.
Constraint 4 is not dissolved, it is inverted, and the plan must say so in those words or the next
reader will build the design believing nothing can reach these fields.

### 1. Does the chosen shape still earn its keep?

Yes, and by more than before. The required-check costs the same in both designs — roughly one `if`
per language — so it cancels out of the comparison. What does not cancel is everything a sixth
member drags in, all of which I re-checked against source this round:

| | Three scalars | Sixth `ContentType` |
|---|---|---|
| Schema | three `str = ""` fields on `Vulnerability` ([app/models.py](app/models.py#L199)) | `ContentType` widened at [app/models.py](app/models.py#L34) — a **one-way door**: once a draft stores the member, removing it makes that draft unloadable |
| Which sections exist | untouched | `content_types_for_status(status)` ([app/report_service.py](app/report_service.py#L172)) gains the segment axis, so it needs the report; `provision(vulnerability)` ([L202](app/report_service.py#L202)) changes signature, and so does its JavaScript twin — which has **seven** call sites, not four: [L1037](app/web/static/app.js#L1037) declaration, then [L1050](app/web/static/app.js#L1050), [L1087](app/web/static/app.js#L1087), [L2579](app/web/static/app.js#L2579), [L3384](app/web/static/app.js#L3384), [L3778](app/web/static/app.js#L3778), [L3998](app/web/static/app.js#L3998) |
| Editor maps | none | `allowed` ([L119](app/web/static/app.js#L119), a missing key is a `TypeError`), `contentNames` ([L118](app/web/static/app.js#L118)), `requiresFragment` ([L121](app/web/static/app.js#L121)), `required_fragments` ([app/report_service.py](app/report_service.py#L212)), the readiness `order` array ([L3455](app/web/static/app.js#L3455)) |
| The required-check | **one addition**: two fields required on Asia | **two carve-outs**: the same requirement, *plus* an exemption, because the generic per-fragment rules at [app/docx_report.py](app/docx_report.py#L124-L145) fire "text is required" on an empty paragraph — so Severity Review Tickets, which must never block, has to be exempted by name on both sides |
| Field identity | the field name *is* the attribute | no fragment model carries a field name. Three fixed labelled values inside one `Content` are either positional (the thing this codebase has exactly one of, and regrets) or a new discriminated fragment type |
| Survival across a save | `provision` never touches them | `provision`'s carry rule ([app/report_service.py](app/report_service.py#L206-L208)) puts the tester's typed CVSS value under `content_has_work` ([L179](app/report_service.py#L179)); a section holding only empty fields is **silently dropped on the next save** |
| Reading it at render | `finding.cvss_score` — the loop already holds the `Vulnerability` ([app/docx_report.py](app/docx_report.py#L614)) | section lookup, then fragment lookup, then run join, per cell |
| Import (now in scope) | three keys in the finding dict at [app/docx_import.py](app/docx_import.py#L486-L492) | a sixth `contents` entry that may only be **appended** past the positional `contents[3]` at [L485](app/docx_import.py#L485), and a `SECTION_HEADINGS` row that `section_of` would turn into a sixth importer section |
| Tests | one parity case, one model round-trip | all of the above, each needing its own |

So: smaller in total, including tests, and the gap widened when the *Answers* put the importer in
scope. **Keep the shape. Rewrite the reason.**

### 2. Where the required-check goes in Python

**Exact place: inside `generation_issues`'s per-finding loop, after the evidence-image loop
([app/docx_report.py](app/docx_report.py#L107-L109)) and before `printed` is computed
([L110](app/docx_report.py#L110)).** That is the last point in the loop that is not about a
`Content`, it already holds `finding` and `label`, and `report` is the function's own argument
([L94](app/docx_report.py#L94)) so the segment is free.

**Message shape.** Every per-finding line in that function is `f"{label}: …"`, where
`label = finding.title or "Untitled finding"` ([L100](app/docx_report.py#L100)):

```
f"{label}: finding details or affected locations are incomplete"     # L102
f"{label}: Production evidence image required"                       # L109
f"{label}: {content.type} needs at least one fragment"               # L117
```

Follow it: `f"{label}: CVSS Score is required"`. Note the function returns
`list(dict.fromkeys(issues))` ([L150](app/docx_report.py#L150)), so two findings sharing a title
collapse to one line — pre-existing, but it means the issue count is not always the finding count.

**The segment gate is mandatory and it is a third implementation of "is this Asia".** The check must
read `report.engagement.segment == "Asia"`; written without that guard it blocks every JH and GWAM
report on a field those reports have no control for. The two existing implementations are
`main_template_path`, which compares the string ([L152-L158](app/docx_report.py#L152)), and
`_populate_cvss_table`, which infers it from the `Section` table's presence
([L610-L612](app/docx_report.py#L610)). This change adds a third. Say so in DATA_MAP rather than
leaving three copies of one rule undocumented.

**`finding_is_complete` must not learn this rule.** Not a preference — three independent reasons:

- `/edit` redirects to `/findings` when any finding fails it ([app/main.py](app/main.py#L644)). The
  CVSS fields live on the Content page, so the tester would be bounced off the only page that can
  fix them, onto one that has no such control. That is the navigation trap the design was supposed
  to avoid, arriving through the back door.
- `generation_issues` already calls it ([app/docx_report.py](app/docx_report.py#L101)), so the
  resulting message would read *"finding details or affected locations are incomplete"* — naming the
  wrong thing entirely.
- It would need a **third** twin, not a second: the Findings page keeps its own incomplete list at
  [app/web/static/app.js](app/web/static/app.js#L2266-L2274), separate from the readiness panel.

**`setup_is_complete` must not either.** `setup_issues` ([app/report_service.py](app/report_service.py#L649))
reads the engagement and `scope_targets` only, is per-report rather than per-finding, and is already
folded into `generation_issues` at [L96](app/docx_report.py#L96). A per-finding rule there would
bounce Findings back to Setup.

**So: block generation, never navigation. One Python owner, and it is `generation_issues`.**

### 3. Where the required-check goes in JavaScript, and how the segment reaches it

**The segment is already reachable. Nothing needs threading and no caller changes.** `report` is
declared `let report = serverReport` at [app/web/static/app.js](app/web/static/app.js#L13) — the top
level of the file's single IIFE. `continuousEditor()` ([L3345](app/web/static/app.js#L3345)),
`updateReadinessPanel` ([L3369](app/web/static/app.js#L3369)) and `fragmentIssues`
([L3381](app/web/static/app.js#L3381)) are all nested inside it and close over that binding;
`updateReadinessPanel` already reads `report.vulnerabilities` directly at
[L3432](app/web/static/app.js#L3432). `report.engagement.segment` works at the `fragmentIssues` call
site today, unchanged.

**But `fragmentIssues` is the wrong home.** It is `finding.contents.filter(…).flatMap(…)`
([L3386](app/web/static/app.js#L3386)) — every issue it emits is about a `Content`, and a scalar
field has none. The right home is the per-finding block at
[L3432-L3441](app/web/static/app.js#L3432), beside `missing.push("affected location")`
([L3437](app/web/static/app.js#L3437)): same scope, same `report`, and it is exactly where the
server puts its own non-content per-finding check.

Three mechanical consequences to design around:

- **Do not fold it into `missing`.** That array is joined into a single issue
  `{finding, message: missing.join(", ")}` ([L3441](app/web/static/app.js#L3441)), so two empty CVSS
  fields would count as one while the server counts two. The parity test compares `data-state` and
  the button only, so it would still pass — but `#issue-count` would disagree with the server's list
  length. Push separate issue objects.
- **The new block's `.content-flag` pill stays hidden unless the issue carries a `contentLabel`.**
  `openByType` ([L3476-L3479](app/web/static/app.js#L3476)) resolves `issue.contentLabel` through
  `typeByLabel` ([L3474](app/web/static/app.js#L3474)), which is built from `contentNames`
  ([L118](app/web/static/app.js#L118)). Adding a pseudo-entry to `contentNames` is safe: every other
  read of that map is `contentNames[content.type]` against a real content
  ([L1250](app/web/static/app.js#L1250), [L2798](app/web/static/app.js#L2798),
  [L2929](app/web/static/app.js#L2929), [L3390](app/web/static/app.js#L3390),
  [L3446](app/web/static/app.js#L3446), [L3500](app/web/static/app.js#L3500),
  [L3917](app/web/static/app.js#L3917), [L3939](app/web/static/app.js#L3939),
  [L3962](app/web/static/app.js#L3962)); only `typeByLabel` and `rank` enumerate it.
- **An issue with no recognised type sorts to the top.** `rank`
  ([L3455-L3459](app/web/static/app.js#L3455)) returns `-1` for an unknown type, which sorts
  **above** every content issue in the review panel.

### 4. The parity test

**It would not cover the new rule at all.** `ready_report` sets
`report.engagement.segment = "JH"` ([tests/test_browser.py](tests/test_browser.py#L61)) and all
twelve cases mutate that one fixture, so the Asia branch never executes in either language. The test
would keep passing against a rule implemented in Python and forgotten in JavaScript — the precise
failure it exists to catch.

**A case must be added. Two, in fact,** or the test cannot tell a correctly gated rule from one that
fires on every Asia report:

- `report.engagement.segment = "Asia"` with `cvss_score` and `cvss_vector` left empty on the
  completed finding → both sides must read `issues`, Generate disabled.
- the mirror, Asia with both filled → both sides `ready`, Generate enabled.

Three things that make the case work, all already true:

- Segment `"Asia"` does not disturb the Setup gate: `setup_issues` only requires the segment to be
  non-empty ([app/report_service.py](app/report_service.py#L654-L655)).
- The loop runs `main.provision_report(report)` then `main.workspace.save(report)` before comparing
  ([tests/test_browser.py](tests/test_browser.py#L3758-L3760)); the new fields survive both, because
  `provision` assigns only `contents`.
- **The escape hatch is the reason the check must stay out of `finding_is_complete`.** The loop
  does `if "/findings" in self.page.url: … continue`
  ([tests/test_browser.py](tests/test_browser.py#L3763-L3767)) — any case the server blocks at the
  route is skipped without comparing the browser at all. Put the rule in `finding_is_complete` and
  the new case is swallowed by that branch, and the JavaScript half is never tested.

### 5. Keep-and-hide costs nothing — for scalars, and on one condition

**Confirmed: it is the absence of code.** I checked every path that could strip an unrendered value:

- `provision` ([app/report_service.py](app/report_service.py#L202-L272)) assigns
  `vulnerability.contents`, `remediation.fragments` and `conclusion.fragments`. No other attribute of
  the `Vulnerability` is touched anywhere in the function.
- `reconcile_targets` ([app/report_service.py](app/report_service.py#L542-L646)) mutates the raw
  payload's `engagement`, writes `payload["scope_targets"]`, and edits each vulnerability's `scope`
  dict. It never deletes a vulnerability key and never reads `contents`.
- `sync_evidence_image_slots` ([app/report_service.py](app/report_service.py#L357)) filters
  `content.fragments` only.
- `Report.model_validate` in `save_report` ([app/main.py](app/main.py#L688)) drops **undeclared**
  keys under Pydantic's default `extra="ignore"`; a declared field with a `""` default round-trips
  untouched. This is the whole reason the model change must ship before the client writes.
- Client: the segment control is a plain `<select data-path="engagement.segment">`, handled by the
  generic `[data-path]` wiring at [app/web/static/app.js](app/web/static/app.js#L1567-L1581), which
  does `report[section][field] = input.value || null` and `scheduleSave()`. No purge, no dialog, no
  re-provision.

So neither `reconcile_targets` nor `provision` — the two candidates named — strips anything. **The
condition: the field must be *not rendered*, not *rendered and cleared*.** If the hidden case is
implemented by emptying the input rather than by omitting it from the block, that is a write, and it
is the one way this becomes lossy.

An orphaned value also cannot leak into a document: `_optional_table(document, "Section")` returns
`None` and `_populate_cvss_table` returns at [L610-L612](app/docx_report.py#L610) before writing
anything.

**What it does cost is the guard in §2.** Keep-and-hide plus a required-check means the check must
be gated on the same segment test as the rendering, in both languages. Miss that and every non-Asia
report is blocked on a field it never shows.

### 6. `invalid_character_issue` gaining an `allow_letters` flag

**The *Answers* say "five existing callers". There are ten.** Every one, verified:

| # | Where | Label | Symbols / flags |
|---|---|---|---|
| 1 | [app/report_service.py](app/report_service.py#L115) | Application name | `APP_NAME_SYMBOLS` = `-:;.()` |
| 2 | [L118](app/report_service.py#L118) | CI number, BSN number | `-`, `allow_spaces=False` |
| 3 | [L121](app/report_service.py#L121) | Application owner, Tester | `-`, `allow_numbers=False` |
| 4 | [L130](app/report_service.py#L130) | `{environment} time` | `:/-` |
| 5 | [L133](app/report_service.py#L133) | `User role {index}` | `/-` |
| 6 | [L136](app/report_service.py#L136) | `Username {index}` | `._@\-`, `allow_spaces=False` |
| 7 | [L138](app/report_service.py#L138) | Limitations | `/,.;:()&'"-`, `allow_line_breaks=True` |
| 8 | [L144](app/report_service.py#L144) | Non-Production name | `/-` |
| 9 | [L604](app/report_service.py#L604) | component scope and its description | `COMPONENT_SCOPE_SYMBOLS` |
| 10 | [app/main.py](app/main.py#L613) | Application name, rename route | `-:()` |

**A `True` default leaves all ten byte-identical.** The only edit is inside `_invalid_characters`
([app/report_service.py](app/report_service.py#L44)): `character.isalpha()` becomes
`(allow_letters and character.isalpha())`, and every existing caller omits the argument.
`_has_allowed_characters` ([L85](app/report_service.py#L85)) and `valid_application_name`
([L107](app/report_service.py#L107)) also call `_invalid_characters` without it, so they need no
change either — though whichever of the two helpers the flag is threaded through, both should be
given the keyword for symmetry with `allow_numbers`.

**Would any be clearer set explicitly? One candidate, and it should still be left alone.** Row 4,
the test-time rule, accepts values like `08:00-17:00` where letters have no meaning — so
`allow_letters=False` would read as an improvement. It is not: it would newly 422 a stored value
like `8am to 5pm`, and it needs its own JavaScript twin and its own parity case. Out of scope.

Worth recording while it is in view, as a pre-existing fault this change does not create: rows 1 and
10 validate the *same field* against *different* symbol sets — `-:;.()` on save, `-:()` on rename —
so a name containing `;` or `.` saves through Setup and is refused by the rename route.

### 7. The editor block's markup

**The planner's inset numbers are wrong.** `taste.css` declares the chrome twice at equal
specificity and the later block wins:

| Rule | Earlier | Later — **effective** |
|---|---|---|
| `.content-block > *:not(.content-toggle)` | `margin-inline: 13px` ([L1367](app/web/static/taste.css#L1367)) | **`11px`** ([L3160](app/web/static/taste.css#L3160)) |
| `.content-block > .content-toggle + *` | `margin-top: 11px` ([L1371](app/web/static/taste.css#L1371)) | **`10px`** ([L3164](app/web/static/taste.css#L3164)) |
| `.content-block > :last-child` | `margin-bottom: 12px` ([L1375](app/web/static/taste.css#L1375)) | **`11px`** ([L3167](app/web/static/taste.css#L3167)) |

Step 6's invariant (13 / 11 / 12) would fail against a real page. The honest form of that check is
not a hard-coded number at all: read the computed margins off an existing `.content-block`'s
children and off the new one, and diff them.

**The markup that looks identical to a free-fragment section:**

- `div.content-block[data-content-type="additional_information"]`, `is-expanded` when open.
- `button.content-toggle` whose innerHTML is exactly the three-child shape
  ([app/web/static/app.js](app/web/static/app.js#L3939)). The trailing `<small>` is not decoration —
  it carries `margin-left: auto` ([taste.css L3076](app/web/static/taste.css#L3076)) and is what
  pushes the `.content-flag` pill to the middle. Omit it and the pill moves.
- Each field as an `article.fragment` holding `div.fragment-head > span.tag` (the field label) plus
  its control, appended as a **direct child** of the block. That buys, with no new CSS: the card
  border, radius and `--surface-raised` ([taste.css L3171](app/web/static/taste.css#L3171)); the
  header strip's `--canvas-deep` background and bottom border
  ([L3184](app/web/static/taste.css#L3184)); the `.tag` treatment
  ([L3193](app/web/static/taste.css#L3193)); and `margin-bottom: 8px` between rows
  ([L3172](app/web/static/taste.css#L3172)), which is the row gap the planner correctly identified
  as absent from `.content-block` itself. A wrapper `div` around the three loses the inset, the
  heading gap and the last-child gap in one stroke.
- **`data-fragment-id` only if the red ring is wanted.** `updateReadinessPanel` toggles
  `.is-incomplete` on `[data-fragment-id]` nodes ([L3478-L3479](app/web/static/app.js#L3478)), and
  the ring is drawn by `.is-incomplete input:placeholder-shown`
  ([taste.css L3099-L3103](app/web/static/taste.css#L3099)). So a ring needs *both* an id the issue
  object points at *and* a `placeholder` on the control. Any id used must not collide with a real
  `frag_id` — `Report.validate_references` enforces those unique across the whole report
  ([app/models.py](app/models.py#L390-L393)) — and `showReviewTarget`
  ([L3362-L3367](app/web/static/app.js#L3362)) will try to jump to it.

**Can the fixed fields reuse the existing textarea behaviour? Partly — less than the proposal
assumes.**

- **Save-on-input: yes, verbatim.** `input.evidence-caption`
  ([app/web/static/app.js](app/web/static/app.js#L2905-L2911)) is the whole pattern — a plain
  `<input>` whose `oninput` assigns and calls `scheduleSave()`. The values then ride the existing
  debounced PUT; nothing else is needed.
- **Styling: yes, by joining the new class to `.evidence-caption`'s rules — in all three places.**
  It is declared at [taste.css L1796](app/web/static/taste.css#L1796),
  [taste.css L3543](app/web/static/taste.css#L3543) and
  [overrides.css L271](app/web/static/overrides.css#L271). Miss one and the field loses either its
  width or its font size.
- **Autosize: no. There is no reusable helper reachable from the Content page.** `rich()`
  ([L979-L993](app/web/static/app.js#L979)) has one but it is contenteditable and reports `runs` —
  the wrong shape for a plain string. The list textarea's autosize is written inline inside
  `renderFragment` ([L3144](app/web/static/app.js#L3144)). The `[data-path]` `grow` helper
  ([L1570-L1577](app/web/static/app.js#L1570)) is declared inside `setup()` and is unreachable from
  the Content page — the same trap as the character rules, and the hoist does not cover it. CVSS
  Score and Vector are single-line by rule and need none; **Severity Review Tickets is multi-line and
  does**, so it needs its own three-line resize or a fixed `rows` that scrolls.
- **Placeholder: use the native one.** `.rich` paints its placeholder from `data-placeholder` via
  `:empty::before`; an `<input>`/`<textarea>` gets `::placeholder`, already styled at
  [taste.css L1817](app/web/static/taste.css#L1817). The native one is also what the
  `.is-incomplete … :placeholder-shown` ring keys on, so it is required if the ring is wanted.

### 8. What the Scribe's import findings imply for the data layer

Four things, each confirmed against source this round:

1. **Ordering is a hard constraint, not a preference.** `parse_report_docx` returns a plain dict that
   `Report.model_validate` consumes, and Pydantic's default `extra="ignore"` drops undeclared keys
   without a word. The three model fields must land before the importer writes them, or the import
   path looks like it works and imports nothing. This is the same ordering argument the proposal
   already makes for the browser, applied to a second writer.
2. **`N/A` → `""` is already `_clean`'s job — but only applied per line.** `_clean`
   ([app/docx_import.py](app/docx_import.py#L71-L74)) is `" ".join(value.split())` then
   `"" if text == "N/A"`. Run over a whole three-line tickets value it flattens the breaks to spaces;
   run per line with empty results dropped, it yields `""` for an old document and
   `"1234\n5678\n9012"` for a new one. Same four lines, different placement — and the placement is
   the entire decision.
3. **Empty CVSS cells import as `""` for free, and an absent `Section` table must be tolerated, not
   raised on.** `_find_table` ([L311-L315](app/docx_import.py#L311)) returns `None`; `_scope_rows`
   ([L322-L323](app/docx_import.py#L322)) returns nothing and carries on, while `_summary_rows`
   ([L346-L347](app/docx_import.py#L346)) raises. Three of the four templates have no `Section`
   table, so the new lookup follows `_scope_rows`. One asymmetry to carry:
   `docx_import._find_table` compares `== header` **case-sensitively**
   ([L313](app/docx_import.py#L313)) while `docx_report._find_table` casefolds
   ([app/docx_report.py](app/docx_report.py#L338-L343)) — spell it exactly `"Section"`.
4. **The scalar shape is precisely what keeps `contents[3]` safe.** The three values become keys in
   the finding dict at [L486-L492](app/docx_import.py#L486), beside `uid`, `title` and `scope`. The
   `contents` literal ([L476-L482](app/docx_import.py#L476)) keeps exactly five entries in the order
   `contents[3]["fragments"] = _empty_proof(…)` ([L485](app/docx_import.py#L485)) depends on;
   `SECTION_HEADINGS` ([L39-L45](app/docx_import.py#L39)) gains no row, and the required triple at
   [L468-L470](app/docx_import.py#L468) is untouched. Under a sixth `ContentType` every one of those
   moves.

One decision the *Answers* create without stating: `_findings` drops every Resolved finding
([L449-L451](app/docx_import.py#L449)) and rewrites every survivor to `open_previously_discovered`
([L489](app/docx_import.py#L489)). A Resolved finding's ticket value therefore never round-trips at
all, while a recovered value always lands on a status where the field is visible. Record that as a
decision, or it is rediscovered as a bug.

### Claims in the planner's Round 1 proposal that are now wrong

1. **"That single decision dissolves constraints 3, 4 and 7."** — True of 3 and 7. **Constraint 4 is
   not dissolved, it is inverted**: two of the three values must now be reachable by
   `generation_issues` and `fragmentIssues`, deliberately.
2. **Constraint 4's invariant, "a finding with all three fields empty produces zero issues and leaves
   `#generate-report` enabled."** — False on an Asia report. Correction: **off** Asia that invariant
   stands unchanged; **on** Asia, two empty CVSS fields must produce two issues and disable the
   button.
3. **Data risks, "Navigation trap: `clear` — No field is required (settled in *Answers*), so no gate
   gains a condition and no page can bounce."** — The premise is false. The conclusion survives, but
   only because the check goes in `generation_issues` and nowhere else; in `finding_is_complete` it
   bounces the tester off the page that holds the field ([app/main.py](app/main.py#L644)).
4. **Data risks, "the character allowlists are JavaScript-only under OQ3's recommendation, which is
   asymmetric in the safe direction."** — The owner chose both languages. Correction: the allowlists
   are twins, and so is the required-check; both need the `twin of` comments this codebase uses and
   both are pinned by browser tests.
5. **Blast radius, "Deliberately unchanged: `app/report_service.py` … `app/docx_import.py`."** — Both
   change now: `report_service.py` for `allow_letters` and the content-side character checks,
   `docx_import.py` for the Section-table and tickets readers. `app/docx_report.py` additionally
   gains the required-check, not just the two value swaps. `app/main.py`, `app/storage.py` and
   `app/workspace.py` do genuinely stay unchanged — the generate route already calls
   `generation_issues` ([app/main.py](app/main.py#L517)).
6. **Open question 3's "Absent an answer I will build (a) and leave `invalid_character_issue`
   untouched."** — Settled the other way: both languages, and the flag is added.
7. **Constraint 9 and open question 4, the `-vuln` reserved-substring risk and the browser rule
   proposed to close it.** — Dropped entirely. A tickets value is digits and line breaks, so no
   reserved substring can be typed into it. Remove the risk row and the rule; the latent fault in the
   existing free-text fields is real but is not this change's.
8. **Open question 5's "Absent an answer I will build (a) and add nothing to the importer."** —
   Settled the other way; `app/docx_import.py` is in scope, and it is the largest single addition the
   *Answers* made.
9. **Step 6's invariant, "`margin-inline: 13px`, the first `margin-top: 11px`, the last
   `margin-bottom: 12px`."** — The effective values are **11px / 10px / 11px**;
   [taste.css L3160-L3168](app/web/static/taste.css#L3160) overrides
   [L1367-L1377](app/web/static/taste.css#L1367). Step 6 as written would fail its own check.
10. **The *Answers*' own "its five existing callers"** (not the planner's, but it will be copied into
    the plan) — there are **ten**, listed in §6 above.

One claim I re-checked and confirmed rather than corrected: `expandedContentTypes` really is seeded
from `finding.contents.map(content => content.type)`
([app/web/static/app.js](app/web/static/app.js#L3770)), so a pseudo-type must be added to that seed
or the block renders collapsed while every real section is open.

### Invariants in play

- **The three fields must be declared on `Vulnerability` before any writer sends them.** No model
  sets `model_config`, so Pydantic v2's default `extra="ignore"` drops undeclared keys on the next
  save. Violated: the tester's typing vanishes on reload, and the importer silently imports nothing.
- **The required-check must be gated on `segment == "Asia"` in both languages.** Violated: every JH
  and GWAM report is blocked on a field it does not show, with no route to a fix.
- **The required-check must live only in `generation_issues` / the readiness panel.** Violated at
  `finding_is_complete`: `/edit` bounces to `/findings`, which has no CVSS control, and the parity
  test's `"/findings" in url` branch stops comparing the two sides at all.
- **Nothing may clear a hidden field.** Keep-and-hide holds only while the hidden case is "not
  rendered". Violated: a mis-clicked segment dropdown destroys every finding's CVSS value at once.
- **`docx_import`'s `contents` literal stays five entries in that order.** Violated: `contents[3]`
  writes the fresh proof-of-concept fragments into the wrong section, silently.
- **`allow_letters` defaults to `True`.** Violated: ten call sites change message and the Setup
  parity test fails.

### Both-sides warning

Four rules in this change are implemented twice and must move together:

| Rule | Python | JavaScript |
|---|---|---|
| CVSS required on Asia | `generation_issues` ([app/docx_report.py](app/docx_report.py#L94)) | the per-finding block in `updateReadinessPanel` ([app/web/static/app.js](app/web/static/app.js#L3432)) |
| "is this Asia" | already twice over — `main_template_path` ([L152-L158](app/docx_report.py#L152)) and `_populate_cvss_table`'s table lookup ([L610-L612](app/docx_report.py#L610)) — this change makes it three | the visibility rule in the block builder, plus the required-check above |
| CVSS Score allowlist, CVSS Vector allowlist, tickets allowlist | `invalid_character_issue` ([app/report_service.py](app/report_service.py#L58)) with the new `allow_letters` | `characterRule` ([app/web/static/app.js](app/web/static/app.js#L1445)), still trapped inside `setup()` until the hoist |
| the invalid-character *message* | the f-string at [L76-L82](app/report_service.py#L76) and `CHARACTER_NAMES` ([L22-L32](app/report_service.py#L22)) | `invalidCharacterMessage` ([L1444](app/web/static/app.js#L1444)), `characterNames` ([L1439](app/web/static/app.js#L1439)), `digitNames` ([L1442](app/web/static/app.js#L1442)) |

The readiness pair is guarded by
`tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` — **but only
once the Asia case of §4 is added**; today that test cannot see the rule. The message pair is guarded
by `test_setup_inputs_report_character_and_date_errors_before_save`, which must keep passing
unchanged across the hoist.

### Map drift

None. I re-read `content_types_for_status`, `provision`, `content_has_work`, `setup_issues`,
`setup_is_complete`, `finding_is_complete`, `scope_has_location`, `reconcile_targets`,
`sync_evidence_image_slots` and `generation_issues` against `docs/DATA_MAP.md` §6, §7 and §12 and
found no claim the source contradicts. `docs/DATA_MAP.md` is unchanged by this round.

Two corrections recorded above are to **this file's earlier rounds**, not to the map, and are left in
place there rather than rewritten: the Round 1 stylesheet table gives the superseded
13px / 11px / 12px insets (§7 above has the effective values), and the *Answers* undercount
`invalid_character_issue`'s callers (§6 above has all ten).

When this ships, DATA_MAP needs: §6 the three fields and their `""` default; §7 that `provision` does
not touch them and why that is the point; §12 four new twin rows — the required-check, the three
allowlists, the segment-derived visibility, and the third copy of the Asia test.

## Round 2 - Planner: revised plan

### What this change is, in plain terms

Three values are collected per finding — Severity Review Tickets, CVSS Score, CVSS Vector — as three
plain `str` fields on `Vulnerability`, each defaulted `""`. They are **not** a sixth `ContentType`
and there is no `Content` behind them. The editor draws them in a block titled *Additional
Information*, built from the same markup a content section uses, rendered only when at least one of
its three fields is visible — which hides it for exactly one cell of the matrix, a non-Asia Open
(New) finding. The three document tokens already exist and only change their source:
`{{severity-review-tickets}}` stops being the constant `"N/A"`, and `{{cvss-score}}` /
`{{cvss-vector}}` stop being empty strings. The importer learns to read all three back out of a
delivered document. Empty CVSS blocks generation on an Asia report and nowhere else; an empty
tickets field never blocks anything and prints `N/A`.

### What the owner's answers changed

Round 1 was written before the *Answers* existed, and two of them moved the ground under it.

**CVSS became required, which inverts the argument Round 1 was built on.** That round's central claim
was that scalar fields are unreachable from `generation_issues` and `fragmentIssues`, so "never
blocks generation" came free. The owner then ruled that empty CVSS blocks generation on Asia reports
while tickets never block. I take the Round 2 Oracle's correction in its own words: **constraint 4 is
not dissolved, it is inverted.** Two of the three values must now be reachable by both readiness
implementations, deliberately. That is a check I have to write, not a constraint I get to dodge, and
Round 1's invariant — *"a finding with all three fields empty produces zero issues and leaves
`#generate-report` enabled"* — is false on an Asia report. Off Asia it still holds exactly as written.

**The import round trip came into scope.** Round 1 recommended adding nothing to
[app/docx_import.py](app/docx_import.py); the owner chose the round trip, knowing it pays nothing
today because every document generated so far writes empty CVSS cells and the literal `N/A` for
tickets. Round 2's Scribe settled the mechanics and I take them as given: read the Section table by
header lookup, match rows on cell 1 the title in document order, read the tickets value as the
paragraph after its literal caption, and clean **per line** rather than over the whole value.

### The shape survives; the reason it survives does not

Three scalars on `Vulnerability` are still the smaller change, and the owner's ruling widened the
margin rather than narrowing it. The required-check costs roughly one `if` per language in either
design, so it cancels out of the comparison. What does not cancel is the tickets field. Under a
sixth `ContentType` that value would sit inside a *printed* section, where the generic per-fragment
rules at [app/docx_report.py](app/docx_report.py#L124-L145) fire `text is required` on an empty
paragraph — so the field that must **never** block would need a named exemption in
`generation_issues` **and** in `fragmentIssues`, on top of the CVSS requirement. The scalar shape
needs the requirement and no carve-out at all.

Everything else a sixth member drags in is unchanged from Round 1 and still true: `ContentType` is a
one-way door, because once a draft stores the member, removing it makes that draft unloadable;
`content_types_for_status` would gain a segment axis and `provision` would change signature on both
sides, and the Oracle counted **seven** JavaScript call sites for that twin, not the four I claimed;
five editor and provisioning maps would each need an entry; no fragment model carries a field name,
so three fixed labelled values inside one `Content` would be positional or a new discriminated
fragment type; `docx_import`'s `contents` literal is indexed as `contents[3]`
([app/docx_import.py](app/docx_import.py#L485)) and a sixth entry could only be appended; and worst,
`provision`'s carry rule would put the tester's typed CVSS value under `content_has_work`, where a
section holding only empty fields is **silently dropped on the next save**.

So: **same shape, different argument.** Round 1 said the scalars make the problem disappear. Round 2
says the scalars make the problem small and explicit — one required-check, gated on segment, written
twice, pinned by two new cases in a contract test that exists today.

### Where the required-check goes, and the three places it must not

**Python: inside `generation_issues`'s per-finding loop**, after the evidence-image loop
([app/docx_report.py](app/docx_report.py#L107-L109)) and before `printed` is computed
([L110](app/docx_report.py#L110)). That is the last point in the loop that is not about a `Content`;
it already holds `finding` and `label`, and `report` is the function's own argument, so the segment
is free. Message shape follows its neighbours: `f"{label}: CVSS Score is required"`.

**Gated on `report.engagement.segment == "Asia"`, in both languages.** Written without that guard it
blocks every JH and GWAM report on a field those reports have no control for. This makes a **third**
implementation of "is this Asia" in `docx_report.py`, beside `main_template_path`'s string compare
([L152-L158](app/docx_report.py#L152)) and `_populate_cvss_table` inferring it from the `Section`
table's presence ([L610-L612](app/docx_report.py#L610)). Three copies of one rule is worth writing
into DATA_MAP rather than leaving for the next reader to find.

**Not in `finding_is_complete`,** and the Oracle's first reason is one I had not seen: `/edit`
redirects to `/findings` when any finding fails it ([app/main.py](app/main.py#L644)), so the tester
would be bounced off the only page carrying the CVSS control, onto one that has none — the
navigation trap arriving through the back door. Two more: `generation_issues` already calls that
function ([L101](app/docx_report.py#L101)), so the resulting line would read *"finding details or
affected locations are incomplete"* and name the wrong thing; and the Findings page keeps a **third**
incomplete list of its own ([app/web/static/app.js](app/web/static/app.js#L2266-L2274)), so the rule
would need three twins rather than two. Not in `setup_issues` either — it is per-report and would
bounce Findings back to Setup.

**JavaScript: beside `missing.push("affected location")`** in `updateReadinessPanel`'s per-finding
block ([app/web/static/app.js](app/web/static/app.js#L3432-L3441)), **not** in `fragmentIssues`.
Round 1 proposed threading the segment into `fragmentIssues`; that was both unnecessary and
wrong-shaped. Unnecessary because `report` is declared at the top of the file's single IIFE
([L13](app/web/static/app.js#L13)) and every one of these functions closes over it, so no signature
and no caller changes. Wrong-shaped because `fragmentIssues` is
`finding.contents.filter(…).flatMap(…)` — every issue it emits is about a `Content`, and these
values have none.

One mechanical consequence to design around: **push separate issue objects, do not fold them into
`missing`.** That array is joined into a single issue ([L3441](app/web/static/app.js#L3441)), so two
empty CVSS fields would count as one while the server counts two. The parity test compares only
`data-state` and the button, so it would still pass — and `#issue-count` would quietly disagree with
the length of the server's list.

### Visibility, and why keep-and-hide is the absence of code

Field visibility is the *Answers* matrix; section visibility is derived from it, so there is one rule
and not two that can drift. The block is appended only when its descriptor list is non-empty.

Keep-and-hide costs nothing because nothing in the app strips a declared field: `provision` assigns
only `contents`, `remediation.fragments` and `conclusion.fragments`; `reconcile_targets` never
deletes a vulnerability key; and `Report.model_validate` round-trips a declared field untouched
(`extra="ignore"` only drops keys the model does not declare). **The one condition is that the hidden
case must be *not rendered*, never *rendered and cleared*.** Emptying an input is a write, and a
mis-clicked segment dropdown would then destroy every finding's CVSS value at once.

### The character rules, twinned

The owner chose both languages, which reverses Round 1's recommendation of a browser-only rule. Three
allowlists, each with a Python owner and a JavaScript twin:

| Field | Python | JavaScript |
|---|---|---|
| Severity Review Tickets | `symbols=""`, `allow_letters=False`, `allow_spaces=False`, `allow_line_breaks=True` | `/^[\p{Nd}\r\n]$/u` |
| CVSS Score | `symbols="."`, `allow_letters=False`, `allow_spaces=False` | `/^[\p{Nd}.]$/u` |
| CVSS Vector | `symbols="./:"`, `allow_spaces=False` | `/^[\p{L}\p{Nd}./:]$/u` |

`invalid_character_issue` gains `allow_letters: bool = True`, threaded into `_invalid_characters` as
`(allow_letters and character.isalpha())`. The *Answers* say it has five existing callers; the Oracle
counted **ten** and listed every one, and I take ten. A `True` default leaves all ten byte-identical,
which is what the message-parity test actually pins.

Two decisions the *Answers* did not make, which follow from the code:

- **The character check is ungated by visibility; only the required-check is gated.** A valid value
  stays valid when its field is hidden, so keep-and-hide cannot strand a draft through this path.
- **The issue string is the bare field label**, identical to what the browser's `validationMessage`
  produces, exactly as the Setup pair is. Prefixing the finding title would make the two sides
  differ, and the server check is a backstop for a route the browser cannot reach — where the field
  is visible, the browser names it in place.

One hazard worth stating rather than fixing: `allow_spaces=False` on the tickets field means a pasted
trailing space is an error. The message names it — `" " (space)` — so it is discoverable, and the
owner named the allowlist explicitly, so widening it is not mine to do.

### The import round trip, and the one thing it must not do

The Scribe settled the mechanics. The decision I am adding is a consequence nobody has stated:
**`import_report` does not run the save path's validation** ([app/main.py](app/main.py#L555-L565)
calls `workspace.import_report` directly), so a value recovered from a hand-edited document could
land on disk and then 422 every subsequent save, leaving a draft the tester cannot save at all. The
importer therefore keeps only ticket lines that are entirely digits, and drops a recovered CVSS value
that fails its own rule. That is not a data-loss mitigation dressed up — a line that is not a number
is not a ticket, and the filter is the definition of the thing being read.

### Data risks, revised

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | `clear` | No new mutation path. The three values ride the existing full `PUT /reports/{id}` body, which already carries `saved_at`. Nothing new needs the `X-Report-Saved-At` header. |
| Lost update | `clear` | No new `Workspace` method and no read-then-write outside `_locked`. `save_if_current` covers these fields like every other. |
| Orphan reference | `clear` | Three opaque strings referencing no `frag_id`, `evidence_id` or `target_id`. This is what makes keep-and-hide safe where the app-type purge was not. |
| Silent stranding | **RISK (accepted)** | A stored CVSS value stops printing when the segment leaves Asia; a stored tickets value stops printing when the status becomes Open (New). Both are silent, both are deliberate, and the owner chose them over a purge. The value is preserved and returns intact when the field does. |
| Schema break | `clear` | Three defaulted `str` fields widen `Vulnerability` permissively. Every `draft.json` on disk still validates, `validate_references` has nothing new to check, no `load_path` repair is needed, and `ContentType` — the one-way door — is untouched. |
| Request/response asymmetry | `clear`, **conditional on step 1 landing first** | Declared fields round-trip. There are now **two** writers to sequence behind the model change, not one: the browser and `parse_report_docx`. Land either before the model and Pydantic drops the keys in silence — the tester watches their typing vanish on reload, and the importer looks like it works while importing nothing. |
| Rule drift | **RISK (managed)** | Four rules now exist twice: the required-check, the three allowlists, the segment-derived visibility, and the invalid-character message. Round 1 claimed the allowlists would be JavaScript-only and "asymmetric in the safe direction"; the owner settled it the other way, so every one is a twin and the drift guard has to be real. Two new cases in `test_browser_readiness_verdict_matches_server_generation_issues` and one new message-parity case are that guard. |
| Navigation trap | `clear`, **but only by construction** | Round 1 called this clear on the false premise that no field is required. The conclusion survives only because the check lives in `generation_issues` and nowhere else; in `finding_is_complete` it bounces the tester off the page holding the field. |
| Derived-state fight | `clear` | `provision` rewrites `vulnerability.contents` wholesale on every PUT and touches no other attribute. Scalars are outside its reach — the design's main dividend, and the reason the tester's CVSS value cannot be dropped by `content_has_work`. |
| Backup exhaustion | `clear` | The fields ride the existing debounced `scheduleSave`; no field triggers its own PUT, so the single `draft.bak.json` is consumed no faster than today. |
| **New: unsavable imported draft** | **RISK, closed in step 9** | The import route does not run the save path's field validation, so an unfiltered legacy ticket string would strand the draft in a permanent 422. Closed by the digits-only filter at the import boundary. |
| **New: Asia fixtures stop rendering** | **RISK, closed in step 8** | `test_every_shipped_template_renders_without_unresolved_placeholders` asserts `generation_issues(report) == []` for both Asia rows, and `_asia_multi_finding_document` renders without `allow_incomplete`. The required-check breaks all of them unless those fixtures gain CVSS values in the same step. |
| ~~Reserved-substring abort~~ | **retracted** | Round 1 raised `-vuln` in a tickets value aborting generation, and proposed a rule to close it. The owner's ticket format — digits and line breaks — makes it untypable. The latent fault in the existing free-text fields is real and is not this change's. |

### Corrections I am adopting

Ten claims from my Round 1 proposal that the Round 2 Oracle contradicted, each stated rather than
quietly dropped:

1. *"That single decision dissolves constraints 3, 4 and 7."* — true of 3 and 7 only; **4 is
   inverted**.
2. *"A finding with all three fields empty produces zero issues and leaves `#generate-report`
   enabled."* — false on Asia; two empty fields must produce two issues and disable the button.
3. *"Navigation trap: `clear` — no field is required."* — the premise is false; the conclusion
   survives only because of where the check goes.
4. *"The character allowlists are JavaScript-only."* — the owner chose both languages; they are
   twins, and so is the required-check.
5. *"Deliberately unchanged: `app/report_service.py` … `app/docx_import.py`."* — both change.
   `app/docx_report.py` additionally gains the required-check, not just the two value swaps.
   `app/storage.py` and `app/workspace.py` do genuinely stay unchanged; `app/main.py` gains one 422
   branch, not none, because the character backstop needs an enforcement point.
6. *"Absent an answer I will leave `invalid_character_issue` untouched."* — settled the other way;
   the flag is added.
7. The `-vuln` risk and the browser rule proposed to close it — dropped entirely.
8. *"Add nothing to the importer."* — settled the other way; it is the largest single addition.
9. *"`margin-inline: 13px`, first `margin-top: 11px`, last `margin-bottom: 12px`."* — the effective
   values are **11px / 10px / 11px**; [taste.css L3160-L3168](app/web/static/taste.css#L3160)
   re-declares those selectors at equal specificity and later. Step 6 as written would have failed
   its own check, which is why the verification is now a diff against a real block and not a
   constant.
10. The *Answers*' *"its five existing callers"* — there are **ten**.

One Round 1 claim the Oracle re-checked and confirmed: `expandedContentTypes` is seeded from
`finding.contents.map(content => content.type)`
([app/web/static/app.js](app/web/static/app.js#L3770)), so the pseudo-type must be added to that seed
or the block renders collapsed while every real section is open.

## Answers

### The section is visible only when one of its fields is

The owner's governing rule, in their words: *"the Additional Information content should only be
visible IF there are visible fields"*. Section visibility is therefore **derived** from field
visibility rather than stated separately, so there is one rule to own instead of two that can drift
apart.

Each field carries its own rule:

| Field | Visible when | Shape |
|---|---|---|
| Severity Review Tickets | status is Open (Previously Discovered) **or** Resolved | one ticket per line, each a 4–5 digit number; every segment |
| CVSS Score | segment is Asia | single line; numbers and `.` only |
| CVSS Vector | segment is Asia | single line; letters, numbers, `.`, `/` and `:` |

### The CVSS Vector allowlist is widened to fit a real vector

As requested the rule allowed *"letters and these symbols /: only"*, which rejects every valid CVSS
vector: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` carries digits and a period in its version
number. Harmless while the field was optional, fatal once it blocks generation — every Asia report
would hold a required field that refuses the only value anyone would type.

The owner chose to widen it to exactly the characters a real vector uses: letters, digits, `.`, `/`
and `:`. Spaces, quotes and prose stay rejected, so the rule keeps its protective intent. Validating
the CVSS grammar itself was offered and declined as too large to keep in step across two languages
and too brittle across CVSS versions.

CVSS Score keeps the requested rule, digits and `.`, which fits `7.5` and `10.0` correctly.

### A CVSS value orphaned by a segment change is kept and hidden

Moving a report off Asia hides the CVSS pair; moving it back shows the typed values again, intact.
No dialog, no clearing.

The owner chose this over purging with a confirmation and over clearing silently. Three things
argued for it. A CVSS score describes the **vulnerability**, not the segment, so a segment change
stops it being printed without making it wrong. Segment is a **report-level** setting, so a purge
would discard values across every finding at once from a single dropdown change. And it matches the
most recent decision taken in this codebase, where a status change was fixed to carry work out of
sight rather than delete it.

This is the third precedent for orphaned data in the app and it now has two votes; the purge-with-
confirmation used when an app type is dropped stays the exception, justified there because the
stranded object is a whole finding rather than a field.

### The character rules live in both languages

Browser rule for feedback as the user types, Python rule as the backstop, and a parity test asserting
the two agree. This follows the setup page, where `invalid_character_issue` already backs
`characterRule` for application name, user roles, usernames, limitations and test times, and where
the code carries warnings about the seam in both languages — *"checking it here would 422 a save"* in
Python, *"a character legal here but not there would 422 the save that accepts it"* in JavaScript.

`invalid_character_issue` needs an `allow_letters` flag to express CVSS Score's digits-and-period
rule, defaulted to `True` so its five existing callers keep their behaviour.

### Verified: `-vuln` in any document text aborts generation, and the ticket format sidesteps it

Checked directly rather than taken from the planner's report. `_unresolved_placeholders` ends with:

```python
unresolved.update(marker for marker in UNRESOLVED_MARKERS if marker in lower)
```

`lower` is the **entire finished document** casefolded, and `UNRESOLVED_MARKERS` contains `"-vuln"`.
So any text anywhere in the document containing `-vuln` in any case raises `ReportGenerationError:
Unresolved template placeholders: -vuln`. A ticket reference such as `SEC-VULN-1234` casefolds to
`sec-vuln-1234` and trips it.

**The owner's ticket format closes this for the new field.** A severity review ticket is only ever a
4–5 digit number, so the field's allowlist is digits and line breaks, and `-vuln` cannot be typed
into it. The planner's proposed marker-narrowing and its twinned validation rule are both dropped;
neither is needed.

**The latent fault remains for existing free-text fields** and is out of scope here. A description
containing `non-vuln` fails generation today with a message naming a template placeholder rather than
the text the user wrote. Worth its own change; not this one.

### The tickets rule checks characters, not length

Digits and line breaks, with no check that a line is 4 or 5 digits long. Enforcing the exact length
was offered — it would catch a dropped or doubled digit, which a character rule cannot — and declined
in favour of a rule that does not need code changes if the tracker ever issues a longer number.

### All three values survive a document import

Importing a finished report as a new draft reads the tickets paragraph and both CVSS cells back out
of the document.

The owner chose this knowing it pays nothing today: every report generated so far writes empty
strings into the CVSS cells and the literal `N/A` for tickets, so importing an existing document
yields three empty values. The return arrives with next year's documents.

**This is the one answer that enlarges the change**, and into `app/docx_import.py`, which no round has
examined yet. Round 2 opens there. Known unknowns for it to settle: whether the importer reads Asia
templates at all, how a CVSS row is matched back to the finding it describes, and whether a literal
`N/A` or an empty cell imports as an empty field rather than as that text.

Which gives one hidden cell and five visible ones:

| Segment | Open (New) | Open (Previously Discovered) | Resolved |
|---|---|---|---|
| Asia | CVSS pair only | all three | all three |
| JH, GWAM | **hidden** | tickets only | tickets only |

The owner's earlier bullet *"not visible… if segment is asia and open (new)"* contradicted both the
bullet after it and the governing rule; read as **not** Asia, matching their opening sentence *"if
the segment is JH and the finding is Open (New), then it is not visible"*.

### Severity Change and Severity Review Tickets are one field

The first draft named it *Severity Change*; the rules that follow, and the clarification, call it
*Severity Review Tickets* throughout and list exactly three fields. The *"one value per line"*
requirement belongs to it.

### Only Severity Review Tickets is optional

Corrected by the owner after Round 1, and it reverses that round's framing:

| Field | Empty at generation |
|---|---|
| Severity Review Tickets | **allowed** — prints the literal `N/A` |
| CVSS Score | **blocks generation** |
| CVSS Vector | **blocks generation** |

A field can only block while it is visible, so the CVSS pair blocks on Asia reports and cannot block
anywhere else — a JH report has no such field to leave empty.

**This undoes the Round 1 proposal's structural escape.** That plan put the three values outside
`contents` precisely so nothing could reach them from `generation_issues`, which dissolved the
"never blocks" constraint by construction. Two of the three must now be reachable, so the check has
to be written deliberately rather than avoided:

- `generation_issues(report)` already takes the whole report, so it can see the segment. No
  signature change on the Python side.
- Its browser twin `fragmentIssues(finding)` takes only the finding, so the segment must reach it.
- `test_browser_readiness_verdict_matches_server_generation_issues` already compares the browser's
  verdict against the server's, so a new rule in one language and not the other fails a test that
  exists today rather than reaching a user.

### Tickets print with a `GRIMPEN-` prefix that is never stored

Added by the owner after the plan was agreed, and it changes Steps 4 and 9 only. The finding still
stores bare digits, one per line, so nothing about the model, the validation or the editor moves.
The prefix is applied when the document is written and removed when a document is read.

| Stage | `3523` and `4111` look like |
|---|---|
| Typed, and stored in the draft | `3523`⏎`4111` |
| Printed in the document | `GRIMPEN-3523`⏎`GRIMPEN-4111` |
| Read back by the importer | `3523`⏎`4111` |

**Emit one format, accept many.** The generator always writes `GRIMPEN-` and nothing else. The
importer is deliberately looser, because the owner reports real documents varying: some carry the
prefix, some do not, and some put several tickets on one line separated by commas rather than on
separate lines.

The importer therefore splits on line breaks, commas and semicolons, trims each piece, removes a
leading letters-and-hyphen prefix whatever those letters are, and keeps the piece only if what
remains is entirely digits. Any other tracker key an older report used is accepted, since the digit
test is what actually guards the value.

**It does not extract digit runs from surrounding text**, which was the obvious alternative and is
the wrong one. `GRIMPEN-3523 (closed 2024)` would yield `2024` as a second ticket, putting a
fabricated reference into a client report with nothing to catch it. Requiring the whole piece to
reduce to digits drops that line instead. A dropped ticket is one the tester retypes after seeing the
gap; an invented one is not noticed at all.

**No length bound on the import filter**, despite tickets being 4–5 digits in practice. The rule to
hold is that *the importer accepts exactly what the field accepts* — no more, so an imported draft
can never hold a value the save path would 422, and no less, so a legitimate six-digit ticket in an
old report is not silently discarded by a rule the field itself does not impose.

## Agreed plan

Ten steps. The tree is working after each: tests green, app usable, and no window in which a writer
sends a field the model does not declare or a required field exists with no control to fill it.

**Word is not needed for any step.** Every test named below runs on macOS. The two suites that cannot
run here are the two Word-automation tests named in `.github/copilot-instructions.md`
(`test_complete_report_saves_generated_docx_to_generated_folder` and
`test_generate_docx_route_uses_template_and_report_filename`); neither is touched by this change.
Two questions are Word's alone and are deliberately left open: whether a multi-line tickets value
splits across a page boundary away from its label, and how a full CVSS v3.1 vector wraps in its
column.

- [x] **Step 1 — Declare the three fields on `Vulnerability`**

  [app/models.py](app/models.py#L199): `severity_review_tickets: str = ""`, `cvss_score: str = ""`,
  `cvss_vector: str = ""`, with one comment recording that these are tester inputs the document
  prints rather than sections of it, and that `""` is already what both output paths mean by "print
  nothing". `ContentType` ([L34](app/models.py#L34)) is **not** touched. `cvss_score` is a `str` and
  not a `float` because autosave fires mid-keystroke, so `9.` has to be storable and `9.0` must not
  be reformatted. Nothing else in this step.

  *Test:* [tests/test_app.py](tests/test_app.py) — a `draft.json` written without the three keys
  loads with all three `""`, and a `PUT /reports/{id}` carrying values returns them in the response
  report.
  *Invariant:* every draft already on disk still validates, and the server returns every field the
  client sends.
  *Without Word:* yes.

- [x] **Step 2 — Express the three character rules in Python, with an enforcement point**

  [app/report_service.py](app/report_service.py#L34): `_invalid_characters` gains
  `allow_letters: bool = True` and its bare `character.isalpha()` becomes
  `(allow_letters and character.isalpha())`. Thread the keyword through `invalid_character_issue`
  ([L58](app/report_service.py#L58)) and `_has_allowed_characters`
  ([L85](app/report_service.py#L85)) for symmetry with `allow_numbers`. All **ten** existing call
  sites omit it — [L115](app/report_service.py#L115), [L118](app/report_service.py#L118),
  [L121](app/report_service.py#L121), [L130](app/report_service.py#L130),
  [L133](app/report_service.py#L133), [L136](app/report_service.py#L136),
  [L138](app/report_service.py#L138), [L144](app/report_service.py#L144),
  [L604](app/report_service.py#L604) and [app/main.py](app/main.py#L613) — so every existing message
  stays byte-identical.

  Then `finding_input_issues(report) -> list[str]` beside `setup_input_issues`
  ([L112](app/report_service.py#L112)), skipping blank values the same way, with one named symbol
  constant per field and the flags from the table in the section above. Labels are the bare field
  names, so the string matches the browser's `validationMessage` exactly.

  [app/main.py](app/main.py#L687-L694): call it in `save_report` after the `setup_input_issues`
  block, returning 422 with code `invalid_finding` and message `Correct the invalid finding fields`.
  A separate code because `invalid_setup`'s message sends the tester to the wrong page; nothing in
  `app.js` branches on either code today, so adding one breaks nothing.

  The check is **ungated by field visibility** — a valid value stays valid while hidden, so
  keep-and-hide cannot strand a draft here. Only the required-check is segment-gated, in step 8.

  *Test:* [tests/test_app.py](tests/test_app.py) — a PUT carrying `cvss_score="9.8a"` returns 422
  `invalid_finding` naming `"a"`; a PUT carrying `severity_review_tickets="1234\n5678"` saves; a PUT
  carrying a valid vector `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` saves. Every existing
  setup-validation test passes unchanged.
  *Invariant:* `allow_letters` defaults `True`, so all ten existing callers produce the identical
  string; a bad value is refused, never silently rewritten.
  *Without Word:* yes.

- [x] **Step 3 — CVSS values reach the Asia summary table**

  [app/docx_report.py](app/docx_report.py#L622-L623): `_replace_cell_placeholder(row.cells[3],
  finding.cvss_score)` and `row.cells[4], finding.cvss_vector`, replacing the two `""` literals and
  the comment above them that says the app does not collect CVSS. The loop already holds the
  `Vulnerability` ([L614](app/docx_report.py#L614)) — no signature change, no report lookup. The
  empty-`rendered` branch ([L624-L627](app/docx_report.py#L624)) keeps writing `""` into all five
  cells.

  *Test:* rewrite
  `tests/test_docx.py::test_asia_section_rows_follow_the_rendered_finding_order`
  ([tests/test_docx.py](tests/test_docx.py#L1101-L1118)) — give `_asia_multi_finding_document`'s
  three findings a different score and vector each, assert cells 3 and 4 per row, and keep the
  row-order assertion the test already makes.
  *Invariant:* a non-Asia render is unchanged — `_optional_table` still returns `None` and the
  function still returns at [L611](app/docx_report.py#L611) before writing anything.
  *Without Word:* yes.

- [x] **Step 4 — Tickets print one prefixed value per line**

  [app/docx_report.py](app/docx_report.py#L759-L767): drop `"severity-review-tickets"` from the
  `values` dict and, after the loop, call
  `replace_component_token_runs(elements, "severity-review-tickets", [Run(text=…)])` where the text
  is the value's non-blank stripped lines each prefixed with `GRIMPEN-` and joined with `\n`, falling
  back to `"N/A"` when there are none. `_set_run_text`
  ([app/docx_components.py](app/docx_components.py#L548-L559)) turns each `\n`
  into a real `<w:br/>`; the string path `replace_component_token` uses does not, which is the whole
  reason the mechanism has to change. Line cleaning and prefixing are render-time only — one owner,
  no JavaScript twin, and the tester's stored text is never rewritten under their caret.

  The prefix is a module constant, not a setting. `N/A` is never prefixed, because it stands for the
  absence of a ticket rather than for one.

  [tests/test_docx_components.py](tests/test_docx_components.py#L67) and
  [scripts/compose_component_test.py](scripts/compose_component_test.py#L51) keep passing the token
  through `compose_docx_components`, which raises on any token it is not given. Leave both alone.

  *Test:* [tests/test_docx.py](tests/test_docx.py) — a retest finding with three ticket lines renders
  one paragraph reading `GRIMPEN-…` on each line and carrying exactly two `w:br`, counted the way
  `test_affected_locations_wrap` counts them ([tests/test_docx.py](tests/test_docx.py#L484)); an
  empty value renders a bare `N/A` with no prefix; an Open (New) finding renders unchanged.
  *Invariant:* `test_section_headings_are_kept_on_the_page_with_the_content_below_them`
  ([tests/test_docx.py](tests/test_docx.py#L828-L831)) still finds the label by exact paragraph text
  — the value must never merge into the label's paragraph.
  *Without Word:* yes. Whether a multi-line value splits from its deliberately un-`keepNext`'d label
  is Word's alone and is out of scope.

- [x] **Step 5 — Hoist the character-rule helpers to module scope**

  [app/web/static/app.js](app/web/static/app.js#L1439-L1487): move `characterNames`, `digitNames`,
  `characterName`, `invalidCharacterMessage`, `characterRule` and `showRuleState` out of
  `function setup()` ([L1432](app/web/static/app.js#L1432)) to module scope beside `rich()`
  ([L979](app/web/static/app.js#L979)). A pure move — `setup()` keeps closing over the same names.

  Leave `setupRules`, `usernameCharacters`, `componentScopeRule`, `wireSetupRule` and
  `validateSetupInputs` inside `setup()`. `wireSetupRule` stamps `data-setup-validated`, which
  `validateSetupInputs` queries ([L1500](app/web/static/app.js#L1500)); the Content page must not
  inherit that marker.

  *Test:* `tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save`
  passes unchanged — it is the one test asserting the browser's `validationMessage` is byte-identical
  to the server's issue string.
  *Invariant:* Setup validation unaltered in message, timing and `data-setup-validated` marking.
  *Without Word:* yes.

- [x] **Step 6 — The Additional Information block**

  [app/web/static/app.js](app/web/static/app.js#L3930): `additionalInformationFields(finding)`
  returning the visible field descriptors — Severity Review Tickets when
  `finding.status !== "open_new"` on every segment, CVSS Score and CVSS Vector when
  `report.engagement.segment === "Asia"`. `report` is the module-scope binding at
  [L13](app/web/static/app.js#L13); nothing is threaded.

  The builder produces `div.content-block[data-content-type="additional_information"]`, `is-expanded`
  when open, headed by a `button.content-toggle` whose innerHTML is exactly the existing three-child
  shape — `<span>Additional Information</span>`, the hidden `span.content-flag`, and a
  `<small>N field(s)</small>`. The trailing `<small>` carries `margin-left: auto`
  ([taste.css L3076](app/web/static/taste.css#L3076)) and is what centres the pill, so it is not
  decoration. The toggle reuses the same offset-measuring `onclick`.

  Each field is an `article.fragment[data-fragment-id]` holding `div.fragment-head > span.tag` (the
  field label) and its control, appended as a **direct child** of the block. A wrapper would lose the
  inset, the heading gap and the last-child gap in one stroke. `article.fragment` brings the card
  border, `--surface-raised`, the head strip and the `margin-bottom: 8px` row gap
  ([taste.css L3171-L3184](app/web/static/taste.css#L3171)) with no new CSS at all.
  `data-fragment-id` is `${finding.uid}:${field}` — the colon cannot collide with a generated
  `frag_id` (`f_` + hex), which `Report.validate_references` requires unique across the whole report
  ([app/models.py](app/models.py#L390-L393)), and it is what `showReviewTarget`'s
  `[data-fragment-id="…"]` lookup ([L3363](app/web/static/app.js#L3363)) and the `.is-incomplete`
  ring key on.

  Controls: single-line `<input>` for the CVSS pair carrying `input.evidence-caption`'s class, and a
  `<textarea>` for tickets with its own autosize written inline — there is no reusable autosize
  helper reachable from the Content page (`rich()` is contenteditable and reports `runs`, the list
  autosize is inline in `renderFragment`, and the `[data-path]` `grow` helper is trapped inside
  `setup()` and step 5 does not cover it). All three carry a native `placeholder`, because
  `.is-incomplete … :placeholder-shown` ([taste.css L3099-L3103](app/web/static/taste.css#L3099)) is
  what draws the ring. `oninput` assigns to the finding and calls `scheduleSave()`, exactly as
  `input.evidence-caption` does ([L2905-L2911](app/web/static/app.js#L2905)); the CVSS pair and the
  tickets field additionally wire `characterRule` to `setCustomValidity` and `showRuleState` under a
  marker other than `ruleInvalid`.

  The block is appended to `box` after the `printedContents.forEach` loop
  ([L4014-L4016](app/web/static/app.js#L4014)) and before `pane.append(box)`, **only when the
  descriptor list is non-empty** — which is the whole of the section-visibility rule, and hides it
  for exactly one cell of the matrix. The `expandedContentTypes` seed
  ([L3770](app/web/static/app.js#L3770)) gains the pseudo-type; `contentNames`
  ([L118](app/web/static/app.js#L118)) gains `additional_information: "Additional Information"` so
  `typeByLabel` resolves it and the pill can count; the readiness `order` array
  ([L3454](app/web/static/app.js#L3454)) gains it at the end, or an unknown type ranks `-1` and its
  issues sort above everything else.

  **Nothing clears a hidden field.** The hidden case is achieved by not rendering the row.

  *Test:* [tests/test_browser.py](tests/test_browser.py) — the five visible cells and the one hidden
  cell of the *Answers* matrix; a typed value survives a reload; and a message-parity case asserting
  a bad CVSS Score's `validationMessage` equals what `invalid_character_issue` returns for the same
  value, mirroring the Setup parity test.
  *Invariant:* `updateReadinessPanel` and `refreshContentOffers` both tolerate a
  `[data-content-type]` block with no backing `Content` — the latter returns early on `if (!content)`
  ([L3620-L3622](app/web/static/app.js#L3620)) — and the existing test that toggles every
  `.content-block` on the page ([tests/test_browser.py](tests/test_browser.py#L3483)) still passes.
  *Without Word:* yes.

- [x] **Step 7 — Styling in sync**

  Join the new input class to `.evidence-caption`'s rules in **all three** places:
  [taste.css L1796](app/web/static/taste.css#L1796),
  [taste.css L3543](app/web/static/taste.css#L3543) and
  [overrides.css L271](app/web/static/overrides.css#L271). Miss one and the field loses either its
  width or its font size. Add whatever the tickets textarea needs beyond that — line height and a
  minimum height — in the same three places.

  *Test:* none. CSS is exempt under the repo's scope map.
  *Verification:* a screenshot of the new block beside an existing section, plus the computed
  `margin-inline`, `margin-top` and `margin-bottom` of each direct child **read out of the page and
  diffed against an existing `.content-block`'s children**, not against constants. Round 1's
  13 / 11 / 12 was wrong — [taste.css L3160-L3168](app/web/static/taste.css#L3160) re-declares those
  selectors at equal specificity and later, so the effective values are **11px / 10px / 11px**. The
  diff is the check precisely so a third re-declaration cannot make it stale.
  *Invariant:* every direct child of the new block reports the same computed insets as the direct
  children of a neighbouring content section.
  *Without Word:* yes.

- [x] **Step 8 — The required-check, both languages, with its parity cases**

  **Python** — [app/docx_report.py](app/docx_report.py#L107-L110): inside `generation_issues`'s
  per-finding loop, after the evidence-image loop and before `printed` is computed, gated on
  `report.engagement.segment == "Asia"`, two lines in the shape
  `f"{label}: CVSS Score is required"`. This is the third implementation of "is this Asia" in the
  file; DATA_MAP records it as such in step 10.

  **JavaScript** — [app/web/static/app.js](app/web/static/app.js#L3432-L3441): in
  `updateReadinessPanel`'s per-finding block, beside `missing.push("affected location")`
  ([L3437](app/web/static/app.js#L3437)), reading the same segment off the module-scope `report`.
  Push **separate** issue objects carrying `contentType: "additional_information"`,
  `contentLabel: contentNames.additional_information` and the field's `fragmentId`; folding them into
  `missing` would count two empty fields as one while the server counts two.

  **Neither rule goes in `finding_is_complete` or `setup_issues`,** for the reasons in the reasoning
  section above.

  **Fixtures move in this step or the suite breaks.** `test_every_shipped_template_renders_without_unresolved_placeholders`
  asserts `generation_issues(report) == []` for both Asia rows
  ([tests/test_docx.py](tests/test_docx.py#L984)), and `_asia_multi_finding_document`
  ([L1031](tests/test_docx.py#L1031)) and `test_asia_section_references_are_marked_for_word_to_compute`
  ([L1124](tests/test_docx.py#L1124)) both render without `allow_incomplete`. Step 3 already gives
  `_asia_multi_finding_document` its values; `_component_report`'s Asia cases need them here.

  *Test:* two new cases in
  `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`
  ([tests/test_browser.py](tests/test_browser.py#L3752)) — Asia with both CVSS fields empty must read
  `issues` and disable Generate on both sides, Asia with both filled must read `ready` and enable it.
  The fixture sets segment `JH` ([L61](tests/test_browser.py#L61)) and all twelve existing cases
  mutate that one report, so without these two the test cannot see the rule in either language. Plus
  named `generation_issues` tests in [tests/test_app.py](tests/test_app.py): JH with empty CVSS
  raises no new issue, Asia with empty raises two, Asia with both filled raises none.
  *Invariant:* the check is gated on segment in **both** languages, or every JH and GWAM report is
  blocked on a field it never shows; and it stays out of `finding_is_complete`, or the parity test's
  `"/findings" in url` branch ([tests/test_browser.py](tests/test_browser.py#L3763-L3767)) swallows
  the new cases and stops comparing the two sides at all.
  *Without Word:* yes.

- [x] **Step 9 — The import round trip**

  [app/docx_import.py](app/docx_import.py#L47-L50): lift the literal
  `"Severity Review Ticket (if applicable):"` to a named constant that `BOILERPLATE` is then built
  from, rather than adding a second copy that can drift from the first.

  **Tickets** — a branch in `_findings`'s element loop
  ([app/docx_import.py](app/docx_import.py#L456-L467)), **not** in `_build_fragments`: for a retest
  finding the label falls after `In Conclusion:`, and `_findings` hard-codes that section to `[]`
  ([L481](app/docx_import.py#L481)), so `_build_fragments` never runs for it and a reader placed
  there would never fire. Capture the label and the paragraph that follows it, `continue` on both so
  neither reaches `sections[current]`.

  Normalise through one new helper, since the formats in the wild vary. `runs_of` has already turned
  each `<w:br/>` into `\n`. Split on line breaks, commas and semicolons; `_clean` each piece; drop a
  leading `[A-Za-z]+-` prefix case-insensitively, so `GRIMPEN-3523` and any older tracker's key both
  reduce; keep the piece only if what remains is non-empty and entirely digits; rejoin with `\n`.

  Three things that helper must not do. It must not run `_clean` over the whole value — that is
  `" ".join(value.split())` and flattens three tickets into one space-separated line. It must not
  extract digit runs from within a piece, or `GRIMPEN-3523 (closed 2024)` yields a fabricated `2024`.
  And it must not impose a 4–5 digit bound, so that it accepts exactly what step 2's rule accepts and
  can never write a value that would 422 every later save, nor drop a longer ticket the field itself
  would allow. `N/A` survives none of the tests and maps to `""`, which is the point — every document
  generated before this change carries that literal.

  **CVSS** — `_find_table(document, "Section")`, spelled exactly, because `docx_import._find_table`
  compares `== header` case-sensitively ([L313](app/docx_import.py#L313)) while
  `docx_report._find_table` casefolds. An absent table returns nothing and carries on, following
  `_scope_rows` ([L322-L323](app/docx_import.py#L322)) and **not** `_summary_rows`, which raises —
  three of the four templates have no Section table. Claim rows on cell 1, the title, in document
  order, immediately after `unclaimed.remove(row)` ([L451](app/docx_import.py#L451)) and **before**
  the `RETAINED_STATUSES` drop, so a Resolved finding consumes its own row and every later row stays
  aligned. Normalise both sides with `" ".join(cell.text.split())` to match the heading
  normalisation at [L424](app/docx_import.py#L424). Never pair by row index — the table carries a row
  per rendered finding while the importer's output omits every Resolved one. Never read cell 0: it
  holds no result run before Word and a section number after it, and neither identifies a finding.
  Put both cells through `_clean` and drop a value that fails its own character rule.

  The `contents` literal ([L476-L482](app/docx_import.py#L476)) keeps exactly five entries in exactly
  that order; the three values become keys in the finding dict at
  [L486-L492](app/docx_import.py#L486) beside `uid`, `title` and `scope`. `SECTION_HEADINGS`
  ([L39-L45](app/docx_import.py#L39)) gains **no** row — `section_of` turns its entries into content
  type keys, which would invent a sixth importer section.

  *Test:* [tests/test_docx_import.py](tests/test_docx_import.py) needs a **new** generation-clean
  `open_previously_discovered` fixture. The suite's only fixture is segment `JH`
  ([L64](tests/test_docx_import.py#L64)) and `open_new` ([L74](tests/test_docx_import.py#L74)), so it
  renders `new_finding.docx` and carries no ticket paragraph at all;
  `tests/test_docx.py::_layout_document` ([tests/test_docx.py](tests/test_docx.py#L763)) is not
  reusable because it renders `allow_incomplete=True`. The new fixture needs description,
  recommended remediation, previous proof of concept, a proof of concept with a numbered list and a
  production image carrying both `evidence_id` and a caption, and a **non-default** `in_conclusion`
  paragraph, or `generation_issues` blocks the render. Assertions: a three-line value survives a full
  **round trip** — rendered as `GRIMPEN-` on each line, imported back as `"1234\n5678\n9012"` exactly,
  which is the assertion that proves prefixing and stripping agree rather than testing either alone;
  the breaks are the point, not the digits. Then the variants, asserted against a hand-built
  paragraph rather than a render, because no generator produces them: `3454, 3453, 2323` on one line
  imports as three; a bare unprefixed `3523` imports unchanged; `OLDKEY-3523` reduces the same way
  `GRIMPEN-3523` does; and `GRIMPEN-3523 (closed 2024)` imports as **nothing**, which is the
  assertion that stops a year becoming a ticket. A second finding with no value renders `N/A` and
  imports as `""`; an Asia render in the shape of
  `_asia_multi_finding_document` with a different score and vector per finding **and at least one
  Resolved finding in the set** imports each retained finding's values matched by title — identical
  values would pass with a broken matcher, and the Resolved finding is what proves the match is not
  positional; and the existing `MAIN.docx` fixture imports with all three fields `""` and no
  exception.
  *Invariant:* `contents[3]["fragments"] = _empty_proof(…)` still writes into `proof_of_concept`; an
  absent Section table is tolerated, never raised on; and the importer never produces a payload that
  `save_report` would refuse.
  *Without Word:* yes — `render_report_docx` → `parse_report_docx` never touches the automation path.

- [x] **Step 10 — Documentation, in the same change**

  [docs/DATA_MAP.md](docs/DATA_MAP.md): §6 the three fields and their `""` default, and that
  `ContentType` is deliberately unchanged; §7 that `provision` does not touch them and why that is
  the point; §12 four new twin rows — the segment-gated required-check, the three allowlists, the
  segment-derived visibility, and the note that "is this Asia" now has three Python implementations —
  plus the two decisions that would otherwise be rediscovered as bugs: a hidden field is kept and
  never cleared, and a Resolved finding's tickets never round-trip because the importer drops the
  finding first.

  [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md): [L104-L107](docs/DOCX_TEMPLATE.md#L104) is directly
  contradicted — it states the app does not collect CVSS — and must be rewritten;
  [L84-L90](docs/DOCX_TEMPLATE.md#L84) names the value source per Section column and that the CVSS
  pair is per finding, not per report; a **new** row for `severity-review-tickets`, which the file
  documents nowhere today beyond the `keepNext` scope-out at
  [L206](docs/DOCX_TEMPLATE.md#L206) — which component carries it, that it owns the paragraph below
  its label, that it prints one value per line via `w:br`, that each line is prefixed `GRIMPEN-`
  while the draft stores bare digits, and that empty prints an unprefixed `N/A`; one sentence
  at [L201-L210](docs/DOCX_TEMPLATE.md#L201) recording that a multi-line value makes the uncovered
  `keepNext` case more visible; one line at [L23-L24](docs/DOCX_TEMPLATE.md#L23) that scripted
  fixtures hard-code `MAIN.docx` and so never print a collected CVSS value.

  This file: status to `shipped` with the date and commit, the checkboxes above ticked, and the
  deviations paragraph.

  *Test:* none.
  *Invariant:* no claim in either document contradicts the code shipped in steps 1–9.
  *Without Word:* yes.

### What this change deliberately does not do

- **No sixth `ContentType`.** No entry in `allowed`, `contentNames` as a section, `requiresFragment`,
  `required_fragments`, `SECTION_HEADINGS` or the seeding maps; no segment axis on
  `content_types_for_status`; no signature change to `provision` on either side; and no one-way
  `Literal` door that would make today's drafts unloadable if this were ever retreated from.
- **No purge when the segment leaves Asia.** No confirmation dialog, no clearing, no
  `dropChannelEverywhere` equivalent. The value is kept, hidden, and shown again intact.
- **No validation of the CVSS grammar**, only its characters. Offered and declined: too large to keep
  in step across two languages and too brittle across CVSS versions.
- **No length or line-count check on tickets.** Digits and line breaks, with no assertion that a line
  is four or five digits, so a longer tracker number needs no code change.
- **No narrowing of `UNRESOLVED_MARKERS`.** The `-vuln` abort is real for existing free-text fields
  and deserves its own change; the new field's digits-only rule makes it untypable there.
- **No `keepNext` on the ticket label.** A multi-line value makes the existing gap more visible, but
  closing it changes a test that pins the scope-out deliberately.
- **No repair pass on load.** Nothing back-fills existing drafts; the three fields default to `""`
  and every reader uses that default.
- **No `finding_is_complete` or `setup_issues` change**, so no navigation gate gains a condition and
  no page can bounce.
- **Nothing for `metadata` in `parse_report_docx`**, which is assigned at
  [app/docx_import.py](app/docx_import.py#L521) and never read again. A real dead-code finding, and
  not this change's to remove.

## What deviated

**The suites were run after the fact, not alongside the work.** The session implementing this had no
terminal until every step was written, so nothing below was observed as it was built. Once the
terminal returned, everything passed on the first run: `tests.test_app` 99 tests with only the known
Word/`pywin32` failure, `tests.test_docx_import` 17, `tests.test_docx` with components and captions
36, and `tests.test_browser` 134 with only the other known Word failure. Line endings were scanned
and nothing flipped.

**Two claims in *Answers* are wrong as written.**

- *"All three values survive a document import"* is false for a **Resolved** finding. The importer
  drops it on `RETAINED_STATUSES` before anything reads its row, so its tickets and CVSS pair are
  discarded with the finding itself. The claim holds only for retained findings. Recorded in
  `docs/DATA_MAP.md` rather than quietly corrected here, because it is the kind of thing that is
  otherwise rediscovered as a bug.
- *"No sixth `ContentType`"* holds on the server and on disk, but not in the browser.
  `additional_information` exists client-side as a pseudo-type in `contentNames`,
  `expandedContentTypes`, the readiness ordering and `data-content-type`. It never reaches
  `Content.type`, `provision`, or a draft file. The distinction matters to anyone grepping for it.

**Step 7 touched four stylesheets rules, not three.** The plan named `taste.css` twice and
`overrides.css` once. There is a fourth: a narrow-viewport media query in `taste.css` that also sets
`.evidence-caption`'s font size. Left alone, the new controls would keep their full-size type on a
narrow screen while every neighbouring caption shrank — precisely the drift the step existed to
prevent.

**Step 9 used `allow_incomplete=True` for the row-matching test.** The plan asked for a
generation-clean multi-finding Asia fixture carrying a Resolved finding. Building one blind, with no
way to run it, was the larger risk; the test renders with `allow_incomplete=True` instead. It still
proves the point it was written for, because the Resolved finding is dropped by the importer either
way. A generation-clean version would be stronger and is worth doing when the suite can be run.

**The importer validates CVSS with local Unicode-category predicates** rather than calling
`report_service`. `_valid_cvss_score` uses `isdecimal()` plus `.`, and `_valid_cvss_vector` uses
`isalpha()` / `isdecimal()` plus `./:`, exactly matching save validation while avoiding a new import
edge into `report_service`. Stress testing found that the original ASCII regexes silently dropped
Unicode values that the save route and generator accepted.

**Tickets are filtered with `isdecimal`, not `isdigit`.** `isdigit` accepts superscripts, which the
save rule's `allow_numbers` does not, so the looser test could have produced a value that then
failed every save.

**Line numbers in *Coordinator notes* have drifted** now the code has moved:
`{{severity-review-tickets}}` from L764 to L772-L776, and `_populate_cvss_table` from L607 to
L614-L632.

**Step 7's visual verification was completed on 2026-09-19.** Desktop and 390 px screenshots showed
the three field cards contained with no overlap; the mobile block had equal `scrollWidth` and
`clientWidth`. The single-line CVSS controls had no computed-style differences from the existing
evidence caption across typography, padding, border, colour and minimum height. The multiline ticket
field deliberately keeps the existing direct-fragment textarea's monospace treatment.

**Stress testing on 2026-09-19 changed three behaviors.** Additional Information cards now accept
programmatic focus so readiness jumps land accessibly; visible invalid values now join readiness and
disable Generate until corrected; and the editor consumes Python's cached Unicode letter/decimal
ranges rather than Chromium's newer category database. Exact validation messages now share ASCII
letter names and a `Unicode U+XXXX` fallback. Regression tests were observed failing against each
unfixed behavior before the fixes were restored.

