# GDT segment and Closed status

> **Status:** shipped · 2026-09-22 · `e998ab5`

## Request

> add another segment, GDT. And another status, Closed.

## Coordinator notes before Round 1

**Size: large.** Both are `Literal` types on the model, so this is a schema change that every
`draft.json` on disk is measured against. The ladder says both rounds, always.

**It reaches the Word document, so the scribe is in.** Segment selects the master template and status
selects the finding component, so neither can be added without deciding what the document does with
it.

**The baseline, read from source rather than recalled:**

```python
Segment = Literal["JH", "GWAM", "Asia"]
Status  = Literal["open_new", "open_previously_discovered", "open_resolved_on_non_prod", "resolved"]
```

Status already has **four** members, not three. `open_resolved_on_non_prod` exists and is easy to
miss; any rule that enumerates statuses has to account for it, and a plan built on a three-status
baseline would be wrong before it started.

**What each axis already drives**, as the reason the scribe is needed:

| Axis | Reaches |
|---|---|
| Segment | `main_template_path` picks between four masters on the Asia axis; `{{segment}}`; the export filename; the Asia-only CVSS table and its required-field rule, which is a Python/JavaScript twin |
| Status | which finding component renders (`new_finding.docx` or `retest_finding.docx`); `STATUS_LABELS`; `content_types_for_status`; the summary table's status column; `STATUS_BY_LABEL` and the retained/dropped rule on import |

**The open question neither agent can answer** is what these two new values *mean* — what a GDT
report should look like, and how Closed differs from the Resolved that already exists. Both rounds
below report on what exists; the semantics come from the owner under *Answers*.

## Round 1 - Oracle: how it works today

**Answer.** `Segment` and `Status` are bare `Literal` aliases in [app/models.py](app/models.py#L10)
and [app/models.py](app/models.py#L32) with no enum object, no label table beside them, and no
iteration anywhere — every consumer hardcodes the members it cares about. Adding a member to either
Literal makes the value *storable* but not *reachable and not printable*: the browser builds both
pickers from its own hardcoded lists, and the document layer looks values up in dicts that raise
`KeyError` rather than falling back. A status is the more dangerous of the two, because
`STATUS_LABELS[finding.status]` is a subscript on the generation path and `provision` contains a
bare `next(...)` that assumes `recommended_remediation` is always printed.

### 1. The two Literals, and what a draft holding an unknown value does

| | Definition | Field |
|---|---|---|
| Segment | `Literal["JH", "GWAM", "Asia"]`, [app/models.py](app/models.py#L32) | `Engagement.segment: Segment \| None = None`, [app/models.py](app/models.py#L239) |
| Status | `Literal["open_new", "open_previously_discovered", "open_resolved_on_non_prod", "resolved"]`, [app/models.py](app/models.py#L10) | `Vulnerability.status: Status = "open_new"`, [app/models.py](app/models.py#L207) |

`Status` has **four** members. `open_resolved_on_non_prod` behaves as an *open* status everywhere
(it is not `open_new`, so it takes the retest template and the five-section list; it is not
`resolved`, so the conclusion sentence reads "Open" and the remediation stays editable). Any rule
written as "open vs resolved" already has three members on the open side.

**A `draft.json` holding an unknown value is not repaired and does not fall back — it fails to
load.** There is no `before` validator, no coercion, and no default-on-invalid for either field.
The path:

- [`Workspace.load_path`](app/workspace.py#L271) repairs only empty list items and stale resolved
  remediation, then ends at `Report.model_validate(draft)` ([app/workspace.py](app/workspace.py#L300)),
  which raises `ValidationError`.
- `ValidationError` subclasses `ValueError`
  (`.venv/lib/python3.14/site-packages/pydantic_core/_pydantic_core.pyi:660`), so
  [`Workspace.list_reports`](app/workspace.py#L120) — which catches `(KeyError, OSError, ValueError)`
  — silently **skips the report**, and it disappears from the manager's normal list.
- [`Workspace.list_legacy_reports`](app/workspace.py#L132) re-reads it, joins the pydantic messages
  into `reason`, and marks `repairable` only when the reason contains `"duplicate fragment id:"`.
  An unknown Literal member therefore lands in the legacy list as **not repairable**, with no
  in-app action.
- [`main.report_or_404`](app/main.py#L158) turns the same error into **HTTP 422**, and
  [the HTTPException handler](app/main.py#L192) renders "This report cannot be opened yet."

Note the asymmetry with DOCX import, which *does* have a fallback: `FALLBACK_STATUS`
([app/docx_import.py](app/docx_import.py#L62)) covers an unknown status **label read out of a Word
table**, never an unknown value in a draft.

### 2. Every place that enumerates statuses, and what an unhandled member does

| Site | File | An unhandled new status… |
|---|---|---|
| `content_types_for_status` | [app/report_service.py](app/report_service.py#L251) | **Falls through to the five-section list.** `if status == "open_new"` … `return [description, recommended_remediation, previous_proof_of_concept, proof_of_concept, in_conclusion]`. Silent, and behaves exactly like `resolved`/`open_previously_discovered`. |
| `provision` — carried sections | [app/report_service.py](app/report_service.py#L281) | Harmless while the five-section list is returned: nothing is unprinted, so nothing is carried. |
| `provision` — remediation | [app/report_service.py](app/report_service.py#L312) | **`StopIteration` → HTTP 500** *if* a new status ever returns a section list without `recommended_remediation`. `remediation = next(content for content in vulnerability.contents if content.type == "recommended_remediation")` has no default. It is reached from `main.provision_report` ([app/main.py](app/main.py#L262)) on every save, so this would break saving, not just generating. |
| `provision` — resolved boilerplate | [app/report_service.py](app/report_service.py#L313) | Takes the `else` arm: the remediation stays tester-editable and any `generated="resolved_remediation"` paragraph is stripped. A `Closed` finding would therefore be asked to write a remediation. |
| `provision` — conclusion word | [app/report_service.py](app/report_service.py#L326) | `"Resolved" if status == "resolved" else "Open"` → prints **"still Open"** for any new status. |
| `finding_is_complete` | [app/report_service.py](app/report_service.py#L804) | Truthiness only (`and vulnerability.status`). Any non-empty status passes. No change needed. |
| `generation_issues` | [app/docx_report.py](app/docx_report.py#L97) | Uses `content_types_for_status` at [L119](app/docx_report.py#L119), so it silently applies the five-section rules. No raise. |
| `STATUS_LABELS` — summary table | [app/docx_report.py](app/docx_report.py#L517) | **`KeyError` → HTTP 500.** `finalized_report` catches only `ReportGenerationError` and `RuntimeError` ([app/main.py](app/main.py#L536)), so a `KeyError` escapes to the global handler ([app/main.py](app/main.py#L204)) as "Something went wrong" with a log reference. |
| `STATUS_LABELS` — finding component | [app/docx_report.py](app/docx_report.py#L769) | Same `KeyError`, same 500. |
| finding template choice | [app/docx_report.py](app/docx_report.py#L759) | `"new_finding.docx" if status == "open_new" else "retest_finding.docx"` — silently takes the retest component. Only `retest_finding.docx` carries `{{severity-review-tickets}}`. |
| conclusion/previous-PoC anchors | [app/docx_report.py](app/docx_report.py#L790) | `if finding.status != "open_new"` — silently renders both extra anchors. |
| `STATUS_BY_LABEL` / `LABEL_BY_STATUS` / `FALLBACK_STATUS` | [app/docx_import.py](app/docx_import.py#L54) | A *new* status is unreachable on import: its printed label is not in `STATUS_BY_LABEL`, so [L658](app/docx_import.py#L658) stores `FALLBACK_STATUS` and the user gets the "was imported as Open (Previously Discovered)" warning at [L783](app/docx_import.py#L783). Round-trip of a Closed finding would therefore **silently downgrade it**. |
| import section-structure check | [app/docx_import.py](app/docx_import.py#L887) | `if row["status"] != "open_new"` picks the five-section expectation; an unknown label additionally relaxes the check at [L895](app/docx_import.py#L895). |
| retest drop rule | [app/docx_import.py](app/docx_import.py#L947) | `if mode == "retest" and row["status"] == "resolved": dropped`. A new status is **kept** on retest, unchanged ([L987](app/docx_import.py#L987)). |
| editable resolved-remediation check | [app/docx_import.py](app/docx_import.py#L962) | Skipped for a new status. |
| import summary `status_counts` | [app/docx_import.py](app/docx_import.py#L1190) | Iterates `STATUS_BY_LABEL.values()`, so a new status is simply **absent from the count** — the manager's "3 findings · 2 Open New" line would under-report. |
| `statuses` (browser) | [app/web/static/app.js](app/web/static/app.js#L119) | See §4 — the value is **unselectable**. |
| `optionLabel` | [app/web/static/app.js](app/web/static/app.js#L277) | Falls back to `value.replaceAll("_"," ")` title-cased. Non-fatal, wrong-looking. |
| `contentTypesForStatus` (browser) | [app/web/static/app.js](app/web/static/app.js#L1078) | Same fall-through as Python. |
| `provision` (browser) | [app/web/static/app.js](app/web/static/app.js#L1090) | `const remediation = vulnerability.contents.find(...)` then `remediation.fragments = …` at [L1105](app/web/static/app.js#L1105) — **`TypeError` in the editor** if a new status ever drops that section. Uncaught, so the page stops rendering. |
| `syncConclusion` | [app/web/static/app.js](app/web/static/app.js#L1055) | `=== "resolved" ? "Resolved" : "Open"`. |
| `offerConclusionRewrite` | [app/web/static/app.js](app/web/static/app.js#L1131) | Same ternary. |
| `pendingLibraryOffers` | [app/web/static/app.js](app/web/static/app.js#L1433) | Suppresses the remediation offer only for `resolved`; a new status keeps the offer. |
| status `<select>` render | [app/web/static/app.js](app/web/static/app.js#L2565) | Built from `statuses`. |
| status `onchange` | [app/web/static/app.js](app/web/static/app.js#L2593) | Uses `contentTypesForStatus`; `replacesRemediation` at [L2599](app/web/static/app.js#L2599) is `resolved`-only. |
| `additionalInformationFields` | [app/web/static/app.js](app/web/static/app.js#L3455) | `status !== "open_new"` → a new status shows Severity Review Tickets. |
| `updateReadinessPanel` / `fragmentIssues` | [app/web/static/app.js](app/web/static/app.js#L3491) | Fall-through via `contentTypesForStatus`. |
| review-panel status word | [app/web/static/app.js](app/web/static/app.js#L3852) | `statuses.find(...)?.[1] \|\| finding.status` — prints the **raw key** for an unlisted status. |
| locked remediation | [app/web/static/app.js](app/web/static/app.js#L4110) | `resolved`-only. |
| manager import labels | [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels[key] \|\| key` — prints the raw key. |

**Summary of failure kinds.** Two hard failures (`STATUS_LABELS` `KeyError` → 500 on generate;
`next(...)`/`.find()` on the remediation → 500 on save and TypeError in the editor, but only if the
section list changes). Everything else is a **silent fall-through into the `resolved`-shaped
branch**, which is the more dangerous class for `Closed`: nothing raises, the document renders, and
the wrong words print.

### 3. Every place that branches on segment

| Site | File | A fourth segment… |
|---|---|---|
| `generation_issues` CVSS gate | [app/docx_report.py](app/docx_report.py#L114) | `segment == "Asia"` → non-Asia branch, CVSS not required. **Harmless, but a decision**: GDT would print no CVSS pair. |
| `main_template_path` | [app/docx_report.py](app/docx_report.py#L161) | `asia = segment == "Asia"` → **silently renders `MAIN.docx` / `MAIN_THICK_MOBILE.docx`**. Only four masters exist: `MAIN`, `MAIN_ASIA`, `MAIN_THICK_MOBILE`, `MAIN_THICK_MOBILE_ASIA` (`resources/`). **Needs a decision.** If GDT gets its own masters the stem logic must stop being a boolean. |
| `_populate_cvss_table` | [app/docx_report.py](app/docx_report.py#L616) | Does **not** read the segment — it infers Asia from the rendered template carrying a table named `Section`. So it follows whatever `main_template_path` chose. |
| `{{segment}}` token | [app/docx_report.py](app/docx_report.py#L273) | `engagement.segment or "N/A"` — prints any string. Harmless. |
| `report_export_filename` | [app/report_service.py](app/report_service.py#L237) | Sanitised passthrough with `"Unassigned"` fallback. Harmless; the export filename becomes `GDT - … - Annual Pentest 2026.docx`. |
| `setup_issues` | [app/report_service.py](app/report_service.py#L752) | Presence-only (`if not engagement.segment`). Harmless. |
| DOCX title parsing | [app/docx_import.py](app/docx_import.py#L1112) | **Hardcoded `parts[0] in ("JH", "GWAM", "Asia")`, not derived from `Segment`.** A GDT report re-imported would fail the title match, leaving `segment=None`, `app_name=""`, `report_type=None`. In `editable` mode that reaches `_editable_engagement` ([app/docx_import.py](app/docx_import.py#L575)) with a blank application name — it does not raise there, but the resulting draft is missing the three fields `setup_issues` requires. **Needs a decision.** |
| header chips | [app/web/static/app.js](app/web/static/app.js#L32) | Prints whatever string. Harmless. |
| `updateSetupValidationNotice` | [app/web/static/app.js](app/web/static/app.js#L627) | Presence-only. Harmless. |
| `requiredMetadata` gate | [app/web/static/app.js](app/web/static/app.js#L2718) | Presence-only. Harmless. |
| `additionalInformationFields` | [app/web/static/app.js](app/web/static/app.js#L3459) | `=== "Asia"` → GDT hides the CVSS fields. Harmless *given* the server twin agrees. |
| `cvssIssues` in `updateReadinessPanel` | [app/web/static/app.js](app/web/static/app.js#L3563) | `=== "Asia"` → no CVSS issues raised. Harmless *given* the server twin agrees. |
| Setup `<select>` | [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | See §4 — **unselectable**. |

So: of thirteen segment sites, only three need a decision — the master-template choice, the import
title allowlist, and (as policy, not code) whether GDT requires the CVSS pair.

### 4. The client-side lists — the half that makes a value reachable

Both pickers are hardcoded in the browser and share nothing with the server:

- **Segment:** four `<option>` elements inline in
  [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7)
  (`Select segment`, `JH`, `GWAM`, `Asia`). Nothing renders this from `Segment`.
- **Status:** the `statuses` array at [app/web/static/app.js](app/web/static/app.js#L119), a list of
  `[value, label]` pairs. It is the **only** source for the finding-row `<select>`
  ([app/web/static/app.js](app/web/static/app.js#L2565)), for `optionLabel`
  ([app/web/static/app.js](app/web/static/app.js#L277)), and for the review panel's status word
  ([app/web/static/app.js](app/web/static/app.js#L3852)).

A Literal member added server-side and not added to these two lists is **unreachable**: no tester
can select it, and `<select>`'s own behaviour makes it worse than invisible — a finding whose stored
status is not among the rendered options renders with **no option selected**, and the first
`onchange` on that row would write whatever the tester picks. There is also a third copy of the
status labels, `STATUS_BY_LABEL` in [app/docx_import.py](app/docx_import.py#L54), and a fourth,
`labels` in [app/web/static/manager.js](app/web/static/manager.js#L208).

A browser test pins the segment list verbatim:
`tests/test_browser.py::test_segment_and_report_type_are_required` asserts
`["Select segment", "JH", "GWAM", "Asia"]` ([tests/test_browser.py](tests/test_browser.py#L477)).
Adding GDT **will fail that assertion** until it is updated.

### 5. Status-driven data movement, and whether work is hidden, carried, or destroyed

`content_types_for_status` ([app/report_service.py](app/report_service.py#L251)) is the single owner:

- `open_new` → `description`, `recommended_remediation`, `proof_of_concept` (3)
- everything else → those plus `previous_proof_of_concept` and `in_conclusion` (5)

The carry rule lives in `provision` ([app/report_service.py](app/report_service.py#L281)) and its
twin at [app/web/static/app.js](app/web/static/app.js#L1090):

```python
carried = [c for c in vulnerability.contents
           if c.type not in types and c.type != "in_conclusion" and content_has_work(c)]
vulnerability.contents = [existing.get(t, Content(type=t)) for t in types] + carried
```

So: a section the status does not print, **which still holds tester work**, is kept on the model
past the end of the printed list. It is not rendered (`generation_issues` skips unprinted sections,
[app/docx_report.py](app/docx_report.py#L119); the editor filters on `printed`,
[app/web/static/app.js](app/web/static/app.js#L3491)) and it is not offered for editing, but it
survives the round trip, so switching status back restores it. **An unprinted section with no work
is dropped**, because `content_has_work` returns false and it is not in `types`.

`in_conclusion` is the deliberate exception on both sides — it is a statement *about* the status, so
it is dropped rather than carried, and re-created empty on the way back.

**Direct answer to the question asked:** if `Closed` printed *fewer* sections than `Resolved`,
existing work in the dropped sections would be **hidden and carried, not destroyed** — provided the
section holds something `content_has_work` recognises. Boilerplate the app wrote itself
(`generated` markers, or a paragraph that is *nothing but* the default conclusion sentence) does not
count as work ([app/report_service.py](app/report_service.py#L260)), so a section holding only
boilerplate **is** dropped. And `in_conclusion` is destroyed outright regardless of its contents
unless the new status also prints it.

The browser warns before this happens: the status `onchange` at
[app/web/static/app.js](app/web/static/app.js#L2593) computes `hidden` from `contentHasWork` and
raises a confirm dialog worded "Nothing is deleted, and changing the status back brings it all with
it." That wording is only true while the carry rule holds.

### 6. `docs/DATA_MAP.md` §12 — the rules that already live in two languages

Eleven rows in [docs/DATA_MAP.md](docs/DATA_MAP.md#L330) are touched by this change and each needs a
twin edit for every new value:

| §12 row | Python | JavaScript |
|---|---|---|
| status to section list | `content_types_for_status` | `contentTypesForStatus` |
| whether a section holds tester work | `content_has_work` | `contentHasWork` |
| resolved remediation boilerplate | `provision` / `RESOLVED_REMEDIATION` | `provision` / `RESOLVED_REMEDIATION` |
| the default In Conclusion sentence | `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN`, `default_conclusion_span`, `is_default_status_conclusion` | `statusConclusionRuns`, `STATUS_CONCLUSION_PATTERN`, `defaultConclusionSpan`, `isDefaultStatusConclusion` |
| which conclusion paragraph the app may write into | `provision`'s conclusion block | `syncConclusion` |
| a printed section that must never be empty | the `{description, recommended_remediation, in_conclusion}` set | `requiresFragment` |
| a conclusion still holding the app's own sentence | `generation_issues` | `fragmentIssues` |
| generation readiness | `generation_issues` | `updateReadinessPanel`, `fragmentIssues` |
| the CVSS pair is required, but only on an Asia report | the `segment == "Asia"` block in `generation_issues` | `cvssIssues` in `updateReadinessPanel` |
| which Additional Information fields a finding shows | no direct owner — the **document** says it (`new_finding.docx` vs `retest_finding.docx`; `_ASIA` templates carry the `Section` table) | `additionalInformationFields` |
| "is this report Asia" | **three** implementations in `docx_report.py` — `generation_issues`, `main_template_path`, and `_populate_cvss_table` (which infers it from the template) | **two** — `updateReadinessPanel` and `additionalInformationFields` |

The status-word ternary (`"Resolved" if … else "Open"`) is a twin the map does **not** list
separately; it is folded into the conclusion-sentence row. It appears at
[app/report_service.py](app/report_service.py#L326),
[app/web/static/app.js](app/web/static/app.js#L1057) and
[app/web/static/app.js](app/web/static/app.js#L1131), and `STATUS_CONCLUSION_PATTERN` hardcodes
`(?:Open|Resolved)` on both sides — so a fifth status wanting a *third* word breaks the
builder/recogniser pair, and every default sentence on disk stops being recognised. That is the one
twin in §12 whose failure mode is silent data rot rather than a visible error.

The only drift guard is
`tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`, which
covers generation readiness alone. Nothing guards `contentTypesForStatus`, the carry rule, or the
status label lists.

### 7. Existing drafts, and whether this is a one-way door

**Confirmed additive.** A text search for `"GDT"`, `"Closed"` and `"closed"` across `data/` returns
nothing, so no draft on disk holds either value and no existing report changes meaning when the
Literals grow. Adding a member to a `Literal` widens the accepted set; it cannot reject anything
that validated before.

**The reverse is a genuine one-way door, and it has three separate doors.**

1. **Drafts.** The moment a tester selects GDT or Closed, `draft.json` holds a value an older build
   rejects. On that older build the report is **not repairable and not openable**: `load_path`
   raises, `list_reports` skips it, `list_legacy_reports` shows it with `repairable: false`
   ([app/workspace.py](app/workspace.py#L146)), and every route returns 422. There is no migration
   path back, and `draft.bak.json` only holds the *previous* revision, so one save after the change
   is enough to strand the report on the old build if the tester saved twice.
2. **Exported bundles.** `parse_import` validates with `Report.model_validate`
   ([app/main.py](app/main.py#L338) and [L360](app/main.py#L360)), so a ZIP or JSON export carrying
   the new value is refused wholesale by an older build with a validation blob.
3. **Generated DOCX.** A `Closed` finding prints its label into the summary table
   ([app/docx_report.py](app/docx_report.py#L517)) and the detail table
   ([app/docx_report.py](app/docx_report.py#L769)). Re-importing that document on **any** build
   whose `STATUS_BY_LABEL` lacks the label silently rewrites it to `open_previously_discovered`
   ([app/docx_import.py](app/docx_import.py#L658)) with a warning
   ([app/docx_import.py](app/docx_import.py#L783)). Unlike the draft case this is not an error — the
   import succeeds and the status is quietly wrong.

### Where adding a Literal member is *not* sufficient

Ordered by the severity of the failure if missed.

| Must also change | If missed |
|---|---|
| `STATUS_LABELS`, [app/docx_report.py](app/docx_report.py#L48) | **`KeyError` → HTTP 500** on every generate and download of a report containing one such finding. Not caught by `finalized_report`'s `except (ReportGenerationError, RuntimeError)` ([app/main.py](app/main.py#L536)); the tester sees "Something went wrong" and a log reference. |
| `statuses`, [app/web/static/app.js](app/web/static/app.js#L119) | Status is **unselectable**; any finding already holding it renders its `<select>` with nothing selected, and the review panel prints the raw key `closed` ([app/web/static/app.js](app/web/static/app.js#L3852)). |
| The segment `<option>` list, [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | Segment is **unselectable**; a report already holding it renders the dropdown blank, and the first Setup edit can silently overwrite it. |
| `main_template_path`, [app/docx_report.py](app/docx_report.py#L161) | GDT **silently renders the JH/GWAM master**. No error, wrong document. If GDT needs its own master the boolean `_ASIA` suffix must become a lookup, and a missing file raises `ReportGenerationError("Template not found: …")` → HTTP 422 with the path, which is at least a clean failure. |
| `content_types_for_status` + `contentTypesForStatus`, [app/report_service.py](app/report_service.py#L251) / [app/web/static/app.js](app/web/static/app.js#L1078) | `Closed` silently gets the five-section `Resolved` shape. If instead it is given a list **without** `recommended_remediation`, `provision`'s bare `next(...)` ([app/report_service.py](app/report_service.py#L312)) raises `StopIteration` → HTTP 500 **on save**, and the browser twin ([app/web/static/app.js](app/web/static/app.js#L1105)) throws `TypeError` and stops rendering the editor. |
| `STATUS_BY_LABEL` + `LABEL_BY_STATUS`, [app/docx_import.py](app/docx_import.py#L54) | A generated `Closed` report re-imported comes back as `open_previously_discovered` via `FALLBACK_STATUS` — succeeds with a warning, so the loss is easy to miss. Also drops the status from `status_counts` ([app/docx_import.py](app/docx_import.py#L1190)). |
| The segment allowlist in the DOCX title parser, [app/docx_import.py](app/docx_import.py#L1112) | A GDT report re-imported loses **segment, application name and report type together** (the title match is one condition), producing a draft that cannot pass `setup_issues`. |
| `labels`, [app/web/static/manager.js](app/web/static/manager.js#L208) | Import summary prints the raw key (`3 closed`). Cosmetic. |
| `STATUS_CONCLUSION_PATTERN` + `status_conclusion_runs`, both sides | Only if `Closed` needs a word other than Open/Resolved. Relaxing one side without the other **freezes every default sentence already on disk** at its stored title and status, because the recogniser is the only link between builder and consumer. |
| `resources/finding_types/*.docx` | Only `new_finding.docx` and `retest_finding.docx` exist. `Closed` takes `retest_finding.docx` by the `!= "open_new"` default ([app/docx_report.py](app/docx_report.py#L759)); a distinct component needs the branch changed as well as the file added. |
| `tests/test_browser.py`, [L477](tests/test_browser.py#L477) | The segment option list is asserted verbatim; adding GDT fails this test until updated. |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L330) §12 | Per the maintenance contract, a change to `models.py` / `report_service.py` / `app.js` must update the affected section in the same change. |

**Not needed:** `finding_is_complete` and `validateFindingsPage` (truthiness only);
`setup_issues`' segment check and its two browser twins (presence only); the `{{segment}}` token and
`report_export_filename` (passthrough); `_populate_cvss_table` (infers from the template, not the
segment); `Workspace` legacy repair (no status or segment arm).

### Contradictions between source and the plans or map

None found. `docs/DATA_MAP.md` §12 matches the source on every row checked. One thing §12 does not
record, and which is load-bearing for this change: the three-way hardcoded segment tuple in
`docx_import._read_docx`'s title parser is a **fourth** copy of "which segments exist", alongside
`Segment`, the Setup `<option>` list, and the Asia branches. The map's "is this report Asia" row
covers the branches but not the allowlist.

## Round 1 - Scribe: the document side

**Answer.** On the document side the two halves of this request cost very different things. **GDT is
nearly free unless the owner wants its own master**: the segment reaches the rendered document as
exactly one printed string, on the title line, plus the template choice. **`Closed` is free only if
it prints the same five sections `Resolved` prints.** The moment it should print fewer, the document
cannot express that from code — the section headings are static paragraphs inside
`retest_finding.docx`, so a shorter Closed finding needs a third component document, authored in
Word by a person. Both of those are the same blocker: **this plan cannot code its way to a new
`.docx`.** Everything else here is a dictionary entry or a tuple member.

Two things in this section cannot be settled from the repository, and are marked where they appear:
whether `MAIN.docx` and `MAIN_ASIA.docx` differ anywhere on the **cover page**, and whether any
status cell carries a Word **content control**. The text extraction used below is blind to both.

### 1. What a fourth segment costs in templates

**The selector.** [`main_template_path`](app/docx_report.py#L160-L167) is four lines:

```python
component = any(channel in report.engagement.tested_channels for channel in COMPONENT_CHANNELS)
asia = report.engagement.segment == "Asia"          # L165
stem = "MAIN_THICK_MOBILE" if component else "MAIN" # L166
return resources / f"{stem}{'_ASIA' if asia else ''}.docx"
```

Confirmed: GDT renders `MAIN.docx` or `MAIN_THICK_MOBILE.docx`, silently.

**What actually differs between `MAIN.docx` and `MAIN_ASIA.docx`.** Measured, not recalled. The two
files cannot be diffed directly — a `.docx` is a ZIP of deflate-compressed parts — but
`graphify-out/converted/` holds a text extraction of each template, and the two extractions are
**identical line for line from the title to `{{findings}}` and through every shared table**. Asia
adds exactly two things, both at the very end, inside *Appendix: Common Vulnerability Scoring System
(CVSS)*:

1. one caption paragraph, `Table  Classification of vulnerabilities based on severity levels.`
   ([MAIN_ASIA_b33945bd.md](graphify-out/converted/MAIN_ASIA_b33945bd.md#L92) against
   [MAIN_17ec8f65.md](graphify-out/converted/MAIN_17ec8f65.md#L89), where the document simply ends);
2. one table,
   `Section | Vulnerability Name | Severity | CVSS Score | CVSS Vector`, with the prototype row
   `{{section-number}} | {{finding}} | {{rating}} | {{cvss-score}} | {{cvss-vector}}`
   ([MAIN_ASIA_b33945bd.md](graphify-out/converted/MAIN_ASIA_b33945bd.md#L185-L187)).

That agrees with the table count measured when the Asia pair was first wired up —
`MAIN_ASIA` is 13 tables to `MAIN`'s 12, `MAIN_THICK_MOBILE_ASIA` 14 to `MAIN_THICK_MOBILE`'s 13
([thick-client-app-type.md](docs/plans/thick-client-app-type.md#L697)) — and with
[docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L18-L21): *"the Asia pair adds a Section table"*.

**Only Word settles the rest.** The extraction is a derived, git-ignored artefact and it is
**demonstrably blind to cover-page shapes** — `_document_texts`
([app/docx_import.py](app/docx_import.py#L455-L461)) exists precisely because python-docx omits
paragraphs nested in cover-page text boxes, and the label `Delivered To`, which
[`_editable_engagement`](app/docx_import.py#L598) reads back out of every generated report, appears
in **no** converted file. So the honest statement is: *in body paragraphs and body tables, the Asia
master is its twin plus one caption and one table, and nothing else differs.* Whether the two covers
carry a different legal entity, logo or footer is not knowable from this repository. Opening both in
Word is the only thing that settles it, and it is worth doing before the owner decides, because it
is the one fact that could turn "GDT needs no master" into "GDT needs two".

**If GDT does get its own masters, this is what must exist.** Two new files in `resources/`,
`MAIN_GDT.docx` and `MAIN_THICK_MOBILE_GDT.docx` (four, if GDT also needs an Asia crossing — it does
not, the axes are segment and app type, so a fourth segment multiplies the app-type axis by one
more row, giving six masters in total). **Nothing in this codebase can author them.** They are
made by a person in Word, which is why the output matches house style, and no step of this plan can
produce, copy or synthesise one. That is the blocker; the code change beside it is small:
`main_template_path`'s `_ASIA` boolean becomes a per-segment suffix lookup, and its `.parent` must
still be `resources/` because the same path is the component fragment root — pinned by
[`test_main_template_path_selects_on_both_axes`](tests/test_docx.py#L1092-L1109).

**What a brand-new master must satisfy, or generation fails loudly.** Every one of these is a hard
precondition raising `ReportGenerationError` → HTTP 422 through
[`finalized_report`](app/main.py#L535-L537):

| Precondition | Where |
|---|---|
| a body paragraph reading exactly `DOCUMENT REVISION HISTORY`, and a section after it | [`_normalize_page_numbering`](app/docx_report.py#L547-L575) via [`_find_body_element`](app/docx_report.py#L540-L545) |
| a body paragraph that is **nothing but** `{{findings}}` | [`_has_exact_body_token`](app/docx_report.py#L532-L538), checked at [L196-L197](app/docx_report.py#L196) |
| tables headed `URL(s) in Scope`, `API Routes`, `Limitations`, `User Roles`, `Findings` | [`_find_table`](app/docx_report.py#L347-L352), resolved by first header cell, never by index |
| a `Findings` summary prototype: either two rows with `{{finding}}`, or five severity rows | [`_populate_summary_table`](app/docx_report.py#L492-L500) |
| exactly one placeholder paragraph per summary cell | [`_replace_cell_placeholder`](app/docx_report.py#L322-L334) |
| no surviving `{{...}}` and none of the seven markers in `UNRESOLVED_MARKERS` | [`_unresolved_placeholders`](app/docx_report.py#L1492-L1497) |

Optional, present only where the axis says so: `Component` ([L481](app/docx_report.py#L481)) and
`Section` ([L619](app/docx_report.py#L619)), both via `_optional_table`, both absent without error.

A new master also widens two tests by name: the four-row matrix in
[`test_main_template_path_selects_on_both_axes`](tests/test_docx.py#L1092) and the smoke render in
[`test_every_shipped_template_renders_without_unresolved_placeholders`](tests/test_docx.py#L1119-L1131).

### 2. Where the segment appears in the rendered document at all

**Once.** `{{segment}}` is supplied by [`_metadata`](app/docx_report.py#L272) as
`engagement.segment or "N/A"` and written by [`_replace_metadata`](app/docx_report.py#L310-L320)
across the body and every header and footer part. It is **braced-only** — `segment` is not in
`PLAIN_METADATA_TOKENS` ([L55](app/docx_report.py#L55)) — so the bare word "segment" in prose is
never rewritten.

In all four shipped masters the token occurs on the title line and nowhere else:

```
PENETRATION TEST REPORT
{{segment}} – {{app-name}} – {{test-type}} 2026
```

([MAIN_17ec8f65.md](graphify-out/converted/MAIN_17ec8f65.md#L6-L7),
[MAIN_ASIA_b33945bd.md](graphify-out/converted/MAIN_ASIA_b33945bd.md#L6-L7); same in both
`THICK_MOBILE` extractions.)

Note the separator is an **en dash**, while `report_export_filename` builds the export name with a
plain hyphen. Both are accepted on the way back in — see §7.

Nothing else inside the render branches on segment. [`_populate_cvss_table`](app/docx_report.py#L616-L621)
deliberately keys off the *presence of the `Section` table*, never `engagement.segment`, so it
follows whatever master was chosen with no second rule to keep in step.

**So: if GDT renders an existing master, the entire document cost is one printed string.** The
document would print `GDT – Northstar Banking – Annual Pentest 2026`, carry no CVSS table, and
demand no CVSS values — `generation_issues` requires the pair only for Asia
([L112-L116](app/docx_report.py#L112)) — and every other page would be byte-identical to a JH
report. That is a coherent, non-broken document. Whether it is the *right* document is the owner's
call, not something the code can be wrong about.

### 3. What a fifth status costs

**Which component a status selects.** One line,
[app/docx_report.py](app/docx_report.py#L759):

```python
template_name = "new_finding.docx" if finding.status == "open_new" else "retest_finding.docx"
```

**How `STATUS_LABELS` reaches the document.** The dict is
[L48-L53](app/docx_report.py#L48). Confirmed: **exactly two call sites**, both bare subscripts.

| Site | What it prints |
|---|---|
| [L517](app/docx_report.py#L517) | the sixth cell of the `Findings` summary table — header `Findings \| Likelihood \| Impact \| Severity \| ID \| Status` |
| [L769](app/docx_report.py#L769) | `{{status}}`, the `Status` row of the per-finding detail table, in **both** finding components ([new_finding](graphify-out/converted/new_finding_3568c9e0.md#L16), [retest_finding](graphify-out/converted/retest_finding_7b5835eb.md#L25)) |

**What the summary table prints in its status column.** The label verbatim, with **no formatting
override**. In [`_populate_summary_table`](app/docx_report.py#L509-L526) the status entry is
`(STATUS_LABELS[finding.status], None)` — a `None` font colour — and the call passes
`font_size_pt=12 if font_color is not None else None`, so unlike Likelihood/Impact/Severity the
status cell is neither recoloured nor resized. It inherits the prototype row's run formatting
exactly. The same is true of `{{status}}` in the detail table, written through
[`replace_component_token`](app/docx_components.py#L72), which preserves the run it replaces into.

**Once `STATUS_LABELS["closed"] = "Closed"` exists, the document prints `Closed` in both cells and
nothing else changes.** The label string is the whole of the status contract on the way out.

### 4. Whether the document can express `Closed` at all

**Yes — it is free text, and nothing in the template constrains it.**

- The summary cell is written by [`_replace_cell_placeholder`](app/docx_report.py#L322-L345), which
  finds the single paragraph in the cell whose flattened text matches `CELL_PLACEHOLDER`
  (`\{\{\s*[^{}]+?\s*\}\}`, [L67](app/docx_report.py#L67)) and substitutes the string. No allowlist,
  no length check, no casing rule.
- The detail cell is written by `replace_component_token`, same absence of validation.
- **No content control anywhere.** A search across the workspace for `w:sdt`, `sdtContent`,
  `dropDownList` and `comboBox` returns no hit in `app/` — every match is an ARIA `combobox` in the
  browser UI. Both extractions show a plain `{{status}}`. *Caveat, and it is a real one:* a Word
  content control added by hand inside the component `.docx` would not appear in the extraction.
  Even then the write would land — `_replace_cell_placeholder` iterates `cell._tc.iter(qn("w:p"))`,
  which descends into `w:sdtContent` — it would simply leave a dropdown holding a value outside its
  own list. Opening `resources/finding_types/*.docx` in Word is the only way to rule that out.
- **No severity colouring or counting depends on the status set.** `RATING_FONT_COLORS` is keyed by
  rating only; summary ordering is `(SEVERITY_ORDER.index(severity), title.casefold())`
  ([L505](app/docx_report.py#L505)), status-independent; and the rendered document contains **no
  per-status count at all**. The only status tally in the codebase is `status_counts` in the import
  summary ([app/docx_import.py](app/docx_import.py#L1190-L1196)), which is manager-page text, not
  document content — and because it iterates `STATUS_BY_LABEL.values()`, it picks a new status up
  for free once the label exists.

**The one genuine constraint on the string is the round trip.** Whatever `STATUS_LABELS` prints must
appear verbatim in `STATUS_BY_LABEL` ([app/docx_import.py](app/docx_import.py#L54-L59)), because the
importer matches on `cell.text.strip()` ([L654](app/docx_import.py#L654)) and on `_clean`ed detail
text ([L929](app/docx_import.py#L929)). `"Closed"` is unambiguous against the existing four and
collides with nothing.

### 5. The two finding components

Read from the extractions; the anchors are also enumerated in
[docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L258-L266).

| | `new_finding.docx` | `retest_finding.docx` |
|---|---|---|
| `{{finding_title}}` in `ReportHeading2` | yes | yes |
| `Description:` + `{{description-fragments-here}}` | yes | yes |
| `Recommended Remediation:` + `{{recommended-remediation-fragments-here}}` | yes | yes |
| `Previous Proof of Concept:` + lead-in + `{{prev-poc-fragments-here}}` | — | **yes** |
| `Proof of Concept:` + lead-in + `{{poc-fragments-here}}` | yes | yes |
| `In Conclusion:` + `{{conclusion-fragments-here}}` | — | **yes** |
| `Severity Review Ticket (if applicable):` + `{{severity-review-tickets}}` | — | **yes** |
| detail table `Severity / ID / Status / Location ×2` | yes | yes |

So retest carries **three** extra blocks, not two. The heading style on the title paragraph matters
beyond appearance: [`_populate_component_findings`](app/docx_report.py#L672-L688) finds it by
`FINDING_HEADING_STYLE` and bookmarks it `vuln_<uid>`, which is what the Asia `Section` column's
`REF` field points at — a component whose title paragraph lost that style would render an Asia report
with no section numbers and no error.

**If `Closed` takes `retest_finding.docx` and prints fewer sections, the unfilled anchors are caught
loudly.** The two optional anchors are added only for non-`open_new` findings
([L790-L794](app/docx_report.py#L790)). Suppose a `Closed` branch skipped them: the paragraphs
`{{prev-poc-fragments-here}}` and `{{conclusion-fragments-here}}` survive into the saved document and
[`_unresolved_placeholders`](app/docx_report.py#L1492-L1497) catches them **twice** — once as literal
`{{...}}` text, once as the substring `-fragments-here` listed in `UNRESOLVED_MARKERS`
([L56-L64](app/docx_report.py#L56)). Generation aborts at
[L203-L205](app/docx_report.py#L203) with `Unresolved template placeholders: …` → HTTP 422. **Nothing
is written; there is no half-finished document.** That is the good failure mode.

The mirror case fails just as loudly: a new component document with a section removed, while the code
still tries to fill it, hits [`_component_anchor_index`](app/docx_report.py#L1342-L1354) —
*"Expected exactly one {{prev-poc-fragments-here}} component anchor; found 0"* — also
`ReportGenerationError`, also 422.

**The third option is the one the owner should see, because it is what happens by default.** Keeping
`retest_finding.docx` and simply passing nothing for those sections is already handled:
[`_render_component_content`](app/docx_report.py#L890-L900) renders a single `N/A` paragraph when the
content is `None` or empty. So a `Closed` finding on the retest component with no previous PoC and no
conclusion prints the **static headings** `Previous Proof of Concept:` and `In Conclusion:` with
`N/A` beneath each. The headings are ordinary paragraphs inside the component file; no code path can
remove them. **Suppressing a section for `Closed` therefore requires a third `.docx` under
`resources/finding_types/`, authored in Word.** That is the second person-only blocker in this plan,
and it is worth noting that the cost of *not* doing it is cosmetic rather than broken —
`Open (Resolved on Non-Prod)` already prints those headings today.

One thing that is free either way: `{{severity-review-tickets}}` is written with
[`replace_component_token_runs`](app/docx_report.py#L775-L777), a no-op on a component that lacks the
token ([docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L245-L256)), so a new component may carry it or
drop it with no code change.

**Whatever is decided here must be mirrored on the import side in the same change.** `_findings`
derives `expected_sections` from the status ([app/docx_import.py](app/docx_import.py#L887-L893)) and
**refuses** any document whose section order differs
([L899-L903](app/docx_import.py#L899)) — *"…does not have the expected section structure for
Closed."* A Closed component printing three sections while the importer expects five means every
Closed report this app generates is a report it cannot read back.

### 6. The import direction

**Confirmed, including the part the oracle called silent — it is not quite silent.**

- `STATUS_BY_LABEL` [L54-L59](app/docx_import.py#L54), `LABEL_BY_STATUS` [L60](app/docx_import.py#L60),
  `FALLBACK_STATUS = "open_previously_discovered"` [L61-L63](app/docx_import.py#L61).
- [`_summary_rows`](app/docx_import.py#L646-L660) reads the sixth cell and stores both the mapped
  status, `STATUS_BY_LABEL.get(cells[5], FALLBACK_STATUS)`, **and the raw `status_label`**. Keeping
  the raw label is what makes the rest of this recoverable.
- **It warns, once per finding**, at [L782-L787](app/docx_import.py#L782):
  `"<title>" had an unrecognised status (Closed) and was imported as Open (Previously Discovered).`
  The warning reaches the user through the import summary
  ([L1199-L1207](app/docx_import.py#L1199)). So the loss is *named* — but the import succeeds, the
  draft is written, and the label is the only trace that anything was assumed. Nothing refuses.
- Two further relaxations fire for an unrecognised label, both deliberate: the section-structure
  expectation is allowed to be the three-section shape when that is what the document actually holds
  ([L895-L898](app/docx_import.py#L895)), and the summary-versus-detail status comparison is skipped
  unless **both** cells name a known label ([L926-L936](app/docx_import.py#L926)). These exist so an
  older or hand-edited report still imports; they are also exactly what would let a Closed document
  through while quietly rewriting it.
- Retained versus dropped: [L947-L949](app/docx_import.py#L947),
  `if mode == "retest" and row["status"] == "resolved": dropped`. With the fallback applied a Closed
  finding is **kept** on a retest, its proof of concept moved into `previous_proof_of_concept` and
  both current PoC and conclusion emptied ([L987-L995](app/docx_import.py#L987)).

**What the round trip needs for `Closed` to survive**, in the order the importer meets them:

1. `"Closed": "closed"` in `STATUS_BY_LABEL` — `LABEL_BY_STATUS` derives, `status_counts` follows.
2. A decision at [L887-L893](app/docx_import.py#L887) on which section shape a Closed document has —
   this is the import twin of §5 and must match the component chosen there.
3. A decision at [L947](app/docx_import.py#L947) on whether a retest drops Closed findings the way it
   drops Resolved. If `Closed` means "this is finished", dropping is the analogue; if it is kept, a
   retest will carry forward a finding nobody intends to re-test.
4. A decision at [L962-L974](app/docx_import.py#L962), the editable-mode check that a `resolved`
   finding's remediation still holds the exact generated `RESOLVED_REMEDIATION` boilerplate and
   nothing else. Whether Closed gets the same guard depends on whether Closed also replaces the
   remediation.

### 7. The DOCX title parser

**Confirmed, at [app/docx_import.py](app/docx_import.py#L1106-L1120).**

```python
app_name, segment, report_type = "", None, None          # L1109
for paragraph in document.paragraphs[:20]:
    parts = [part.strip() for part in re.split(r"\s[\u2013\u2014-]\s", paragraph.text) if part.strip()]
    if len(parts) >= 3 and parts[0] in ("JH", "GWAM", "Asia"):   # L1112
        segment, app_name = parts[0], " - ".join(parts[1:-1])
        label = re.sub(r"\s+\d{4}$", "", parts[-1])
        report_type = REPORT_TYPE_BY_LABEL.get(label)
        if mode == "editable" and report_type is None:
            raise ReportImportError(f"Unknown report type: {label}")
        break
```

The tuple is a literal, not derived from `Segment`, and the comparison is exact and case-sensitive.
The split accepts en dash, em dash or hyphen, so the en dash the masters print and the hyphen
`report_export_filename` writes both parse — GDT changes nothing there.

**What is lost when the parse fails, and why all three go together:** the three assignments are
inside one `if`, so failing the segment check means the loop never breaks and the initialisers at
L1109 stand. The result is `segment=None`, `app_name=""`, `report_type=None` — the oracle is right
that they are one unit. Two consequences worth stating precisely:

- **No error is raised.** The `Unknown report type` raise at L1116-L1117 is *inside* the matched
  branch, so a GDT title never reaches it. The import succeeds with three empty fields, handed
  straight to [`_editable_engagement`](app/docx_import.py#L575-L613) as
  `"app_name": "", "segment": None, "report_type": None`.
- **Document-side consequence, if such a draft were ever regenerated:** `main_template_path` would
  see `segment=None`, choose the non-Asia master, and `{{segment}}` would print `N/A` on the title
  line. It never gets that far in practice — `setup_issues` blocks generation on all three missing
  fields first — but that is the shape of the silent half.

This is a **one-tuple edit**; there is no second copy of the segment allowlist inside the importer.

### 8. `STATUS_CONCLUSION_PATTERN`

[app/report_service.py](app/report_service.py#L497):

```python
STATUS_CONCLUSION_PATTERN = re.compile(r'The finding ".*" is(?: still)? (?:Open|Resolved)\.', re.DOTALL)
```

**What it is for on the document side.** The pattern never reaches the rendered XML — nothing
substitutes it into a template. Its one document-layer consumer is
[`generation_issues`](app/docx_report.py#L121-L126), which calls `is_default_status_conclusion` and
**blocks generation** with `in_conclusion still holds the default sentence`. It is a gate on whether
the report may render at all, on the reasoning that the app writing its own conclusion is the same
as the section being blank. Its other duties — re-deriving the sentence when the title or status
changes, and keeping `content_has_work` from mistaking boilerplate for tester work
([app/report_service.py](app/report_service.py#L258-L262)) — are the oracle's ground.

**What a third status word does to sentences already on disk.**

- **Widening the alternation is additive and safe.** `(?:Open|Resolved|Closed)` still matches every
  sentence any existing draft or document holds, because those sentences all end in `Open.` or
  `Resolved.`, and the optional `(?: still)?` already tolerates either phrasing. Nothing freezes,
  nothing is re-matched differently.
- **The dangerous order is builder first.** If
  [`status_conclusion_runs`](app/report_service.py#L500-L508) begins emitting `… is Closed.` while
  the pattern still reads `(?:Open|Resolved)`, then for every Closed finding
  `default_conclusion_span` returns `None`, so: `provision` stops re-deriving that sentence when the
  title changes, `content_has_work` starts counting the app's own boilerplate as tester work, and —
  the document-side one — `generation_issues` **stops flagging it**, so the report generates with
  the app's placeholder sentence printed in In Conclusion. Silent, and in the delivered document.
- **Already-generated `.docx` files are unaffected either way.** The sentence lives in `draft.json`
  fragments; a finished document is only ever re-read through the importer, where In Conclusion comes
  back as ordinary paragraph fragments with no recognition of the sentence at all.

If `Closed` reuses the word `Resolved` in its sentence, none of this applies and the pattern needs no
edit. That is a semantics decision for the owner, not a technical one.

### 9. What in `docs/DOCX_TEMPLATE.md` becomes wrong

| Lines | Today | Why it breaks |
|---|---|---|
| [L11-L21](docs/DOCX_TEMPLATE.md#L11) | the 2×2 selection matrix, columns *not Asia* / `segment == "Asia"` | GDT silently lands in "not Asia". Needs at minimum a sentence saying so; needs a redrawn matrix if GDT gets masters, and the "sole owner of the choice" paragraph rewritten from a boolean to a lookup |
| [L217-L220](docs/DOCX_TEMPLATE.md#L217) | items 3 and 4 enumerate the statuses per component by name | item 4 lists three statuses; `Closed` must join it, or item 5 must name a third component |
| [L237-L238](docs/DOCX_TEMPLATE.md#L237) | *"Previous Proof of Concept and In Conclusion exist only in retest finding components"* | wrong the moment a third component exists |
| [L249-L256](docs/DOCX_TEMPLATE.md#L249) | Severity Review Tickets: *"prints for `open_previously_discovered`, `open_resolved_on_non_prod` and `resolved` … never for `open_new`"* | the same three-status enumeration, a second time |
| [L154-L158](docs/DOCX_TEMPLATE.md#L154) | *"supports these four canonical template structures"* and *"all known statuses and their printed sections"* | the count is wrong if masters are added; the statuses phrase survives by wording but is the sentence a reader will check against `STATUS_BY_LABEL` |
| [L104-L142](docs/DOCX_TEMPLATE.md#L104) | the Section table, described as Asia-only, with the CVSS requirement scoped to `segment == "Asia"` | correct as written **unless** the owner wants GDT to print CVSS |

[L56](docs/DOCX_TEMPLATE.md#L56) (`segment` → "Selected segment") needs no change: it is a
passthrough and stays true for any string.

### Document-side decisions the planner must carry to the owner

1. **Does GDT need its own master pair?** If yes, two Word-authored `.docx` files must exist before
   any code lands, and `main_template_path` stops being a boolean. If no, the document cost of GDT
   is one printed string. Worth opening `MAIN.docx` and `MAIN_ASIA.docx` in Word first — the cover
   page is the one region this repository cannot see, and it is where a segment difference would
   live.
2. **Does GDT print CVSS?** Purely a consequence of question 1: the `Section` table is the only place
   CVSS prints, and it exists only in the Asia masters.
3. **Does a `Closed` finding print the same five sections as `Resolved`?** If yes, `Closed` is a
   dictionary entry on both sides and no `.docx` changes. If no, it needs a third component document
   made in Word, **and** a matching `expected_sections` arm in the importer, or every Closed report
   this app writes is one it cannot read back.
4. **Does a retest drop `Closed` findings the way it drops `Resolved`?** One line,
   [app/docx_import.py](app/docx_import.py#L947), but it decides whether last year's Closed findings
   reappear in this year's draft.

## Round 1 - Planner: proposal and open questions

**Understanding.** Two independent widenings of two `Literal` aliases, bundled by the request but
not by the code: `Segment` gains `GDT` and `Status` gains `closed`. Neither is a feature — each is a
value that must become *storable*, then *printable*, then *readable back*, then finally *selectable*,
in that order, because the moment a picker offers it a draft on disk can hold it and every consumer
downstream must already know what to do. The cheapest correct version of both ships without a single
new `.docx`: GDT renders the existing non-Asia master and prints one extra string on the title line;
`Closed` prints the same five sections `Resolved` prints, on `retest_finding.docx`, exactly as
`open_resolved_on_non_prod` already does. Everything beyond that cheapest version is gated on a
person opening Word, and I have written those as preconditions rather than steps because no code
path in this repository can satisfy them.

### Blast radius

| File | What changes | Twin |
|---|---|---|
| [app/models.py](app/models.py#L10) | `Status` gains `"closed"` | — |
| [app/models.py](app/models.py#L32) | `Segment` gains `"GDT"` | — |
| [app/docx_report.py](app/docx_report.py#L48) | `STATUS_LABELS["closed"] = "Closed"` | [app/docx_import.py](app/docx_import.py#L54) `STATUS_BY_LABEL`, [app/web/static/app.js](app/web/static/app.js#L119) `statuses`, [app/web/static/manager.js](app/web/static/manager.js#L208) `labels` — **four copies of one table** |
| [app/docx_report.py](app/docx_report.py#L161) | `main_template_path`'s `asia` boolean becomes a per-segment suffix lookup with an explicit entry for every member | — (server-only; `_populate_cvss_table` infers from the rendered template, so it follows for free) |
| [app/docx_import.py](app/docx_import.py#L54) | `"Closed": "closed"`; `LABEL_BY_STATUS` and `status_counts` derive | the three other label copies above |
| [app/docx_import.py](app/docx_import.py#L947) | the retest drop rule, per Q2 | none — import is server-only |
| [app/docx_import.py](app/docx_import.py#L1112) | `parts[0] in ("JH", "GWAM", "Asia", "GDT")` | a **fourth** hardcoded copy of "which segments exist", which §12 does not record |
| [app/web/static/app.js](app/web/static/app.js#L119) | `statuses` gains `["closed", "Closed"]` — **last edit of the Closed half** | [app/docx_report.py](app/docx_report.py#L48) |
| [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | one `<option value="GDT">` — **last edit of the GDT half** | [app/models.py](app/models.py#L32) |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels.closed = "Closed"` | cosmetic, but it is the import summary the tester reads |
| [app/report_service.py](app/report_service.py#L497) *(Q3=B only)* | `STATUS_CONCLUSION_PATTERN` alternation widened | [app/web/static/app.js](app/web/static/app.js#L133) — **must ship first, and in the same commit as each other** |
| [app/report_service.py](app/report_service.py#L326) *(Q3=B only)* | the status-word ternary | [app/web/static/app.js](app/web/static/app.js#L1057) `syncConclusion` and [app/web/static/app.js](app/web/static/app.js#L1131) `offerConclusionRewrite` — **three sites, two languages** |
| [app/report_service.py](app/report_service.py#L251) *(Q1=B only)* | `content_types_for_status` gains a `closed` arm | [app/web/static/app.js](app/web/static/app.js#L1078) `contentTypesForStatus` |
| [app/report_service.py](app/report_service.py#L312) *(Q1=B only)* | the bare `next(...)` needs a guard **in the same step** | [app/web/static/app.js](app/web/static/app.js#L1105) the bare `.find(...)` |
| [app/docx_import.py](app/docx_import.py#L887) *(Q1=B only)* | an `expected_sections` arm matching the new component | none |
| [tests/test_app.py](tests/test_app.py#L673) | a fifth-status sibling of `test_the_fourth_status_saves_and_prints_what_previously_discovered_prints` | — |
| [tests/test_docx.py](tests/test_docx.py#L1092) | the four-row matrix becomes six | — |
| [tests/test_docx.py](tests/test_docx.py#L1119) | the smoke render gains two GDT cases | — |
| [tests/test_browser.py](tests/test_browser.py#L477) | the verbatim segment list gains `"GDT"` — **same commit as the `<option>`, never earlier** | — |
| [tests/test_browser.py](tests/test_browser.py#L3139) | a fifth-status sibling of `test_the_fourth_status_is_offered_and_prints_the_retest_sections` | — |
| [tests/test_docx_import.py](tests/test_docx_import.py#L728) | Closed round-trips as `closed`, not the fallback; a GDT title yields all three fields | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L330) | §12: the label-table row gains its fourth copy; the "is this report Asia" row gains the title-parser allowlist | — |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L11) | the six regions the scribe enumerated | — |

Per the data-layer contract, the `docs/DATA_MAP.md` slice **rides with the step that changes the
rule**, not with a docs step at the end — steps 1, 6, 7 and 9 each touch a file the contract names.

### Preconditions — a person in Word, before the step that needs them

These are not steps. Nothing in this repository can author a `.docx`, and no step below may be
written as though it could.

- **P1 — someone opens `MAIN.docx` and `MAIN_ASIA.docx` in Word and compares the cover pages.**
  Blocks Q4 only, not any code. The scribe established that the two masters are identical line for
  line through every body paragraph and body table bar one caption and one table, *and* that the
  cover page is the one region the text extraction is demonstrably blind to. If the covers carry a
  different legal entity, logo or footer, "GDT needs no master" is wrong and Q4 flips.
- **P2 — `MAIN_GDT.docx` and `MAIN_THICK_MOBILE_GDT.docx` exist in `resources/`.** Required only if
  Q4 = B. Each must satisfy the six hard preconditions the scribe listed (the `DOCUMENT REVISION
  HISTORY` paragraph, a paragraph that is nothing but `{{findings}}`, the five tables resolved by
  header cell, the summary prototype, one placeholder paragraph per summary cell, no surviving
  `{{...}}`). Every one of them fails loudly as `ReportGenerationError` → 422, which is the good
  failure mode, but it is still a failure the step cannot pre-empt.
- **P3 — a third component `.docx` exists in `resources/finding_types/`.** Required only if Q1 = B.
  The section headings are static paragraphs inside the component file; no code path can remove one.
- **P4 — someone opens `resources/finding_types/*.docx` in Word and confirms the `Status` cell is
  not a content control.** Cheap, blocks nothing: the scribe showed the write lands either way. It
  would simply leave a Word dropdown holding a value outside its own list, which is the kind of
  thing that surfaces a year later in a client's copy.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation path. A status or segment change is an ordinary field edit through the existing `PUT /reports/{id}`, which already carries `saved_at` in the body. |
| Lost update | clear | No new read-then-write. `provision_report` is called exactly where it is called today, inside the existing lock discipline; widening a `Literal` adds no second writer. |
| Orphan reference | clear under Q1 = A; **RISK** under Q1 = B | Under A nothing is unprinted, so nothing is carried and nothing is dropped. Under B, `content_has_work` returns true for any fragment holding an `evidence_id`, so an image-bearing section is carried rather than dropped and its PNG survives `_drop_orphan_evidence` — but a section holding *only* app-written boilerplate is dropped outright, and `in_conclusion` is dropped regardless of what it holds. |
| Silent stranding | clear | Neither axis touches `scope`, `target_ids`, environments or app types, so no finding can lose its last location as a consequence of this change. |
| Schema break, forwards | clear | Widening a `Literal` cannot reject anything that validated before, and the oracle confirmed no draft on disk holds either string. `validate_references` does not read either field. |
| Schema break, backwards | **RISK** | The one-way door, and it has three doors. Once a draft holds `GDT` or `closed`, an older build cannot open it *at all*: `load_path` raises, `list_reports` silently skips it, `list_legacy_reports` marks it `repairable: false`, every route 422s. Exports are refused wholesale. There is no migration back and the plan does not invent one — it only delays the moment of no return to the final step of each half. |
| Request/response asymmetry | clear | No new field in either direction. Both values travel in fields the client already sends and the server already returns. |
| Rule drift | **RISK — the largest** | Six twins in play: the four-copy label table; `content_types_for_status`/`contentTypesForStatus`; the status-word ternary at three sites in two languages; `STATUS_CONCLUSION_PATTERN` on both sides; the `RESOLVED_REMEDIATION` replacement rule; and the segment allowlist, which has **four** copies once the title parser is counted. Only generation readiness has a drift guard today. Step 1 adds the one contract test that makes the worst of these impossible to ship. |
| Navigation trap | clear | No new required field. GDT is one more option in a select that is already required, and `setup_issues` tests presence only, so a tester can always satisfy the gate on the page that holds the control. |
| Derived-state fight | **RISK** under Q1 = B only | The server's `provision` rewrites `contents` to the server's list on every save. If the two `content_types_for_status` twins disagree about what `closed` prints, the editor renders sections the server deletes, and the tester's work vanishes on reload with no error anywhere. Under Q1 = A both sides fall through to the same five-section branch and cannot disagree. |
| Backup exhaustion | **RISK** | Not from double-writing — one status change is one PUT — but because `draft.bak.json` holds only the previous revision. Two saves after a tester first picks `Closed` and no version remains that an older build can open. This is the reason the picker is the last edit rather than the first. |
| Round-trip downgrade | **RISK** | A generated Closed report re-imported on any build whose `STATUS_BY_LABEL` lacks the label comes back as `open_previously_discovered`. It does not raise — it warns once per finding and succeeds. Step 2 closes this for *this* build; nothing can close it for an older one. |
| Import refusal on shape | clear under Q1 = A; **RISK** under Q1 = B | `expected_sections` already gives every non-`open_new` status the five-section shape, so under A no arm is needed and none should be added. Under B a component printing three sections while the importer expects five means every Closed report this app writes is one it cannot read back — so the component and the import arm must land in the **same step**, never two. |
| Bare status subscripts | clear once step 1 lands | Three exist. Two are `STATUS_LABELS` on the generate path ([app/docx_report.py](app/docx_report.py#L517), [app/docx_report.py](app/docx_report.py#L769)) and step 1 fixes both. The third, `LABEL_BY_STATUS[row["status"]]` in the import error message at [app/docx_import.py](app/docx_import.py#L902), **cannot** miss: `row["status"]` is written by `STATUS_BY_LABEL.get(cells[5], FALLBACK_STATUS)`, so both branches yield a key that is already in the table. |

### Plan

Two halves, independent of each other. Either may ship alone. Within each half the ordering rule is
the one the repository already states in the docstring of
[tests/test_browser.py](tests/test_browser.py#L3139): *"The dropdown is the last thing to learn a
status, because until the server, the document and the importer all know it, offering it hands the
tester a value that loses work."* That is precedent, not invention, and it applies verbatim to the
segment `<option>` too.

#### Part A — `Closed`, with no new `.docx`

- [ ] **Step 1 — Make `closed` storable and printable.** [app/models.py](app/models.py#L10) widens
      `Status`; [app/docx_report.py](app/docx_report.py#L48) gains `"closed": "Closed"`. §12's label
      row in [docs/DATA_MAP.md](docs/DATA_MAP.md#L330) records that the table has four copies.
      **Test:** `test_the_fifth_status_saves_and_prints_what_resolved_prints` in
      [tests/test_app.py](tests/test_app.py#L673), modelled on its fourth-status sibling — `provision`
      gives it the five-section shape, and a `PUT` round-trips it. Plus a one-line contract test,
      `set(STATUS_LABELS) == set(get_args(Status))`, which is the only thing that makes the
      `KeyError` → HTTP 500 impossible to ship again. **Invariant:** after this step no draft on disk
      can hold `closed`, because nothing offers it.
- [ ] **Step 2 — Make it readable back.** [app/docx_import.py](app/docx_import.py#L54) gains
      `"Closed": "closed"`; `LABEL_BY_STATUS` and the import summary's `status_counts` derive for
      free. The retest drop rule at [app/docx_import.py](app/docx_import.py#L947) is settled per Q2.
      `expected_sections` is **deliberately untouched** — `status != "open_new"` already yields the
      five-section shape — and the step should say so, so nobody later "fixes" it. **Test:** in
      [tests/test_docx_import.py](tests/test_docx_import.py#L728), a generated report holding a
      Closed finding imports as `closed` with no warning, rather than as the fallback with one.
      **Invariant:** `STATUS_LABELS[s] == LABEL_BY_STATUS[s]` for every status — the string the
      document prints and the string the importer matches are the same string.
- [ ] **Step 3 — Section rules, both sides.** *Under Q1 = A this step is empty, and that is the
      point:* `content_types_for_status` and `contentTypesForStatus` both fall through to the
      five-section branch, which is exactly what Closed should print, and `recommended_remediation`
      stays in the list so neither `provision`'s bare `next(...)` nor the browser's bare `.find()`
      can throw. *Under Q1 = B* this step gains the `closed` arm in
      [app/report_service.py](app/report_service.py#L251) **and**
      [app/web/static/app.js](app/web/static/app.js#L1078), the guard on both bare lookups, the
      matching `expected_sections` arm in [app/docx_import.py](app/docx_import.py#L887), and it may
      not land before P3. **Test:** a browser test asserting the section list the editor renders
      equals the section list the server stores after a save — the drift guard §12 currently lacks
      for this row. **Invariant:** the two `content_types_for_status` twins return equal lists for
      every member of `Status`.
- [ ] **Step 4 — Widen the recogniser, and only the recogniser.** *Q3 = B only.*
      `STATUS_CONCLUSION_PATTERN` becomes `(?:Open|Resolved|Closed)` in
      [app/report_service.py](app/report_service.py#L497) and
      [app/web/static/app.js](app/web/static/app.js#L133), in one commit. The builder is **not**
      touched. **Test:** every sentence shape already on disk still matches, and a hand-written
      `… is Closed.` now matches too. **Invariant:** the recogniser is never narrower than the
      builder. Widening it is provably additive; narrowing it silently freezes every default sentence
      on disk at the title and status it was stored with.
- [ ] **Step 5 — Widen the builder.** *Q3 = B only.* The status-word ternary at
      [app/report_service.py](app/report_service.py#L326),
      [app/web/static/app.js](app/web/static/app.js#L1057) and
      [app/web/static/app.js](app/web/static/app.js#L1131) learns the third word. **Test:** a Closed
      finding's default sentence reads `is Closed.` and `is_default_status_conclusion` returns true
      for it, so `generation_issues` still blocks a report whose conclusion is the app's own
      sentence. **Invariant:** every sentence the builder can produce is matched by the pattern
      shipped in step 4 — which is why this step cannot precede it.
- [ ] **Step 6 — Make it selectable.** `statuses` in
      [app/web/static/app.js](app/web/static/app.js#L119) and `labels` in
      [app/web/static/manager.js](app/web/static/manager.js#L208). **Test:**
      `test_the_fifth_status_is_offered_and_saves` in
      [tests/test_browser.py](tests/test_browser.py#L3139), mirroring its fourth-status sibling
      including the docstring that states why this is last. **Invariant:** this is the first moment a
      draft can hold `closed`, and by now the server, the document, the importer and both section
      rules already know it.

#### Part B — `GDT`, with no new `.docx`

- [ ] **Step 7 — Widen `Segment` and state the template choice out loud.**
      [app/models.py](app/models.py#L32) widens `Segment`.
      [app/docx_report.py](app/docx_report.py#L161) replaces the `asia = segment == "Asia"` boolean
      with a suffix table carrying an explicit entry for every member — `JH` and `GWAM` and `GDT` map
      to `""`, `Asia` to `"_ASIA"` — so GDT taking the JH master becomes a decision the file records
      rather than a fall-through. Output is byte-identical for the three existing segments. §12's
      "is this report Asia" row in [docs/DATA_MAP.md](docs/DATA_MAP.md#L330) is rewritten from a
      boolean to a lookup. **Test:** widen the matrix in
      [tests/test_docx.py](tests/test_docx.py#L1092) from four rows to six (`("web","GDT")` →
      `MAIN.docx`, `("thick_client","GDT")` → `MAIN_THICK_MOBILE.docx`), keeping the existing
      `chosen.parent == resources` assertion on every branch, and widen the smoke render at
      [tests/test_docx.py](tests/test_docx.py#L1119) to the same six so a GDT report is proved to
      render with no unresolved placeholder. *Under Q4 = B this step instead maps GDT to `"_GDT"`,
      the matrix and the smoke render grow to eight, and it may not land before P2.*
      **Invariant:** `main_template_path` remains the sole owner of the choice, and its `.parent`
      stays `resources/` because that path doubles as the component fragment root.
- [ ] **Step 8 — Teach the importer's title parser.** The literal tuple at
      [app/docx_import.py](app/docx_import.py#L1112) gains `"GDT"`. **Test:** in
      [tests/test_docx_import.py](tests/test_docx_import.py#L728), a GDT report's title yields
      `segment`, `app_name` **and** `report_type` — all three asserted together, because the three
      assignments live inside one `if` and a failed match loses them as a unit with no error raised.
      **Invariant:** a segment the app can print is a segment the app can read back. The en dash the
      masters print and the hyphen `report_export_filename` writes both already parse, so GDT changes
      nothing about the split.
- [ ] **Step 9 — Make it selectable.** One `<option value="GDT">GDT</option>` in
      [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7), and the verbatim
      assertion at [tests/test_browser.py](tests/test_browser.py#L477) widened **in the same edit** —
      widening it earlier fails at HEAD, widening it later leaves the suite red.
      **Invariant:** first moment a draft can hold `GDT`, and by now the Literal, the template
      chooser and the importer already know it.
- [ ] **Step 10 — Correct `docs/DOCX_TEMPLATE.md`.** The six regions the scribe enumerated: the
      selection matrix at [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L11), the two separate
      three-status enumerations at [L217](docs/DOCX_TEMPLATE.md#L217) and
      [L249](docs/DOCX_TEMPLATE.md#L249), the retest-only claim at
      [L237](docs/DOCX_TEMPLATE.md#L237), the template count at
      [L154](docs/DOCX_TEMPLATE.md#L154), and the Asia-only CVSS scoping at
      [L104](docs/DOCX_TEMPLATE.md#L104). **Test:** none — this is the one step with nothing to
      assert on, which is exactly why it is written down rather than assumed.

### What I would not do

1. **Turn `STATUS_LABELS[...]` into `.get(status, ...)` with a fallback.** The `KeyError` → HTTP 500
   is unpleasant but it is *loud*, and it is the only thing that makes shipping a status with no
   label impossible. A fallback converts it into a wrong word printed into a delivered client
   document. The one-line contract test in step 1 removes the failure without removing the alarm.
2. **Add a default to `provision`'s bare `next(...)` while passing through.** It is load-bearing: it
   asserts that `recommended_remediation` is in every status's section list. A default would let a
   list ship without it and surface as a required section nobody can fill. If Q1 = B genuinely drops
   it, the guard lands in step 3 with a test, not speculatively now.
3. **Render the setup `<option>` list from `Segment` through the Jinja context.** It looks like the
   fix for four hardcoded copies and removes exactly one. `statuses` in `app.js` cannot import from
   Python, and the importer's tuple is a parse allowlist rather than a picker, so the same class of
   bug survives at a cost of a route-context change and a rewritten browser assertion.
4. **Ship the Literal and the picker in one commit, or the picker first.** Selectable-but-unsaveable
   is the state that strands a tester: the client model holds the value, every `PUT` 422s, and the
   only way out is changing it back. Storable-but-unselectable, the ordering above, is inert — no
   draft can acquire the value until the last step of each half.
5. **Widen the conclusion builder before the recogniser, or both together.** Builder-first is the one
   failure in this whole change that is silent in a delivered document: the pattern stops matching,
   `provision` stops re-deriving the sentence, `content_has_work` starts counting boilerplate as
   tester work, and `generation_issues` stops flagging it — so the app's own placeholder sentence
   prints into In Conclusion with nothing raised anywhere.
6. **Treat `draft.bak.json` as a rollback.** It holds one revision. Two saves after a tester first
   picks a new value and no version remains that an older build can open. The mitigation is
   sequencing, not backups.

### Open questions

**Q1 — Does a `Closed` finding print the same five sections `Resolved` prints, or fewer?**

Every status other than `Open (New)` prints five sections today: Description, Recommended
Remediation, Previous Proof of Concept, Proof of Concept, In Conclusion. They are static headings
inside `retest_finding.docx`, so no code can remove one.

- **Option A — the same five.** Closed becomes a label and nothing else. No Word author, no import
  arm, no `provision` guard, no risk of the two section-list twins disagreeing. A Closed finding with
  no previous proof and no conclusion prints those headings with `N/A` beneath each — which is
  already what `Open (Resolved on Non-Prod)` does today, so the precedent is shipped and visible.
- **Option B — fewer.** Needs a third `.docx` authored in Word (P3), a matching `expected_sections`
  arm or every Closed report this app writes becomes one it cannot read back, a guard on two bare
  lookups that currently assume the remediation is always printed, and it accepts that a tester's
  written In Conclusion is **destroyed rather than carried** when a finding becomes Closed — that
  section is the deliberate exception to the carry rule.

**Recommendation: A.** The cost of not suppressing is cosmetic; the cost of suppressing is a Word
author, a round-trip break, and the only path in this change that can destroy typed work.

**Q2 — Does GDT need its own master pair?**

The segment reaches the rendered document as exactly one string, on the title line. A GDT report on
the existing master would read `GDT – Northstar Banking – Annual Pentest 2026`, carry no CVSS
appendix table, and demand no CVSS values — every other page byte-identical to a JH report.

- **Option A — no master.** The entire document cost of GDT is that one string. Step 7 as written.
- **Option B — its own pair.** `MAIN_GDT.docx` and `MAIN_THICK_MOBILE_GDT.docx` authored in Word
  before any code lands (P2), six masters in `resources/`, and each must satisfy six hard
  preconditions that fail as HTTP 422 if missed. Choosing B also answers **whether GDT prints
  CVSS**, because the `Section` table is the only place CVSS appears and it exists only in the Asia
  masters — so B with a Section table makes the pair required on every GDT finding, and B without
  one does not.

**Recommendation: A, conditional on P1.** The scribe measured the Asia master as its twin plus one
caption and one table through every body paragraph and body table — but the cover page is the one
region this repository cannot see, and a per-segment legal entity or logo is exactly the kind of
thing that would live there. Someone should open both files in Word before this is answered.

**Q3 — What word does a Closed finding's conclusion sentence use, and does Closed replace the
remediation the way Resolved does?**

Today `provision` writes `The finding "X" is still Open.` for three statuses and
`The finding "X" is Resolved.` for one, and it replaces the remediation with
`None, the vulnerability has been remediated.` for `resolved` alone.

- **Option A — Closed reuses Resolved's behaviour entirely.** The sentence says `is Resolved.`, the
  remediation is replaced with the remediated boilerplate, `STATUS_CONCLUSION_PATTERN` needs no edit
  and steps 4 and 5 disappear. But a finding whose printed status cell says `Closed` and whose
  conclusion says `Resolved` is a contradiction in a delivered document.
- **Option B — Closed gets its own word and keeps the remediation editable.** The sentence says
  `is Closed.`; steps 4 and 5 exist and must ship in that order across two commits. The remediation
  falls to `provision`'s existing `else` arm, which strips any `resolved_remediation` boilerplate —
  so a tester moving a finding from Resolved to Closed finds the remediation **emptied**, and it is
  a required section, so generation is blocked until they write one. That is correct if Closed means
  "not remediated", and an annoyance if it means "remediated and signed off".
- **Option C — Closed's own word, plus the remediated boilerplate.** Coherent only if Closed means
  "Resolved and accepted", which raises the question of why it is not just Resolved.

**Recommendation: B**, on the reading that a status named Closed is an end state reached for reasons
other than remediation — risk accepted, won't fix, out of scope. If the owner's Closed *does* mean
remediated-and-signed-off, A is cheaper and honest, and Q1 = A makes it three dictionary entries in
total.

**Q4 — Does a retest drop Closed findings the way it drops Resolved?**

One line, [app/docx_import.py](app/docx_import.py#L947). Importing last year's report as a retest
draft currently drops every `resolved` finding and keeps everything else, moving each kept finding's
proof of concept into Previous Proof of Concept and emptying the current proof and conclusion.

- **Option A — drop, like Resolved.** Last year's Closed findings never appear in this year's draft.
  If a Closed finding needs re-testing it has to be recreated by hand.
- **Option B — keep.** Every Closed finding carries forward as something to re-test, and the tester
  deletes each one individually if that was not intended.

**Recommendation: A**, consistent with the Q3 = B reading that Closed is an end state. Note the
asymmetry this creates and that it is probably right: a Closed finding is dropped from the retest
draft but its remediation is not boilerplate-filled, because "finished with" and "remediated" are
different claims.

## Round 2 - Oracle: verdict on the proposal

**Verdict.** The plan's two load-bearing judgements survive the Answers: **picker last** and
**recogniser before builder** are both correct, and I verified the second one through the gate it
protects rather than taking it on the planner's word. Part A got *cheaper* than the plan assumed —
Q1 = A retires three risk rows and empties step 3 — and Part B got cheaper still, because the owner
kept `main_template_path`'s boolean that step 7 proposed to replace. But the conclusion sentence
moved ground the proposal was standing on: **step 4's regex literal is wrong in two ways, step 5 is
not a ternary edit but a missing third arm in a two-way builder, and that builder has five call
sites in two languages rather than three.** Three things in scope are named nowhere in the plan:
`Workspace.load_path`, the retest-drop notice in `manager.js`, and the `dropped_resolved` summary
key. Nothing in the proposed shape breaks a `draft.json` on disk.

### 1. Risk rows that are wrong, in either direction

**Marked `clear`, actually a risk.**

| Row | Why it is not clear |
|---|---|
| *Derived-state fight* — "**RISK** under Q1 = B only" | The Q1 = B half is dead (below), and the reasoning for A is right: both `content_types_for_status` twins fall through to the same branch and cannot disagree. What the row misses is a **second derived-state owner this change touches and the plan never names**: [`Workspace.load_path`](app/workspace.py#L271) rewrites `recommended_remediation` *on load*, outside `provision` and outside any save. [app/workspace.py](app/workspace.py#L286-L295) empties the runs of any single unlabelled paragraph reading exactly `RESOLVED_REMEDIATION` on a finding whose status is not `resolved`, then persists the draft with `atomic_write_json` ([app/workspace.py](app/workspace.py#L297-L298)). A Closed finding takes that arm. See §2.1. |
| *Round-trip downgrade* — "**RISK**", closed by step 2 | Right about `STATUS_BY_LABEL`, but only half the round trip once the settled retest answer lands. The manager will tell the tester `"N Resolved findings were not included: …"` for a list that now contains Closed findings — the word is **hardcoded**, not looked up ([app/web/static/manager.js](app/web/static/manager.js#L203)). The `labels.closed = "Closed"` edit the plan lists does not reach that string. |
| *Bare status subscripts* — "clear once step 1 lands. Three exist." | The three named are correct, including the reasoning that `LABEL_BY_STATUS[row["status"]]` at [app/docx_import.py](app/docx_import.py#L902) cannot miss. But the census stops at `KeyError`-shaped risks and so misses the two that matter after the Answers: [`status_conclusion_runs`](app/report_service.py#L500-L508) and [`statusConclusionRuns`](app/web/static/app.js#L128-L132) are **total functions** that answer for an unknown status word instead of raising — they emit a wrong sentence silently. §4(a). |

**Marked `RISK`, already handled or settled away.**

| Row | Why |
|---|---|
| *Orphan reference* — "**RISK** under Q1 = B" | Dead. Q1 = A is settled; the row's own A-branch reasoning is correct. Delete the conditional rather than leave a risk whose condition can no longer be true. |
| *Import refusal on shape* — "**RISK** under Q1 = B" | Dead, and verified rather than assumed: `expected_sections` at [app/docx_import.py](app/docx_import.py#L887-L893) branches on `row["status"] != "open_new"`, so Closed gets the five-section expectation with no arm added. Step 2 is right to say so explicitly. |
| *Backup exhaustion* — "**RISK**" | Overstated as a separate row. `draft.bak.json` is not a distinct hazard here; it is the same one-way door as *Schema break, backwards*, with the same mitigation (picker last). Two rows for one hazard reads as two hazards. Fold it in as a sentence. |
| *Rule drift* — "the largest", six twins | The verdict is right and the count of twins is right. The **membership is wrong**: "the status-word ternary at three sites in two languages" is five sites. §2.4. |

Everything else in the table I checked and agree with, including the two I most expected to be wrong:
*Stale write* and *Lost update* are genuinely clear — `provision_report` is called from exactly the
places it is called today ([app/main.py](app/main.py#L262-L266)), inside the existing lock, and
widening a `Literal` adds no second writer to the save path.

### 2. Files and sites the planner missed

**2.1 [app/workspace.py](app/workspace.py#L286-L295) — absent from the blast radius entirely.**

Direct answer to the question asked: **a Closed finding cannot be mis-tagged by it.** The arm that
writes `generated: "resolved_remediation"` is gated on `vulnerability.get("status") == "resolved"`
([app/workspace.py](app/workspace.py#L292)), so Closed never acquires the marker. It can be
**mis-emptied**: the `elif stale` arm at [app/workspace.py](app/workspace.py#L295) sets
`fragments[0]["runs"] = []` and the draft is rewritten to disk. That is today's behaviour for every
non-resolved status and it is deliberate — but the rationale, recorded at
[docs/DATA_MAP.md](docs/DATA_MAP.md#L247), is *"the reopened case is damage from before the marker
existed"*, and Closed is an end state rather than a reopening. So a Closed finding whose remediation
a tester genuinely wrote as "None, the vulnerability has been remediated." is silently emptied on the
next load. Narrow, but it directly contradicts the Answers' promise that Closed leaves the
remediation alone, and note it contradicts `provision` too — a tester's identical wording *survives*
provisioning by design, pinned by
`tests/test_app.py::test_a_testers_own_remediation_survives_provisioning`
([tests/test_app.py](tests/test_app.py#L706-L715)), and is then removed at load. This needs a
decision in the plan, not necessarily a code change.

**2.2 [app/web/static/manager.js](app/web/static/manager.js#L203)** — the dropped-findings notice,
hardcoded to the word "Resolved". The plan lists `manager.js` once, for `labels`, and marks it
cosmetic. This second edit in the same file is not cosmetic: it is the only sentence the tester ever
sees naming what the import threw away.

**2.3 `dropped_resolved`** — the summary key itself, built at
[app/docx_import.py](app/docx_import.py#L1190-L1194), read at
[app/web/static/manager.js](app/web/static/manager.js#L198), documented at
[docs/DATA_MAP.md](docs/DATA_MAP.md#L188), and asserted in four places:
[tests/test_docx_import.py](tests/test_docx_import.py#L223),
[tests/test_docx_import.py](tests/test_docx_import.py#L321),
[tests/test_docx_import.py](tests/test_docx_import.py#L1060) and
[tests/test_browser.py](tests/test_browser.py#L4729). It becomes a misnomer. Rename it (a four-file
edit) or keep it and say why; either is defensible, not seeing it is not.

**2.4 The JavaScript half of the status-word ternary is four sites, not two.** The plan names
[app/web/static/app.js](app/web/static/app.js#L1058) (`syncConclusion`) and
[app/web/static/app.js](app/web/static/app.js#L1131) (`offerConclusionRewrite`). It misses
**[app/web/static/app.js](app/web/static/app.js#L3949)** — the *"Put it back"* offer that restores
the sentence into an emptied paragraph — and **[app/web/static/app.js](app/web/static/app.js#L3966)**
— the *"This conclusion does not state whether the finding is open or resolved"* offer, which both
appends and replaces. Both call `statusConclusionRuns` with the same
`finding.status === "resolved" ? "Resolved" : "Open"`. Miss them and the Content page writes
`is still Open.` into a Closed finding — which the widened recogniser then **accepts as the app's own
sentence**, so it neither counts as work nor raises anything. Five sites in total:
[app/report_service.py](app/report_service.py#L326) plus those four.

**2.5 [docs/DATA_MAP.md](docs/DATA_MAP.md#L190)** — §11's *"only `resolved` is dropped"* becomes
false under the settled retest answer, and the plan's map row covers §12 only. Also in §12, beyond
the two rows the plan names: the Additional Information table at
[docs/DATA_MAP.md](docs/DATA_MAP.md#L419-L421) enumerates the four statuses as **column headers** and
gains a fifth, and the four-copy label paragraph at [docs/DATA_MAP.md](docs/DATA_MAP.md#L428) gains a
row per copy.

### 3. Does the proposed shape break any `draft.json` on disk?

**No.** Three independent reasons, each verified against source rather than inferred:

- Widening a `Literal` only widens the accepted set, and neither field has a `before` validator,
  coercion or default-on-invalid ([app/models.py](app/models.py#L10),
  [app/models.py](app/models.py#L32)). Nothing that validated before is rejected.
- Under the settled Q1 = A, [`content_types_for_status`](app/report_service.py#L251-L255) is
  untouched, so no finding on disk changes section shape and the carry-or-drop rule at
  [app/report_service.py](app/report_service.py#L288) never runs differently for any stored status.
- The conclusion change is additive on the recogniser — §4(b). Every sentence on disk ends in
  `Open.` or `Resolved.` and still matches.

The plan's *Schema break, backwards* row remains the real hazard and is stated correctly; I re-ran
the check and no draft under `data/` holds `GDT` or `closed`.

### 4. The claims the Answers moved, checked against source

**(a) The regex needs two widenings, and the builder needs a third arm the pattern cannot police.**

Today, both sides, verbatim:

```python
STATUS_CONCLUSION_PATTERN = re.compile(r'The finding ".*" is(?: still)? (?:Open|Resolved)\.', re.DOTALL)
```
([app/report_service.py](app/report_service.py#L497))

```js
const STATUS_CONCLUSION_PATTERN = /^The finding "[\s\S]*" is(?: still)? (?:Open|Resolved)\./;
```
([app/web/static/app.js](app/web/static/app.js#L133))

The Answers' sentence requires **both** the verb group `(?: still)?` → `(?: still| now)?` **and** the
alternation `(?:Open|Resolved)` → `(?:Open|Resolved|CLOSED)`. Neither pattern carries
`re.IGNORECASE` or the `i` flag, so `CLOSED` must appear upper case in the literal on both sides.
Step 4 says only *"becomes `(?:Open|Resolved|Closed)`"* — wrong case, and silent on the verb group.
As written it ships a recogniser that cannot match the sentence step 5 builds, which is the exact
failure step 4 exists to prevent.

The builder is a **two-way branch on the word**, not a lookup, on both sides:

```python
Run(text=f'The finding "{title}" is still ' if status_word == "Open" else f'The finding "{title}" is '),
Run(text=status_word, bold=True),
```
([app/report_service.py](app/report_service.py#L501-L503))

```js
{text: `The finding "${title}" is ${statusWord === "Open" ? "still " : ""}`},
{text: statusWord, bold: true},
```
([app/web/static/app.js](app/web/static/app.js#L129-L130))

So passing `"CLOSED"` today produces `The finding "X" is CLOSED.` — the `now` is missing. **And the
widened pattern accepts that string**, because `(?: still| now)?` is optional. That is the trap in
this whole change: the recogniser structurally *cannot* detect the builder's missing arm, so the only
guard is a test asserting the produced string verbatim on both sides. One thing the Answers get for
free: `Run(text=status_word, bold=True)` already gives bold-not-italic with no edit.

**(b) `default_conclusion_span` and `defaultConclusionSpan` both survive unchanged.**

Neither breaks on upper case or on the new verb phrase. Both locate the sentence by
`rfind` / `lastIndexOf` on `'The finding "'` ([app/report_service.py](app/report_service.py#L513-L515),
[app/web/static/app.js](app/web/static/app.js#L136-L139)) — a marker the status word does not appear
in — then anchor the pattern at that index, Python with `.match(stripped, index)` and JavaScript with
`^` against `stripped.slice(index)`. Equivalent, and both are span-preserving for existing text
because the two widenings are pure alternation additions. **A sentence already on disk still matches
after the change.**

One second-order effect worth writing down rather than discovering: `content_has_work` and
`contentHasWork` both gate on `is_default_status_conclusion`
([app/report_service.py](app/report_service.py#L262), [app/web/static/app.js](app/web/static/app.js#L1084)).
The moment the recogniser widens, a paragraph a tester hand-typed as `The finding "X" is now CLOSED.`
stops counting as work, so a section holding only that is dropped rather than carried. That is the
intended end state — but it takes effect at step 4, one step before the app can produce the sentence
itself.

**(c) Recogniser before builder is right; the reverse is the one silent failure in the change.**

Verified through the gate rather than taken on trust. `is_default_status_conclusion` is the sole
condition on the `in_conclusion still holds the default sentence` issue at
[app/docx_report.py](app/docx_report.py#L121-L126), which `generation_issues` returns and
`finalized_report` blocks on; the browser twin is `isDefaultStatusConclusion` at
[app/web/static/app.js](app/web/static/app.js#L1049-L1053), feeding the readiness panel. Builder-first
would make `default_conclusion_span` return `None` for every Closed sentence, so: `provision` stops
re-deriving it on a title change ([app/report_service.py](app/report_service.py#L328-L336)),
`content_has_work` starts counting the app's own boilerplate as tester work, and — the one that
reaches a client — **the generation block disappears** and the placeholder sentence prints. There is
no symmetric failure recogniser-first: widening is additive, and the only effect before step 5 is
(b) above. The plan's ordering and its stated reason both stand.

**(d) The bare `next(...)` is genuinely safe; the `resolved_remediation` unwind is not what the
Answers describe.**

`recommended_remediation` is in the list for **every** status
([app/report_service.py](app/report_service.py#L251-L255)), and `provision` rebuilds `contents` from
that list at [app/report_service.py](app/report_service.py#L289) *before* the lookup. So the bare
`next(...)` at [app/report_service.py](app/report_service.py#L312) and the bare `.find()` at
[app/web/static/app.js](app/web/static/app.js#L1105) cannot miss under Q1 = A. **Confirmed safe**, and
the plan is right to refuse a speculative default.

The unwind is where the Answers and the source disagree. The Answers say *"`Closed` leaves whatever
the tester wrote."* True only for a finding that never passed through Resolved:

- Entering Resolved **replaces the whole fragment list**
  ([app/report_service.py](app/report_service.py#L314-L319)). The tester's remediation is destroyed at
  that moment and is *not* carried, because the carry rule at
  [app/report_service.py](app/report_service.py#L288) rescues only sections the status does not print,
  and this one is always printed.
- Resolved → Closed then takes the `else` arm
  ([app/report_service.py](app/report_service.py#L320-L323)), strips the
  `generated="resolved_remediation"` paragraph, and leaves `[ParagraphFragment(runs=[])]`. So
  **Resolved → Closed leaves the remediation empty**, and it is a required section
  ([app/docx_report.py](app/docx_report.py#L122-L124)), so generation is blocked until the tester
  rewrites it.
- Closed → Resolved → Closed destroys what they wrote under Closed by the same route.
- Closed on a fresh finding, and Closed → any open status, behave exactly as the Answers describe.

The browser warns on the first hop but not the second: `replacesRemediation` at
[app/web/static/app.js](app/web/static/app.js#L2599) is
`nextStatus === "resolved" && finding.status !== "resolved"`, so moving *into* Resolved prompts and
moving *out of* it into Closed does not. None of this is new code — it is today's behaviour for every
open status — but the plan must record it, because "Closed leaves the remediation alone" will be read
as a promise the code does not make.

**(e) The retest drop, and every other `"resolved"` literal.** The rule is one line,
[app/docx_import.py](app/docx_import.py#L947). Exhaustive check of the literal elsewhere:

| Site | Under the settled answers |
|---|---|
| [app/docx_import.py](app/docx_import.py#L57) `"Resolved": "resolved"` | gains `"Closed": "closed"`. Step 2, as planned. |
| [app/docx_import.py](app/docx_import.py#L962) editable-mode boilerplate check | **correctly left alone** — Closed writes no boilerplate, so there is nothing to assert. |
| [app/docx_import.py](app/docx_import.py#L984-L986) the comment *"Resolved never reaches here at all"* | becomes incomplete; Closed will not reach there either. One-line comment edit in the same step. |
| [app/docx_import.py](app/docx_import.py#L1192) `dropped_resolved` | misnomer. §2.3. |
| [app/web/static/manager.js](app/web/static/manager.js#L203) | wrong word to the user. §2.2. |
| [app/report_service.py](app/report_service.py#L313), [app/web/static/app.js](app/web/static/app.js#L1106) | the boilerplate arm; correctly untouched. |
| [app/web/static/app.js](app/web/static/app.js#L1433) library remediation offer, [app/web/static/app.js](app/web/static/app.js#L4110) editor remediation lock, [app/web/static/app.js](app/web/static/app.js#L2599) `replacesRemediation` | all `resolved`-only and all **correct to leave**: Closed keeps an editable remediation, so it must keep the offer, stay unlocked, and raise no replacement warning. |

**(f) The pickers — both confirmed, only one pinned verbatim.**

- **Segment:** four `<option>` elements inline at
  [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7), inside
  `<label>Segment<select data-path="engagement.segment">`. **Asserted verbatim** at
  [tests/test_browser.py](tests/test_browser.py#L477) — an `assertEqual` on the whole list,
  `["Select segment", "JH", "GWAM", "Asia"]`.
- **Status:** `statuses` at [app/web/static/app.js](app/web/static/app.js#L119). **No test asserts it
  verbatim.** The nearest is [tests/test_browser.py](tests/test_browser.py#L3147-L3150), an `assertIn`
  on one label inside `test_the_fourth_status_is_offered_and_prints_the_retest_sections`.

So step 6 breaks no assertion, and step 9 breaks exactly one — the plan's insistence that the
`<option>` and [tests/test_browser.py](tests/test_browser.py#L477) move in the same edit is right.

### Claims in the proposal that are now wrong

1. **Step 4** — *"`STATUS_CONCLUSION_PATTERN` becomes `(?:Open|Resolved|Closed)`"*.
   **Correction:** `Closed` → `CLOSED`, and the verb group widens too. Both sides become
   `The finding ".*" is(?: still| now)? (?:Open|Resolved|CLOSED)\.`; both patterns are
   case-sensitive.
2. **Step 5** — *"the status-word ternary … learns the third word"*, and its test —
   *"a Closed finding's default sentence reads `is Closed.`"*. **Correction:** the ternary is not the
   whole edit. `status_conclusion_runs` ([app/report_service.py](app/report_service.py#L500-L508)) and
   `statusConclusionRuns` ([app/web/static/app.js](app/web/static/app.js#L128-L132)) branch **two
   ways** on `status_word == "Open"` and need a **third arm** emitting `is now `. The sentence reads
   `The finding "X" is now CLOSED.`
3. **Step 5's test** — *"`is_default_status_conclusion` returns true for it"*. **Correction:**
   necessary but not sufficient, and misleading as the only assertion: the widened pattern accepts
   `is CLOSED.` as readily as `is now CLOSED.`, so a recognition-only test passes with the third arm
   missing. Assert the produced string verbatim, on both sides.
4. **Blast radius** — *"the status-word ternary … three sites, two languages"*. **Correction:** five
   sites — [app/report_service.py](app/report_service.py#L326),
   [app/web/static/app.js](app/web/static/app.js#L1058),
   [app/web/static/app.js](app/web/static/app.js#L1131),
   [app/web/static/app.js](app/web/static/app.js#L3949),
   [app/web/static/app.js](app/web/static/app.js#L3966).
5. **Step 7** — *"replaces the `asia = segment == "Asia"` boolean with a suffix table"*.
   **Correction:** the Answers say *"`main_template_path` keeps Asia as a boolean"*. That edit is now
   contradicted and must be dropped; [app/docx_report.py](app/docx_report.py#L161) is untouched. What
   survives of step 7 is [app/models.py](app/models.py#L32), the four-row matrix widened to six at
   [tests/test_docx.py](tests/test_docx.py#L1092), and the smoke render at
   [tests/test_docx.py](tests/test_docx.py#L1119). §12's *"is this report Asia"* row
   ([docs/DATA_MAP.md](docs/DATA_MAP.md#L366)) stays a boolean and gains only the title-parser
   allowlist.
6. **Blast radius, `manager.js`** — *"`labels.closed = "Closed"` … cosmetic"*. **Correction:** two
   edits in that file, and the second ([app/web/static/manager.js](app/web/static/manager.js#L203))
   misreports to the tester which findings a retest dropped.
7. **Risk rows *Orphan reference*, *Import refusal on shape*, *Derived-state fight*** — all three
   carry a `Q1 = B` branch. **Correction:** the condition is settled false. State them as `clear`
   without the conditional, and give *Derived-state fight* its real content:
   [`Workspace.load_path`](app/workspace.py#L286-L295) as a second writer of
   `recommended_remediation`, outside `provision` and outside the save path.
8. **Preconditions P2, P3 and questions Q1–Q4** — all resolved by the Answers. **Correction:** P2 and
   P3 are void; **P1 and P4 survive as facts worth recording, not as blockers** — P1 because the
   owner took GDT's branding on judgement with the cover page unverified, and P4 because a content
   control in the `Status` cell would quietly hold an out-of-list value in a client's copy.

**Invariants in play.**

- *The recogniser is never narrower than the builder.* Violated → every default sentence on disk
  freezes at its stored title and status, `content_has_work` counts boilerplate as work, and
  `generation_issues` stops blocking a report whose conclusion the app wrote. Silent, and in a
  delivered document.
- *The string the document prints is the string the importer matches.* `STATUS_LABELS[s]` must equal
  `LABEL_BY_STATUS[s]` for every member. Violated → a generated Closed report re-imports as
  `open_previously_discovered` with one warning and no error.
- *`recommended_remediation` is in every status's section list.* Violated → `StopIteration` → HTTP
  500 on save, and `TypeError` in the editor. It is what makes the bare `next(...)` safe, so it is an
  invariant rather than an accident.
- *A status the picker offers is a status the server, the document and the importer already know.*
  Violated → the tester selects a value that 422s every save, or loses work on the next provision.

**Both-sides warning.** Four rules in this change are implemented in Python **and** JavaScript and
must move together, in one commit each: `STATUS_CONCLUSION_PATTERN`
([app/report_service.py](app/report_service.py#L497) / [app/web/static/app.js](app/web/static/app.js#L133));
the sentence builder ([app/report_service.py](app/report_service.py#L500) /
[app/web/static/app.js](app/web/static/app.js#L128)); the status word feeding it
([app/report_service.py](app/report_service.py#L326) plus **four** JavaScript call sites, §2.4); and
the label table, which is four copies across
[app/docx_report.py](app/docx_report.py#L48), [app/docx_import.py](app/docx_import.py#L54),
[app/web/static/app.js](app/web/static/app.js#L119) and
[app/web/static/manager.js](app/web/static/manager.js#L208). Only the first two have a named twin
comment in the source; the other two rely on the reader knowing.

**Map drift.** None. I re-checked §11 ([docs/DATA_MAP.md](docs/DATA_MAP.md#L188-L190)), §12's
conclusion rows ([docs/DATA_MAP.md](docs/DATA_MAP.md#L374-L393)), the four-copy paragraph
([docs/DATA_MAP.md](docs/DATA_MAP.md#L428)) and the `load_path` repair note
([docs/DATA_MAP.md](docs/DATA_MAP.md#L247)) against source; every one is accurate for what is shipped
today, so nothing is corrected here. The lines listed in §2.5 become wrong **when this ships**, not
before, and belong to the step that changes each rule.

## Round 2 - Planner: revised plan

**Understanding, restated after the Answers.** Two independent widenings, still bundled by the
request and still not by the code. `Segment` gains `GDT`, which renders the existing non-Asia master
and reaches the document as one printed string on the title line. `Status` gains `closed`, which
prints the same five sections `Resolved` prints on the same `retest_finding.docx`, differs from
`Resolved` in its printed label, in its conclusion sentence — `The finding "X" is now **CLOSED**.` —
in leaving the Recommended Remediation alone, and in being dropped by a retest import. **No `.docx`
is authored by a person anywhere in this change.** Both halves keep the Round 1 ordering rule:
*storable, then printable, then readable back, and only then selectable.*

### What the Answers made cheaper

Both open questions landed on the cheap branch, and two of them retired work rather than adding it.

- **Q1 = A (Closed prints five sections).** Step 3 of the Round 1 plan — the `closed` arm in both
  `content_types_for_status` twins, the guard on two bare lookups, the `expected_sections` arm —
  **is now empty and is deleted rather than kept as an empty step**. The fall-through is the correct
  behaviour, and the importer's `status != "open_new"` branch already yields the five-section shape.
  Step 2 below still says so out loud so that nobody later "fixes" it.
- **Q2 = A (no GDT masters).** Preconditions P2 and P3 are void. Nothing in this change waits on
  Word.
- **Q3 = B and Q4 = A** each cost one half-step, below.

### Where the Oracle corrected me

Six corrections, each verified against source before adopting it. They are written out rather than
quietly absorbed, because four of them are the kind of mistake that would have been made again.

1. **Step 4's regex literal was wrong in two ways, not one.** I wrote *"becomes
   `(?:Open|Resolved|Closed)`"*. Both wrong halves matter. The Answers' sentence is `is now
   **CLOSED**` — so the alternation needs `CLOSED` in **upper case** (neither pattern carries
   `re.IGNORECASE` or the `i` flag, confirmed at
   [app/report_service.py](app/report_service.py#L497) and
   [app/web/static/app.js](app/web/static/app.js#L133)), **and** the verb group must widen from
   `(?: still)?` to `(?: still| now)?`. As I wrote it, step 4 would have shipped a recogniser that
   cannot match the sentence step 5 builds — the exact failure step 4 exists to prevent. Correct
   literal, both languages:
   `The finding ".*" is(?: still| now)? (?:Open|Resolved|CLOSED)\.`
2. **The builder is not a ternary to tweak; it is a two-way branch needing a third arm.**
   [`status_conclusion_runs`](app/report_service.py#L500) and
   [`statusConclusionRuns`](app/web/static/app.js#L128) both branch on `status_word == "Open"` and
   emit `is still ` or `is `. Passing `"CLOSED"` through them today produces `The finding "X" is
   CLOSED.` — the `now` silently missing. Each side needs a three-way verb choice keyed by the
   status word.
3. **The recognition-only test I proposed cannot detect that miss.** I wrote the step 5 test as
   *"`is_default_status_conclusion` returns true for it"*. The widened pattern accepts `is CLOSED.`
   exactly as readily as `is now CLOSED.`, because the verb group is optional — so that test passes
   with the third arm absent. **The recogniser structurally cannot police the builder here.** The
   only guard is asserting the produced string **verbatim**, on both sides. Note this also means
   simply adding `"CLOSED"` to the `status_word` tuple in the existing drift guard,
   [`test_the_conclusion_recogniser_matches_what_the_builder_writes`](tests/test_app.py#L2073), is
   **not sufficient** — that test feeds the builder's output back to the recogniser and would go
   green on the broken sentence.
4. **The status word is five sites, not three.** I named
   [app/report_service.py](app/report_service.py#L326),
   [app/web/static/app.js](app/web/static/app.js#L1058) and
   [app/web/static/app.js](app/web/static/app.js#L1131). I missed
   [app/web/static/app.js](app/web/static/app.js#L3949) — the *"Put it back"* offer — and
   [app/web/static/app.js](app/web/static/app.js#L3966) — the *"does not state whether the finding
   is open or resolved"* offer. Missing either writes `is still Open.` into a Closed finding, which
   the widened recogniser then **accepts as the app's own sentence**, so it neither counts as work
   nor raises anything. Because five inline copies of a three-way rule is how a sixth gets it wrong,
   step 4 below collapses them to one named helper per language.
5. **Step 7's `main_template_path` edit is contradicted by the Answers and is dropped.** I proposed
   replacing the `asia = segment == "Asia"` boolean with a per-segment suffix lookup so that GDT
   taking the JH master became a recorded decision. The Answers say *"`main_template_path` keeps
   Asia as a boolean"*. [app/docx_report.py](app/docx_report.py#L161) is therefore **untouched**, and
   §12's *"is this report Asia"* row ([docs/DATA_MAP.md](docs/DATA_MAP.md#L366)) stays a boolean. What
   survives is the Literal, the widened matrix and the widened smoke render — the decision is
   recorded in the test matrix instead of in the code.
6. **Three sites were absent from the blast radius**, listed in the next section. One of them,
   [app/workspace.py](app/workspace.py#L286), is a file the Round 1 proposal never named at all.

### What the Answers themselves got wrong

The *Answers* section said *"`Closed` leaves whatever the tester wrote"* about the Recommended
Remediation. That holds only for a finding that was never Resolved. Entering `Resolved` **replaces
the whole fragment list** ([app/report_service.py](app/report_service.py#L314)), and the unwind arm
([app/report_service.py](app/report_service.py#L320)) only strips the boilerplate it wrote — it
restores nothing. So Open → Resolved → Closed ends with an **empty** remediation, which is a
required section, so generation is blocked until the tester writes one. The browser warns on the way
*into* Resolved and not on the way out (`replacesRemediation` at
[app/web/static/app.js](app/web/static/app.js#L2599) is
`nextStatus === "resolved" && finding.status !== "resolved"`). None of this is new behaviour and the
plan changes none of it — but the correction is now recorded in the *Answers* section itself, because
"Closed leaves the remediation alone" would otherwise be read as a promise the code does not make.

### Revised blast radius

Round 1's table minus the five things the Answers retired, plus the three the Oracle found. `RM`
marks a row removed since Round 1, `NEW` a row added.

| File | What changes | Twin |
|---|---|---|
| [app/models.py](app/models.py#L10) | `Status` gains `"closed"` | — |
| [app/models.py](app/models.py#L32) | `Segment` gains `"GDT"` | — |
| [app/docx_report.py](app/docx_report.py#L48) | `STATUS_LABELS["closed"] = "Closed"` | the other three label copies |
| ~~[app/docx_report.py](app/docx_report.py#L161)~~ | **`RM`** — `main_template_path` keeps its boolean per the Answers | — |
| ~~[app/report_service.py](app/report_service.py#L251)~~, ~~[app/web/static/app.js](app/web/static/app.js#L1078)~~ | **`RM`** — Q1 = A, both twins fall through correctly | — |
| ~~[app/report_service.py](app/report_service.py#L312)~~, ~~[app/web/static/app.js](app/web/static/app.js#L1105)~~ | **`RM`** — the bare `next(...)`/`.find()` cannot miss under Q1 = A | — |
| ~~[app/docx_import.py](app/docx_import.py#L887)~~ | **`RM`** — `expected_sections` already gives Closed the five-section shape | — |
| [app/report_service.py](app/report_service.py#L497) | pattern → `is(?: still\| now)? (?:Open\|Resolved\|CLOSED)` | [app/web/static/app.js](app/web/static/app.js#L133) — one commit |
| [app/report_service.py](app/report_service.py#L500) | third verb arm in the builder | [app/web/static/app.js](app/web/static/app.js#L128) — one commit |
| [app/report_service.py](app/report_service.py#L326) | the status word, via a new named helper | [app/web/static/app.js](app/web/static/app.js#L1058), [L1131](app/web/static/app.js#L1131), [L3949](app/web/static/app.js#L3949), [L3966](app/web/static/app.js#L3966) — **five sites, two languages** |
| [app/docx_import.py](app/docx_import.py#L54) | `"Closed": "closed"`; `LABEL_BY_STATUS` and `status_counts` derive | the three other label copies |
| [app/docx_import.py](app/docx_import.py#L947) | retest drops `closed` as it drops `resolved` | — |
| [app/docx_import.py](app/docx_import.py#L984) | the comment *"Resolved never reaches here at all"* becomes incomplete | — |
| [app/docx_import.py](app/docx_import.py#L1112) | `parts[0] in ("JH", "GWAM", "Asia", "GDT")` — a **fourth** copy of "which segments exist" | — |
| [app/docx_import.py](app/docx_import.py#L1192) | **`NEW`** — `dropped_resolved` becomes a misnomer; decision and reasoning in step 5 | [app/web/static/manager.js](app/web/static/manager.js#L198) |
| [app/workspace.py](app/workspace.py#L286) | **`NEW`** — `load_path`'s stale-remediation arm is a second writer of `recommended_remediation`, outside `provision` and outside the save path. Decision in step 6 | — |
| [app/web/static/manager.js](app/web/static/manager.js#L203) | **`NEW`** — the dropped-findings notice hardcodes the word "Resolved"; `labels` does not reach it | — |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels.closed = "Closed"` | the three other label copies |
| [app/web/static/app.js](app/web/static/app.js#L119) | `statuses` gains `["closed", "Closed"]` — **last edit of the Closed half**; `optionLabel` ([L277](app/web/static/app.js#L277)) and the review-panel word ([L3852](app/web/static/app.js#L3852)) both read from it and are fixed for free | [app/docx_report.py](app/docx_report.py#L48) |
| [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | one `<option value="GDT">` — **last edit of the GDT half** | [app/models.py](app/models.py#L32) |
| [tests/test_app.py](tests/test_app.py#L673) | a fifth-status sibling; plus the verbatim-sentence assertions | — |
| [tests/test_docx.py](tests/test_docx.py#L1092), [L1119](tests/test_docx.py#L1119) | four rows → six, on both the matrix and the smoke render; plus the `Status` ↔ `STATUS_LABELS` contract test | — |
| [tests/test_docx_import.py](tests/test_docx_import.py#L1038), [L1121](tests/test_docx_import.py#L1121) | Closed round-trips as `closed` with no warning; a retest drops it; a GDT title yields all three fields; plus the `STATUS_LABELS` ↔ `LABEL_BY_STATUS` contract test | — |
| [tests/test_browser.py](tests/test_browser.py#L477) | the verbatim segment list gains `"GDT"` — **same edit as the `<option>`** | — |
| [tests/test_browser.py](tests/test_browser.py#L3139) | a fifth-status sibling | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L190) | **`NEW`** — §11's *"only `resolved` is dropped"* | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L247) | **`NEW`** — §7's `load_path` repair note gains the Closed case | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L366) | §12's *"is this report Asia"* row gains the importer's title allowlist as a copy; **stays a boolean** | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L374) | §12's conclusion row and the paragraph describing the sentence | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L419) | §12's Additional Information grid: a `Closed` column, and `GDT` joins the `JH, GWAM` row | — |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L428) | the four-copy label paragraph | — |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L217), [L249](docs/DOCX_TEMPLATE.md#L249) | the **two** three-status enumerations gain `Closed` | — |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L11) | one sentence: GDT lands in the *not Asia* column deliberately | — |

Three regions the scribe flagged need **no** edit after the Answers, and the plan says so rather than
leaving them to be discovered: [L154](docs/DOCX_TEMPLATE.md#L154) (*"four canonical template
structures"* — still four), [L237](docs/DOCX_TEMPLATE.md#L237) (*"Previous Proof of Concept and In
Conclusion exist only in retest finding components"* — still true, no third component), and
[L104](docs/DOCX_TEMPLATE.md#L104) (CVSS scoped to Asia — still true, GDT is not Asia).

Per the data-layer contract, every `docs/DATA_MAP.md` slice **rides with the step that changes the
rule**. The same is applied to `docs/DOCX_TEMPLATE.md`, which is why Round 1's trailing docs step is
gone: a shared docs step at the end cannot exist when the two halves must be separable.

### Preconditions — now facts to record, not blockers

P2 and P3 are void: no master pair, no third component. Two survive, and **neither blocks a step**.

- **P1 — the cover pages of `MAIN.docx` and `MAIN_ASIA.docx` are unverified.** The scribe measured
  the two masters as identical through every body paragraph and body table bar one caption and one
  table, and established that the text extraction is **blind to cover-page text boxes**. GDT's
  branding was taken on the owner's judgement with that region unexamined. If GDT ever needs a
  different title block, that is a Word-authoring job plus a three-way template selection — a new
  plan, not a late step in this one.
- **P4 — the `Status` cell in `resources/finding_types/*.docx` is not known to be free of a Word
  content control.** The write lands either way; the residue would be a Word dropdown in a client's
  copy holding a value outside its own list. Cheap to check, blocks nothing.

### Data risks, revised

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation path; a status or segment change is an ordinary field edit through the existing `PUT /reports/{id}`, which already carries `saved_at`. |
| Lost update | clear | `provision_report` is called from exactly where it is called today ([app/main.py](app/main.py#L262)), inside the existing lock. Widening a `Literal` adds no second writer to the save path. |
| Orphan reference | clear — **corrected** | Round 1 marked this `RISK under Q1 = B`. Q1 = A is settled, so the condition can no longer be true and the conditional is deleted rather than left standing. Nothing is unprinted, so nothing is carried and nothing is dropped. |
| Import refusal on shape | clear — **corrected** | Same dead conditional. Verified: `expected_sections` at [app/docx_import.py](app/docx_import.py#L887) branches on `row["status"] != "open_new"`, so Closed gets the five-section expectation with no arm added. |
| Derived-state fight | **RISK** — **corrected, and it is a different risk than I wrote** | Round 1 marked this `RISK under Q1 = B`; that condition is dead, and both `content_types_for_status` twins now provably cannot disagree. The real content is the second derived-state owner I never named: [`Workspace.load_path`](app/workspace.py#L286) empties the runs of an unlabelled paragraph reading exactly `RESOLVED_REMEDIATION` on any non-`resolved` finding, then rewrites the draft to disk — outside `provision`, outside the save path, on *load*. A Closed finding takes that arm. Settled in step 6. |
| Silent stranding | clear | Neither axis touches `scope`, `target_ids`, environments or app types. |
| Schema break, forwards | clear | Widening a `Literal` cannot reject anything that validated before; neither field has a `before` validator, coercion or default-on-invalid. `validate_references` reads neither field. Re-checked: no draft under `data/` holds `GDT` or `closed`. |
| Schema break, backwards | **RISK** | The one-way door, three doors: a draft holding either value cannot be opened at all by an older build (`load_path` raises, `list_reports` skips it, `list_legacy_reports` marks it `repairable: false`, every route 422s); exports are refused wholesale; a generated Closed document re-imports as `open_previously_discovered` with a warning. **Folded in from Round 1's separate *Backup exhaustion* row:** `draft.bak.json` holds one revision, so two saves after a tester first picks a new value there is no version an older build can open. That is the same hazard with the same mitigation, and listing it twice read as two. The mitigation is sequencing — picker last — not backups. |
| Request/response asymmetry | clear | No new field in either direction. |
| Rule drift | **RISK — the largest** | Verdict unchanged, membership corrected. Five twins: the four-copy label table; `STATUS_CONCLUSION_PATTERN`; the sentence builder; the status word at **five** sites in two languages; and the segment allowlist, four copies once the importer's title tuple is counted. Steps 1, 2 and 4 each add the contract test that makes the worst of these impossible to ship. |
| Navigation trap | clear | No new required field. GDT is one more option in an already-required select and `setup_issues` tests presence only. |
| Round-trip downgrade | **RISK, half-closed by step 2** — **corrected** | Step 2 fixes `STATUS_BY_LABEL` for this build. What Round 1 missed is the other half: the retest notice at [app/web/static/manager.js](app/web/static/manager.js#L203) hardcodes *"N **Resolved** findings were not included"* and will name Closed findings with the wrong word. `labels.closed` does not reach that string. Step 5. |
| Total functions answering for an unknown status | **RISK** — **new row** | Round 1's *Bare status subscripts* row censused only `KeyError`-shaped risks and so stopped at the two `STATUS_LABELS` subscripts plus the safe `LABEL_BY_STATUS[row["status"]]`. `status_conclusion_runs` and `statusConclusionRuns` are **total** — they answer for any word rather than raising — so a missing third arm emits a wrong sentence silently. This is the only failure in the change with no loud edge anywhere. Step 4's verbatim assertion is the whole guard. |
| Importable before selectable | **RISK, narrow** — **new row** | Step 2 makes the importer accept a `Closed` status cell, and step 9 makes it accept a `GDT` title, both **before** the matching picker exists. A hand-edited Word document imported in that window writes a draft holding a value no picker offers: the status `<select>` renders with nothing selected and the review panel prints the raw key; the segment `<select>` renders blank and the first Setup edit can silently overwrite it. No typed content is lost — only the new value itself. Mitigation is release granularity, not ordering: **land each half's steps in one release**, so the window exists only mid-branch. Reversing the order instead would hand a tester a value that 422s every save, which is worse. |

### The ordering rule, and why it is stated twice

Within each half the value must become **storable, then printable, then readable back, and only then
selectable**. Every earlier step is inert: until the picker lands, no draft can acquire the value, so
there is no window in which a draft holds something the code has not learned, and no window in which
a picker offers something the server would reject. The precedent is already in the repository, in the
docstring of [tests/test_browser.py](tests/test_browser.py#L3139).

Inside the Closed half there is a second ordering with a sharper edge: **the recogniser ships before
the builder.** Builder-first is the only silent failure in this entire change — `default_conclusion_span`
would return `None` for every Closed sentence, so `provision` stops re-deriving it on a title change,
`content_has_work` starts counting the app's own boilerplate as tester work, and
`generation_issues` **stops blocking** a report whose conclusion the app wrote, which prints the
placeholder into a delivered document. Recogniser-first has no symmetric failure: widening is purely
additive, every sentence on disk still matches, and the only effect before the builder lands is that
a hand-typed `The finding "X" is now CLOSED.` stops counting as tester work — which is the intended
end state, one step early.

### What I would not do

1. **Turn `STATUS_LABELS[...]` into `.get(status, ...)` with a fallback.** The `KeyError` → HTTP 500
   is unpleasant but loud, and it is the only thing that makes shipping a status with no label
   impossible. A fallback converts it into a wrong word printed into a client document. The contract
   test in step 1 removes the failure without removing the alarm.
2. **Add a default to `provision`'s bare `next(...)`.** Verified safe under Q1 = A:
   `recommended_remediation` is in the list for every status and `provision` rebuilds `contents` from
   that list before the lookup. The bare call is load-bearing — it asserts the invariant.
3. **Render the setup `<option>` list from `Segment` through the Jinja context.** It looks like the
   fix for four hardcoded copies and removes exactly one: `statuses` in `app.js` cannot import from
   Python, and the importer's tuple is a parse allowlist rather than a picker.
4. **Leave the status word as five inline ternaries.** Three of them were already wrong in my own
   Round 1 census. A nested three-way conditional copied five times is how the sixth site gets
   written wrong; one named helper per language costs a line and makes the count irrelevant.
5. **Widen the conclusion builder before the recogniser, or both in one commit.** See above. One
   commit is nearly as bad as the wrong order, because it removes the step at which the additive
   half can be proved on its own.
6. **Rename `dropped_resolved` across the wire.** Reasoning in step 5 — the user-visible sentence is
   what is actually wrong, and a half-landed rename fails *silently*.
7. **Treat `draft.bak.json` as a rollback.** It holds one revision. The mitigation for the one-way
   door is sequencing.

## Answers

### Closed prints the same five sections as Resolved

Description, Recommended Remediation, Previous Proof of Concept, Proof of Concept, In Conclusion.

This is the answer that keeps the change codeable. Printing **fewer** sections was the only branch
that required a person in Word — a third file in `resources/finding_types/` — and it carried three
further costs: `expected_sections` would refuse every Closed document on import, making the round
trip impossible; a finding switched to Closed would hold typed work in sections that no longer
print, which is the carry-or-destroy problem this codebase has already been bitten by once; and the
bare `next(...)` in `provision` with its `.find()` twin would raise, giving a 500 on save and a
broken editor.

`Closed` therefore reuses `retest_finding.docx` and the existing `content_types_for_status` branch.
It differs from `Resolved` only in its printed label and in how a retest treats it.

### GDT reuses the existing non-Asia masters

No `MAIN_GDT.docx`, no `MAIN_THICK_MOBILE_GDT.docx`. `main_template_path` keeps Asia as a boolean
and GDT falls into the same branch as JH and GWAM, so the document cost of the whole segment is one
printed string — `{{segment}}` on the title line.

This was taken on the owner's judgement of what a GDT report looks like. The scribe measured
`MAIN_ASIA.docx` as `MAIN.docx` plus one caption paragraph and one `Section` table, body text
otherwise identical, but attached a caveat worth keeping: **the extraction is blind to the cover
page.** If GDT ever needs different branding or a different title block, that is a Word-authoring
job and a three-way template selection, not a code change.

### Closed's conclusion sentence, and the remediation it does not touch

The exact line, given by the owner:

> The finding "X" is now **CLOSED**.

Three things follow, and each one moves the pattern:

- **`is now` is a third verb phrase.** The pattern allows `is` and `is still` today; it must allow
  `is now` as well.
- **`CLOSED` is upper case** while `Open` and `Resolved` are title case. Deliberate. Recorded here
  because it looks like a mistake, and anyone who tidies it to `Closed` freezes every default
  sentence already on disk — nothing would recognise them as the app's own sentence any more.
- **Bold, not italic.** Matching `Run(text=status_word, bold=True)` in the existing builder.

So the pattern becomes, in both languages:

```
The finding ".*" is(?: still| now)? (?:Open|Resolved|CLOSED)\.
```

**Closed does not overwrite the Recommended Remediation.** `Resolved` replaces it with
`RESOLVED_REMEDIATION` and tags the paragraph `generated="resolved_remediation"`; `Closed` leaves
whatever the tester wrote. The owner's wording is a state change rather than a claim that the
vulnerability is gone, so a remediation is still worth printing.

**Corrected by Round 2, because this section said it wrong.** "Leaves whatever the tester wrote"
holds only when the finding was never Resolved. Entering `Resolved` **destroys** the original
remediation, and the unwind arm only strips the boilerplate it wrote — it restores nothing. So a
finding that goes Open → Resolved → Closed ends with an **empty** remediation, not its original one.
That is existing behaviour and not introduced here, but a plan that claims otherwise would be
setting up the next bug report.

**Owner's ruling, in their words: "CLOSED STATUS IS DIFFERENT FROM RESOLVED STATUS. DO NOT EDIT THE
RECOMMENDED REMEDIATION OF CLOSED STATUS… the recommended remediation will stay the same just like
open status. but when importing a vuln with closed status, drop it like it's resolved."**

So `Closed` borrows exactly one rule from `Resolved` — the retest drop — and none of the others:

| | Resolved | Closed | Open statuses |
|---|---|---|---|
| App writes the remediation | yes | **no** | no |
| App removes it on a status change | yes | **no** | no |
| Dropped on a retest import | yes | **yes** | no |

This confirms Step 6's *no code change* rather than overruling it: treating Closed like the open
statuses is what the existing `!= "resolved"` conditions already do. The one consequence the owner
should know is inherited rather than chosen — a tester who types the exact sentence
`None, the vulnerability has been remediated.` into a Closed finding loses it on the next load,
because the load repair cannot tell a typed copy from stale boilerplate. That is true of every open
status today, and Closed is being treated the same way deliberately.

### A retest drops Closed findings, as it drops Resolved

Only in `retest` mode: `if mode == "retest" and row["status"] == "resolved"` gains `Closed`. Editable
mode is unaffected and keeps every finding as written, which is also the way back for anyone who
needs a dropped finding.

A dropped finding takes its evidence and its typed work with it. That is already true of Resolved,
and editable mode is the recovery path.

## Agreed plan

Two halves, **independent of each other**. Part A (steps 1–7) and Part B (steps 8–10) share no file
except `app/models.py`, where they touch different lines, and neither reads the other's value.
Either may ship alone, in either order.

**The ordering rule inside each half is load-bearing, not stylistic.** The value becomes *storable*,
then *printable*, then *readable back*, and only then *selectable* — so at no point does a draft on
disk hold a value some consumer has not learned, and at no point does a picker offer a value the
server would reject. Every step before the last one in each half is inert: nothing can acquire the
value yet.

**Inside Part A the recogniser ships before the builder (step 3 before step 4)**, because a builder
emitting a sentence the pattern does not match is the one failure in this change that raises nothing
anywhere and prints the app's own placeholder into a delivered document.

**On verification:** every step below is provable on this machine. Two tests fail here for reasons
that predate this change and are not to be investigated —
`tests/test_app.py::test_generate_docx_route_uses_template_and_report_filename` and
`tests/test_browser.py::test_complete_report_saves_generated_docx_to_generated_folder` — both needing
Microsoft Word and `pywin32`. Neither is touched by any step, and `tests/test_docx.py` and
`tests/test_docx_import.py` exercise DOCX generation and round-trip in full without Word.

### Part A — `closed`

- [x] **Step 1 — Make `closed` storable and printable.**
      [app/models.py](app/models.py#L10): `Status` gains `"closed"`.
      [app/docx_report.py](app/docx_report.py#L48): `STATUS_LABELS` gains `"closed": "Closed"`, which
      is the whole of the status contract on the way out — both call sites
      ([L517](app/docx_report.py#L517), [L769](app/docx_report.py#L769)) are bare subscripts and the
      cell inherits the prototype run's formatting with no colour or size override.
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L419): §12's Additional Information grid gains a `Closed`
      column (it behaves as Previously Discovered, because `additionalInformationFields` gates on
      `status !== "open_new"` and needs no edit), and the four-copy label paragraph
      ([L428](docs/DATA_MAP.md#L428)) gains the fifth member.
      **Test:** `test_the_fifth_status_saves_and_prints_what_resolved_prints` in
      [tests/test_app.py](tests/test_app.py#L673), modelled on its fourth-status sibling — `provision`
      gives it the five-section shape, the remediation is **not** the remediated boilerplate, and a
      `PUT` round-trips the status. Plus a one-line contract test in
      [tests/test_docx.py](tests/test_docx.py#L1092)'s module:
      `set(STATUS_LABELS) == set(get_args(Status))`.
      **Invariant:** every member of `Status` has a printed label. Violated → `KeyError` → HTTP 500 on
      every generate of a report containing one such finding, escaping `finalized_report`'s
      `except (ReportGenerationError, RuntimeError)` to the global handler.
      **Verifiable without Word:** yes — `tests.test_app`, `tests.test_docx`.

- [x] **Step 2 — Make it readable back.**
      [app/docx_import.py](app/docx_import.py#L54): `STATUS_BY_LABEL` gains `"Closed": "closed"`.
      `LABEL_BY_STATUS` derives, and the import summary's `status_counts`
      ([L1192](app/docx_import.py#L1192)) follows for free because it iterates
      `STATUS_BY_LABEL.values()`.
      `expected_sections` at [app/docx_import.py](app/docx_import.py#L887) is **deliberately
      untouched** — `row["status"] != "open_new"` already yields the five-section shape, which is
      exactly what Closed prints — and the step should say so in the commit message so that nobody
      later "fixes" it into an arm.
      [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L217) and
      [L249](docs/DOCX_TEMPLATE.md#L249): the two separate three-status enumerations gain `Closed`.
      **Test:** beside
      [`test_an_unrecognised_status_is_assumed_rather_than_refusing_the_document`](tests/test_docx_import.py#L1121)
      — a generated report holding a Closed finding imports as `closed` **with no warning**, rather
      than as `open_previously_discovered` with one, and its section list matches what provisioning
      produces. Plus a contract test: `LABEL_BY_STATUS[s] == STATUS_LABELS[s]` for every member.
      **Invariant:** the string the document prints is the string the importer matches. Violated →
      a generated Closed report re-imports as `open_previously_discovered`; the import *succeeds*
      with one warning, so the loss is easy to miss.
      **Verifiable without Word:** yes — `tests.test_docx_import`.

- [x] **Step 3 — Widen the recogniser, and only the recogniser.**
      [app/report_service.py](app/report_service.py#L497) and
      [app/web/static/app.js](app/web/static/app.js#L133), **one commit**, both becoming
      `The finding ".*" is(?: still| now)? (?:Open|Resolved|CLOSED)\.` — two widenings, not one: the
      verb group **and** the alternation, with `CLOSED` upper case because neither pattern carries
      `re.IGNORECASE` or the `i` flag. The builder is **not** touched.
      `default_conclusion_span` / `defaultConclusionSpan` need no edit: both locate the sentence by
      `rfind`/`lastIndexOf` on `'The finding "'`, a marker the status word does not appear in.
      **Test:** in [tests/test_app.py](tests/test_app.py#L2073), assert every sentence shape already
      on disk still matches — `is Open.`, `is still Open.`, `is Resolved.` — and that a hand-written
      `The finding "X" is now CLOSED.` now matches; the browser twin gets the same pair in
      [tests/test_browser.py](tests/test_browser.py).
      **Invariant:** the recogniser is never narrower than the builder. Widening is provably
      additive; narrowing silently freezes every default sentence on disk at the title and status it
      was stored with.
      **Verifiable without Word:** yes — `tests.test_app`, `tests.test_browser`.
      **Note the one-step-early effect, so it is not discovered:** from this step a paragraph a
      tester hand-typed as `The finding "X" is now CLOSED.` stops counting as work in
      `content_has_work` / `contentHasWork`, so a section holding only that is dropped rather than
      carried. That is the intended end state, arriving one step before the app can write the
      sentence itself.

- [x] **Step 4 — Widen the builder, all five word sites and both third arms.**
      [app/report_service.py](app/report_service.py#L500) and
      [app/web/static/app.js](app/web/static/app.js#L128), **one commit**: each builder's two-way
      branch on `status_word == "Open"` becomes a three-way verb choice — `Open` → `is still `,
      `CLOSED` → `is now `, otherwise `is `. `Run(text=status_word, bold=True)` already gives the
      bold-not-italic the Answers specify, with no edit.
      The status word itself becomes **one named helper per language** — `status_conclusion_word(status)`
      and `statusConclusionWord(status)` — called from all five sites:
      [app/report_service.py](app/report_service.py#L326),
      [app/web/static/app.js](app/web/static/app.js#L1058),
      [L1131](app/web/static/app.js#L1131), [L3949](app/web/static/app.js#L3949) and
      [L3966](app/web/static/app.js#L3966). The last two are the *"Put it back"* and *"does not state
      whether the finding is open or resolved"* offers on the Content page; missing either writes
      `is still Open.` into a Closed finding.
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L374): §12's conclusion row and the paragraph describing the
      sentence gain the third verb phrase and the third word.
      **Test:** assert the **produced string verbatim** on both sides —
      `The finding "X" is now CLOSED.` — not merely that the recogniser accepts it. A
      recognition-only test passes with the third arm missing, because the widened pattern accepts
      `is CLOSED.` just as readily. Extend
      [`test_the_conclusion_recogniser_matches_what_the_builder_writes`](tests/test_app.py#L2073) with
      `"CLOSED"` as well, but only **in addition to** the verbatim assertion: on its own it goes green
      on the broken sentence. The browser twin asserts the same string through
      [tests/test_browser.py](tests/test_browser.py).
      **Invariant:** every sentence the builder can produce is matched by the pattern shipped in step
      3 — which is why this step cannot precede it — *and* the sentence the builder produces is the
      sentence the Answers specify, which the pattern cannot police.
      **Verifiable without Word:** yes — `tests.test_app`, `tests.test_browser`.

- [x] **Step 5 — Drop Closed findings on a retest, and say so in the right word.**
      [app/docx_import.py](app/docx_import.py#L947): the drop rule becomes
      `mode == "retest" and row["status"] in ("resolved", "closed")`. Editable mode is untouched and
      remains the recovery path for anyone who needs a dropped finding.
      [app/docx_import.py](app/docx_import.py#L984): the comment *"Resolved never reaches here at
      all"* becomes incomplete — one-line edit naming Closed too.
      [app/web/static/manager.js](app/web/static/manager.js#L203): the notice
      *"N **Resolved** findings were not included"* is the only sentence a tester ever sees naming
      what the import threw away, and the word is hardcoded — it must name both statuses.
      [app/docx_import.py](app/docx_import.py#L1192): **`dropped_resolved` keeps its name**, with a
      one-line comment recording what it now holds. Renaming is a four-test, two-file, one-contract
      edit ([tests/test_docx_import.py](tests/test_docx_import.py#L223),
      [L321](tests/test_docx_import.py#L321), [L1060](tests/test_docx_import.py#L1060),
      [tests/test_browser.py](tests/test_browser.py#L4729),
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L188)) for no user-visible gain, and a half-landed rename
      fails **silently**: `summary.dropped_resolved || []` reads empty and the notice simply vanishes.
      The tester-visible string is the thing that is actually wrong, and this step fixes that.
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L190): §11's *"only `resolved` is dropped"*.
      **Test:** beside
      [`test_a_retest_inherits_every_status_except_open_new`](tests/test_docx_import.py#L1038) — a
      retest of a report holding a Closed finding drops it and names it in `dropped_resolved`, while
      an `open_resolved_on_non_prod` finding beside it is still kept. Depends on step 2, because the
      rule reads `row["status"]`.
      **Invariant:** a finding named in `dropped_resolved` is named to the tester with the status it
      actually had. A dropped finding takes its evidence and typed work with it, so the notice is the
      only trace.
      **Verifiable without Word:** yes — `tests.test_docx_import`, `tests.test_browser`.

- [x] **Step 6 — Settle `load_path` for Closed, and pin it.**
      [app/workspace.py](app/workspace.py#L286): the stale-remediation arm empties the runs of a
      single unlabelled paragraph reading exactly `RESOLVED_REMEDIATION` on any finding whose status
      is not `resolved`, then rewrites the draft to disk. A Closed finding takes that arm, so a
      tester who genuinely typed that sentence loses it on the next load — and note this **contradicts
      `provision`**, where the same wording survives by design, pinned by
      [`test_a_testers_own_remediation_survives_provisioning`](tests/test_app.py#L706).
      **Decision: no code change.** Closed is one more status in the same class as the three open
      statuses, and the repair exists to strip boilerplate claiming a fix that never happened — which
      is exactly what an unlabelled `RESOLVED_REMEDIATION` paragraph on a Closed finding is, since
      `provision`'s unwind arm strips only the *marked* copy and leaves an unmarked legacy one behind.
      Exempting `closed` would be the one place in this change where a status silently keeps a
      sentence claiming remediation.
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L247): §7's repair note records that Closed takes the
      emptying arm and why, so it reads as a decision rather than a fall-through.
      **Test:** in [tests/test_app.py](tests/test_app.py) or
      [tests/test_storage.py](tests/test_storage.py), a draft written with `status: "closed"` and an
      unlabelled `RESOLVED_REMEDIATION` paragraph loads with that paragraph emptied, and the
      **resolved** case still gains the marker rather than being emptied.
      **Invariant:** no status other than `resolved` keeps an unmarked paragraph claiming the
      vulnerability was remediated.
      **Verifiable without Word:** yes — `tests.test_app` / `tests.test_storage`.
      **This is the one step the owner may want to overrule**; it changes no behaviour today, so
      reversing it later costs one conditional and one test.

- [x] **Step 7 — Make `closed` selectable.**
      [app/web/static/app.js](app/web/static/app.js#L119): `statuses` gains
      `["closed", "Closed"]`. `optionLabel` ([L277](app/web/static/app.js#L277)) and the review
      panel's status word ([L3852](app/web/static/app.js#L3852)) both read from that list and are
      fixed for free — before this step the review panel prints the raw key.
      [app/web/static/manager.js](app/web/static/manager.js#L208): `labels.closed = "Closed"`, so the
      import summary reads `2 Closed` rather than `2 closed`.
      **Test:** `test_the_fifth_status_is_offered_and_saves` in
      [tests/test_browser.py](tests/test_browser.py#L3139), mirroring its fourth-status sibling
      **including the docstring that states why this is last** — select `closed` in the finding row,
      wait for the `PUT`, and assert the server stored it and gave it the five-section shape. No
      existing assertion breaks: `statuses` is pinned nowhere verbatim, the nearest being an
      `assertIn` on one label at [tests/test_browser.py](tests/test_browser.py#L3147).
      **Invariant:** a status the picker offers is a status the server, the document, the importer,
      the recogniser and the builder already know. This is the **first moment a draft can hold
      `closed`**, and therefore the first moment the one-way door opens.
      **Verifiable without Word:** yes — `tests.test_browser`.

### Part B — `GDT`

- [x] **Step 8 — Make `GDT` storable, and prove what it renders.**
      [app/models.py](app/models.py#L32): `Segment` gains `"GDT"`.
      [app/docx_report.py](app/docx_report.py#L161) is **untouched** — per the Answers,
      `main_template_path` keeps `asia = segment == "Asia"` as a boolean and GDT falls into the same
      branch as JH and GWAM. The decision is recorded in the test matrix instead of in the code,
      which is the point of widening the matrix rather than just the Literal. `{{segment}}` needs no
      edit: [`_metadata`](app/docx_report.py#L272) passes `engagement.segment or "N/A"` straight
      through, so printability is free and the smoke render is what proves it.
      [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L11): one sentence saying GDT lands in the *not
      Asia* column deliberately. The 2×2 matrix itself stays, as do
      [L154](docs/DOCX_TEMPLATE.md#L154) and [L104](docs/DOCX_TEMPLATE.md#L104).
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L419): §12's Additional Information grid — the `JH, GWAM`
      row becomes `JH, GWAM, GDT`.
      **Test:** widen
      [`test_main_template_path_selects_on_both_axes`](tests/test_docx.py#L1092) from four rows to six
      — `("web", "GDT")` → `MAIN.docx`, `("thick_client", "GDT")` → `MAIN_THICK_MOBILE.docx` — keeping
      the `chosen.parent == resources` assertion on every branch; and widen
      [`test_every_shipped_template_renders_without_unresolved_placeholders`](tests/test_docx.py#L1119)
      to the same six, so a GDT report is *proved* to render with no unresolved placeholder rather
      than assumed to.
      **Invariant:** `main_template_path` remains the sole owner of the choice, and its `.parent`
      stays `resources/` because that path doubles as the component fragment root.
      **Verifiable without Word:** yes — `tests.test_docx` renders end to end here.

- [x] **Step 9 — Teach the importer's title parser.**
      [app/docx_import.py](app/docx_import.py#L1112): the literal tuple gains `"GDT"`. This is the
      **fourth** copy of "which segments exist" and the one §12 does not record; it is a parse
      allowlist, not a picker, and there is no second copy inside the importer. The split at
      [L1111](app/docx_import.py#L1111) already accepts en dash, em dash and hyphen, so the en dash
      the masters print and the plain hyphen `report_export_filename` writes both parse — GDT changes
      nothing there.
      [docs/DATA_MAP.md](docs/DATA_MAP.md#L366): §12's *"is this report Asia"* row gains the title
      allowlist as a copy of the segment set, and **stays a boolean** on the template axis.
      **Test:** in [tests/test_docx_import.py](tests/test_docx_import.py#L1038)'s class, a GDT
      report's title yields `segment`, `app_name` **and** `report_type` — all three asserted
      together, because the three assignments live inside one `if` and a failed match loses them as a
      unit, with **no error raised**: the `Unknown report type` raise is inside the matched branch, so
      a GDT title never reaches it.
      **Invariant:** a segment the app can print is a segment the app can read back.
      **Verifiable without Word:** yes — `tests.test_docx_import`.

- [x] **Step 10 — Make `GDT` selectable.**
      [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7): one
      `<option value="GDT">GDT</option>`.
      [tests/test_browser.py](tests/test_browser.py#L477): the verbatim assertion
      `["Select segment", "JH", "GWAM", "Asia"]` gains `"GDT"` **in the same edit** — widening it
      earlier fails at HEAD, widening it later leaves the suite red.
      **Test:** that same assertion in
      `test_segment_and_report_type_are_required`; no new test is needed, because the list is already
      pinned verbatim and the storable/printable/readable halves are proved by steps 8 and 9.
      **Invariant:** first moment a draft can hold `GDT`, and by now the Literal, the template
      chooser and the importer already know it.
      **Verifiable without Word:** yes — `tests.test_browser`.

### What this change deliberately does not do

1. **No new `.docx` anywhere.** No `MAIN_GDT.docx`, no `MAIN_THICK_MOBILE_GDT.docx`, no third
   component under `resources/finding_types/`. Nothing in this repository can author one, so a step
   that needed one would be a step that could not be taken.
2. **Closed prints no fewer sections than Resolved.** A Closed finding with no previous proof and no
   conclusion prints those static headings with `N/A` beneath each, exactly as
   `Open (Resolved on Non-Prod)` does today. Suppressing them needs a Word author, an
   `expected_sections` arm, and it accepts that a tester's written In Conclusion is *destroyed
   rather than carried* on the way into Closed.
3. **`main_template_path` stays a boolean.** GDT renders `MAIN.docx` / `MAIN_THICK_MOBILE.docx`, no
   CVSS appendix, no CVSS requirement. Per the Answers, on the owner's judgement, with the cover
   pages unverified (P1).
4. **No migration, and no way back.** Once a draft holds `GDT` or `closed` an older build cannot open
   it at all, and `draft.bak.json` holds one revision. Sequencing delays the door; nothing closes it.
5. **No fallback for an unknown status label on the generate path.** `STATUS_LABELS[...]` stays a
   bare subscript; the contract test in step 1 is the guard, not a `.get`.
6. **No default on `provision`'s bare `next(...)`** or its browser `.find()` twin. Both are safe under
   the settled section rule and both are load-bearing assertions of it.
7. **`dropped_resolved` is not renamed.** The wire key stays; the tester-visible sentence is fixed.
8. **The four copies of the status label table and the four copies of the segment set are not
   unified.** Contract tests pin two of the four label copies to each other; `app.js` and
   `manager.js` cannot import from Python, and the importer's segment tuple is a parse allowlist
   rather than a picker.
9. **`resolved`-only rules stay `resolved`-only**, verified one by one and correct to leave: the
   library remediation offer ([app/web/static/app.js](app/web/static/app.js#L1433)), the editor
   remediation lock ([L4110](app/web/static/app.js#L4110)), `replacesRemediation`
   ([L2599](app/web/static/app.js#L2599)), the editable-mode boilerplate check
   ([app/docx_import.py](app/docx_import.py#L962)), and the `RESOLVED_REMEDIATION` replacement arm in
   `provision`. Closed keeps an editable remediation, so it must keep the offer, stay unlocked, and
   raise no replacement warning.

## What deviated

**Validation ran after the implementation.** Final unittest discovery exercised 373 tests; all 371
portable tests passed. The two documented macOS Word/`pywin32` generation cases remain
environment-limited, so only a Windows generate-then-import run can prove their Word-side path.

**Step 4's helper has four JavaScript callers, not three.** Round 1 inventoried three status-word
ternaries; the shipped `statusConclusionWord` is called from four sites in `app.js` — the two Round 1
found plus the Content page's *"Put it back"* and *"does not state whether the finding is open or
resolved"* offers, which the Round 2 verdict caught. Missing either would have written
`is still Open.` into a Closed finding.

**Step 1's test split into three.** The plan named one test; what shipped is
`test_the_fifth_status_saves_and_keeps_the_remediation_the_tester_wrote` for the section shape and
the untouched remediation, `test_the_conclusion_builder_writes_the_exact_sentence_each_status_owns`
asserting the produced string **verbatim** for all five statuses, and
`test_every_status_has_a_label_the_importer_can_read_back` covering both label maps at once rather
than one contract test per step. The verbatim assertion is the one that matters: the widened pattern
accepts `is CLOSED.` as readily as `is now CLOSED.`, so a recognition-only test goes green on a
missing verb arm.

**Step 2 gained a second test.** Beyond the retest drop, `test_an_editable_import_keeps_a_closed_finding_as_closed`
asserts a Closed finding survives an editable import **with no warning** — the failure it guards
against succeeds loudly enough to look fine, since an unrecognised label downgrades to
`open_previously_discovered` and merely warns.

**The plan's section pointers into `docs/DATA_MAP.md` were stale.** The "only `resolved` is dropped"
text lives in §7 rather than §11, and the `load_path` repair note in §8 rather than §7. The
documentation was updated where the text actually is.

**`docs/DATA_MAP.md` §12 needed one claim retracted.** It described the four label copies as having
no drift guard. Two of the four are now pinned to each other by the step 1 contract test, so that
sentence was corrected rather than left standing.

## Follow-up: the GFT segment, 2026-09-22

A fifth segment, `GFT`, was added on exactly the terms settled here — no master of its own, reusing
the non-Asia pair, the whole document cost being one printed string.

**No exchange was run, deliberately.** This plan had already located every place the segment set
lives and the owner had already answered the two questions that made `GDT` large: which template,
and whether it prints CVSS. With nothing left to discover, four subagent calls would have
rediscovered this document. It is recorded here rather than in a plan of its own, because a plan
costs more than the change it would describe.

The same three source sites, the same three test sites:

| | |
|---|---|
| `app/models.py` | `Segment` gains `"GFT"` |
| `app/docx_import.py` | the title-parser allowlist gains it |
| `app/web/templates/page1_setup.html` | one `<option>`, last as always |
| `tests/test_docx.py` | both matrices widen from six rows to eight |
| `tests/test_browser.py` | the verbatim option list, in the same edit as the `<option>` |
| `tests/test_docx_import.py` | the title test, rewritten — see below |

**One thing was improved rather than copied.** `test_a_gdt_report_title_yields_segment_name_and_report_type_together`
tested one hardcoded segment, so adding a sixth would have needed a third near-identical test and a
seventh a fourth. It is now
`test_every_segment_the_model_allows_parses_back_out_of_a_title`, driven from `get_args(Segment)`.

That converts a copied test into a **drift guard**: a segment added to the `Literal` but not to the
importer's allowlist now fails there. This plan's *"what this change deliberately does not do"* listed
the segment set's copies as unguarded, and one of those copies no longer is. The picker remains
guarded only by the verbatim browser assertion, which is unchanged.

**Verified.** `tests.test_docx` and `tests.test_docx_import` 95 tests, `tests.test_app` 106,
`tests.test_browser` 163 — the only failures the two known Word/`pywin32` cases. The drift guard
passes across all five segments, which is what makes the importer's allowlist and the `Literal`
agree in fact rather than by assumption. No line endings flipped.
