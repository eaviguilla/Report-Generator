# Import a generated DOCX as a retest draft

> **Status:** shipped · 2026-09-15 · `95b6769`

## Request

> there are 2 new files in the root folder. One is a report that I want to be imported by this app itself. then another is a python script that can export the data from that report to import to the app. Do not use the python script but, use it as reference. You know the data that we put in the report. now use it as reference to know how to get those data in the report. I only care about vulns that are Open, new or previously discovered, the description and recommended remediation of those vulns, and the latest Proof of concept that they have, which is Labeled Proof of Concept. Disregard the Previous proof of Concept. If a POC is labeled as Proof of Concept instead of a Previous Proof of Concept, then it is automatically the latest POC. I want to be able to get all the fragments, and when I import a Report, all details from that report will be a draft in the app. And all the latest POC of the Open vulns in that report will be the Previous POC for the draft in the app.

### Supplied material

- `JH - Northstar Customer Portal - Annual Pentest 2026.docx` — a report produced by this app, to be imported.
- `docx_to_vulnreport_bundle.py` — a standalone converter, **reference only, not to be used or shipped**. Its docstring states it "removes Resolved/Closed findings, discards every source Previous Proof of Concept section, moves each retained finding's current Proof of Concept into Previous Proof of Concept, and creates an empty current Proof of Concept for the next retest", emitting a ZIP for the existing Import command.

### Restated requirement

Import a generated DOCX directly in the app. Keep only findings whose status is Open (New) or Open (Previously Discovered). For each, carry over description, recommended remediation, and the section labelled **Proof of Concept** — which is by definition the latest. Ignore any **Previous Proof of Concept** section in the source. In the resulting draft, the carried-over Proof of Concept becomes the **Previous Proof of Concept**. All fragment types must survive.

## Round 1 - Oracle: how it works today

### 1. The existing import path

**Accepts both.** `POST /reports/import` takes a single multipart `file` and branches on content sniffing, not on filename or content type: [app/main.py](app/main.py#L509-L518) reads the bytes, then [parse_import](app/main.py#L286-L337) calls `zipfile.is_zipfile(io.BytesIO(contents))`. Not a ZIP → treated as bare `draft.json`. Is a ZIP → treated as a bundle.

**Bare-JSON branch** ([app/main.py](app/main.py#L287-L294)): 10 MB cap (`MAX_JSON_IMPORT_BYTES`), `json.loads`, `Report.model_validate`, then:

```python
if report.evidence:
    raise ValueError("Reports with evidence must be imported from a VulnReport ZIP bundle")
```

So a JSON-only import can never carry images.

**ZIP branch** ([app/main.py](app/main.py#L296-L337)) validates, in order: ≤1000 members, no duplicate paths, `draft.json` present, no encrypted entries (`flag_bits & 1`), total uncompressed ≤250 MB, `draft.json` ≤10 MB, `Report.model_validate`, then **exact set equality** — `set(names) - {"draft.json"} == {evidence.file for evidence in report.evidence.values()}`. One extra file or one missing file fails. Then per image: ≤20 MB, `sha256` must match `evidence.sha256`, PIL `format == "PNG"`, `image.size == (width_px, height_px)`, pixel count ≤40 M, `image.verify()`.

**ID allocation.** `report_id` is reminted unconditionally; `app_id` is *not* touched at all ([app/workspace.py](app/workspace.py#L138-L158)):

```python
imported.report_id = f"r_{uuid.uuid4().hex[:12]}"
imported.saved_at = now
imported.folder_name_hint = FolderHint()
destination = self.save(imported)
```

The folder is then derived in [_save_unlocked](app/workspace.py#L310-L322) as `<first ASCII letter of app_name, else X>_<safe_name(app_id)>/<YYYY-MM>_Report_<report_id[2:]>/`. Because `report_id` is fresh, the report-folder name is unique and there is **no collision handling, because no collision is possible**. `evidence_id`, `frag_id`, `uid`, `target_id` and `display_id` are all **preserved verbatim** — [tests/test_app.py](tests/test_app.py#L784) asserts the imported report serves the *same* `evidence_id`.

**Evidence files** are written after the draft is saved, and the whole report directory is torn down if any write fails ([app/workspace.py](app/workspace.py#L149-L157)). `import_report` re-validates a second time.

**It returns** `{"report_id": report.report_id}` only. Any of `UnicodeDecodeError, JSONDecodeError, BadZipFile, UnidentifiedImageError, OSError, ValidationError, ValueError` becomes **422** `"Select a valid VulnReport export: {error}"`; size failures raise **413** from inside `parse_import`.

**Not established in the source:** any call to `provision`, `sync_evidence_image_slots`, or `reconcile_targets` on the import path. `provision_report` is only wired to the PUT handler ([app/main.py](app/main.py#L245-L249), [app/main.py](app/main.py#L642)).

The browser's file picker is restricted to `accept="application/zip,application/json,.zip,.json"` ([app/web/templates/home.html](app/web/templates/home.html#L4)).

### 2. The export path

[app/main.py](app/main.py#L429-L445) builds a deflated ZIP containing exactly:

- `draft.json` — `report.model_dump(mode="json", by_alias=True)`, `indent=2`, `ensure_ascii=False`, plus a trailing newline
- `evidence/<evidence_id>.png` for every entry in `report.evidence`, sorted

Filename comes from [report_export_filename](app/report_service.py#L138-L152): `"{Segment} - {App Name} - {Report Type} {Year}.zip"`.

[export_bundle](app/workspace.py#L160-L174) loads under the lock and raises `ValueError` (→422) if any evidence file is missing or resolves outside `evidence/`.

**Import is *not* strictly the inverse of export.** Four asymmetries, all in source:

| | Export | Import |
|---|---|---|
| `report_id` | preserved | reminted ([app/workspace.py](app/workspace.py#L145)) |
| `saved_at` | preserved | overwritten with `now`, then bumped again by `_save_unlocked` |
| `_folder_name_hint` | preserved | reset to `FolderHint()` |
| evidence integrity | never checked | sha256 + PNG format + exact dimensions enforced |

The last row is the sharp one: export will happily emit a bundle whose `evidence.sha256` no longer matches the bytes on disk, and that bundle will be rejected on import. [tests/test_app.py](tests/test_app.py#L786-L791) exercises exactly that rejection.

### 3. The content-section model

Section names are a closed literal ([app/models.py](app/models.py#L18)):

```python
ContentType = Literal["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]
```

[Content](app/models.py#L85-L87) is just `{type: ContentType, fragments: list[Fragment]}`. **The schema does not constrain which fragment types may live in which section, and does not constrain which sections a status requires.** The only schema-level rule is "no duplicate `type` within one finding" ([app/models.py](app/models.py#L218-L220)).

The status → section rule lives in [provision](app/report_service.py#L154-L206):

```python
types = ["description", "recommended_remediation", "proof_of_concept"]
if vulnerability.status != "open_new":
    types = ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]
existing = {content.type: content for content in vulnerability.contents}
vulnerability.contents = [existing.get(content_type, Content(type=content_type)) for content_type in types]
```

Behaviour by status:

- **`open_new`** — exactly three sections. `previous_proof_of_concept` and `in_conclusion`, **if present, are dropped** along with their fragments.
- **`open_previously_discovered`** — all five, in order. An existing section object is reused by identity, so its fragments survive.
- **`resolved`** — same five, plus `recommended_remediation.fragments` is **unconditionally replaced** with one paragraph reading `"None, the vulnerability has been remediated."` ([app/report_service.py](app/report_service.py#L183-L185)).

Seed fragments, only when a section is empty ([app/report_service.py](app/report_service.py#L163-L169)): `description` and `recommended_remediation` get one empty `paragraph`; both proof-of-concept sections get one `numbered_list` with a single empty item. `in_conclusion` gets its status sentence synthesised — `The finding "<title>" is still Open.` — with the status word bold ([app/report_service.py](app/report_service.py#L186-L206)).

**Directly relevant to the request:** a PoC that should land as a Previous PoC must arrive on a finding whose `status != "open_new"`. If the importer writes `previous_proof_of_concept` onto an `open_new` finding, the model accepts it and it persists on disk — but the first browser save runs `provision` and **silently deletes it**. Import never calls `provision`, so the loss is deferred, not immediate.

### 4. Fragment types

`Fragment` is a discriminated union on `type` ([app/models.py](app/models.py#L82)). Seven members:

| `type` | Model | Fields beyond `frag_id` / `type` |
|---|---|---|
| `paragraph` | [ParagraphFragment](app/models.py#L29-L33) | `runs: list[Run] = []`, `generated: Literal["status_conclusion"] \| None` |
| `numbered_list`, `bulleted_list` | [ListFragment](app/models.py#L40-L43) | `items: list[ListItem]` — **`min_length=1`** |
| `table` | [TableFragment](app/models.py#L46-L51) | `caption: str \| None`, `header: list[ListItem]`, `rows: list[list[ListItem]]` |
| `note` | [NoteFragment](app/models.py#L54-L57) | `runs: list[Run]` |
| `image` | [ImageFragment](app/models.py#L60-L66) | `environment: Environment \| None`, `evidence_id: str \| None`, `caption: str = ""`, `width_mm: float \| None` |
| `code_block` | [CodeFragment](app/models.py#L69-L73) | `caption: str \| None`, `text: str = ""` |
| `instance_title` | [InstanceTitleFragment](app/models.py#L76-L79) | `text: str = ""` |

`Run` is `{text, bold, italic, underline}`; `ListItem` is `{runs}`.

**Fragment ID constraint.** `frag_id: StableId` ([app/models.py](app/models.py#L19)):

```python
StableId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
```

Uniqueness is report-wide, not section-wide.

**Image binding.** `validate_references` requires every non-null `evidence_id` to be a key of `report.evidence`; `EvidenceItem.file` must be `evidence/<name>.png` and the basename must equal the dict key. `ImageFragment.environment` is an `Environment` enum, not a `target_id`; the link to scope is computed by [fragment_applies](app/report_service.py#L277-L282) via [affected_environments](app/report_service.py#L209-L235). [sync_evidence_image_slots](app/report_service.py#L284-L310) guarantees one slot per affected environment, appending missing ones to `proof_of_concept` **only**.

**Client-only rule.** [app/web/static/app.js](app/web/static/app.js#L94) restricts the editor's add-fragment menu per section — the PoC sections allow only `numbered_list, image, bulleted_list, instance_title, note, code_block` (no `paragraph`, no `table`). **The server enforces none of this.**

### 5. The DOCX generator, read in reverse

Each finding renders from one of two component documents ([app/docx_report.py](app/docx_report.py#L598-L646)):

```python
template_name = "new_finding.docx" if finding.status == "open_new" else "retest_finding.docx"
```

The section headings live **in those DOCX files, not in Python**. `retest_finding.docx`:

```
{{finding_title}}
Description:                            {{description-fragments-here}}
Recommended Remediation:                {{recommended-remediation-fragments-here}}
Previous Proof of Concept:
The following demonstrates the vulnerability:
                                        {{prev-poc-fragments-here}}
Proof of Concept:
The following demonstrates the vulnerability:
                                        {{poc-fragments-here}}
In Conclusion:                          {{conclusion-fragments-here}}
Severity Review Ticket (if applicable): {{severity-review-tickets}}
```

`new_finding.docx` is the same minus *Previous Proof of Concept*, *In Conclusion* and *Severity Review Ticket*. The two retest-only anchors are populated **only when `status != "open_new"`**. `severity-review-tickets` is always the literal `"N/A"`.

**Ordering:** grouped by `SEVERITY_ORDER`, each group introduced by a severity-title component, within a group sorted by `title.casefold()`. Every finding after the first gets a page break.

| Fragment | Rendered as |
|---|---|
| `paragraph` | one `paragraph_fragment.docx` paragraph |
| `note` | `note_fragment.docx`, body is the literal **`Note: {{note-fragment}}`** |
| `numbered_list` / `bulleted_list` | **one cloned component per item**, sharing a `numbering_ids` map so numbering is continuous |
| `code_block` | caption paragraph *first* (if any), then `code_fragment.docx` with `text` as a **single run** |
| `instance_title` | `title_fragment.docx`, bare text, no marker |
| `table` | caption paragraph *first*, then two prototype rows; header row only if `header` non-empty |
| `image` | black-bordered raster at `min(width_mm or 155, 155)` mm, then a caption paragraph using `_display_value(caption)` — empty caption becomes literal `"N/A"` |

**An empty section renders as a single paragraph containing `"N/A"`.**

**Environment labels for PoC images.** For the two PoC anchors only, a run of images with a new `environment` is preceded by an `instance_title` component containing `PROD:` or `<non_production_label>:` ([app/docx_report.py](app/docx_report.py#L653-L673)).

**Captions become Word fields.** [add_native_image_captions](app/docx_captions.py#L98-L140) rewrites each image caption into `Figure ` + `SEQ Figure` field + `<n>` + `" " + caption_text`.

#### Lossy / ambiguous structures — flagged

1. **`instance_title` vs. the PoC environment label** — both are `title_fragment.docx`. Nothing distinguishes them structurally.
2. **`note` vs. `paragraph`** — the `Note: ` prefix is template text, so a paragraph beginning `"Note: "` is indistinguishable.
3. **Caption ownership** — captions precede tables and code blocks but *follow* images, and are emitted even when absent (`"N/A"`).
4. **`"N/A"` is quadruply overloaded** — empty section, empty image caption, empty engagement value, no affected locations. A tester-typed `"N/A"` is unrecoverable from a synthesised one.
5. **Two adjacent list fragments of the same type render as one continuous run.**
6. **`code_block.text` is a single run**; multi-paragraph code does not round-trip.
7. **Images are re-rasterised with a black border** and possibly upscaled to 192 DPI. The embedded PNG is **not** the uploaded bytes, so `sha256`/`width_px`/`height_px` must be recomputed, and the border is baked in.
8. **`width_mm` is clamped to ≤155.**
9. **Long values are broken with `w:br`** inside a single run for scope cells and affected-location bullets; `_wrap_long_value` inserts no marker and is not reversible.
10. **Table column metadata does not round-trip.**

### 6. The finding detail table

Per-finding table rows are `Severity | ID | Status | Location (Production Environment) | Location (Lower Region Environment)`. **Likelihood and impact are not in this table** — only in the summary table. Affected locations are real bullet paragraphs, or literal `"N/A"`.

Summary table columns, sorted by `(severity rank, title.casefold())`: title, likelihood, impact, severity, `display_id`, status.

**The exact status strings** ([app/docx_report.py](app/docx_report.py#L46-L50)):

| `status` | Document text |
|---|---|
| `open_new` | `Open (New)` |
| `open_previously_discovered` | `Open (Previously Discovered)` |
| `resolved` | `Resolved` |

Severity/likelihood/impact are `.title()`-cased. An unset `display_id` writes the **empty string**.

### 7. Scope and engagement round-tripping

`_metadata` ([app/docx_report.py](app/docx_report.py#L213-L246)) is the complete set reaching the document: `segment`, `app-name`, `report-name`, `test-type` (= `report_type`), `app-owner`, `report-date`, `tester-name`, prod/non-prod window start/end/time, `prod-web`, `non-prod-web`, `prod-api`, `non-prod-api`, `limitation-set`, `role1/2`, `username1/2`. Scope tables cover **web and API only**.

**The converter's docstring is correct** — `ci_number` and `bsn_number` appear nowhere.

**Engagement fields unrecoverable from a generated DOCX:**

| Field | Why |
|---|---|
| `ci_number`, `bsn_number` | never rendered |
| `test_type` (`web`/`api`/`mobile`/`web_api`) | the `test-type` token is `report_type`, not this field |
| `tested_environments` | only inferable; an untested environment prints `N/A` dates, indistinguishable from a tested one with no dates |
| `start_date`, `end_date` | top-level dates never rendered; only `test_windows` |
| `classification`, `template_set`, `app_version` | never rendered |
| `non_production_label` | only leaks via a non-production PoC image label |
| `test_accounts` beyond the first two | `_metadata` emits `role1/2` only; recovery must read the User Roles table |

**Scope fields unrecoverable:** `ScopeTarget.target_id` and `.order`, and **every `channel == "mobile"` target**. Per-finding, `Scope.mode` is unrecoverable.

### 8. Existing drafts on disk

Top-level keys in dump order: `schema_version`, `report_id`, `app_id`, `app_version`, `saved_at`, `_folder_name_hint`, `engagement`, `scope_targets`, `vulnerabilities`, `evidence`.

- `schema_version` must be exactly `"1.4"` — a `Literal`, so any other value is a hard failure, not a migration.
- The alias is `_folder_name_hint`.
- `saved_at` must parse as a datetime; real drafts carry an offset. `save_if_current` compares for **equality**, so a naive datetime will not match.
- `engagement.test_type` missing → [load_path](app/workspace.py#L246-L263) rewrites the file, migrating from legacy `tested_channels`.
- Any list fragment with zero items → `load_path` silently injects `{"runs": []}` **and rewrites the file**.

### 9. Dual-implementation rules

| Rule | Python | JavaScript |
|---|---|---|
| status → section list | [provision](app/report_service.py#L156-L158) | [provision](app/web/static/app.js#L846-L849) **and a third inline copy** at [app.js](app/web/static/app.js#L1592) |
| required seed fragments | `required_fragments` ([report_service.py](app/report_service.py#L163-L169)) | `required` ([app.js](app/web/static/app.js#L850)) — **already divergent**: Python seeds `["numbered_list"]`, JS seeds `["numbered_list", "image"]` |
| resolved-remediation sentence | [report_service.py](app/report_service.py#L183-L185) | [app.js](app/web/static/app.js#L856) |
| conclusion sentence + `generated` marker | `provision` / `_is_default_status_conclusion` | `syncConclusion` / `isDefaultStatusConclusion` |
| status display strings | `STATUS_LABELS` | `statuses` ([app.js](app/web/static/app.js#L92)) — byte-identical today |
| image slots per environment | `sync_evidence_image_slots` | `syncEvidenceImageSlots` |
| affected environments / channels | `affected_environments`, `affected_channels` | `affectedEnvironments`, `affectedChannels` |
| scope resolves to a location | `scope_has_location`, `_scope_reaches_a_location` | `scopeHasLocation` |
| placeholder-text regex | `PLACEHOLDER_TEXT` | `placeholderPattern` |
| generation readiness | `generation_issues` | `updateReadinessPanel` / `fragmentIssues` |

`tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` is the drift contract test.

**Server-only:** `Report.validate_references`, `parse_import`, `import_report`, all upload limits.
**Client-only:** the `allowed` fragment-type-per-section map.

### 10. Invariants an imported draft could violate

From [Report.validate_references](app/models.py#L209-L233), in evaluation order:

1. Duplicate `target_id` → `"duplicate scope target id"`
2. Duplicate `uid` → `"duplicate vulnerability id"`
3. Duplicate `display_id` → `"two findings cannot share the same finding number"`. Must match `^[0-9]{1,5}$`; `""` is not legal, `null` is.
4. Duplicate content `type` within one finding → reachable if a reader sees two `Proof of Concept:` headings.
5. Custom scope referencing a missing target — **checked only when `mode == "custom"`**.
6. Duplicate `frag_id` anywhere → has a repair path, [repair_duplicate_fragment_ids](app/workspace.py#L196-L217).
7. Orphaned image evidence.
8. Evidence filename/key mismatch.

Beyond the model, a valid draft can still be **unopenable**: `/edit` bounces unless every finding passes [finding_is_complete](app/report_service.py#L474-L476); `/findings` bounces unless [setup_issues](app/report_service.py#L435-L455) is empty — requiring segment, report type, tester, and per tested environment both window dates **and at least one scope target**.

### Traps a planner should expect

1. **`provision` is not on the import path.** A `previous_proof_of_concept` on an `open_new` finding persists, renders nothing, and is destroyed by the first browser save. Status must be set by the importer.
2. **The `required_fragments` / `required` mismatch is live** — Python seeds one `numbered_list`, JS seeds `["numbered_list", "image"]`.
3. **The DOCX carries no CI, BSN, `test_type`, `tested_environments`, top-level dates, or mobile scope.** A DOCX-only import cannot pass `setup_issues` without inventing or prompting. `app_id_for` falls back to `app_name` when CI and BSN are blank, so folder identity silently changes shape.
4. **Evidence bytes in the DOCX are not the uploaded bytes** — re-rasterised with a baked-in black border, possibly upscaled.
5. **`instance_title` and the generated `PROD:` / `UAT:` label are the same component.**
6. **`"N/A"` means four different things** and the tester can also type it.
7. **Two adjacent same-type list fragments are indistinguishable from one.**
8. **Captions precede tables/code but follow images**, and are `SEQ Figure` fields by the time they are written.
9. **The import route branches on `zipfile.is_zipfile`, and a `.docx` *is* a ZIP** — it would fall into the bundle branch and fail on `"Report bundle is missing draft.json"`, a confusing error rather than a clean rejection. The file picker also only accepts `.zip,.json`.
10. **Long values were broken with `w:br`** on the way out, with no marker; not reversible without rejoining.
11. **`display_id` collisions are report-scoped and fatal.** A blank ID cell must import as `null`, not `""` and not a synthesised sequence.
12. **Pre-import and post-import validation are separate calls**; only the first is inside the 422-wrapping `try`.

**Map drift corrected.** [docs/DATA_MAP.md](docs/DATA_MAP.md) section 6 listed only five of the eight `validate_references` checks and stated the `scope.target_ids` rule without its `mode == "custom"` qualifier. Replaced with all eight in source order, plus a note that the schema constrains neither fragment-type-per-section nor status-required sections, and that `provision` runs on `PUT` and library insert only.

## Round 1 - Planner: proposal and open questions

### Understanding

Add a third branch to the existing import so a DOCX this app generated can be dropped on the same Import button and become a **new retest draft**. Findings whose summary status is `Open (New)` or `Open (Previously Discovered)` are retained; `Resolved` is dropped. For each retained finding, `Description`, `Recommended Remediation` and the section headed `Proof of Concept:` are recovered with all seven fragment types intact; the source `Previous Proof of Concept:` is discarded unread. The recovered PoC is written into the new draft's `previous_proof_of_concept`, and — because `previous_proof_of_concept` cannot survive on an `open_new` finding — **every retained finding is written as `open_previously_discovered`, regardless of its source status.** The new `proof_of_concept` is left for `provision` to seed empty.

### Blast radius

| File | Change | Why |
|---|---|---|
| `app/docx_import.py` | **New**, ~400 lines: block iteration, section ranges, engagement/scope/summary/detail parsing, style-driven fragment recovery, evidence extraction, finding promotion | The inverse of `docx_report.py`, and must share its constants |
| [app/main.py](app/main.py) | DOCX sniff **before** the bundle branch; `except` gains `OpcError`; response gains `source` + `summary` | `zipfile.is_zipfile` swallows DOCX today; `PackageNotFoundError` is not `ValueError`/`OSError` and would 500 |
| [app/docx_report.py](app/docx_report.py) | Read-only import of `STATUS_LABELS`, component map, severity constants | One definition of the status strings, not two |
| [app/web/templates/home.html](app/web/templates/home.html) | `accept` gains `.docx` | Hint only; the server sniff is the gate |
| [app/web/static/manager.js](app/web/static/manager.js) | Show import summary before navigating | A DOCX import silently mutates statuses and drops findings |
| `tests/test_docx_import.py` | **New**, round-trip suite | |
| [tests/test_app.py](tests/test_app.py) | DOCX accepted; corrupt DOCX → 422 not 500; real bundle still takes the bundle branch | The branch collision is the sharpest regression risk |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | Record that import now runs `provision` + `sync_evidence_image_slots` | Required by the data-layer contract |

Not touched: `models.py`, `workspace.py`, `storage.py`, `report_service.py`. **No schema change, no migration.**

### Data risks

| # | Concern | Verdict | Reasoning |
|---|---|---|---|
| 1 | `.docx`-is-a-ZIP branch collision | **RISK** | Lands in the bundle branch, dies on `"missing draft.json"`. Fixed by ordering a `word/document.xml` sniff first |
| 2 | Status → section provisioning | **RISK** | `provision` not on import path; `open_new` + previous PoC renders nothing and is destroyed on first save. Must force `open_previously_discovered` |
| 3 | `previous_proof_of_concept` survival | **RISK** | Same root; correct status is the whole mitigation |
| 4 | Derived-state fight on first save | **RISK** | Hand-built sections get rewritten by `provision_report` on first PUT. Neutralised by calling `provision` at import and asserting idempotence |
| 5 | Rule drift (Python vs JS) | **clear** | Only because we call the existing `provision`. Hand-rolling would add a **fourth** copy of the status→section rule |
| 6 | Fragment-ID uniqueness | **clear** | Minted `f_<12 hex>` in one pass; `validate_references` enforces twice before disk |
| 7 | Evidence re-import and hashing | **RISK** | Embedded PNG is re-rasterised/bordered/upscaled. `sha256`, `width_px`, `height_px` must be recomputed |
| 8 | Border stacking on regeneration | **RISK** | Extracted image already has a border; regenerating adds a second. Accepted and documented |
| 9 | `display_id` handling | **RISK** | Generator writes `""`; pattern rejects `""` and duplicates are fatal. Map non-matching to `None`, never `""`, never synthesised |
| 10 | Scope/target reconstruction | **RISK** | `_wrap_long_value` inserted `w:br` with no marker; a long URL returns broken and silently demotes a real target to a bogus custom location. Must rejoin |
| 11 | Findings with Location `N/A` | **RISK** | Rebuilds as empty `custom`, so `/edit` bounces. Recoverable on Findings; must be surfaced in the summary |
| 12 | `setup_issues` completeness | **RISK** | Clear except mobile engagements, where no scope target is recoverable |
| 13 | `finding_is_complete` | **RISK** | Metadata reliable from the summary table; the scope leg is risk 11 |
| 14 | Schema validation | **clear** | `model_validate` runs twice before `atomic_write_json` |
| 15 | Route exception coverage | **RISK** | `PackageNotFoundError` outside the `except` tuple → **500** instead of 422 |
| 16 | Unbounded parse cost | **RISK** | Per-image/pixel/total caps live *inside* the bundle branch; the DOCX branch needs its own |
| 17 | Duplicate content type in one finding | **RISK** | A second `Proof of Concept:` heading silently overwrites the earlier range in a dict. Must detect and reject |
| 18 | `ListFragment.items` `min_length=1` | **RISK** | Empty list → `ValidationError`; if it slipped through, `load_path` rewrites the file. Emit no fragment rather than an empty one |
| 19 | `code_block` line breaks | **RISK** | Newlines became `w:br`, which `paragraph.text` drops — silently flattens multi-line code. Must read `w:br` |
| 20 | `"N/A"` overloading | **RISK** | Converts "absent" into "tester typed N/A". Map a lone `"N/A"` caption to `""` and a single-`"N/A"` section to empty |
| 21 | `instance_title` vs `PROD:` label | **RISK** | Same component. A tester title reading exactly `PROD:` is consumed. No fix; accepted, low likelihood |
| 22 | `note` vs `paragraph` | **RISK** | Eliminated if `note_fragment.docx` carries a distinct style — step 1 verifies |
| 23 | Adjacent same-type lists merging | **RISK** | Structural only; no text or formatting lost. Accepted |
| 24 | Fragment type per section | **clear** | Source PoC came through the same editor, so promoted fragments are already compatible |
| 25 | Orphan evidence reference | **clear** | Minted next to its fragment; enforced by `validate_references` and set equality |
| 26 | Stale write / `saved_at` | **clear** | Import is a create; no `saved_at` round-trips |
| 27 | Lost update / locking | **clear** | Fresh `report_id` no other actor holds |
| 28 | Backup exhaustion | **clear** | Target `draft.json` does not exist |
| 29 | Folder identity | **clear** | Blank CI/BSN → `app_id_for` falls back to `app_name`, grouping the retest under the same app folder |
| 30 | Two imports of the same DOCX | **clear** | `display_id` uniqueness is report-scoped |

### Where the parsing code lives

**A new `app/docx_import.py`.** `scripts/html_to_fragments.py` was deleted because it had **no caller**; this module has one on a request path. It cannot live in `main.py` because it must import constants from `docx_report.py`, and `main.py` importing a parser that imports the generator inverts the layering. As a sibling of `docx_report.py` / `docx_captions.py` / `docx_components.py` it sits in the existing DOCX cluster.

### How the user chooses this import

**Same button, same endpoint, sniff ordered before the bundle branch.**

```
zipfile.is_zipfile?
  no  → bare draft.json               (unchanged)
  yes → contains "word/document.xml"? → DOCX retest import   (new, checked first)
        otherwise                     → VulnReport bundle     (unchanged)
```

Deterministic, not heuristic: a bundle contains exactly `draft.json` plus `evidence/*.png` (enforced by set equality today), so no bundle can contain `word/document.xml`. The route returns `{"report_id", "source", "summary"}` — additive — and the manager shows what was retained, dropped, promoted and left blank before navigating.

### What the DOCX cannot carry

Rule: **never invent a value a navigation gate or the generator would treat as authoritative.**

| Field | Decision |
|---|---|
| `ci_number`, `bsn_number` | Leave `""`, name in summary. Not gated; both are on the Setup landing page. No prompt |
| `test_type` | **Infer** from which scope tables have rows — those tables are rendered from `scope_targets`, so this is not a guess |
| `tested_environments` | **Infer** from `N/A` dates. The ambiguity is harmless: "tested with no dates" already fails `setup_issues` |
| `start_date`, `end_date` | `None`. Never rendered, never gated |
| `non_production_label` | Recovered from label paragraphs and table row labels; default `UAT` |
| Mobile scope | **Unrecoverable** — open question 1 |
| `Scope.mode` | Always `custom`, rebuilt from Location bullets. Reconstructing `all` would invent breadth |
| `target_id` / `order` | Minted fresh; `order` = row order |
| `test_accounts` | From the full User Roles table, not the two tokens |
| `app_owner` | `""`. Exists only inside boilerplate prose; ungated |
| `display_id` | Verbatim when it matches `^[0-9]{1,5}$`, else `None` |
| `library_ref`, `poc_variant` | `None`. Nothing identifies the entry; the new empty PoC should let the library offer fire fresh |

### Techniques taken from the reference converter

**Adopted:** block iteration over `body.iterchildren()`; section ranges sliced between heading paragraphs; finding boundaries via `Report Heading 2` within severity `Report Heading 1`; summary- and detail-table parsing (likelihood and impact exist *only* in the summary); run-level formatting capture; image resolution via `a:blip/@r:embed` → `related_parts[...].blob`; `wp:extent` → `width_mm` clamped to 155; `Figure N ` prefix stripping; environment-label paragraphs setting the current environment; skipping `The following demonstrates the vulnerability:`; `"".join(value.splitlines())` on scope cells (the fix for risk 10).

**Rejected:** the entire ZIP-emission half (~250 lines re-implementing `validate_references` and `import_report` as a parallel rulebook); `is_code_paragraph` font sniffing (false-positives on mono runs — use the component style); `list_kind`'s numbering-XML walk (~45 lines; the two list components have distinct styles); `fallback_list_kind` per section (guessing silently changes a tester's list type); `parse_revision`'s mega-regex (unanchored, breaks on the first template edit); `parse_application_owner`'s prose regex; `ConversionError` on one unlabelled image (aborting the whole import over one finding is too blunt); **`open_conclusion`** — it writes `generated: None`, making a synthesised sentence look tester-authored and permanently blocking refresh, a real bug; and vendoring wholesale (~55% is CLI, bundle writing, duplicate validation and heuristics).

**Added:** fragment types identified by the `w:pStyle` values of `resources/fragments/*.docx` themselves — the generator clones component bodies wholesale and `_validate_component` proves the styles survive, so the components are an exact fingerprint.

### Plan

**Step 1 — Prove the style fingerprints.** Reads `resources/fragments`, `resources/finding_types`. Test: `test_component_styles_are_distinct` and `test_section_headings_match_components`. Invariant: fragment recovery is driven by the generator's own components; a template edit fails the test instead of silently mislabelling every fragment. **If it fails, the `note` prefix heuristic and numbering walk come back as scoped fallbacks — decide here.**

**Step 2 — Engagement, scope, summary.** `app/docx_import.py`. Test: `test_engagement_round_trip` — generate a DOCX from a synthetic `Report`, re-import, assert fields match and `setup_issues` returns **only** what the DOCX genuinely cannot carry. **No committed fixture**; the test generates its own DOCX, so no customer report enters the repo.

**Step 3 — Fragment recovery.** Test: `test_all_fragment_types_round_trip` — all seven types plus formatting, nested table cells, multi-line `code_block`, captioned table and image; assert `w:br` newlines survive (19), a lone `"N/A"` caption returns `""` (20), no zero-item list is emitted (18). Invariant: no fragment type is silently downgraded to `paragraph`.

**Step 4 — Filter, promote, provision.** Test: `test_open_findings_promoted_to_previous_poc` — one of each status; assert Resolved is gone, **both** survivors are `open_previously_discovered`, source PoC is in `previous_proof_of_concept`, source Previous PoC appears nowhere, and `proof_of_concept` holds only the seed. Plus `test_provision_is_idempotent_after_import`. Invariant: **no carried PoC can be destroyed by the first browser save.** Protects risks 2, 3, 4 together.

**Step 5 — Evidence.** Test: `test_evidence_is_rehashed_and_rebound` — `sha256`/dimensions computed from emitted bytes; every `evidence_id` referenced exactly once; result would pass the bundle branch's own checks if re-exported.

**Step 6 — Wire the route.** *Nothing before this is reachable; the app cannot regress until here.* DOCX sniff ahead of the bundle branch; DOCX-branch caps mirroring the bundle branch; `OpcError` in the `except` tuple; `source` + `summary` in the response. Test: DOCX imports; corrupt DOCX → **422 not 500**; **existing bundle still takes the bundle branch**; oversized DOCX → 413.

**Step 7 — UI.** `accept` gains `.docx`; summary rendered before navigation. Invariant: the user is never told "imported" without being told what was dropped or changed.

**Step 8 — Docs.** DATA_MAP's claim that `provision` runs only on `PUT` and library insert becomes false in step 4 and must be corrected in the same change.

### What the planner would not do

Write `status = "open_new"` for a source `Open (New)` finding (faithful-looking, destroys the PoC) · hand-build the five sections (a fourth copy of a rule whose third copy already drifted) · vendor the reference converter · add a second endpoint or button · synthesise `display_id`s · prompt for CI/BSN before importing · widen a Location-`N/A` finding to `mode="all"` · trust `wp:extent` for pixel dimensions · detect and crop the baked-in border.

### Open questions raised

1. **Mobile-scope reports** — reject with a clear message, or import with empty scope and let `setup_issues` block? *Default: import and name it in the summary.*
2. **Resolved findings** — drop entirely, or import as `resolved` for the user to delete? *Default: drop, report the count.*
3. **`report_type` of the resulting draft** — carry verbatim from the title, or force `retest`? *Default: carry verbatim.*

## Round 2 - Oracle: verdict on the proposal

Six `clear` verdicts are wrong, and one `RISK` mitigation backfires into a concrete user-visible defect.

### Risk rows that are wrong

**Row 5 — "rule drift: clear, because we call the existing `provision`" → WRONG about layering.**
`provision(vulnerability)` takes a `Vulnerability` alone ([app/report_service.py](app/report_service.py#L154)); `sync_evidence_image_slots(vulnerability, report)` needs both ([app/report_service.py](app/report_service.py#L284)). The function that pairs them is **not in `report_service.py`** — `provision_report` lives in the route layer ([app/main.py](app/main.py#L245-L249)). `main.provision` is a plain re-export of `report_service.provision`, not a wrapper. Since `main.py` will import `docx_import`, **`docx_import` cannot import `main.provision_report` — circular import.** It must duplicate that loop, or `provision_report` must move into `report_service.py`. Either way **"Not touched: `report_service.py`" is unsustainable.** Direction is safe (`docx_report` already imports `report_service`, and nothing in `report_service` imports `main`), the plan just does not acknowledge the cost.

**Row 6 — `clear` STANDS.** Nothing constrains `frag_id` length; `repair_duplicate_fragment_ids` tests membership only ([app/workspace.py](app/workspace.py#L205-L210)); tests use free-form IDs. `f_<12 hex>` is cosmetically inconsistent with the eight `f_<8 hex>` sites, not a data risk.

**Row 24 — "came through the same editor" → WRONG reasoning, `clear` → RISK (low).**
The `allowed` map gates **only the add menu** ([app/web/static/app.js](app/web/static/app.js#L2333) is its sole consumer); rendering and deletion are section-agnostic. And the premise is false: a `paragraph` or `table` in a PoC is reachable today via `insert_library`'s wholesale `deepcopy` ([app/main.py](app/main.py#L672)), via JSON import, and in any draft older than the map. Promoting a source PoC `table` into `previous_proof_of_concept` yields a one-way trapdoor — visible and deletable, but not recreatable.

**Row 29 — "folder identity: clear" → WRONG, and the most consequential error.**
`app_id_for` does fall back to `app_name` ([app/workspace.py](app/workspace.py#L34-L36)), but **it is never reached from the import path.** `import_report` touches only `report_id`, `saved_at`, `folder_name_hint` ([app/workspace.py](app/workspace.py#L146-L149)). `app_id_for` has exactly two call sites, both guarded by `if report.app_id == "unnamed"` ([app/main.py](app/main.py#L566), [app/main.py](app/main.py#L642)). And `app_id: str` is **required with no default** ([app/models.py](app/models.py#L199)).

| Importer does | Result |
|---|---|
| omits `app_id` | `model_validate` **fails** → 422 |
| sets `"unnamed"` | lands in `X_unnamed/`, moved on first PUT |
| calls `app_id_for` with blank CI/BSN | `safe_name(app_name)` |

**None matches the original.** Verified on disk: `P_CI-7` has `app_id: "CI-7"` → re-import gives `PoC_Variant_Demo` → folder `P_PoC_Variant_Demo`. `T_fda434` has `app_id: "fda434"` from BSN → re-import gives `testapp`. And it is **permanent**: `save_report` overwrites the submitted value with `payload["app_id"] = prior.app_id` ([app/main.py](app/main.py#L629)), so typing the CI back in never re-derives it. The retest is orphaned from its predecessor forever.

**Row 26 — `clear` STANDS.** Nothing on the import path compares `saved_at`; `import_report` → `save` → `_save_unlocked`, never `save_if_current`. Caveat: `saved_at` and `report_id` are required with no default, so the constructed placeholders must be legal even though both are overwritten after validation.

### The PoC seed divergence — Row 4's mitigation backfires

Python seeds `["numbered_list"]` for both PoC sections ([app/report_service.py](app/report_service.py#L161-L167)); JS seeds `["numbered_list","image"]` ([app/web/static/app.js](app/web/static/app.js#L850)). Both seed only into an **empty** section, so the carried Previous PoC correctly blocks its own seed.

But `sync_evidence_image_slots` scans images across **every** content section, not just the PoC ([app/report_service.py](app/report_service.py#L286-L291)). For a single-environment finding whose carried Previous PoC contains at least one image:

- every carried Previous-PoC image's `environment` is **rewritten** to that single environment;
- `missing` is then empty, so **no image slot is appended to the new `proof_of_concept`**.

The imported draft's new PoC contains **exactly one empty `numbered_list` and nothing else**, where the browser would have produced `numbered_list` + `image`. **Visible immediately and permanently** — `provision` only seeds empty sections, so no later save repairs it. Step 4's assertion "`proof_of_concept` holds only the seed" will pass while describing the wrong outcome, because "the seed" is ambiguous between the two implementations.

### Files the planner missed

- **`app/report_service.py`** — see Row 5.
- **`tests/test_browser.py`** — missing from the blast radius entirely, and it pins the exact failure string: `assertTrue(page.get_by_text("Select a valid VulnReport ZIP or JSON export").is_visible())` ([tests/test_browser.py](tests/test_browser.py#L1209)). Changing the copy breaks the test; leaving it breaks the UX.
- The server string `"Select a valid VulnReport export: {error}"` is **not** asserted anywhere — that half is free.
- Response shape is safe: `manager.js` destructures by key ([app/web/static/manager.js](app/web/static/manager.js#L136)); tests read `["report_id"]`, never compare whole dicts. The `accept` attribute has no test.

### Can the round-trip tests run without Word?

**Yes, but only outside the route.** Word is required in exactly one place ([app/docx_captions.py](app/docx_captions.py#L45-L49)), reached unconditionally from the generate routes via `update_docx_bytes_with_word` ([app/main.py](app/main.py#L479)) — so **`/generate` always returns 422 on this machine**. Existing tests patch around it. But `render_report_docx` is pure `python-docx` including `add_native_image_captions`, and `tests/test_docx.py` already calls it directly.

Two constraints the planner did not state:
1. `render_report_docx` **refuses any report with generation issues** unless `allow_incomplete=True` ([app/docx_report.py](app/docx_report.py#L150-L153)). The fixture must be generation-**clean**, a much higher bar than model-valid.
2. SEQ Figure numbers are written **statically** ([app/docx_captions.py](app/docx_captions.py#L175)), so the test DOCX carries literal `Figure 1 ` prefixes — which is exactly what the importer must strip. Representative, but by accident.

### Not settled

**Component styles as an "exact fingerprint."** `_validate_component` proves styles **resolve** in the main template, not that they are **distinct** between components ([app/docx_components.py](app/docx_components.py#L197-L207)). Worse, `FRAGMENT_COMPONENT_FILES` ([app/docx_report.py](app/docx_report.py#L73-L81)) covers `paragraph`, `numbered_list`, `bulleted_list`, `note`, `code_block`, `instance_title`, `caption` — **`table` and `image` have no component and no style fingerprint.** The strategy covers 5 of 7 types; the other two must be recognised structurally.

### Does the proposed shape break any existing draft?

**No — the planner is right.** Both drafts on disk are `schema_version "1.4"`; no new required field, no `ContentType` addition, no union member. **Calling `provision` at import cannot alter how an existing draft loads** — `load_path` performs only the `tested_channels` and empty-`items` repairs and never calls `provision`. The new call operates on an in-memory object before `atomic_write_json`. The only caveat is Row 29: the new draft lands in a new app folder. Nothing on disk is corrupted; the plan simply does not achieve what it claimed.

### Blunt list

**Simply wrong:** (1) Row 29 — no `app_id_for` on the import path, `app_id` required with no default, and frozen after the first save. (2) "Not touched: `report_service.py`". (3) Row 5's reasoning — `provision_report` is what the PUT path runs and it lives in `main.py`. (4) Row 24's reasoning. (5) Row 4's mitigation suppresses the new PoC image slot and silently rewrites carried image environments. (6) The rejection of `open_conclusion` is justified with a false claim — the app's own `provision` writes `generated: None` at [app/report_service.py](app/report_service.py#L198) and refresh still works via `_is_default_status_conclusion`. Reject it for a true reason or not at all. (7) `tests/test_browser.py` missing from the blast radius.

**Treated as settled but not:** (8) component styles as a fingerprint — 5 of 7 types, distinctness unproven. (9) Whether the fixtures can be built at all — `allow_incomplete` is unspecified and a generation-clean synthetic report with seven fragment types, two environments and evidence is materially more work than the steps imply. (10) The `required_fragments` / `required` divergence — routing around it via `provision` converts a latent inconsistency into a first-impression defect. **Decide which side is correct before step 4.**

### Map drift corrected

Two claims in [docs/DATA_MAP.md](docs/DATA_MAP.md) that source contradicts: the folder-migration claim (the move happens **only** while `app_id == "unnamed"`, and `save_report` discards the submitted `app_id`), and the `sync_evidence_image_slots` claim that it guarantees "no slots for unaffected ones" (there is no deletion — stale slots persist and are merely hidden by `fragment_applies`).

## Round 2 - Planner: revised plan

### Corrected blast radius

| File | Change |
|---|---|
| `app/docx_import.py` | **New.** Returns `(payload: dict, evidence_files: dict[str, bytes])` — the same shape as `parse_import`, so `Workspace.import_report` is reused unchanged |
| [app/report_service.py](app/report_service.py) | **Gains `provision_report`**, moved verbatim from `main.py` |
| [app/main.py](app/main.py) | Delete the local `provision_report`; re-import it from `report_service` (keeps `main.provision_report` resolvable for [tests/test_browser.py](tests/test_browser.py#L955)). DOCX sniff before the bundle branch; `OpcError`/`PackageNotFoundError` added to the `except` tuple; response gains `source` and `summary` |
| [app/workspace.py](app/workspace.py) | Widen the migration gate in `_save_unlocked` from `== "X_unnamed"` to `.endswith("_unnamed")` |
| [app/docx_report.py](app/docx_report.py) | Read-only import of `STATUS_LABELS`, `FRAGMENT_COMPONENT_FILES`, `SEVERITY_ORDER`, the wrap-character sets |
| [app/web/static/manager.js](app/web/static/manager.js#L140) | Failure copy → `"Select a valid VulnReport ZIP, JSON, or report DOCX"`; render the summary before navigating |
| [app/web/templates/home.html](app/web/templates/home.html#L4) | `accept` gains `.docx` + the Word MIME type |
| [tests/test_browser.py](tests/test_browser.py#L1209) | Update the pinned copy string |
| [tests/test_app.py](tests/test_app.py) | DOCX accepted; corrupt DOCX → 422 not 500; **bundle still takes the bundle branch**; oversized → 413 |
| `tests/test_docx_import.py` | **New.** Round-trip suite, all calling `render_report_docx` directly |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §2, §6/§7, §12 |

Untouched: `models.py`, `storage.py`, `library.py`. **No schema change, no migration, no new required field.**

### Decision A — `app_id` is `"unnamed"`, and the migration gate widens

| Option | Outcome | Verdict |
|---|---|---|
| Omit `app_id` | `model_validate` fails → 422 | Ruled out: required, no default |
| Derive via `app_id_for` | `N_Northstar_Customer_Portal`, then **frozen** by `payload["app_id"] = prior.app_id`; retest orphaned from its predecessor permanently, repairable only by hand-editing `draft.json` | Ruled out: writes a wrong value no UI can correct |
| Prompt for the CI at import | Correct folder, but adds a field to a one-click flow | Ruled out: the CI is already a Setup field, and option 4 reaches the same folder through it |
| `"unnamed"` + widened gate | Lands in `<Letter>_unnamed/`; the first save after the tester types the CI derives the real `app_id` **and moves the directory** into the predecessor's folder | **Chosen** |

Without the widening this option is the worst of all — `app_id` becomes `CI-7` while the folder stays `N_unnamed` forever, because the gate only recognises `X_unnamed` and the imported draft knows its `app_name`. Per risk 33 the widening cannot move anything already on disk: `<L>_unnamed` with `L != X` is unreachable today.

### Decision B — `provision_report` moves to `report_service.py`

Model-to-model code with no `Request`, no `HTTPException`, no workspace access; `report_service` already owns both halves. Duplicating the loop into `docx_import` is rejected — the status→section rule already exists three times and one copy has drifted.

### Decision C — the importer constructs the new PoC explicitly

**Target content** per kept finding: one empty `numbered_list`, then one empty `ImageFragment` per affected environment, in that order. A finding with no resolvable location gets the `numbered_list` only.

**Order:** (1) promote to `open_previously_discovered` with the carried PoC in `previous_proof_of_concept` and an empty `proof_of_concept`; (2) `provision` — seeds the `numbered_list` and the conclusion sentence, leaves the non-empty Previous PoC alone; (3) the importer appends the per-environment image slots itself; (4) `sync_evidence_image_slots` runs as a **guard, not a producer** — `missing` is already empty, so its only permitted effect is the single-environment label rewrite, which the importer counts.

Step 3 exists because `sync_evidence_image_slots` cannot tell a carried historical image from a needed retest slot — its scan spans every content section, so one carried image suppresses the new slot entirely. Round 1 inverted this. The alternative (provision and sync *before* attaching the Previous PoC) produces the right slots but leaves carried image environments un-normalised, so the **first browser save** would silently rewrite them. Step 4 makes the import result a fixed point instead.

### Decision D — the seed divergence: JS is correct, the fix is not in this change

`required` seeding `["numbered_list","image"]` is what every tester has seen and what every draft on disk was built with; Python's `required_fragments` should become the same. **But Decision C removes the dependency** — the importer states the PoC contents rather than inheriting a seed, so the round-trip tests pass identically before and after. Bundling the fix would make a round-trip regression and a provisioning regression indistinguishable.

The test that would catch the drift **does not exist**: `test_browser_readiness_verdict_matches_server_generation_issues` cannot see it, because both sides flag an env-less image slot identically — the verdicts agree while the documents differ. The test to add *with the fix* is `test_browser_provisioned_sections_match_server_provisioning`: create an `open_previously_discovered` finding with zero scope targets, save, assert the server's canonical `contents` deep-equals the browser's copy.

### Corrected risk rows

| # | Concern | Verdict | Reasoning |
|---|---|---|---|
| 4 **†** | Derived-state fight on first save | **RISK** | Round 1's mitigation backfired — a carried Previous-PoC image empties `missing`, so the new PoC gets **no** image slot. Mitigation is now Decision C plus a fixed-point assertion |
| 5 **†** | Rule drift | **RISK** | `provision_report` sits in the route layer, and `main.py` importing `docx_import` makes it unimportable. Mitigated by Decision B |
| 6 | Fragment-ID uniqueness | **clear** | Use `f_<8 hex>` for consistency with the eight existing sites |
| 24 **†** | Fragment type per section | **RISK (low)** | Round 1's reasoning was false. `allowed` gates only the add menu; a PoC `paragraph`/`table` is already reachable via `insert_library`'s deepcopy, JSON import, and pre-`allowed` drafts. Promoting a source `table` is a one-way trapdoor — visible, editable, deletable, not re-addable. Accept and name it in the summary; do **not** downgrade it to a paragraph |
| 26 | Stale write | **clear** | Caveat: `report_id`/`saved_at` are required with no default, so the placeholders must be legal even though both are overwritten |
| 29 **†** | `app_id` and folder identity | **RISK (high)** | Round 1 was wrong on every leg. See Decision A |
| 31 **new** | Seed divergence | **clear by construction** | Neither seed fires: the Previous PoC arrives non-empty and the new PoC is constructed explicitly. JS `provision` does not run on page load, only on creation and status change |
| 32 **new** | Source `In Conclusion` discarded | **RISK (low)** | Dropped; `provision` writes the fresh default. Tester-edited conclusion prose is lost — question 5 |
| 33 **new** | Widening the migration gate | **clear** | `<L>_unnamed` with `L != X` is unreachable today, so nothing on disk moves |
| 34 **new** | Failure copy pinned by a test | **RISK** | [tests/test_browser.py](tests/test_browser.py#L1209) asserts the string verbatim. Change both in one commit. The server-side `"Select a valid VulnReport export: {error}"` is asserted nowhere and stays |

Rows 1-3, 7-23, 25, 27-28, 30 stand as written in Round 1.

### What the DOCX cannot carry

Rule: **never invent a value a navigation gate or the generator would treat as authoritative.**

| Field | Decision |
|---|---|
| `app_id` | `"unnamed"` — Decision A |
| `ci_number`, `bsn_number` | `""`, named in the summary. Both live on the Setup landing page |
| `test_type` | **Infer** from which scope tables have rows — those render from `scope_targets`, so this is derivation, not a guess |
| `tested_environments` | **Infer** from which windows carry real dates. The ambiguity is harmless: "tested with no dates" already fails `setup_issues` |
| `start_date`, `end_date` | `None`. Never rendered, never gated |
| `non_production_label` | Recovered from PoC labels and scope-row labels; default `UAT` |
| `Scope.mode` | Always `custom`. Reconstructing `all` would invent breadth the document does not assert |
| `display_id` | Verbatim when it matches `^[0-9]{1,5}$`, else `None` — never `""`, never synthesised |
| `library_ref`, `poc_variant` | Unset, so the library offer fires fresh on the empty new PoC |
| Source `In Conclusion` | **Discarded unread.** Adopting the converter's `open_conclusion` is rejected because it would be a **third Python spelling** of a sentence that must stay in step with `_is_default_status_conclusion`'s regex — **not**, as Round 1 claimed, because `generated: None` blocks refresh. The app's own `provision` writes `generated = None` and refresh works fine |
| Source `Previous Proof of Concept` | Discarded unread, per the request |

### Ordered steps

**1. Prove what the components actually fingerprint** — `tests/test_docx_import.py`. `FRAGMENT_COMPONENT_FILES` has **no entry for `table` or `image`**, and an `image` is a `paragraph_fragment.docx` paragraph containing an inline drawing, so it is *style-identical* to a `paragraph`. Recognition is therefore: `table` = `w:tbl` body child; `image` = `w:p` with a descendant `a:blip`; `paragraph` = the paragraph style with **no** `a:blip`; the other five by `w:pStyle`; caption owner = the preceding image paragraph if present, else the following `w:tbl` or code paragraph — provable from `add_native_image_captions`, which converts a caption only when its previous sibling is an image. **Tests:** styles pairwise disjoint; caption style disjoint from all six; table and image recognised structurally. **Invariant:** a template edit fails a test instead of silently mislabelling every fragment in every future import. *If the distinctness test fails, the plan stops here* — the `note`-prefix heuristic and the numbering-XML walk return as scoped fallbacks, and that is a decision, not a silent fallback.

**2. Fixture builder** — every test calls `render_report_docx` **directly** with **`allow_incomplete=False`**. No test touches `/reports/{id}/generate`, which always 422s without Word. `allow_incomplete=True` is rejected outright: it substitutes a `[Evidence image not attached: ...]` *paragraph* for an image, so the importer would read a paragraph where the shipping generator emits an image. The fixture must be **generation-clean** (`generation_issues(fixture) == []`), built in code and never committed. **Test:** `test_fixture_is_generation_clean`. **Invariant:** the suite tests the document the generator actually ships. *Note:* SEQ numbers are static, so the fixture carries literal `Figure 1 ` prefixes — exactly what the importer must strip.

**3. Engagement, scope, summary and detail tables** — `test_engagement_round_trip` asserts `setup_issues` returns **only** what the DOCX genuinely cannot carry; plus `test_long_scope_target_is_rejoined` (risk 10) and `test_blank_finding_number_imports_as_null` (risk 9). **Invariant:** no scope target invented, demoted or split.

**4. Fragment recovery** — all eight types, run-level formatting, captioned table and image, multi-line `code_block`, nested cell. Asserts `w:br` newlines survive, a lone `"N/A"` caption returns `""`, a single-`"N/A"` section returns empty, no zero-item list is emitted, the `Figure N ` prefix is stripped; plus `test_duplicate_poc_heading_is_rejected`. **Invariant:** no type silently downgraded to `paragraph`.

**5. Filter, promote, provision** — `app/docx_import.py` + the `provision_report` move. `test_new_proof_of_concept_has_a_slot_per_environment` asserts the new PoC is exactly `[numbered_list, image(production), image(non_production)]` for a finding whose carried Previous PoC already holds both — *the test Round 1 would have passed while describing the wrong outcome*. `test_provision_report_is_a_fixed_point_after_import` deep-copies, re-provisions, asserts `model_dump` equality. **Invariant:** no carried content and no needed slot can be created or destroyed by the first browser save.

**6. Evidence** — `sha256`, `width_px`, `height_px` recomputed from the emitted bytes, never copied; `set(evidence_files) == {e.file for e in report.evidence.values()}`. **Invariant:** no orphan evidence, no mismatched hash, no `evidence_id` referenced twice.

**7. Widen the folder-migration gate** — [app/workspace.py](app/workspace.py), **before** the route, so no import can land in a folder it cannot leave. Plus `test_existing_x_unnamed_migration_unchanged` to prove the widening is a superset. **Invariant:** a draft that starts without a CI can always reach its real folder, and nothing on disk moves.

**8. Wire the route** — nothing before this is reachable from the browser. Sniff order, DOCX-branch size/pixel caps mirroring the bundle branch, `OpcError` in the `except` tuple. **Tests:** DOCX imports with `source: "docx"`; **an existing bundle still takes the bundle branch**; truncated DOCX → **422 not 500**; oversized → 413; bare `draft.json` unchanged. **Invariant:** the two existing formats behave byte-for-byte as today.

**9. UI and copy** — `accept`, the `manager.js` string and the [tests/test_browser.py](tests/test_browser.py#L1209) assertion in one commit. The summary names: findings retained, dropped as Resolved, statuses rewritten, PoCs promoted, conclusions discarded, findings with no location, fragments now un-re-addable, images whose label was corrected, and the CI/BSN prompt. **Invariant:** the user is never told "imported" without being told what was dropped, rewritten or left blank.

**10. Docs** — [docs/DATA_MAP.md](docs/DATA_MAP.md) §2, §6/§7, §12. **Invariant:** the data-layer contract is satisfied in the same change, not after it.

### What I would not do

Write `status = "open_new"` for a source `Open (New)` finding (faithful-looking; destroys the promoted PoC on the first save) · set `app_id` from `app_name` (frozen, orphaned, no UI repair) · leave `"unnamed"` without widening the gate (worse than either clean option) · duplicate `provision_report`'s loop (a fourth copy of a rule whose third copy already drifted) · rely on `provision` + `sync_evidence_image_slots` to produce the new PoC · fix the seed divergence inside this change · widen the `allowed` map (a product decision, not a consequence of import) · test through `/generate` or render with `allow_incomplete=True` · hand-build the five content sections · vendor the reference converter · add a second endpoint or button · synthesise `display_id`s · widen a Location-`N/A` finding to `mode="all"` · trust `wp:extent` for pixel dimensions · detect and crop the baked-in border.

## Answers

**2. Mobile-scope reports — import with empty scope.** Setup blocks until the tester fills it in. No mobile example or template exists yet, so nothing is designed against a guess.

**3. Resolved findings — drop them.** Count reported in the import summary.

**4. `report_type` — not carried.** Annual pentest, retest, deployment pentest and the rest describe the engagement's purpose, which is the tester's call. Imports as `None`; `setup_issues` blocks until it is chosen. *Supersedes the Round 1 answer, which carried it verbatim.*

**5. Source `In Conclusion` — drop it silently.** No summary line. Supersedes Round 2 open question 5; risk 32 becomes *accepted, unreported*.

**6. Images are carried over** into `previous_proof_of_concept`, evidence bytes and all.

- **`previous_proof_of_concept` requires written steps and an image.** Applies to every previously-discovered finding, imported or hand-made.
- **Every image carries an environment**, in every section. The per-fragment requirement at [app/docx_report.py](app/docx_report.py#L119-L127) is unchanged.
- **Previous-PoC images do not satisfy environment coverage.** Only `proof_of_concept` images prove the retest.

So two edits, not the relaxation Round 2 sketched:

1. `provision`'s `required_fragments` table asks for `["numbered_list"]` ([app/report_service.py](app/report_service.py#L161-L167)) while the `else` branch that builds an `ImageFragment` ([app/report_service.py](app/report_service.py#L180)) is **unreachable dead code** — no table entry ever names `"image"`. Adding it to `previous_proof_of_concept` activates code that already exists, and settles the Round 2 seed divergence in favour of JS.
2. The coverage check scopes to `proof_of_concept` — the discovered bug below.

**7. Accept the double border.** A carried image keeps its baked-in border and the generator adds another. **No schema change** — `Evidence` gains no flag. Note that borders **compound per generation**: an import of an import shows three rings.

**1. Folder naming — key the app folder on the app name, and make the report folder readable.**

```
Northstar_Customer_Portal/2026-09_Annual_Pentest_7edb3423a1bc/
Northstar_Customer_Portal/2027-03_Retest_9f2a11c4e007/
```

Safe because `find_path` and `list_reports` both scan `apps_root.glob("*/*/draft.json")` ([app/workspace.py](app/workspace.py#L221), [app/workspace.py](app/workspace.py#L100)) — **no lookup depends on the folder name**. Old and new shapes coexist with no migration.

This **deletes Decision A, the gate widening, and risk 29**: a DOCX carries the app name and the report type, so an import lands in its predecessor's folder on the first save with no `"unnamed"` detour and no dependency on the tester typing a CI. `app_id` stops deciding the folder.

### Discovered bug - evidence check counts the wrong section

`generation_issues` collects images from **every** content section ([app/docx_report.py](app/docx_report.py#L101-L106)) before asking whether each affected environment has evidence ([app/docx_report.py](app/docx_report.py#L107-L110)). A carried Previous-PoC image with a matching environment therefore **satisfies the new PoC's evidence requirement**.

Normally the empty new-PoC slot still fails the per-fragment check, so the report is blocked anyway. But when `sync_evidence_image_slots` appends **no** slot — the exact backfire Round 2 found, and the exact import case — both guards fail together and a retest generates with **no new proof-of-concept evidence at all**. Pre-existing; reachable today by any hand-made previously-discovered finding.

Fix: scope the evidence-image-required check to `proof_of_concept`. Mirrored in JS.

### Settled - grouping and folder moves

The folder name is **not cosmetic**: it is the manager's group heading, via `"app_folder": report.folder_name_hint.app_folder or report.app_id` ([app/main.py](app/main.py#L415)) and `groupReportsByFolder` ([app/web/static/manager.js](app/web/static/manager.js#L25)).

- **The manager groups by `app_name`**, not by folder. Headings follow the live name, so a rename is correct immediately and folder drift never shows.
- **A folder moves only while it is still `unnamed`.** A brand-new report starts in `unnamed/` and relocates once the name exists; after that the name on disk is fixed. `PATCH /reports/{id}/name` never moves anything.

Nothing reads a folder name, so disk drift after a rename is inert and hand-renaming stays safe.

### Settled - how an image's environment is recovered

No inference from image content is needed. The generator writes a `PROD:`/`UAT:` paragraph **once per run of images**, not once per image ([app/docx_report.py](app/docx_report.py#L700-L710)), and `label_images` is true for **both** PoC sections ([app/docx_report.py](app/docx_report.py#L647)). The importer tracks the running label within each section: an image inherits the last label seen, until a new one appears.

For a generation-clean document this is lossless, because every image already requires an environment. An image appearing before any label in its section imports as `None`, and the tester is required to set it.

This recovers the label. It does **not** fix the vanishing-image problem — knowing an image is UAT is what makes it get hidden in a PROD-only retest. Both changes are needed.

**8. Every PoC in these reports has an image**, so a text-only source PoC cannot occur. `previous_proof_of_concept` seeds its image slot unconditionally — option (a).

**9. Not carried — the tester supplies these.** They describe the *new* engagement, so inheriting them would put last year's facts on this year's cover page.

| Field | Imported as |
|---|---|
| `test_windows` (per-environment test dates) | `{}` — empty |
| `report_date` | `None` |
| `start_date`, `end_date` | `None` |
| `report_type` | `None` |

`test_type` (web / API / both) **is** derived, from which scope tables have rows — it describes the scope being imported, not the engagement's purpose, and leaving it at its `"web"` default would make `reconcile_targets` delete every imported API target on the tester's first save.

`setup_issues` already blocks on a missing report type and missing dates, so the tester is stopped on Setup until they fill them in. No new gate is needed.

**10. Engagement fields.** Carried: `segment`, `app_owner`. Not carried: `tester`, `limitations`, `test_accounts`.

`tester` and `report_date` follow the app's own convention for a new draft — `create_report` sets `tester=self.tester` and `report_date=now.date()` ([app/workspace.py](app/workspace.py#L93)), so an import does the same. The tester field is the person importing, not the person who wrote the original.

`app_owner` is the one field here that costs real work: it is a prose token ([app/docx_report.py](app/docx_report.py#L51)) substituted mid-sentence, so recovering it means matching the surrounding boilerplate. Reliable only while that sentence is stable, and it yields `"N/A"` when the original was blank — which must map back to `""`.

**11. A report with no open findings still imports.** Engagement, scope and testing details come across; `vulnerabilities` is empty. The draft blocks on generation at *"at least one finding"* until the tester adds one, which is the correct end state — there is nothing to retest, but the setup work is still worth keeping. The import summary says so explicitly.

## Agreed plan

`POST /reports/import` gains a third branch: a DOCX this app generated becomes a **new retest draft**.

Findings whose summary status reads `Open (New)` or `Open (Previously Discovered)` are kept and rewritten to `open_previously_discovered`; `Resolved` findings are dropped. For each kept finding the importer recovers `Description`, `Recommended Remediation`, and the `Proof of Concept:` section, and discards `Previous Proof of Concept:` and `In Conclusion:` unread. The recovered PoC — steps, images, evidence bytes and all — becomes the draft's `previous_proof_of_concept`. A fresh empty `proof_of_concept` is constructed for the retest.

Three rules shape it:

- **`previous_proof_of_concept` is a historical record.** It is never measured against the current retest's scope — not filtered, not relabelled, not counted as evidence.
- **The app labels only the slots it created.** An image carrying real evidence keeps its recovered environment, or stays unset for the tester.
- **Nothing new is written to disk.** No schema change, no migration, no new required field.

### 1. Prove what the components fingerprint

`FRAGMENT_COMPONENT_FILES` has **no entry for `table` or `image`**, and an image renders as a paragraph-styled `w:p` containing a drawing — style-identical to a `paragraph`. So recognition is: `table` = `w:tbl` body child; `image` = `w:p` with a descendant `a:blip`; `paragraph` = paragraph style with no `a:blip`; the other five by `w:pStyle`; a caption's owner is the preceding image paragraph if there is one, else the following table or code paragraph.

**Files:** `tests/test_docx_import.py`. **Tests:** the six component style sets are pairwise disjoint; the caption style is disjoint from all six; table and image are recognised structurally. **Invariant:** a template edit fails a test instead of silently mislabelling every fragment in every future import.

**`note` vs `paragraph`.** A note is recognised by the literal `Note: ` prefix a finished report shows in front of its value. **Confirmed by test**: the component is fed `{"note-fragment": "Retest both affected environments."}` and renders as `"Note: Retest both affected environments."` ([tests/test_docx_components.py](tests/test_docx_components.py#L72), [tests/test_docx_components.py](tests/test_docx_components.py#L153)). The prefix lives in `note_fragment.docx`; `_render_text_component` injects only `fragment.runs` ([app/docx_report.py](app/docx_report.py#L734-L735)). So the importer detects on the prefix and must **strip it** when rebuilding the runs, or regeneration produces `Note: Note: …`. A paragraph whose text genuinely begins `Note: ` is read as a note, which is accepted.

### 2. Previous PoC is a historical record

One principle, three call sites, all of which currently treat previous-PoC images as current-scope images:

| Site | Today | After |
|---|---|---|
| `fragment_applies` ([app/report_service.py](app/report_service.py#L278-L281)) | Hides an image whose environment left the scope — a carried UAT screenshot **silently vanishes** from a PROD-only retest | Previous-PoC images are never hidden |
| `sync_evidence_image_slots` ([app/report_service.py](app/report_service.py#L288-L296)) | Relabels every image for a single-environment finding, and fills any `None` by position | Assigns environments only to slots with no evidence |
| `generation_issues` coverage ([app/docx_report.py](app/docx_report.py#L101-L110)) | Scans all sections, so a carried image **satisfies the new PoC's evidence requirement** | Counts `proof_of_concept` images only |

**Mechanism.** `fragment_applies` cannot currently tell which section a fragment came from, so it gains the content type as a parameter and returns `True` unconditionally for `previous_proof_of_concept`. Both call sites already have `content` in scope ([app/docx_report.py](app/docx_report.py#L688), [app/docx_report.py](app/docx_report.py#L119)), so no restructuring is needed. `sync_evidence_image_slots` computes coverage from `proof_of_concept` images alone and assigns an environment only where `evidence_id is None`. `generation_issues` scopes its per-environment evidence check the same way.

One rule stated once: **environment coverage is a property of `proof_of_concept`.** A carried image is rendered, labelled with the environment it was found in, and counted for nothing.

**Files:** a PROD-only retest and renders; a retest with evidence only in the previous PoC still reports *"Production evidence image required"*; an image with evidence and no environment stays `None` across a save; plus `test_browser_readiness_verdict_matches_server_generation_issues` passing unchanged. **Invariant:** history is never rewritten to match the present, and last year's screenshot never counts as this year's proof.

*Independent of import. Fixes bugs reachable today by any hand-made previously-discovered finding.*

### 3. Seed the previous-PoC image slot

`provision`'s table asks for `["numbered_list"]` while the `ImageFragment` branch at [app/report_service.py](app/report_service.py#L180) is unreachable dead code. Add `"image"` to `previous_proof_of_concept`, matching what the browser has always done.

**Files:** [app/report_service.py](app/report_service.py), [docs/DATA_MAP.md](docs/DATA_MAP.md). **Test:** a server-provisioned previously-discovered finding has the same section shape as a browser-provisioned one. **Invariant:** the two implementations seed identically, so an imported draft and a hand-made one are indistinguishable.

### 4. Folder naming and manager grouping

App folder becomes `safe_name(app_name)`, report folder becomes `{report_date:%Y-%m}_{report_type}_{report_id[2:]}` — the draft's own report date, not the clock at save time. The manager groups by `app_name` rather than by folder.

**A folder segment is provisional until the value that names it exists.** The app folder reads `unnamed` while `app_name` is blank; the report folder reads `Report` while `report_type` is `None`. Each is renamed by the save that supplies its missing value, then frozen — so editing `report_date` afterwards does not move anything. `PATCH /reports/{id}/name` never moves anything.

**Files:** [app/workspace.py](app/workspace.py), [app/main.py](app/main.py), [app/web/static/manager.js](app/web/static/manager.js), [docs/DATA_MAP.md](docs/DATA_MAP.md). **Tests:** a named report lands in `Northstar_Customer_Portal/2026-09_Annual_Pentest_<id>/`; a blank report starts in `unnamed/` and relocates on the save that names it; a rename changes the heading and leaves the folder alone; the four existing folders still load and group. **Invariant:** every report is reachable and correctly grouped regardless of which naming scheme created its folder.

*Safe because `find_path` and `list_reports` both scan `apps_root.glob("*/*/draft.json")` — no lookup depends on a folder name.*

### 5. Fixture builder

Every test calls `render_report_docx` **directly** with **`allow_incomplete=False`**. No test touches `/reports/{id}/generate`, which always 422s without Word. `allow_incomplete=True` is rejected: it substitutes a placeholder *paragraph* for a missing image, so the importer would read a paragraph where the real generator emits an image.

The fixture is generation-clean, built in code, never committed: two environments, web and API targets, three findings covering all three statuses, real PNG bytes, and a PoC exercising all eight fragment types.

**Files:** `tests/test_docx_import.py`. **Test:** `generation_issues(fixture) == []`. **Invariant:** the suite tests the document the generator actually ships.

*The fixture carries literal `Figure 1 ` prefixes, because SEQ numbers are written statically — exactly what the importer must strip.*

### 6. Engagement, scope and tables

**Carried:** `app_name`, `segment`, `app_owner`, `non_production_label`, scope targets. **Derived:** `test_type` from which scope tables have rows, `tested_environments` from which environments the scope covers — facts in the document, not guesses. **Not carried:** `test_windows`, `start_date`, `end_date`, `report_type`, `limitations`, `test_accounts`, `ci_number`, `bsn_number`. **From the app, not the document:** `tester`, `report_date`.

Each finding carries its `display_id`, `title`, `severity` and affected locations, in document order; `status` is rewritten in step 8. `library_ref`, `poc_variant` and `poc_variant_declined` are left unset, so the library offer fires fresh against the empty new PoC.

`Scope.mode` is always `custom`. `display_id` is kept only when it matches `^[0-9]{1,5}$`, else `None` — never `""`. Long scope values split by `w:br` are rejoined. An unrecognised paragraph style **rejects the import by name** rather than silently becoming a `paragraph`.

**Files:** `app/docx_import.py`. **Tests:** engagement round-trip, asserting `setup_issues` returns **only** what the DOCX genuinely cannot carry; a wrapped long URL rejoins to one target; a blank finding number imports as `None`. **Invariant:** no scope target is invented, demoted or split.

### 7. Fragment recovery

**Files:** `app/docx_import.py`. **Tests:** all eight types round-trip with run-level formatting, a captioned table, a captioned image, a multi-line `code_block` whose `w:br` newlines survive, and a nested cell; a lone `"N/A"` caption returns `""`; a single-`"N/A"` section returns empty; no zero-item list is emitted; the `Figure N ` prefix is stripped; a duplicate `Proof of Concept:` heading is rejected by name. **Invariant:** no fragment type is silently downgraded to `paragraph`.

**Two detail layouts, not one.** Findings render from `new_finding.docx` or `retest_finding.docx` depending on status, so an `Open (New)` finding has only `Description`, `Recommended Remediation` and `Proof of Concept:` — no `Previous Proof of Concept:` and no `In Conclusion:` at all. Their absence is normal and must not read as a malformed document; only a *missing* `Description`, `Recommended Remediation` or `Proof of Concept:` is an error.

**Headings match exactly, never by substring.** `Previous Proof of Concept:` **contains** `Proof of Concept:`. A `startswith`, `in`, or `endswith` test finds two PoC sections in every retest finding and takes the earlier one — importing last year's evidence as this year's, silently. Exact equality after whitespace normalisation, with `Previous Proof of Concept:` matched first.

**The layout cross-checks the status.** Status is read from the summary table, but the detail layout independently implies it: a `Previous Proof of Concept:` heading means the finding cannot be `Open (New)`. When the two disagree the document was misparsed, so reject by finding name rather than guess. Free integrity check on the riskiest inference in the importer.

### 8. Filter, promote, provision

`provision_report` moves from [app/main.py](app/main.py) to [app/report_service.py](app/report_service.py) — `main.py` imports `docx_import`, so `docx_import` cannot import back. `main.py` re-exports it, keeping `main.provision_report` resolvable for the existing browser test.

Per kept finding: promote to `open_previously_discovered` with the carried PoC in `previous_proof_of_concept` and an empty `proof_of_concept`; run `provision`; then construct the new PoC explicitly as one empty `numbered_list` plus one empty image slot per affected environment; then run `sync_evidence_image_slots` as a guard that should find nothing to do.

**Files:** `app/docx_import.py`, [app/report_service.py](app/report_service.py), [app/main.py](app/main.py). **Tests:** the resolved finding is gone and both survivors are `open_previously_discovered`; the source Previous PoC and In Conclusion appear nowhere; for a two-environment finding whose carried previous PoC already holds both environments, the new `proof_of_concept` is exactly `[numbered_list, image(production), image(non_production)]`, all empty; and `provision_report` re-run on a deep copy of the import is a **fixed point**. **Invariant:** no carried content and no needed retest slot can be created or destroyed by the first browser save.

### 9. Evidence

`sha256`, `width_px` and `height_px` are recomputed from the emitted bytes, never copied — embedded images are re-rasterised at 192 DPI with a baked-in border. That border is accepted and compounds per generation.

**Files:** `app/docx_import.py`. **Test:** hashes and dimensions match the emitted PNGs; every `evidence_id` is referenced exactly once; `set(evidence_files) == {e.file for e in report.evidence.values()}`, so the payload would satisfy `import_report`'s own set-equality check. **Invariant:** no orphan evidence, no mismatched hash, no shared `evidence_id`.

### 10. Wire the route

A `.docx` **is** a ZIP, so today it falls into the bundle branch and dies on *"missing draft.json"*. A `word/document.xml` sniff is ordered **first**; no bundle can contain that name, since set equality already restricts a bundle to `draft.json` plus `evidence/*.png`. `PackageNotFoundError` and `OpcError` are neither `ValueError` nor `OSError`, so both join the `except` tuple or a corrupt file returns 500. The DOCX branch gets its own size, per-image and pixel caps, mirroring the bundle branch's.

**Files:** [app/main.py](app/main.py), [tests/test_app.py](tests/test_app.py). **Tests:** a generated DOCX imports and returns `source: "docx"`; **an existing bundle still takes the bundle branch**; a truncated DOCX returns **422, not 500**; an oversized DOCX returns 413; a bare `draft.json` imports unchanged. **Invariant:** the two existing import formats behave exactly as they do today.

**Untrusted input.** This is the first place the app parses XML it did not write. The DOCX is opened with entity resolution and external DTD loading **disabled**, so a crafted `word/document.xml` cannot mount an entity-expansion or external-entity attack, and the uncompressed size is capped before parsing so a decompression bomb is refused rather than expanded. Evidence filenames are minted by the app and never taken from the document; `EvidenceItem.file` already rejects anything that is not a single-segment PNG under `evidence/` ([app/models.py](app/models.py#L184-L191)), so path traversal is closed by the model.

### 11. UI and copy

`accept` gains `.docx` and the Word MIME type. The failure message becomes `"Select a valid VulnReport ZIP, JSON, or report DOCX"` — and [tests/test_browser.py](tests/test_browser.py#L1209) pins the old wording verbatim, so both change together. The import summary renders **before** navigation and names: findings retained, findings dropped as Resolved, statuses rewritten, PoCs promoted to Previous PoC, findings left with no affected location, images that arrived without an environment, fragments that can no longer be re-added from the menu, and the reminder to enter a CI or BSN on Setup.

**Files:** [app/web/templates/home.html](app/web/templates/home.html), [app/web/static/manager.js](app/web/static/manager.js), [tests/test_browser.py](tests/test_browser.py). **Invariant:** the user is never told "imported" without being told what was dropped, rewritten or left blank.

### 12. Docs

**Files:** [docs/DATA_MAP.md](docs/DATA_MAP.md) — the historical-record principle, the previous-PoC seed, `provision` on the import path, `provision_report`'s new home, and the folder scheme. Also correct two existing drift items the oracle found: the folder-migration claim, and the `sync_evidence_image_slots` claim that it guarantees "no slots for unaffected ones". **Invariant:** the data-layer contract is satisfied in the same change, not after it.

### Deliberately not done

Write `open_new` for a source `Open (New)` finding — it destroys the promoted PoC on the first save. Adopt the reference converter's `open_conclusion` — a third Python spelling of a sentence that must track `_is_default_status_conclusion`'s regex. Rely on `provision` + `sync_evidence_image_slots` to produce the new PoC. Widen the `allowed` fragment-type map — a product decision, not a consequence of import. Crop the baked-in image border. Infer an image's environment from its pixels. Test through `/generate`, or render with `allow_incomplete=True`. Vendor the reference converter, add a second endpoint or button, synthesise `display_id`s, widen a Location-`N/A` finding to `mode="all"`, or trust `wp:extent` for pixel dimensions.

### Known gap

Mobile-scope reports import with empty scope and are blocked on Setup until the tester fills it in. No mobile example or report template exists yet, so nothing here is designed against a guess.
