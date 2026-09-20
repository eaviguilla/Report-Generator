# Setup network access field

> **Status:** shipped · 2026-09-21 · `c599dc6`
>
> Steps 1-5 are done. **Step 6 is deliberately not done** — it is the manual Word edit, and the
> accepted consequence of answer Q1a is that every cover prints `Internal` until it is. Nothing in
> the app will say so, which is why it is left unticked rather than quietly closed.
>
> Two deviations. **The R16 whole-list-assertion class is real and wider than the three sites the
> oracle named.** It broke `test_retest_default_preserves_the_retest_projection_except_named_neutral_fixes`
> twice — once for the new `network` key in the engagement projection, once for the new `warnings`
> key in the summary — a test written in the *previous* change and not on anyone's list. The three
> `setup_issues` assertions R16 actually named never fired, because Q2b removed the `setup_issues`
> line entirely. **And the step 4 warning is unconditional**, so every DOCX import now returns a
> `warnings` key where retest summaries previously had one only when something was genuinely
> ambiguous; the manager result dialog now always shows a notice. That follows from the agreed
> wording but is a visible behaviour change worth naming.

## Request

> another input for the setup page. Users have to select the network access of the tester in the
> application. Make it a drop down, required. Options are: Internal, External.
>
> Also, in the report generation, in the templates, it will be tagged as {{network}}. For now, the
> templates that is saved here in the resources is not updated. Just to know the position, the
> tagging {{network}} will replace the word Internal in the table of the very first page labeled as
> Application Type.
>
> make changes in the code where the word Internal in the first page is already replaced by the tag
> {{network}}

### Coordinator's notes on the request

Three things are stated that later rounds must not quietly drop:

1. The control is a **dropdown**, **required**, with exactly two options: `Internal` and `External`.
   It describes the network access *the tester had* to the application, so it is engagement-level
   rather than per finding — but confirm that against how the document prints it.
2. The token is `{{network}}`, and it lands in the **Application Type** table on the **first page**,
   replacing the word that currently reads `Internal`.
3. **The shipped templates under `resources/` do not carry `{{network}}` yet.** The code is to be
   written as though they do. That asymmetry is the sharp edge of this change: generation must not
   break on today's templates, and must fill the token on tomorrow's. Every round must say what
   happens in both cases.

Size judged **Large** (new schema field, new required Setup gate with a JavaScript twin, and it
reaches the `.docx`), so both rounds run and `scribe` is included in round 1.

Working-tree context for every agent: the editable-DOCX-import change is **implemented but
uncommitted** (`app/docx_import.py`, `app/main.py`, `app/report_service.py`,
`app/web/static/manager.js`, tests, docs). Read the working tree, not `HEAD`.

## Round 1 - Oracle: how it works today

**Answer.** `Engagement` is the right home, and this field has an exact precedent already in it:
`segment` and `report_type` are closed `Literal`s typed `| None = None`, rendered as a `<select>`
with a blank first `<option>`, and made "required" by one thing only — a line in `setup_issues`.
Nothing else in the app enforces a required Setup value. Adding `network` the same way costs no new
save validation, no new binding code, and no `load_path` repair; adding it any other way either
strands every draft on disk or breaks autosave on a brand-new report. The word `network` appears
**nowhere** in `app/` today (searched the whole package), and no draft under `data/apps/` carries the
key.

---

### 1. Where the field would live

`Engagement` confirmed — [app/models.py](app/models.py#L231-L268). The three comparable fields are
not the same shape as each other:

| Field | Declaration | Kind |
|---|---|---|
| `segment` | `Segment \| None = None` ([app/models.py](app/models.py#L238)), `Segment = Literal["JH", "GWAM", "Asia"]` ([app/models.py](app/models.py#L32)) | **closed Literal, nullable, no default value** |
| `report_type` | `ReportType \| None = None` ([app/models.py](app/models.py#L239)), `ReportType = Literal["annual_pentest", "retest", "deployment_pentest", "new_test"]` ([app/models.py](app/models.py#L33)) | **closed Literal, nullable, no default value** |
| `non_production_label` | `NonProductionLabel = "NON-PROD"` ([app/models.py](app/models.py#L244)), where `NonProductionLabel = Annotated[str, Field(min_length=1, max_length=40)]` ([app/models.py](app/models.py#L28)) plus a stripping `field_validator` ([app/models.py](app/models.py#L261)) | **validated free text, always populated** |

So: two closed Literals, one validated free text. `non_production_label` is **not** a precedent for
this field — it was a Literal until 2026-09-17 and was widened to free text only because its picker
gained an **OTHERS** escape hatch. It is never blank, so it never needed a completeness rule.

**The precedent for a required two-option enum is `segment` / `report_type`.** There is no
two-option enum in the schema today, but the arity is irrelevant — the pattern is: closed `Literal`,
`| None`, default `None`, blank `<option value="">` in the template, and one line in `setup_issues`.

**A fresh draft represents it as `None`.** [`Workspace.create_report`](app/workspace.py#L113)
constructs `Engagement(tester=self.tester, report_date=now.date())` and lets every other field take
its model default, so a new report is born with `segment=None`, `report_type=None` — and would be
born with `network=None`. It is then saved immediately, before the tester has seen the page.

**Two options for the stored token, both with precedent, and the source does not settle it.**
`Segment` stores its display text verbatim (`"JH"`, `"Asia"`) and needs no label map. `ReportType`
stores snake_case and maps through `REPORT_TYPE_LABELS`
([app/report_service.py](app/report_service.py#L14-L19)), which exists **only** because
`report_export_filename` needs a human label for a filename
([app/report_service.py](app/report_service.py#L239)). Storing `"Internal"`/`"External"` follows the
`segment` precedent and matches the document's word exactly; storing lowercase follows
`report_type` and needs a label map in Python plus a hand-written `<option>` label. Not established
in the source which is correct here — flagging for the planner, not advising.

### 2. The required-ness — three tiers, and only one of them is right

There are three distinct enforcement points, and they are **not interchangeable**:

**Tier 1 — blocks navigation *and* generation.** [`setup_issues`](app/report_service.py#L746)
collects missing engagement details; [`setup_is_complete`](app/report_service.py#L779) is
`not setup_issues(report)`. Two route gates read it: `/findings`
([app/main.py](app/main.py#L726-L727)) and `/edit` ([app/main.py](app/main.py#L735-L736)), both
redirecting to `/setup?incomplete=setup`. **And `generation_issues` opens with
`issues = setup_issues(report)`** ([app/docx_report.py](app/docx_report.py#L96-L98)), which
`finalized_report` turns into a 422 ([app/main.py](app/main.py#L518-L520)). So joining tier 1 buys
navigation blocking *and* generation blocking in one line. This is where `segment` and `report_type`
live, and it is where `network` belongs.

**Tier 2 — 422s a save.** [`setup_input_issues`](app/report_service.py#L162) is called from
`save_report` and returns HTTP 422 with code `invalid_setup`
([app/main.py](app/main.py#L782-L789)). Every check inside it is guarded by `if value` — its
docstring is literally *"Return invalid Setup values without treating blank draft fields as
errors."* It reports **malformed** values, never missing ones.

> **If `network` joins tier 2, autosave breaks for every report.** `create_report` saves a draft
> with `network=None` before the page renders; the very first autosave of every new report would
> 422, and every existing draft would become unsavable until its tester picked a value — with the
> save button stuck on an error the tester cannot dismiss by editing the field they were editing.

**Tier 3 — blocks generation only.** The rest of
[`generation_issues`](app/docx_report.py#L96-L131). If `network` went here alone, a tester would
pass Setup, fill in every finding, write every section, and only discover the missing value at the
Generate click. It also would not appear in the Setup validation notice, because that notice is
driven by `setup_issues`' JavaScript twin.

**Verdict: tier 1 (`setup_issues`), matching `segment` and `report_type` exactly.**

### 3. Existing drafts on disk — what actually happens

**Concrete, from a real file.** `data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json`
carries an `engagement` object with exactly these keys: `app_name`, `ci_number`, `bsn_number`,
`app_owner`, `segment` (`"JH"`), `report_type` (`"annual_pentest"`), `start_date`, `end_date`,
`tested_environments`, `tested_channels`, `non_production_label` (`"UAT"`), `test_windows`,
`test_accounts`, `limitations`, `tester`, `report_date`, `classification`, `template_set`. **No
`network` key**, and there is no `network` symbol anywhere in `app/`. There are eight app folders
under `data/apps/`, six of them under `unnamed/` alone.

**If `network` were declared required with no default:**

1. [`Workspace.load_path`](app/workspace.py#L271-L300) ends in `Report.model_validate(draft)`, which
   raises `ValidationError`.
2. [`Workspace.list_reports`](app/workspace.py#L120-L130) catches `(KeyError, OSError, ValueError)`.
   Pydantic v2's `ValidationError` subclasses `ValueError`, so the draft is **silently skipped** and
   vanishes from the manager's valid list.
3. [`Workspace.list_legacy_reports`](app/workspace.py#L132-L148) catches `ValidationError`
   explicitly and lists the draft as invalid, with
   `"repairable": "duplicate fragment id:" in reason` — which is **False** for a missing-field
   error. So every draft on disk lands in the legacy list **with no repair button**.

The `Report` before-validators do not help: the app-type and `normalise_scope_modes` hooks in
[app/models.py](app/models.py#L280-L318) run *before* field validation and neither injects defaults
for engagement scalars. `load_path`'s two repairs are the empty-`items` fragment fix and the
`RESOLVED_REMEDIATION` boilerplate fix — neither touches `engagement`.

**The established pattern is: declare it with a default, and add no `load_path` repair.** Every
field added since the schema settled follows it — `continue_numbering: bool = False`,
`ScopeTarget.description: str = ""`, `severity_review_tickets` / `cvss_score` / `cvss_vector`
(`str = ""`), `content_offer_resolved` / `content_offer_dismissed` (`default_factory=dict`), and for
dropdowns specifically, `segment` / `report_type` (`| None = None`). §8 of the map records the
reason a back-filling repair would be wrong, and the source agrees: `load_path` writes with
[`atomic_write_json`](app/storage.py), which burns the single `draft.bak.json` level (§3) to write a
value nothing was missing.

**`schema_version` does not move.** It is `Literal["1.4"]`
([app/models.py](app/models.py#L343)) and **no code anywhere branches on it** — bumping it would
make every draft on disk unloadable and buy nothing.

**The real, intended cost.** With `network: NetworkAccess | None = None` plus a `setup_issues` line,
every existing draft still **loads, saves, and keeps every value** — but becomes *setup-incomplete*.
A tester reopening Northstar_Banking is bounced from `/findings` back to `/setup` with the
validation notice, and `POST /reports/{id}/generate` 422s, until they pick a value. That is a
behaviour change for 100% of drafts on disk, and it is unavoidable if the field is genuinely
required. It is not a bug, but the plan should say it out loud.

### 4. Python/JavaScript twins this change creates

| Rule | Python | JavaScript |
|---|---|---|
| the option list and its order | the `Literal` in [app/models.py](app/models.py#L32) | the hand-written `<option>` elements in [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7). **There is no options constant in `app.js`** — `segment` and `report_type` are template-only, so this is a Python↔template twin, not a Python↔JS one |
| setup completeness | the missing-value block in [`setup_issues`](app/report_service.py#L748-L757) | **two** separate sites: [`validateSetupPage`](app/web/static/app.js#L2714)'s `requiredMetadata` array, and [`updateSetupValidationNotice`](app/web/static/app.js#L623-L626). Both hand-list the same four `[data-path=...]` selectors; a fifth must be added to **both** or the gate and the notice disagree |
| the issue wording | `issues.append("segment")` / `"report type"` ([app/report_service.py](app/report_service.py#L751-L753)) | `missing.push("segment")` / `"report type"` ([app/web/static/app.js](app/web/static/app.js#L624-L625)) — the strings must match, because the notice renders `Missing: <joined>` |
| the form control and its seeding | — | **none needed.** The generic `[data-path]` loop ([app/web/static/app.js](app/web/static/app.js#L1579-L1592)) seeds `input.value = report[section][field] ?? ""` and writes back `report[section][field] = input.value \|\| (input.matches('select, input[type="date"]') ? null : "")`. A `<select data-path="engagement.network">` with a blank first option binds, seeds and saves with **zero new JavaScript** |
| the Setup card counter | — | [`setupSectionSummary`](app/web/static/app.js#L650-L670) counts `.fields input, .fields select` for the Application card and prints `N of M`. Adding a select changes that count automatically; no code change, no test pins the number |
| the readiness panel | `generation_issues` includes `setup_issues` | **no twin exists.** [`updateReadinessPanel`](app/web/static/app.js#L3393) walks `report.vulnerabilities` only and never mirrors `setup_issues`. The browser's readiness verdict already ignores Setup completeness entirely; that stays invisible because `/edit` refuses to open on an incomplete setup. **No readiness-panel change is needed** — but see the test below |

**The existing drift guards, and the one that will break.**

- [`tests/test_browser.py::test_segment_and_report_type_are_required`](tests/test_browser.py#L458-L477)
  is the closest model for this field: it asserts the **exact option text list** of both dropdowns
  (`["Select segment", "JH", "GWAM", "Asia"]`), then asserts the Next click bounces with
  `"segment"` and `"report type"` in `#setup-validation-note`, then that choosing both lets Next
  through. A `network` twin belongs in that shape.
- [`tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`](tests/test_browser.py#L3781)
  is the map's named server/browser contract test — and **it will break**. Its fixture
  [`ready_report`](tests/test_browser.py#L56-L80) sets `segment`, `report_type`, environments,
  windows and a scope target but would not set `network`. `generation_issues` then returns a setup
  issue, `/edit` redirects to **`/setup?incomplete=setup`** — but the test's only redirect branch
  checks `"/findings" in self.page.url`, so it falls through to
  `wait_for_selector("#issue-count")` on the Setup page and times out.
- **The fix is cheap, and the plan should say so rather than budgeting for it.** All **122** call
  sites funnel through the one `ready_report` helper, so a single line there covers `test_browser`
  entirely. `tests/test_app.py` builds complete engagements by hand in about **13** places
  (lines 566, 792, 828, 861, 1322, 1455, 1577, 1729, 1748, 1836, 2111 …), each of which needs the
  key added.

### 5. The save and seed path — nothing new is required

- **Seed.** The [`setup` route](app/main.py#L716-L721) renders
  `report.model_dump(mode="json", by_alias=True)` into the `data-report` attribute on `<main>`
  ([app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L3)); the client does
  `JSON.parse(root.dataset.report)`. A new `Engagement` field appears there automatically. `None`
  arrives as JSON `null`, and the `?? ""` in the `[data-path]` seed maps it onto the blank
  `<option value="">`.
- **PUT body.** `save()` sends `JSON.stringify(clone(report))` wholesale
  ([app/web/static/app.js](app/web/static/app.js#L786)). Nothing enumerates engagement fields, so
  the value travels for free. An unchosen select writes JSON `null`, which is **exactly why the
  model field must be `| None`** rather than a bare `str` — a non-nullable field would 422 the
  first autosave of every new report.
- **Response.** `save_report` returns the canonical
  `report.model_dump(mode="json", by_alias=True)` ([app/main.py](app/main.py#L829-L831)), merged
  back by [`applyCanonicalReport`](app/web/static/app.js#L484) /
  [`reconcileCanonicalObject`](app/web/static/app.js#L433). `network` is **not** in the skip list
  `["saved_at", "app_id", "_folder_name_hint", "scope_text"]`
  ([app/web/static/app.js](app/web/static/app.js#L437)), so it reconciles like any other scalar: if
  the live value still matches what was sent, the canonical value wins. Correct by default.
- **`scope_text`-style request-only state does not apply.** `network` is a real persisted field that
  the server echoes back, so it is on the ordinary path, not the asymmetric one.
- **Local-draft recovery needs no normaliser.** The shape-repair blocks in `setup()` — the
  `tested_environments` array coercion ([app/web/static/app.js](app/web/static/app.js#L1526-L1531))
  and the `scope_text` total normalisation
  ([app/web/static/app.js](app/web/static/app.js#L1560-L1578)) — exist only for fields whose *shape*
  changed after drafts were cached. A nullable scalar that has only ever been a nullable scalar
  needs none.
- **Ordering note.** `reconcile_targets` runs on the raw `payload` **before**
  `Report.model_validate` ([app/main.py](app/main.py#L773-L786)) and touches only `scope_text` /
  `scope_targets`. It never sees engagement scalars.

### 6. Invariants and sharp edges

**§13 entries that bear on this:**

- **"A new export dropped into an older build loses every `description`."** The same one-way door
  applies verbatim. No model in [app/models.py](app/models.py) sets `model_config`, so Pydantic v2's
  default `extra="ignore"` deletes an undeclared key with no error: a bundle or draft carrying
  `network` opened in a build without the field loses it silently. The corollary the map records for
  `content_offer_resolved` and `continue_numbering` applies too — **once shipped, the field must
  stay declared forever**, even if abandoned, or it is silently deleted from every draft on the next
  save.
- **"A hidden Additional Information field keeps its value, and nothing ever clears it."** This is
  the precedent for valid-but-hidden values — and it **does not bite here as specified**, because
  the dropdown is unconditional: no segment, environment or app-type gate hides it. It starts biting
  the moment anyone gates it (e.g. "only meaningful for thick client"), at which point the
  established answer is the CVSS one: keep the value, hide the control, keep validating it.
- **"`scope_text` asymmetry."** Does not apply; `network` is symmetric.
- **`report_export_filename`** ([app/report_service.py](app/report_service.py#L228-L243)) composes
  segment + app_name + report_type + year. `network` is not part of it, and adding it would rename
  every export. Nothing in the request asks for that.

**"Never discard user content without a prompt" — the map does not state that rule in those words,
and the source shows a split, not a single rule.** Orphaned values are **kept and hidden** in three
places (`provision` carries an unprinted section, `sync_evidence_image_slots` never deletes an
uploaded screenshot, nothing clears the CVSS pair). The one true **purge** — removing an app type,
which deletes scope targets and reachable evidence — is confirmed with a dialog
(`findingsStrandedBy` / `dropTargetsEverywhere`). A two-option dropdown with no dependent data
neither orphans nor purges anything, so **neither arm applies** and no confirmation is owed.

**The new sharp edge this field creates:** *every draft on disk becomes setup-incomplete on the
first load after this ships.* It loads, saves, and keeps every value, but `/findings` and `/edit`
bounce to Setup and generation 422s until a value is picked. There is no back-fill, and per the
map's own `load_path` reasoning there should not be one — but the bounce is real and universal, and
a plan that does not mention it will read as a regression when it happens.

### Open questions for the planner

1. **Stored token.** `"Internal"` / `"External"` (segment precedent — no label map, matches the
   document's word exactly, but puts display text in the schema, which is what made
   `non_production_label`'s widening a one-way door) or `"internal"` / `"external"` (report_type
   precedent — needs a `NETWORK_LABELS` map in Python and hand-written `<option>` labels). **Not
   established in the source.**
2. **Does `network` participate in DOCX import?**
   [`_editable_engagement`](app/docx_import.py#L569-L609) builds the engagement dict from the
   document and returns a **fixed key set with no `network`**, so an editable import would produce
   `network=None` and land setup-incomplete — the same state as every existing draft. Whether the
   importer should read the Application Type table's word back out is a `scribe` / planner call; I
   record only that the key is absent today and the field would default cleanly.
3. **`finalize_editable_import` does not check setup completeness.**
   ([app/main.py](app/main.py#L588-L616)) It runs `setup_input_issues` and `finding_input_issues`
   (tier 2) but never `setup_issues` (tier 1), so a `network`-less editable import imports
   successfully and is simply incomplete afterwards. No change needed; noting it so nobody "fixes"
   it into a rejection.

### Map drift

**None found.** Every §6, §7, §8, §12 and §13 claim I checked against source held: the `Engagement`
field shapes, `setup_issues` / `setup_is_complete` and both route gates, `load_path`'s two repairs,
`list_legacy_reports`' `repairable` test, the `reconcileCanonicalObject` skip list, and the
`extra="ignore"` consequence. One thing the map states as a table row is worth restating as a fact
because it is easy to misread: §12's *"setup completeness"* row names `validateSetupPage` and
`updateSetupValidationNotice` as the JavaScript side — those are **two independent
implementations**, not one function called twice, and the readiness panel is a third surface that
deliberately does **not** mirror `setup_issues` at all. `docs/DATA_MAP.md` needs no edit for this
round; it will need §6, §12 and §13 entries once the field ships.

## Round 1 - Scribe: the document side

**Answer.** Registering `{{network}}` in `_metadata` is a **one-line, zero-risk change that does
nothing visible until someone hand-edits the four templates** — `_replace_metadata` no-ops on an
absent token, by design and with a comment saying so
([app/docx_report.py](app/docx_report.py#L290-L292)). The reverse asymmetry is the one that bites,
and it is already guarded: a template that gains `{{network}}` while the code does not supply it
fails **every** render and one named test. So *code first, templates later* is the safe order, and
it is the order the request asks for.

Two things do not match the request, and both matter:

1. **I could not verify the "Application Type" table, and the evidence I do have says the word
   `Internal` is somewhere dangerous.** See §1 — read it before writing any find-and-replace step.
2. **`Engagement.classification: str = "Confidential"` already exists**
   ([app/models.py](app/models.py#L250)) and is **never printed** — no `classification` key in
   `_metadata` ([app/docx_report.py](app/docx_report.py#L263-L299)). If the first-page cell that
   reads `Internal` is a *document classification* rather than network access, this field is its
   real home and `{{network}}` would be overloading the wrong cell. Ten seconds in Word settles it.

---

### 1. The premise — what I could and could not verify

**I could not open the templates in this session, and I am not going to pretend otherwise.** The
tools available to me here are read/search only, with no shell. `resources/MAIN.docx` reads back as
`PK\x03\x04 … 08 00` — a ZIP whose members are deflate-compressed (`[Content_Types].xml` is the
first) — so a byte read yields compressed bytes and a text search over them finds nothing. I ran
both: the byte read returned the ZIP header, and a literal search for `Application Type` across
`resources/MAIN*.docx` returned **zero matches**, which proves only that the bytes are compressed.

What I do have is `graphify-out/converted/`, a text extraction of each template. It is a derived,
git-ignored artefact, not source, and **it is demonstrably incomplete in exactly the region this
change targets** — see the trap below. Everything in this section is labelled with which of the two
it came from.

#### What the extraction shows (all four templates)

| Template | Extraction |
|---|---|
| `MAIN.docx` | `graphify-out/converted/MAIN_17ec8f65.md` |
| `MAIN_ASIA.docx` | `graphify-out/converted/MAIN_ASIA_b33945bd.md` |
| `MAIN_THICK_MOBILE.docx` | `graphify-out/converted/MAIN_THICK_MOBILE_7491d434.md` |
| `MAIN_THICK_MOBILE_ASIA.docx` | `graphify-out/converted/MAIN_THICK_MOBILE_ASIA_e3b181d8.md` |

- **No table anywhere is headed `Application Type`.** The extraction lists every table in each
  document, and the full header set is: `Version | Modification | Date | Author`,
  `Environment | From | To | Time`, `Resource | URL`, two `Risk Category | Description` matrices,
  `Finding Severity Rating | …`, `URL(s) in Scope`, `User Roles | Username`, `API Routes`,
  `Component | Description` (component pair only), `Limitations`,
  `Findings | Likelihood | Impact | Severity | ID | Status`,
  `Severity | CVSS Score | Impact | Exploitability`, and — Asia pair only — the Section table.
- **The first page carries no table at all** in the extraction. It opens
  `PENETRATION TEST REPORT` / `{{segment}} – {{app-name}} – {{test-type}} 2026`, then goes straight
  to `DOCUMENT REVISION HISTORY`.
- **The word `Internal` appears exactly once per template, and it is not on the first page.** It is
  a *column header of the Manulife Remediation Timelines policy table*:

  ```
  | Finding Severity Rating | Non-Production | Production | Production |
  | Finding Severity Rating | Non-Production | External   | Internal   |
  ```

  [MAIN_17ec8f65.md L124], [MAIN_ASIA_b33945bd.md L127], [MAIN_THICK_MOBILE_7491d434.md L126],
  [MAIN_THICK_MOBILE_ASIA_e3b181d8.md L129]. A merged `Production` header split into `External` and
  `Internal` sub-columns. **Note that `External` is right next to it** — see §4.

#### The trap: the extraction cannot see the first page

Do **not** read the above as "there is no Application Type table". The source proves the extractor
is blind to cover-page content:

- [`_document_texts`](app/docx_import.py#L455-L461) exists with the docstring *"Include paragraphs
  nested in cover-page shapes, which python-docx omits"*, and iterates
  `document.element.body.iter(qn("w:p"))` rather than `document.paragraphs`.
- [`_editable_engagement`](app/docx_import.py#L598) then reads
  `_labelled_value(texts, "Delivered To")` — so a label paragraph reading **`Delivered To`** exists
  in the generated document, on or near the cover.
- **`Delivered To` appears nowhere in any converted file.** Neither does any other cover-page label.

So the extractor skipped the same cover-page shape that `document.paragraphs` skips —
`w:txbxContent` inside `mc:AlternateContent` / `w:pict`. **The first page is precisely the blind
spot.** The user's `Application Type` table may well be there, unseen by both the extractor and by
`document.tables`.

#### What follows from that, whether or not the table is there

- **If `{{network}}` is placed in a cover-page shape it will still be replaced.**
  [`_replace_metadata`](app/docx_report.py#L308-L318) walks `root.iter(qn("w:p"))` from
  `document.element`, and lxml's `.iter()` descends into `w:txbxContent`. Same for
  [`_unresolved_placeholders`](app/docx_report.py#L1491-L1496), which iterates `w:t` from the same
  roots. **Token replacement in a text box is already supported.**
- **A cover-page *table* is invisible to `document.tables`.** python-docx's `document.tables` returns
  top-level body tables only. So [`_find_table`](app/docx_report.py#L345-L350) and the importer's
  table sweep would never see an Application Type table nested in a shape — but `_document_texts`
  *would* see its cell paragraphs. That asymmetry is the whole of §6.
- **`mc:AlternateContent` usually stores the same text twice** (a DrawingML `mc:Choice` and a VML
  `mc:Fallback`). `.iter()` visits both, so replacement hits both copies and neither check
  double-counts. `_labelled_value` de-duplicates through a `set`
  ([app/docx_import.py](app/docx_import.py#L463-L471)), so identical duplicates are harmless — but
  it **raises** on two *different* values for one label, which is a live failure mode if only one
  copy ever got edited.

#### How to settle it in under a minute

Open `resources/MAIN.docx` in Word, click the first-page table, and answer three questions: (a) is
the row label `Application Type`, (b) is the value cell the literal word `Internal` or something
like `Web`, and (c) is there a separate `Classification` row. Or, on any machine with Python:

```sh
.venv/bin/python -c "import zipfile,re;x=zipfile.ZipFile('resources/MAIN.docx').read('word/document.xml').decode();print(re.findall(r'<w:t[^>]*>([^<]*)</w:t>',x)[:80])"
```

The first eighty text nodes are the cover page. **Until that is run, no plan step should assume the
table exists.**

---

### 2. How a metadata token is replaced — the exact contract

`render_report_docx` ([app/docx_report.py](app/docx_report.py#L169-L208)) calls
`_replace_metadata(document, report)` at [L188](app/docx_report.py#L188), after the scope and
summary tables and before the findings body.

[`_metadata(report)`](app/docx_report.py#L263-L299) returns a flat `dict[str, str]` of token name →
printed string. [`_replace_metadata`](app/docx_report.py#L308-L318) then:

```python
for token, value in sorted(_metadata(report).items(), key=lambda item: len(item[0]), reverse=True):
    escaped = re.escape(token)
    patterns = [re.compile(r"\{\{\s*" + escaped + r"\s*\}\}", re.IGNORECASE)]
    if token in PLAIN_METADATA_TOKENS:
        patterns.append(re.compile(r"(?<![\w-])" + escaped + r"(?![\w-])", re.IGNORECASE))
    for root in _document_roots(document):
        for paragraph in root.iter(qn("w:p")):
            for pattern in patterns:
                replace_pattern_across_text_nodes(paragraph, pattern, value)
```

The contract, point by point:

| Question | Answer |
|---|---|
| Must the token own a paragraph? | **No.** It is a substring replacement inside a paragraph's text. Only `{{findings}}` must own its paragraph, and that is a separate check — [`_has_exact_body_token`](app/docx_report.py#L530-L536) uses `pattern.fullmatch`. |
| Can it sit mid-sentence, or mid-table-cell? | **Yes**, both. A cell is just paragraphs. |
| Is `{{…}}` required? | **Yes for `network`.** Bare-text matching applies only to `PLAIN_METADATA_TOKENS = {"app-name", "app-owner", "tester-name", "report-name"}` ([app/docx_report.py](app/docx_report.py#L55)). |
| Whitespace inside the braces? | Tolerated — `\{\{\s*…\s*\}\}`. `{{ network }}` works. |
| Case? | `re.IGNORECASE`. `{{Network}}` and `{{NETWORK}}` both work. |
| Split Word runs? | **Handled.** [`replace_pattern_across_text_nodes`](app/docx_components.py#L402-L441) concatenates every `w:t` in the paragraph, locates the match by character offset, writes the replacement into the first node, blanks the middle nodes and truncates the last. This is why a token typed in Word — where spell-check and revision marks routinely shred a word into three runs — still resolves. |
| Repeated occurrences? | All of them, in one paragraph and across the document. The `while nodes:` loop re-searches until no match remains. |
| What formatting survives? | The **first** touched run's formatting wins for the whole value: paragraph style, font family, size, bold, italic, underline. Font colour and size are changed only when explicitly passed, which `_replace_metadata` never does (they are for rating tags via `_replace_cell_placeholder`). So `{{network}}` inherits whatever the template author typed — which is what makes hand-editing the `.docx` safe: style the token like the word it replaces and the output matches. |
| Headers and footers? | Covered. [`_document_roots`](app/docx_report.py#L301-L306) yields `document.element` plus every `HeaderPart` / `FooterPart`. |
| Ordering hazard? | Tokens are replaced longest-name-first so a short name cannot eat a longer one's prefix. `network` (7 chars) is not a substring of any existing token and contains none. **No interaction.** |

**One hard requirement: the value must be a `str`, never `None`.** `replace_pattern_across_text_nodes`
does `prefix + replacement + suffix`; a `None` raises `TypeError`, not a `ReportGenerationError`, and
it would escape as a 500 rather than a validation message. `_metadata` already guards every nullable
engagement field — `engagement.segment or "N/A"`, `_display_value(...)`,
`REPORT_TYPE_LABELS.get(engagement.report_type or "", "N/A")`. **`network` must follow:
`engagement.network or "N/A"`.** This is not optional even though `setup_issues` will require the
field, because **the preview path bypasses `setup_issues` entirely**:
`render_report_docx(..., allow_incomplete=True)` skips the raise at
[app/docx_report.py](app/docx_report.py#L182-L184) and still runs `_replace_metadata`. Same for
`scripts/generate_report.py --allow-incomplete` ([scripts/generate_report.py](scripts/generate_report.py#L30)).

---

### 3. The two asymmetries

**(a) Token in the code, absent from the template → silent, deliberate no-op.**

`_replace_metadata` compiles a regex and finds nothing. No error, no warning, no log line. This is
not incidental — it is a documented, load-bearing design decision, with a comment at
[app/docx_report.py](app/docx_report.py#L290-L292):

```python
# The two component templates spell the same token in opposite orders. Both keys are always
# supplied: _replace_metadata no-ops on a token the template does not carry.
values["mobile-thick"] = values["thick-mobile"] = _component_channel_label(report)
```

`mobile-thick` / `thick-mobile` and the `binaries` pair already live this way: supplied always,
present in two of four templates. **`network` on today's un-updated templates is exactly that case
and is already proven in production.** Adding it changes nothing observable until a template carries
it. `docs/DOCX_TEMPLATE.md` states the same rule in its component-scope section.

**(b) Token in the template, empty or `None` value → two very different outcomes.**

- **Empty string `""`:** replaced with nothing, leaving an empty cell. Generation succeeds. The
  unresolved check never sees it because the braces are gone. `cvss-score` and `cvss-vector` relied
  on precisely this for their whole first life, and `docs/DOCX_TEMPLATE.md` records it: *"An empty
  field still prints an empty cell, so the token itself never blocks a render."*
- **`None`:** `TypeError` inside the replacer (see §2). Avoid by construction.
- **Token left unreplaced for any reason:** hard failure at the very end of generation.
  [`_unresolved_placeholders`](app/docx_report.py#L1491-L1496) flattens every `w:t` across the body,
  headers and footers, and returns `set(re.findall(r"\{\{.*?\}\}", text))`. Any survivor raises
  `ReportGenerationError(f"Unresolved template placeholders: …")`
  ([app/docx_report.py](app/docx_report.py#L202-L204)), which
  [app/main.py](app/main.py#L518-L520) surfaces as a 422. **It fires after all the work is done and
  before the bytes are returned — no partial document is ever written.**

**What this means for the un-updated templates, stated plainly for the plan:** adding
`"network": engagement.network or "N/A"` to `_metadata` today leaves generation **bit-for-bit
identical** on all four shipped templates. When someone later inserts `{{network}}` into the `.docx`
by hand, it starts printing with **no further code change**. And if they insert it *before* the code
lands, `_unresolved_placeholders` refuses the render and
`test_every_shipped_template_renders_without_unresolved_placeholders` goes red — a loud, immediate,
correctly-aimed failure. **The asymmetry is safe in the direction this change travels and guarded in
the other.**

---

### 4. What the code can usefully do today — and the find-and-replace question

**Beyond registering the token: nothing, and nothing else should be attempted.**

**Recommendation: do not find-and-replace the literal word `Internal`. It is reckless, and I can
name the damage.**

1. **The word `Internal` is a Manulife policy table header in all four templates.** It is the
   fourth column header of the Remediation Timelines table — `Finding Severity Rating |
   Non-Production | External | Internal`. Replacing the literal string document-wide rewrites a
   reproduced corporate standard. With a tester who picked `External`, that header becomes
   `… | External | External` — **a policy table with two identically-named columns**, in a document
   that goes to an application owner as evidence of a standard being applied. Nothing in the
   pipeline would catch it: it is a legal string replacement producing a legal document.
2. **It is the only occurrence the extraction can see.** If the cover-page `Internal` exists at all
   it is in the blind spot (§1), so a find-and-replace written today would hit **only** the wrong
   one.
3. **A scoped variant is not much better.** "Replace `Internal` only inside the first-page table"
   needs `document.tables`, which cannot see a table inside a cover-page shape (§1), so it would
   silently match nothing — and `_find_table` raises `ReportGenerationError("Template table not
   found: …")` if asked for a header it cannot see, turning a cosmetic feature into a generation
   blocker on all four templates.
4. **There is no precedent for it.** Every value in this pipeline is written into a token the
   template author placed deliberately. Nothing anywhere rewrites the template's own prose.

**A related trap the planner must be told about, because it looks like the obvious shortcut:**
**do not add `"network"` to `PLAIN_METADATA_TOKENS`** ([app/docx_report.py](app/docx_report.py#L55)).
That set makes the token match as **bare text, case-insensitively, anywhere in the document** — and
the word *network* is in the prose of all four templates. The CVSS appendix Medium row reads
*"…attacker must reside on the same network, requires user privileges."*
([MAIN_17ec8f65.md L179], [MAIN_ASIA_b33945bd.md L182], [MAIN_THICK_MOBILE_7491d434.md L184],
[MAIN_THICK_MOBILE_ASIA_e3b181d8.md L187]). Adding `network` to that set turns it into *"…must
reside on the same Internal, requires user privileges."* The existing members are all
hyphenated and report-specific (`app-name`, `app-owner`, `tester-name`, `report-name`) precisely
because a bare English word is unsafe there. **`{{network}}` braced-only is the correct and only
form.**

**So the whole document-side change is one line in `_metadata`, plus a row in
`docs/DOCX_TEMPLATE.md`.** Everything else is a Word edit somebody makes by hand, and the plan
should name it as a follow-up task with an owner rather than a code step.

---

### 5. Per report, not per finding — confirmed

**Report-level, and the same table already prints several engagement values through the same
mechanism.**

- `_metadata` takes `report` and reads `report.engagement` only
  ([app/docx_report.py](app/docx_report.py#L263-L299)). Every key it returns is engagement-level;
  there is no per-finding metadata path. Per-finding values go through a different route entirely —
  `_populate_summary_table`, `_populate_cvss_table`, and `_render_finding_component`, which fill
  cloned rows and component documents, not `{{…}}` tokens in the shell.
- The first page already resolves `{{segment}}`, `{{app-name}}` and `{{test-type}}` in the title
  line, confirmed in the extraction of all four templates. `{{report-date}}`, `{{tester-name}}` and
  bare `app-owner` resolve in the revision-history region just after it. **A first-page token is by
  construction engagement-level in this pipeline.**
- The corroborating evidence is the importer reading them straight back off those pages:
  [`_revision_metadata`](app/docx_import.py#L474-L480) recovers report date and tester from the
  `Version | Modification | Date | Author` row, and `_labelled_value(texts, "Delivered To")` recovers
  the owner ([app/docx_import.py](app/docx_import.py#L598)).
- A per-finding network value would also be unprintable: there is no token in any finding component
  for it, and adding one would mean a new `.docx` edit in `resources/finding_types/`, which is not
  what was asked.

---

### 6. Reading a finished report back — `network` is **not** recoverable today

**Working-tree state, as instructed.** `app/docx_import.py` is uncommitted; this is read from the
working tree.

**Today the answer is a flat no, and the reason is structural, not an oversight.**
[`_editable_engagement`](app/docx_import.py#L569-L609) returns a **fixed dict literal** with exactly
thirteen keys — `app_name`, `app_owner`, `segment`, `report_type`, `tested_environments`,
`tested_channels`, `non_production_label`, `test_windows`, `test_accounts`, `limitations`, `tester`,
`report_date`. There is no `network`, and no passthrough. Whatever the model's default is, that is
what an editable import produces.

**What it would take, and it is cheaper than it sounds — *if* the table turns out to be real.**

The mechanism already exists and is already used for a first-page value:

```python
"app_owner": _labelled_value(texts, "Delivered To"),
```

[`_labelled_value`](app/docx_import.py#L463-L471) finds every paragraph whose text equals the label
and returns the next non-empty paragraph, raising if two different values disagree. Because
[`_document_texts`](app/docx_import.py#L455-L461) iterates **`w:p` from the body element**, its flat
list includes (a) paragraphs inside table cells and (b) paragraphs inside cover-page shapes. So a
two-column `Application Type | Internal` row *and* a label/value paragraph pair both flatten to
`[…, "Application Type", "Internal", …]` and both are readable by the identical call:

```python
"network": _labelled_value(texts, "Application Type"),   # illustrative only — not to be applied by me
```

Three caveats the planner must carry:

1. **It depends entirely on §1.** If the label is not literally `Application Type`, or the value cell
   holds `Web` rather than `Internal`, this reads the wrong thing. Settle §1 first.
2. **The value must be validated, not trusted.** The document is user-supplied input. An unrecognised
   string must not reach the model — `report_type` already sets the precedent at
   [app/docx_import.py](app/docx_import.py#L1079): `raise ReportImportError(f"Unknown report type:
   {label}")` in editable mode. Membership in the two-value `Literal` is the check.
3. **`_labelled_value` raises on conflicting values.** If a hand-edited template leaves one
   `mc:AlternateContent` copy stale, or if `Application Type` appears twice with different values,
   the **entire import is rejected**, not just this field. That is consistent with how the rest of
   editable import behaves, but it makes the label choice a correctness decision.

**If it is not recoverable — what editable import must do instead.** Leave `network` unset so it
lands at the model default (`None`), **and add a warning**. Do **not** guess a value; `Internal` is
the commoner answer and would therefore be wrong quietly, in a field a tester may never revisit
because it already looks filled. The file has the exact pattern for this, used three times in
`_editable_engagement` alone:

```python
warnings.append("No app type was visible in the DOCX; review the default Web selection.")
```

and the warnings surface to the user through
[`summary["warnings"]`](app/docx_import.py#L1163-L1166). Two further consequences to write down:

- **`restored_engagement`** at [app/docx_import.py](app/docx_import.py#L1158-L1161) is a hand-written
  list of what was recovered — `"application", "owner", "segment", "report type", "report date",
  "tester", "test windows", "accounts", "limitations", "scope"`. **Add `"network access"` only if it
  is genuinely recovered.** This list is shown to the user; a false entry is worse than a missing one.
- **An import with no `network` lands setup-incomplete**, which the `loremaster` already established
  is the same state as every existing draft — and `finalize_editable_import` does not gate on
  `setup_issues`, so the import still succeeds. With a warning attached, that is the correct
  behaviour: the tester is told, and Setup will not let them past until they choose. **Silence is
  the only wrong answer here.**

**One incidental find worth recording.** [app/docx_import.py](app/docx_import.py#L1063-L1068) builds
a `metadata` dict from every two-cell table row in the document — and **never reads it**. It is dead
code. It is also, almost exactly, a key/value table reader for the kind of table this change
describes. Do not wire `network` through it (it uses `document.tables`, which cannot see a
cover-page table, §1) — but someone should either delete it or explain it, and this change is the
moment it became relevant.

---

### 7. Contract drift — one doc row, one named test

**`docs/DOCX_TEMPLATE.md` needs one row, in the *Engagement fields* table**, alongside `segment`,
`app-name` / `report-name`, `test-type`, `app-owner`, `report-date`, `tester-name` and the two
window triples:

| Template token | Report value |
|---|---|
| `network` | Internal or External network access |

That table is the canonical token list, and the sentence under it already covers the rest of the
contract: *"Tokens may be wrapped in `{{...}}` or appear as plain text where the template already
uses that form. Split Word runs are supported."* — **and that sentence is exactly why the row needs
a qualifier.** `network` is braced-only (§4). The clearest fix is to note it on the row itself rather
than to restate the rule. **No new section is warranted**; this is an ordinary engagement token, not
a new mechanism.

Worth adding one short paragraph, though, because it is the unusual part of this change and the
`loremaster` cannot cover it: **the token is registered in the code before the templates carry it,
and that is deliberate.** Without a note, the next reader finds a token in `_metadata` with no
template using it and assumes it is dead.

**The drift test, by name: `test_every_shipped_template_renders_without_unresolved_placeholders`**
([tests/test_docx.py](tests/test_docx.py#L1059-L1070)). It renders all four templates through the
real renderer and asserts `generation_issues(report) == []` first. Its docstring states the intent:
*"Each carries its own anchors, table headers and tokens, and every one of them is a hard
precondition."*

**It catches exactly one of the two directions:**

| Drift | Caught? |
|---|---|
| Template gains `{{network}}`, code does not supply it | **Yes, hard.** `_unresolved_placeholders` raises; the test fails on all four subtests. |
| Code supplies `network`, template does not carry it | **No.** Silent no-op by design (§3a). Nothing fails, and nothing should. |

That is the right shape — the dangerous direction is the guarded one — but the plan should say it
out loud, because **it means no test will prove the code half of this change works.** The only
honest verification is: hand-edit one template, render, open it in Word, look at the first page. On
a Mac that cannot be done at all — generation needs Windows with Word — so this is a
"only Word knows" item and the plan should assign it to someone who can run it.

**Two test-fixture consequences in my territory, which the `loremaster`'s test-churn count does not
include** (it covered `tests/test_app.py` and `tests/test_browser.py`):

- **`tests/test_docx.py` constructs `Engagement(...)` at eight sites** — L55, L300, L321, L374,
  L456, L541, L778 and L1016 — of which
  [`_component_report`](tests/test_docx.py#L1004-L1040) at L1016 is the shared helper feeding both
  template tests. Once `network` joins `setup_issues`, every fixture that renders **without**
  `allow_incomplete=True` starts raising `ReportGenerationError`, and
  `self.assertEqual(generation_issues(report), [])` at
  [tests/test_docx.py](tests/test_docx.py#L1069) fails outright. `_component_report` covers both
  tests at L1041 and L1059 in one edit; the other seven are individual.
  `Engagement(app_name="Northstar Banking")` at L300 is the deliberately-incomplete fixture for
  `test_template_without_the_findings_anchor_is_rejected` and needs **no** change.
- **`tests/test_docx_import.py` constructs `Engagement(...)` once**, at
  [L66](tests/test_docx_import.py#L66) — the round-trip fixture that renders a report and reads it
  back. One line. If §6 lands a recovery path, this is also where its round-trip assertion belongs.
- **`scripts/generate_showcase_reports.py` builds an `Engagement(...)` at
  [L405](scripts/generate_showcase_reports.py#L405)** and renders through a hard-coded
  `resources/MAIN.docx` ([L45](scripts/generate_showcase_reports.py#L45)). It bypasses
  `main_template_path` deliberately, but not `generation_issues` — **the showcase script breaks
  unless its engagement gains the field.** It is easy to miss because it is not a test.

---

### Open questions for the planner

**One question, and everything else in this section waits on it.**

**Does the first-page `Application Type` table actually exist, and does its value cell read
`Internal`?** I could not open the `.docx` from this session (no shell; the members are
deflate-compressed), and the one text extraction available is provably blind to the cover page. The
extraction shows **no** `Application Type` table and shows the word `Internal` in exactly one place
— as a column header of the Manulife Remediation Timelines policy table, next to `External`.

Three outcomes, with what each costs:

1. **The table exists and reads `Internal`.** The request is correct as written. One line in
   `_metadata`, one row in `docs/DOCX_TEMPLATE.md`, a hand edit to four `.docx` files as a
   follow-up, and optionally the `_labelled_value("Application Type")` recovery in §6.
2. **The table exists but the label or value differs** (e.g. the row is `Classification` and reads
   `Internal`, or `Application Type` reads `Web`). Then `{{network}}` is being aimed at the wrong
   cell, and `Engagement.classification` ([app/models.py](app/models.py#L250)) — which already
   exists, defaults to `"Confidential"` and has never been printed — is the more likely real subject.
   That is a different change with a different name.
3. **There is no such table.** Then the template author must choose where `{{network}}` goes before
   anything can print, and the code half is unchanged either way.

**In all three cases the code step is identical and safe**, so the planner can proceed with
`"network": engagement.network or "N/A"` in `_metadata` without waiting. **What must wait is any
step that names a specific cell, and any find-and-replace of the literal word `Internal`** — which I
recommend against outright, in every outcome.

### Template contract drift

One row in the *Engagement fields* table of `docs/DOCX_TEMPLATE.md`, noting that `network` is
braced-only, plus a short note that the token is registered ahead of the templates on purpose. I
have **not** made that edit: `docs/DOCX_TEMPLATE.md` describes the pipeline as it is, and the token
does not exist in it yet. It should be written when the code lands, in the same change.

### Coordinator verification of the premise (settles the scribe's open question)

The scribe could not open the templates and reported, with an explicit caveat, that it found no
"Application Type" table. **That caveat was correct and the negative finding was wrong.** I read
`word/document.xml` out of all four templates directly. The user's description is accurate.

Every one of the four templates (`MAIN`, `MAIN_ASIA`, `MAIN_THICK_MOBILE`, `MAIN_THICK_MOBILE_ASIA`)
contains `txbxContent`, which is why both the markdown extraction and `document.paragraphs` miss
this block. The cover block reads, as consecutive text nodes:

```
'Application', '{{', 'app-name', '}}', 'Application Type', 'Internal', 'Delivered To', 'app-owner'
```

Confirmed counts, identical in all four templates:

| String | Count | Where |
|---|---|---|
| `Application Type` | **2** | the cover block, which appears twice (once followed by `Prepared By`, once by `Table of Contents`) |
| `Internal` | **3** | twice as the value beside `Application Type`; once as a column header in the Remediation Timelines table |
| `External` | **1** | only the Remediation Timelines header, beside that third `Internal` |
| `Delivered To` | 2 | the same two cover blocks |
| `network` | **3** | lowercase prose only — "…attacker must reside on the same network…" |

Four consequences the planner must treat as fact:

1. **The Application Type table is real**, is on the cover, and its value cell is the literal word
   `Internal`. No step is blocked on opening Word.
2. **It occurs twice, not once.** Whoever edits the templates must replace both, or the second block
   keeps printing a hardcoded `Internal`. This belongs in the handover note.
3. **Find-and-replace of `Internal` is confirmed reckless**, exactly as the scribe argued: a
   document-wide replacement also rewrites the Remediation Timelines header, and with `External`
   chosen that policy row becomes `External | External`. Rejected on evidence, not on caution.
4. **Braced-only is mandatory**, also confirmed: the bare word `network` already appears three times
   in body prose, so a plain-text token would corrupt a sentence in every report.

Note for the field-shape question: `app-name` is **braced and split across three runs**, while
`app-owner` sits in the template as **bare text**. Both already work, which is direct evidence that
the existing replacement handles split runs and that the braced form the user asked for is the safe
one to add.

## Round 1 - Planner: proposal and open questions

**Understanding.** Add one engagement-level dropdown to Setup — *Network Access*, two options,
required — persist it on `Engagement`, make it block Findings/Content navigation and generation the
same way `segment` does, and register a `{{network}}` metadata token so the cover-page **Application
Type** cell prints it once somebody hand-edits the four `.docx` files. The code half is roughly six
lines; **the whole cost of this change is fixtures, twins, and the gap between the code shipping and
the templates being edited.** Nothing here is per finding, no new route, no new page.

---

### 1. The field, decided

```python
NetworkAccess = Literal["Internal", "External"]        # beside Segment / ReportType, app/models.py L32
network: NetworkAccess | None = None                   # in Engagement, after report_type, app/models.py L239
```

Closed `Literal`, **nullable**, default `None`, no `Field(...)`, no validator. Exactly the
`segment` / `report_type` shape.

**Stored casing: verbatim display text, `"Internal"` / `"External"`.** Taking the position the
oracle left open, on four grounds:

1. **The document prints the literal word `Internal`** — coordinator verification, cover block. With
   verbatim storage the `_metadata` line is `engagement.network or "N/A"` and there is no map
   between what the tester picks, what is stored, and what prints.
2. **`REPORT_TYPE_LABELS` exists for one reason that does not apply here** —
   `report_export_filename` needs a human label ([app/report_service.py](app/report_service.py#L239)).
   `network` is deliberately not part of the export filename, so a `NETWORK_LABELS` map would exist
   *solely* to undo a lowercasing that served nothing.
3. **It keeps the deferred import path a membership test**, not a reverse-map that can drift.
4. **The oracle's counter-argument does not transfer.** `non_production_label` became a one-way door
   because its picker gained an **OTHERS** escape hatch and had to widen to free text. A two-value
   closed set of network access has no such escape hatch on the table; `Segment` has stored its own
   display text since the schema settled and has never needed one.

`schema_version` does not move. No `load_path` repair. No back-fill — see risk **R1**.

### 2. Enforcement tier: **tier 1, `setup_issues`** — one line

```python
if not engagement.network:
    issues.append("network access")
```

placed beside `report type` in [`setup_issues`](app/report_service.py#L746-L754). That single line
buys both gates the request needs: `/findings` and `/edit` bounce to `/setup?incomplete=setup`
([app/main.py](app/main.py#L726-L736)), and `generation_issues` opens with `setup_issues(report)`
([app/docx_report.py](app/docx_report.py#L96-L98)), which `finalized_report` turns into a 422.

**Why tier 2 (`setup_input_issues`) is wrong, stated as the failure it causes.**
[`Workspace.create_report`](app/workspace.py#L113) constructs the engagement and **saves the draft
before the Setup page has rendered**, so a brand-new report exists on disk with `network=None`.
`setup_input_issues` is called from `save_report` and returns HTTP 422 `invalid_setup`
([app/main.py](app/main.py#L782-L789)). A missing-value check there would therefore **422 the very
first autosave of every new report**, and leave every existing draft unsavable — with the save
button parked on an error the tester cannot clear by editing the field they are editing. That is
also why the field must be `| None`: the `[data-path]` writer sends JSON `null` for an unchosen
`<select>` ([app/web/static/app.js](app/web/static/app.js#L1579-L1592)), and a non-nullable `str`
would 422 at model validation for the same reason. Tier 2 needs **no** line at all — the `Literal`
already rejects a malformed value at `Report.model_validate`, exactly as `segment` does.

**Why tier 3 (`generation_issues` alone) is wrong.** The tester would pass Setup, fill every
finding, write every section, and meet the missing value at the Generate click. It would also never
appear in `#setup-validation-note`, because that notice mirrors `setup_issues`, not
`generation_issues`.

### 3. Blast radius

| File | Change |
|---|---|
| [app/models.py](app/models.py#L32) | `NetworkAccess` Literal + `Engagement.network` |
| [app/report_service.py](app/report_service.py#L746) | one `setup_issues` line, string `"network access"` |
| [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | one `<label>` + `<select data-path="engagement.network">` with a blank first option |
| [app/web/static/app.js](app/web/static/app.js#L2714) | `validateSetupPage`'s `requiredMetadata` array — **twin A** |
| [app/web/static/app.js](app/web/static/app.js#L623) | `updateSetupValidationNotice` — **twin B, an independent implementation of the same rule** |
| [app/docx_report.py](app/docx_report.py#L263) | one `_metadata` key, `engagement.network or "N/A"` |
| [app/docx_import.py](app/docx_import.py#L569) | a warning in `_editable_engagement`; **no** key, **no** `restored_engagement` entry |
| [tests/test_browser.py](tests/test_browser.py#L56) | one line in `ready_report`, + a new required-field test |
| [tests/test_app.py](tests/test_app.py#L566) | ~13 hand-built engagements |
| [tests/test_docx.py](tests/test_docx.py#L1016) | 7 of 8 `Engagement(...)` sites (L300 stays incomplete deliberately) |
| [tests/test_docx_import.py](tests/test_docx_import.py#L66) | one site |
| [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405) | one kwarg — **not covered by any suite** |
| `docs/DATA_MAP.md`, `docs/DOCX_TEMPLATE.md` | contracts, see Step 8 |

No new route, no new model, no new JavaScript beyond the two twin lines: the generic `[data-path]`
loop seeds, binds and saves the select for free, and `network` is not in the
`reconcileCanonicalObject` skip list, so the server's canonical value reconciles normally.

### 4. Data risks

Not an all-clear table. Five real risks, each with the control that answers it.

| # | Failure mode | Verdict | Reasoning and control |
|---|---|---|---|
| **R1** | **Existing drafts on disk** | **RISK — accepted, not fixed** | They load, save and keep every value (nullable + default, no `ValidationError`, no `list_legacy_reports` demotion). But **100% of drafts on disk become setup-incomplete on first load**: `/findings` and `/edit` bounce to Setup and generation 422s until a value is picked. Control: state it in the release note and in `docs/DATA_MAP.md` §13. Deliberately **no** `load_path` back-fill — it would fabricate a value nobody chose and burn the single `draft.bak.json` level on load (see R6). |
| **R2** | **First-autosave path** | clear **because of two deliberate choices** | `create_report` saves before the page renders. Clear only while the field stays `| None = None` *and* the rule stays in tier 1. Either slipping breaks every new report's first save. Control: Step 1's test creates a report and saves it untouched. |
| **R3** | **Stale write / `saved_at`** | clear | No new mutation path. The value rides the existing whole-report `PUT`, which already carries `saved_at`; nothing reads-then-writes outside `Workspace._locked`. |
| **R4** | **Python/JavaScript twins drifting** | **RISK** | Three hand-maintained sites for one rule: the `<option>` list vs the `Literal`, and `setup_issues` vs **two independent** JS implementations (`validateSetupPage.requiredMetadata` and `updateSetupValidationNotice`). Adding to one JS site only makes the gate and the notice disagree — Next refuses with a notice that lists nothing. The issue string must be byte-identical across all three. Control: Step 5's browser test asserts the exact option text *and* the notice wording *and* that Next then passes. |
| **R5** | **DOCX round trip (editable import)** | **RISK** | `_editable_engagement` has no `network` key, so an import lands `None`. Worse is the tempting fix: because the cover block occurs **twice with the same hardcoded `Internal`**, `_labelled_value` de-duplicates through a set and would return `"Internal"` **without raising — for every document generated from today's un-edited templates, whatever the tester actually chose.** A silently wrong value in a field that looks filled. Control: **do not recover in this change.** Leave unset, emit a warning, and keep `"network access"` out of `restored_engagement`. |
| **R6** | **Generation on templates without the token** | clear | `_replace_metadata` no-ops on an absent token by documented design — the `mobile-thick` / `thick-mobile` pair already ships this way ([app/docx_report.py](app/docx_report.py#L290-L292)). Output is bit-for-bit identical on all four templates. Control: the existing `mobile-thick` precedent; §5 below covers what the tester sees. |
| **R7** | **`None` reaching the replacer** | **RISK** | `render_report_docx(..., allow_incomplete=True)` skips `setup_issues` entirely (preview, and `scripts/generate_report.py --allow-incomplete`), so `network` can be `None` at `_replace_metadata`, where `prefix + None + suffix` raises `TypeError` — a **500, not a 422**. Control: `engagement.network or "N/A"`, mandatory, matching every other nullable engagement value in `_metadata`. |
| **R8** | **Schema break / one-way door** | **RISK, permanent** | No model sets `model_config`, so Pydantic's default `extra="ignore"` deletes the key with no error. A bundle or draft carrying `network` opened by a build without the field **loses it silently on the next save**. Control: once shipped the field must stay declared forever even if abandoned — recorded in `docs/DATA_MAP.md` §13 beside `content_offer_resolved`. |
| **R9** | **Navigation trap** | clear | The gate redirects **to** `/setup`, and `/setup` has no gate. The control that satisfies the requirement is on the page the user is sent to. No loop. |
| **R10** | **Derived-state fight** | clear | Tester-authored, never derived. `provision_report` does not touch engagement scalars, and `network` is absent from the `reconcileCanonicalObject` skip list, so it reconciles like any scalar. |
| **R11** | **Orphan reference / silent stranding** | clear | A two-value scalar with no dependent data. Nothing references it; changing it strands nothing and purges nothing, so **no confirmation dialog is owed**. |
| **R12** | **Backup exhaustion** | clear **conditional on R1** | Only true while no `load_path` back-fill exists. A back-fill would write on load and again on the tester's first edit, consuming the single `.bak` level. |
| **R13** | **Request/response asymmetry** | clear | Symmetric. `save_report` echoes it in the canonical dump; this is not a `scope_text`-style request-only field. |
| **R14** | **Named test blocker** | **RISK — hangs, does not fail** | [`test_browser_readiness_verdict_matches_server_generation_issues`](tests/test_browser.py#L3781): its fixture would not set `network`, so `/edit` redirects to `/setup?incomplete=setup`, the test's only redirect branch checks `"/findings" in url`, and it falls through to `wait_for_selector("#issue-count")` and **times out**. Control: Step 2. |
| **R15** | **Named script blocker** | **RISK — no suite catches it** | [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405) renders through `generation_issues`, which opens with `setup_issues`. Every showcase render raises the moment the gate lands, and nothing in `tests/` covers the script. Control: Step 2. |

### 5. The template asymmetry, spelled out

**Today, with un-edited templates.** `_metadata` supplies `network`; `_replace_metadata` compiles
`\{\{\s*network\s*\}\}`, matches nothing, and returns. **Generation output is byte-identical to
today's.** What the tester sees: they pick *External* in Setup, pass the gate, generate — and the
cover page still reads **`Internal`**, in both blocks, because it is hardcoded template prose. **This
is the sharp edge of shipping code-first: for the duration of the gap, a chosen value of `External`
produces a document that contradicts it.** That is a wrong document, not a missing feature — hence
open question 1.

**Once the templates are edited.** Both cover `Internal` cells become `{{network}}`; the chosen value
prints; **no further code change**. Split Word runs are handled, the first touched run's formatting
wins, and `txbxContent` is reached because `_replace_metadata` iterates `w:p` via lxml `.iter()`.

**If a template is edited before the code lands.** `_unresolved_placeholders` raises and
`test_every_shipped_template_renders_without_unresolved_placeholders` goes red on all four subtests —
loud, immediate, correctly aimed. **So: code first, templates second.** That is also the order the
request asks for.

**The cover block occurs twice — what that means for whoever edits the `.docx`.** Per coordinator
verification, `Application Type` / `Internal` appears **twice** per template, once before
`Prepared By` and once before `Table of Contents`, in all four files — **eight edits, not four.**
Consequences of editing only one:

- The second block keeps printing a hardcoded `Internal` on every report, in a document that now
  also prints the real value — two contradictory statements on one cover.
- It poisons any future import recovery: `_labelled_value` **raises on two differing values for one
  label**, so the *entire* import would be rejected, not just this field.
- Both copies live in `mc:AlternateContent` / `w:txbxContent`, which is why python-docx, the
  markdown extraction and the scribe all missed them — they are easy to miss in Word too.

**Two things the template editor must not do**, both confirmed on evidence rather than caution:
no document-wide find-and-replace of `Internal` (the third occurrence is the Remediation Timelines
column header sitting beside `External`; with `External` chosen that policy row becomes
`External | External`), and **`network` must never join `PLAIN_METADATA_TOKENS`** (the bare word
appears three times in body prose — *"…must reside on the same network…"* — which would render as
*"…the same Internal…"*). Braced-only is the only correct form.

**Verification is a Word-only item.** Generation needs Windows with Word, so nobody on a Mac can
confirm the cover renders correctly. Step 9 assigns it.

### 6. Open questions for the user

**Q1 — What happens during the gap between the code shipping and the eight template cells being
edited?** During that window a tester who picks **External** generates a report whose cover page
says **Internal**, because the word is still hardcoded prose. Options: **(a)** ship the code now,
treat the Word edit as an immediate follow-up, and accept that any report generated in between is
wrong on the cover if `External` was chosen; **(b)** hold the Setup field out of the release until
the four `.docx` files are edited, so the dropdown and the printed value arrive together; **(c)**
ship the code and block generation while `network == "External"` until the token is present.
**Recommendation: (b) if any real report will be generated before the templates are edited,
otherwise (a).** (c) is rejected — it puts a template's state into a validation rule and would have
to be found and removed later. This is the only question that changes what a reader of a delivered
report sees.

**Q2 — Nullable-and-required, or defaulted?** **(a)** `network: NetworkAccess | None = None` plus the
`setup_issues` line — genuinely required, and **every report already on disk becomes
setup-incomplete on its next open** until its tester picks a value (Findings/Content bounce to
Setup, generation 422s). **(b)** `network: NetworkAccess = "Internal"` — no draft is ever disturbed,
nothing to re-pick, but a value **nobody chose** is stored in every report and printed on every
cover once the templates carry the token, and the dropdown is then not really required at all.
**Recommendation: (a).** The field's entire purpose is to record a fact about the engagement; a
default silently asserts that fact on the tester's behalf, and `Internal` being the commoner answer
is exactly what makes the wrong ones invisible. The cost is one dropdown per existing report, once.

**Q3 — Should a later change read the value back out of a finished DOCX on editable import?** Not in
this change (R5: today every document says `Internal` regardless, so recovery would import a
confidently wrong value). Once the templates carry `{{network}}` it becomes recoverable via
`_labelled_value(texts, "Application Type")`, validated against the `Literal`. Options: **(a)**
follow-up plan, gated on the template edit; **(b)** never — testers re-pick on import, as they do
for anything else the document does not carry. **Recommendation: (a), as a separate plan.** One
thing is unverified and must be checked first: the coordinator dumped **text nodes**, whereas
`_labelled_value` matches whole *paragraph* text — whether `Application Type` occupies its own
paragraph is not yet established, and the recovery does not work if it does not.

### 7. Plan

Ordered so the app is never left in a state where a save or a suite fails. **Fixtures move before
the gate** — reversing steps 2 and 4 leaves the entire DOCX suite and the showcase script red in
between, for no gain.

- [ ] **Step 1 — Declare the field.** [app/models.py](app/models.py#L32): add
  `NetworkAccess = Literal["Internal", "External"]` beside `Segment`/`ReportType`, and
  `network: NetworkAccess | None = None` to `Engagement` after `report_type`. No default value, no
  validator, no `schema_version` bump, **no `load_path` repair.**
  *Test:* `tests/test_app.py` — a new report saves untouched, and an existing `draft.json` with no
  `network` key still loads and round-trips with every other value intact.
  *Invariant:* every draft on disk loads and saves unchanged; the first autosave of a new report
  succeeds with `network` absent (R2).

- [ ] **Step 2 — Unblock the fixtures and the script, before the gate exists.**
  [tests/test_browser.py](tests/test_browser.py#L56) `ready_report` — one line,
  `report.engagement.network = "Internal"`, which covers all 122 call sites and is the fix for
  **R14**'s timeout. [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405)
  — add `network="Internal"` to the `Engagement(...)`, the fix for **R15**.
  [tests/test_app.py](tests/test_app.py#L566) ~13 hand-built engagements;
  [tests/test_docx.py](tests/test_docx.py#L1016) 7 of 8 sites — `_component_report` covers both
  template tests in one edit, and `Engagement(app_name="Northstar Banking")` at L300 **stays
  incomplete**, it is the deliberate fixture for `test_template_without_the_findings_anchor_is_rejected`;
  [tests/test_docx_import.py](tests/test_docx_import.py#L66) one site.
  *Test:* `tests.test_docx`, `tests.test_docx_components`, `tests.test_docx_import` — green before
  and after, since the field is not yet required.
  *Invariant:* no fixture that renders through `generation_issues` lacks the field when Step 4 lands.

- [ ] **Step 3 — Add the control.**
  [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7): a
  `<label>Network Access<select data-path="engagement.network"><option value="">Select network
  access</option><option value="Internal">Internal</option><option value="External">External</option></select></label>`
  in the Application card, after **Report Type**. No JavaScript: the `[data-path]` loop seeds
  `null → ""` onto the blank option and writes back `"" → null`. `setupSectionSummary`'s `N of M`
  counter updates itself and no test pins the number.
  *Test:* covered by Step 5's browser test.
  *Invariant:* an unchosen select persists as `null`, never `""`; the control renders before it is
  required, so no user can meet a gate they cannot satisfy. **This is a visual change to the Setup
  grid — screenshot the Application card and compare against the current layout before calling it
  done, per the repo's visual rule.**

- [ ] **Step 4 — Close the gate, on all three surfaces at once.**
  [app/report_service.py](app/report_service.py#L746) `setup_issues`:
  `if not engagement.network: issues.append("network access")`, placed after the `report type`
  check. [app/web/static/app.js](app/web/static/app.js#L2714) `validateSetupPage` — add
  `root.querySelector('[data-path="engagement.network"]')` to `requiredMetadata`.
  [app/web/static/app.js](app/web/static/app.js#L623) `updateSetupValidationNotice` — add
  `if (!root.querySelector('[data-path="engagement.network"]')?.value) missing.push("network access");`.
  All three in one commit; the string is `"network access"` in both languages.
  *Test:* Step 5.
  *Invariant:* **R4** — the gate and the notice never disagree. Nothing is added to
  `setup_input_issues` (**R2**), and nothing to `updateReadinessPanel`, which deliberately does not
  mirror `setup_issues`.

- [ ] **Step 5 — Prove the requirement, in the shape the existing one uses.**
  New `tests/test_browser.py::test_network_access_is_required`, modelled on
  [`test_segment_and_report_type_are_required`](tests/test_browser.py#L458-L477): assert the exact
  option text `["Select network access", "Internal", "External"]`, fill everything else, click
  **Next: Findings**, assert the URL is still `/setup` and `#setup-validation-note` contains
  `network access`, then select `Internal` and assert Next passes. Add a `setup_issues` assertion in
  `tests/test_app.py` for the server half.
  *Test:* `tests.test_browser` (this test plus `test_browser_readiness_verdict_matches_server_generation_issues`),
  and the named `tests/test_app.py` setup tests.
  *Invariant:* the option list, the gate and the notice wording are pinned together, so **R4** fails
  loudly instead of drifting.

- [ ] **Step 6 — Register the token.** [app/docx_report.py](app/docx_report.py#L263) `_metadata`:
  `"network": engagement.network or "N/A"`, beside `"segment"`. **Nothing else** — not
  `PLAIN_METADATA_TOKENS`, no `_find_table`, no find-and-replace of `Internal`.
  *Test:* `tests.test_docx` — `test_every_shipped_template_renders_without_unresolved_placeholders`
  still passes on all four templates (proving the no-op), plus a unit assertion that
  `_metadata(report)["network"]` is `"N/A"` when `network is None`.
  *Invariant:* **R7** — the replacer never receives `None`, including on the `allow_incomplete`
  preview path. Output on today's templates is byte-identical (**R6**).

- [ ] **Step 7 — Tell the truth on editable import.**
  [app/docx_import.py](app/docx_import.py#L569) `_editable_engagement`: append a warning in the
  existing style — *"Network access was not read from the DOCX; choose Internal or External in
  Setup."* Add **no** `network` key and **no** `"network access"` entry to `restored_engagement`
  ([app/docx_import.py](app/docx_import.py#L1158-L1161)); that list is shown to the user and a false
  entry is worse than a missing one. `finalize_editable_import` stays as it is — it gates on tier 2
  only, so the import still succeeds and lands setup-incomplete, which is correct.
  *Test:* `tests.test_docx_import` — the import succeeds, `network` is `None`, and the warning is in
  `summary["warnings"]`.
  *Invariant:* **R5** — no value is ever fabricated into a field that then looks filled.

- [ ] **Step 8 — Move the documentation contracts, in this same change.**
  `docs/DATA_MAP.md`: the `Engagement` field row in §6, a `setup completeness` twin entry in §12
  naming **all three** sites, and a §13 entry carrying **R1** (every draft becomes setup-incomplete,
  no back-fill, and why) and **R8** (`extra="ignore"` — the field must stay declared forever).
  Required by `.github/instructions/data-layer.instructions.md`, which applies to `app/models.py`,
  `app/report_service.py` and `app/web/static/app.js`. `docs/DOCX_TEMPLATE.md`: a
  `network → Internal or External network access` row in the *Engagement fields* table, marked
  **braced-only**, plus a short note that the token is registered ahead of the templates
  deliberately so the next reader does not take it for dead code. This plan file: status to
  `shipped`, date, commit, and the deviations paragraph.
  *Test:* none — documentation only.
  *Invariant:* no code fact ships without the contract that describes it.

- [ ] **Step 9 — Hand over the Word edit (not a code step).** In each of `resources/MAIN.docx`,
  `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx`, `MAIN_THICK_MOBILE_ASIA.docx`, replace **both**
  `Internal` value cells beside `Application Type` — the block before `Prepared By` **and** the block
  before `Table of Contents` — with `{{network}}`, styled like the word it replaces. **Eight edits.**
  Do **not** touch the `Internal` in the Remediation Timelines header. Then render one report per
  template on a Windows machine with Word and look at the first page.
  *Test:* `tests.test_docx` —
  `test_every_shipped_template_renders_without_unresolved_placeholders` is the guard that the edit
  did not outrun the code; it must be run **after** Step 6 is merged, never before.
  *Invariant:* both occurrences move together, or the cover contradicts itself and future import
  recovery is poisoned.

### 8. What I would not do

- **Back-fill `network` in `load_path` so existing drafts stay complete.** It writes a value nobody
  chose into every report on disk, on *load*, burning the single `draft.bak.json` level before the
  tester has typed anything — and it prints on the cover as if it were an assertion about the
  engagement. The honest cost is one dropdown per existing report (R1, Q2).
- **Find-and-replace the literal word `Internal`.** Rejected on the coordinator's evidence: the third
  occurrence is a reproduced Manulife policy table header, and with `External` chosen that row
  becomes `External | External` in a document delivered as evidence of a standard being applied.
  Nothing in the pipeline would catch it — it is a legal replacement producing a legal document.
- **Add `network` to `PLAIN_METADATA_TOKENS`.** The bare word appears three times in body prose;
  every existing member of that set is hyphenated and report-specific for exactly this reason.
- **Recover the value on DOCX import now.** The cover reads `Internal` in both blocks on every
  document today, and `_labelled_value` de-duplicates identical values without raising — so it would
  succeed, look right, and be wrong for every tester who chose `External` (R5).
- **Put the rule in `setup_input_issues` because "it is a save-time validation".** It 422s the first
  autosave of every new report and makes every existing draft unsavable.
- **Bump `schema_version`.** Nothing branches on it, and every draft on disk would stop loading.
- **Fold `network` into `report_export_filename`.** It would rename every export, and nothing asked
  for that.

### Coordinator verification of the planner's two challenges

The planner raised one contradiction and one gap in my earlier verification. I checked both against
source; **the planner is right on both counts.**

**1. `Application Type` and `Internal` each own their own paragraph.** My first dump listed text
nodes, and the planner correctly noted that `_labelled_value` matches whole paragraph text. Reading
`resources/MAIN.docx` paragraph by paragraph resolves it — the cover block is four consecutive
single-run paragraphs, and the whole block appears twice:

```
p[10] 'Application Type'   p[11] 'Internal'   p[12] 'Delivered To'   p[13] 'app-owner'
p[18] 'Application Type'   p[19] 'Internal'   p[20] 'Delivered To'   p[21] 'app-owner'
p[149] 'Internal'                                 <- Remediation Timelines header
```

This is the **same shape** as the `Delivered To` / `app-owner` pair the importer already reads, and
it means the future `{{network}}` will own its paragraph exactly as `app-owner` does. The label is
therefore a usable anchor once the templates are edited.

**2. Recovery would silently return `Internal` today.** Confirmed at
[app/docx_import.py](../../app/docx_import.py#L463-L471): `_labelled_value` collects following
values into a **set**, raises only when `len(values) > 1`, and otherwise returns the single member.
Two cover blocks both reading the hardcoded `Internal` collapse to `{"Internal"}` — one value, no
error, wrong answer for every tester who chose `External`. The planner's decision to defer recovery
and warn instead is correct, and the scribe's "cheaper than it sounds" leaning is superseded.

A consequence worth carrying into the agreed plan: recovery becomes correct **only** once the
templates are edited **and both blocks** carry the token. If only one is edited, the set holds
`{"Internal", "External"}` and `_labelled_value` raises `ReportImportError`, failing the whole
import. That makes "edit both blocks" a correctness requirement, not tidiness.

## Round 2 - Oracle: verdict on the proposal

**Answer.** The shape is right and the tier is right: I re-derived both from source and the planner's
`network: NetworkAccess | None = None` plus one `setup_issues` line is exactly what `segment` and
`report_type` do. **Existing drafts survive — yes**, and I name the validator path below. Two things
are wrong. **R14 is materially understated**: it names one browser test and claims `ready_report`
covers the rest, but **four browser tests build their report through the Setup form from `/new` and
never call `ready_report`** — each walks the gate by hand and each will fail. And **R7 is
misclassified in the safe direction for the wrong reason**: `None` cannot reach the replacer at all
on today's templates, because `replace_pattern_across_text_nodes` returns before touching
`replacement` when the pattern does not match. The `or "N/A"` guard is still mandatory, but it is a
*latent* defect that arms itself the day Step 9 lands, not a live one — which changes when it must
be verified, not whether.

Two files are missing from the blast radius, one of them a second hand-written engagement literal
the round 1 report did not surface either.

---

### 1. The risk table, row by row against source

Both directions checked. Ten rows stand as written and I am not restating them.

| # | Planner | Verdict | Settling function |
|---|---|---|---|
| R1 | RISK, accepted | **stands** | `load_path` → `Report.model_validate`; see §3 |
| R2 | clear | **stands** | `Workspace.create_report` ([app/workspace.py](../../app/workspace.py#L113-L118)) then `save_report`'s `Report.model_validate` ([app/main.py](../../app/main.py#L779)) — `null` is legal against `NetworkAccess \| None` |
| R3 | clear | **stands** | no new mutation path; `save_if_current` unchanged |
| R4 | RISK | **stands** | three hand-maintained sites, confirmed in §2 |
| R5 | RISK | **stands, widen** | correct about `_editable_engagement`; misses the second engagement literal, §2 |
| R6 | clear | **stands** | `_replace_metadata` ([app/docx_report.py](../../app/docx_report.py#L290-L292)) |
| **R7** | **RISK** | **reclassify → latent, not live** | see below |
| R8 | RISK, permanent | **stands** | verified directly: **`model_config` appears nowhere in `app/models.py`**, so Pydantic v2's `extra="ignore"` applies to every model |
| R9 | clear | **stands** | the `setup` route ([app/main.py](../../app/main.py#L716-L719)) has no gate; the redirect target is reachable |
| R10 | clear | **stands** | `provision_report` ([app/main.py](../../app/main.py#L262-L267)) iterates `report.vulnerabilities` only and never reads `engagement` |
| R11, R12, R13 | clear | **stand** | R13 confirmed at [app/main.py](../../app/main.py#L812-L813), the canonical echo |
| **R14** | RISK, one test | **reclassify → RISK, five tests, and `ready_report` covers only one of them** | see below |
| R15 | RISK | **stands** | [scripts/generate_showcase_reports.py](../../scripts/generate_showcase_reports.py#L405) |
| — | *absent* | **new row owed: R16, exact-equality assertions on `setup_issues`** | see below |

**R7 — `None` reaching the replacer is latent, not live.**
[`replace_pattern_across_text_nodes`](../../app/docx_components.py#L402-L441) opens with

```python
    nodes = list(paragraph.iter(qn("w:t")))
    while nodes:
        text = "".join(node.text or "" for node in nodes)
        match = pattern.search(text)
        if not match:
            return
```

The `prefix + replacement + suffix` concatenation is eleven lines further down, **after** the match.
On the four shipped templates `{{network}}` matches nothing, so a `None` value is inert: the
`allow_incomplete` preview path and `scripts/generate_report.py --allow-incomplete` cannot 500
today. The `TypeError` becomes reachable the moment a template carries the token — i.e. the day
Step 9 lands, on a machine nobody can test it on. **Keep `engagement.network or "N/A"`, and move it
from "control that prevents a live 500" to "control that must be in place before the Word edit",
because no test can ever demonstrate it.** The planner's Step 6 unit assertion
(`_metadata(report)["network"] == "N/A"` when `None`) is therefore the *only* thing that will ever
exercise it — it is load-bearing, not a nicety.

**R14 — the browser fixture fix does not cover the browser tests that matter.**
The planner's Step 2 is right that `ready_report` ([tests/test_browser.py](../../tests/test_browser.py#L56-L80))
is a one-line fix covering every test that creates its report server-side. But **four tests never
call it.** They `page.goto(f"{self.base_url}/new")`, fill the Setup form through the UI, and then
walk the gate:

| Test | `/new` at | Passes the gate at |
|---|---|---|
| `test_authoring_workflow_autosave_fragments_and_manager_grouping` | [L174](../../tests/test_browser.py#L174) | [L206-L207](../../tests/test_browser.py#L206) `wait_for_url("**/reports/*/findings")` |
| `test_segment_and_report_type_are_required` | [L460](../../tests/test_browser.py#L460) | [L477](../../tests/test_browser.py#L477) `wait_for_url("**/findings")` |
| `test_a_second_component_row_lands_as_its_own_target` | [L792](../../tests/test_browser.py#L792) | [L810](../../tests/test_browser.py#L810) |
| `test_a_component_needs_a_description_before_setup_will_let_you_leave` | [L920](../../tests/test_browser.py#L920) | [L959](../../tests/test_browser.py#L959) |

Each needs a `select_option` for the new dropdown before its final Next. Two of the four are
**hangs, not failures** — `wait_for_url` times out rather than asserting — which is the same failure
mode R14 already describes and the reason these are easy to mis-diagnose as flake. The fifth,
`test_browser_readiness_verdict_matches_server_generation_issues` ([L3781](../../tests/test_browser.py#L3781)),
is the one the planner named and is genuinely fixed by the `ready_report` line.

Note the irony in the second row: `test_segment_and_report_type_are_required` is the test the plan
models Step 5 on, and it is also one of the tests Step 4 breaks. The new `test_network_access_is_required`
does not replace it.

**R16 — three exact-equality assertions on `setup_issues` (owed, absent from the table).**

```python
self.assertEqual(report_service.setup_issues(blank), ['production Thick Client description for "Acme.exe"'])
```

[tests/test_app.py](../../tests/test_app.py#L1813), and the same shape at
[L1817](../../tests/test_app.py#L1817) and [L1822](../../tests/test_app.py#L1822) (the last asserting
`[]`). These compare the **whole list**, so a `"network access"` entry breaks them even though the
rule under test is untouched. Their fixture is `_component_scope_report`
([tests/test_app.py](../../tests/test_app.py#L1746)), which is inside the planner's "~13 hand-built
engagements" — so the *fix* is already budgeted, but the plan should say these three are
equality-not-membership, because a reader skimming Step 2 will patch the dict and not think to check
what the assertion compares.

**One framing correction that changes nothing but will mislead the implementer.** The plan describes
tiers 1 and 2 as siblings. They are nested: `setup_issues` **ends** with

```python
    return [*issues, *setup_input_issues(engagement)]
```

[app/report_service.py](../../app/report_service.py#L776). Tier 1 is a strict superset of tier 2.
"Tier 2 needs no line" is correct, but the reason is stronger than stated — anything added to tier 2
would *also* appear in tier 1 and in the Setup notice, so the two tiers are not independently
choosable in the direction the plan implies.

### 2. Files the planner missed

**Both round 1 facts were carried correctly.** The two independent JavaScript implementations appear
as twin A and twin B in the blast radius, in R4, and as two separate edits in Step 4 — correct. The
readiness panel's deliberate absence of a `setup_issues` twin is carried in Step 4's invariant line —
also correct, and I re-confirmed it: [`updateReadinessPanel`](../../app/web/static/app.js#L3393)
mirrors only finding-level rules from `generation_issues` (the `in_conclusion` rule at
[L3425](../../app/web/static/app.js#L3425), the Asia CVSS gate at [L3478](../../app/web/static/app.js#L3478))
and never the setup block.

**Missed — [app/docx_import.py](../../app/docx_import.py#L1105-L1115), the *second* engagement
literal.** `parse_report_docx` supports two modes, `IMPORT_MODES = {"editable", "retest"}`
([app/docx_import.py](../../app/docx_import.py#L60)), and **retest** mode never reaches
`_editable_engagement`:

```python
    engagement = {
        "app_name": app_name, "app_owner": "", "segment": segment, "report_type": None,
        "tested_environments": environments or ["production"], ...
    }
    if mode == "editable":
        engagement = _editable_engagement(...)
```

`retest` is the **default** mode for a DOCX upload — `mode = docx_mode or "retest"`
([app/main.py](../../app/main.py#L635)). So the plan's Step 7 warning, appended inside
`_editable_engagement`, never fires for the commoner path, while `summary["warnings"]` is still
surfaced for it through the `elif warnings:` branch
([app/docx_import.py](../../app/docx_import.py#L1166)). **What it needs:** either the same warning
appended for retest mode, or an explicit sentence in the plan that retest imports land
`network=None` silently and that this is accepted. Today the plan says neither, and R5's stated
control ("leave unset, emit a warning") is only half-true as written.

**Missed — [tests/test_app.py](../../tests/test_app.py#L90), `test_report_management_lifecycle`.**
It sets `report["engagement"]["segment"]` and `["report_type"]` at L88-89 and then asserts a full
lifecycle. It is not in round 1's line list (566, 792, 828, 861, 1322, 1455, 1577, 1729, 1748, 1836,
2111), so a reader working that list will skip it. The reliable enumeration is
`grep -n '"report_type"\|report_type =' tests/test_app.py`, which returns **eleven** engagement
sites, not thirteen, and includes L90.

**Checked and genuinely not needed, so nobody spends time on them:**

- **`docs/FORM_DEPENDENCIES.md`** — it records only cross-field *dependencies* (what re-renders or
  gets dropped when another field changes). `network` gates nothing and is gated by nothing, so it
  earns no row. The planner's omission is correct.
- **`tests/test_docx_components.py`, `tests/test_docx_captions.py`, `tests/test_storage.py`** — none
  constructs a `Report` or an `Engagement`; searched all three. Step 2 lists
  `tests.test_docx_components` in its test line, which is harmless but will find nothing.
- **The seed path and the canonical merge** — `setup` renders `model_dump(mode="json", by_alias=True)`
  into `data-report` ([app/main.py](../../app/main.py#L719)) and `save_report` echoes the same dump
  ([app/main.py](../../app/main.py#L812)); `network` is absent from `reconcileCanonicalObject`'s skip
  list. Nothing to change, as the plan says.
- **`scripts/compose_component_test.py`, `scripts/generate_report.py`** — neither builds an
  `Engagement`; `generate_showcase_reports.py` is the only script that does.

**One count correction to my own round 1 report.** I said "eight app folders under `data/apps/`".
There are **14 draft files** on disk today. I re-read every one: **none carries a `network` key**,
and every `engagement` object holds the same 18 keys as the Northstar file. The conclusion is
unchanged; the number was wrong.

### 3. Do existing drafts survive? **Yes.**

The path a real draft takes, end to end:

[`Workspace.load_path`](../../app/workspace.py#L271-L300) → `read_json(path)` → two repair sweeps that
walk **only** `draft["vulnerabilities"][…]["contents"][…]["fragments"]` (the empty-`items` list fix
and the `RESOLVED_REMEDIATION` boilerplate fix) → `return Report.model_validate(draft)` at
[L300](../../app/workspace.py#L300). Neither repair reads `engagement`, and no `mode="before"`
validator on `Report` injects engagement scalars.

With `network: NetworkAccess | None = None`, an absent key takes the field default. No
`ValidationError`, so `list_reports` ([app/workspace.py](../../app/workspace.py#L120-L130)) does not
skip it and `list_legacy_reports` ([app/workspace.py](../../app/workspace.py#L132-L148)) never sees
it — which is the demotion I warned about in round 1, and **the planner's chosen shape avoids it.**
Verified against `data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json` and the
other 13.

Every draft loads, saves, and keeps every value. All 14 become *setup-incomplete* — R1, correctly
stated and correctly accepted.

### 4. The two specific questions

**Does an unchosen `<select>` write `null` or `""`? — `null`. The planner is right, and `| None` is
required.** The generic handler, [app/web/static/app.js](../../app/web/static/app.js#L1579-L1592):

```javascript
    root.querySelectorAll("[data-path]").forEach(input => {
      const [section, field] = input.dataset.path.split(".");
      input.value = report[section][field] ?? "";
      …
      input.oninput = () => { report[section][field] = input.value || (input.matches('select, input[type="date"]') ? null : ""); … };
```

For `<option value="">` the DOM `.value` is `""`, which is falsy, so the right-hand branch runs and
`input.matches('select, …')` is true — the model receives **`null`**. The seed at L1581 is its exact
mirror (`?? ""` maps `null` back onto the blank option). **A `Literal` with an empty-string member
would be wrong in both directions:** this handler never delivers `""` for a select, so the member
would be unreachable from the browser, and `if not engagement.network` would still treat it as
missing — an inhabited-but-always-invalid state. Two further consequences worth writing down:

- `oninput` fires only on interaction, so a select the tester never touches never writes at all. The
  value stays `None` from `create_report`, and `""` is not reachable from this page by any route.
- `validateSetupPage` filters with `!input?.value.trim()`
  ([app/web/static/app.js](../../app/web/static/app.js#L2716)) — DOM-side, not model-side — so it
  reads the blank option correctly with no change beyond adding the selector to `requiredMetadata`.

**Does tier 1 block both gates *and* generation, and leave the save path alone? — Yes to all three,
confirmed at four call sites.**

- `/findings`: `if not setup_is_complete(report): return RedirectResponse(f"/reports/{report_id}/setup?incomplete=setup", status_code=303)`
  ([app/main.py](../../app/main.py#L726-L727)).
- `/edit`: the identical two lines ([app/main.py](../../app/main.py#L735-L736)).
- Generation, quoted as asked — [app/docx_report.py](../../app/docx_report.py#L96-L99):

  ```python
  def generation_issues(report: Report) -> list[str]:
      """Return report-completeness issues that should block final DOCX output."""
      issues = setup_issues(report)
  ```

  and `finalized_report` turns a non-empty list into
  `raise HTTPException(422, {"message": "Complete the report before generating it", "issues": issues})`
  ([app/main.py](../../app/main.py#L517-L520)), reached by both `GET` and `POST /reports/{id}/generate`.
- **Save is untouched.** `save_report` calls `setup_input_issues(report.engagement)` directly
  ([app/main.py](../../app/main.py#L782-L789)) and never `setup_issues`. The import list at
  [app/main.py](../../app/main.py#L30) brings in `setup_input_issues` and `setup_is_complete` — **not
  `setup_issues`** — so there is no other route through which a tier 1 line could reach a save.
  `finalize_editable_import` is the same: `issues = [*setup_input_issues(report.engagement), *finding_input_issues(report)]`
  ([app/main.py](../../app/main.py#L601)), so an import with no `network` still succeeds.

### 5. What the planner should change

1. **Widen R14 and Step 2** to the four `/new`-driven browser tests above. `ready_report` is one line
   and covers one of the five affected tests, not all of them.
2. **Add R16** — the three whole-list `setup_issues` assertions at
   [tests/test_app.py](../../tests/test_app.py#L1813-L1822).
3. **Reclassify R7** from a live 500 to a latent one, and mark Step 6's `_metadata` unit assertion as
   the only verification the guard will ever receive.
4. **Name [app/docx_import.py](../../app/docx_import.py#L1105) in Step 7** and decide, out loud,
   whether retest-mode imports warn or stay silent.
5. **Add [tests/test_app.py](../../tests/test_app.py#L90)** to Step 2's enumeration.

Everything else — the field shape, the stored casing, tier 1, the no-back-fill call, the refusal to
recover on import, the braced-only token, the eight Word edits, and the ordering of Step 2 before
Step 4 — I checked against source and would not change.

### Map drift

**None.** Every claim above was read from source this round. `docs/DATA_MAP.md` still needs no edit
until the field ships, at which point the plan's Step 8 is the correct scope — with one addition:
§12's setup-completeness row should note that `setup_issues` **returns `setup_input_issues`'s output
as its tail**, because the map currently presents them as two separate rules and that is what led the
plan to describe the tiers as siblings.

## Round 2 - Planner: revised plan

**Understanding.** Add one engagement-level dropdown to Setup — *Network Access*, two options
(`Internal` / `External`), required — persist it on `Engagement`, make it block Findings/Content
navigation and generation exactly the way `segment` does, and register a `{{network}}` metadata
token so the cover-page **Application Type** cell prints it once somebody hand-edits the four
`.docx` files. The application code is roughly six lines. **The whole cost of this change is
fixtures, twins, and the gap between the code shipping and the templates being edited.** No new
route, no new page, nothing per finding.

### 0. What this revision changed, and what it held

Six corrections absorbed from the oracle's audit, plus one I am widening further:

| # | Round 1 said | Now |
|---|---|---|
| 1 | R14 breaks **one** browser test, fixed by one line in `ready_report` | R14 breaks **five**, and `ready_report` fixes **one** of them. The other four drive Setup from `/new` and walk the gate by hand. **Widened beyond the oracle: all five fail as timeouts, not assertions** — the oracle counted two; I read all four `/new` tests and every one crosses its gate through `wait_for_url`. Lines below. |
| 2 | R7 is a live 500 on the preview path | R7 is **latent**. `replace_pattern_across_text_nodes` returns before touching `replacement` when the pattern does not match, so `None` is inert while no template carries the token. It **arms the day Step 9 lands**, on a machine nobody can test on. |
| 3 | — | **R16 added**: three whole-list equality assertions on `setup_issues` break even though their rule is untouched. A class of breakage, not a one-off. |
| 4 | Step 7 warns inside `_editable_engagement` | `_editable_engagement` is the **editable** path only. `retest` is the **default** import mode and has its **own** hand-written engagement literal. The warning moves to cover both. |
| 5 | "eight app folders under `data/apps/`" | **14 draft files on disk**, none carrying a `network` key. All 14 become setup-incomplete. |
| 6 | Tiers 1 and 2 described as siblings | They are **nested**: `setup_issues` ends `return [*issues, *setup_input_issues(engagement)]` ([app/report_service.py](app/report_service.py#L776)). Tier 1 is a strict superset of tier 2. |

**Held from round 1, unchanged:** tier 1 enforcement and the stated reasons for rejecting tiers 2
and 3; verbatim `"Internal"` / `"External"` storage; `{{network}}` braced-only and never in
`PLAIN_METADATA_TOKENS`; **no** find-and-replace of the literal word `Internal`; **no** import
recovery in this change, warn instead; no back-fill, no `schema_version` bump; Step 2 (fixtures)
before Step 4 (gate); and the full *What I would not do* list.

### 1. The field, decided

```python
NetworkAccess = Literal["Internal", "External"]        # beside Segment / ReportType, app/models.py L32
network: NetworkAccess | None = None                   # in Engagement, after report_type, app/models.py L239
```

**Model shape in one line: `network: NetworkAccess | None = None` — type
`Literal["Internal", "External"] | None`, default `None`, nullable **yes**, and `""` is not a legal
value and must never be added to the `Literal`.**

That last clause is not style, it is what the oracle read out of the generic writer
([app/web/static/app.js](app/web/static/app.js#L1579-L1592)):

```javascript
input.value = report[section][field] ?? "";
input.oninput = () => { report[section][field] = input.value || (input.matches('select, input[type="date"]') ? null : ""); … };
```

The blank `<option value="">` yields DOM `.value === ""`, which is falsy, so the select branch runs
and the model receives **`null`**. The seed is its exact mirror. Three consequences:

- **`""` is unreachable from the browser for a `<select>`.** An empty-string `Literal` member would
  be inhabitable only by hand-edited JSON, and `if not engagement.network` would still call it
  missing — an inhabited-but-always-invalid state. Do not add one.
- **`oninput` fires only on interaction.** A select the tester never touches never writes at all;
  the value stays `None` from `create_report`. This is why the field must be nullable.
- **`validateSetupPage` filters DOM-side** with `!input?.value.trim()`
  ([app/web/static/app.js](app/web/static/app.js#L2716)), so it reads the blank option correctly
  with no change beyond adding the selector.

**Stored casing: verbatim display text, `"Internal"` / `"External"`.** Four grounds, unchanged from
round 1: the document prints the literal word `Internal` (coordinator verification); the only reason
`REPORT_TYPE_LABELS` exists is `report_export_filename`'s need for a human label
([app/report_service.py](app/report_service.py#L239)), and `network` is deliberately not part of the
export filename, so a `NETWORK_LABELS` map would exist solely to undo a lowercasing that served
nothing; verbatim keeps any future import recovery a membership test rather than a reverse map that
can drift; and `non_production_label`'s widening was forced by an **OTHERS** escape hatch that a
two-value closed set does not have.

No `Field(...)`, no validator, no `schema_version` bump, no `load_path` repair, no back-fill.

### 2. Enforcement tier: **tier 1, `setup_issues`** — one line

```python
if not engagement.network:
    issues.append("network access")
```

beside the `report type` check in [`setup_issues`](app/report_service.py#L746-L754). That line buys
both gates the request needs: `/findings` and `/edit` bounce to `/setup?incomplete=setup`
([app/main.py](app/main.py#L726-L736)), and `generation_issues` opens with `setup_issues(report)`
([app/docx_report.py](app/docx_report.py#L96-L98)), which `finalized_report` turns into a 422
([app/main.py](app/main.py#L517-L520)).

**The tiers are nested, not parallel — correcting round 1's framing.** `setup_issues` ends with
`return [*issues, *setup_input_issues(engagement)]` ([app/report_service.py](app/report_service.py#L776)).
Tier 2 is a *subset* of tier 1, not an alternative to it. The practical consequence for the
implementer: you cannot put a rule in tier 2 and keep it out of the Setup notice, and the reason
tier 2 needs no line here is stronger than "we chose tier 1" — anything added there would appear in
both.

**Why tier 2 (`setup_input_issues`) is wrong, stated as the failure it causes.**
[`Workspace.create_report`](app/workspace.py#L113) builds the engagement and **saves the draft before
the Setup page has rendered**, so a brand-new report exists on disk with `network=None`.
`setup_input_issues` is called from `save_report` and returns HTTP 422 `invalid_setup`
([app/main.py](app/main.py#L782-L789)). A missing-value check there would **422 the very first
autosave of every new report** and leave all 14 existing drafts unsavable — save button parked on an
error the tester cannot clear by editing the field they are editing. Tier 2 needs **no** line: the
`Literal` already rejects a malformed value at `Report.model_validate`, exactly as `segment` does.

**Why tier 3 (`generation_issues` alone) is wrong.** The tester would pass Setup, fill every finding,
write every section, and meet the missing value at the Generate click. It would also never appear in
`#setup-validation-note`, which mirrors `setup_issues`, not `generation_issues`.

### 3. Blast radius

| File | Change |
|---|---|
| [app/models.py](app/models.py#L32) | `NetworkAccess` Literal + `Engagement.network` |
| [app/report_service.py](app/report_service.py#L746) | one `setup_issues` line, string `"network access"` |
| [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7) | one `<label>` + `<select data-path="engagement.network">` with a blank first option |
| [app/web/static/app.js](app/web/static/app.js#L2714) | `validateSetupPage`'s `requiredMetadata` array — **twin A** |
| [app/web/static/app.js](app/web/static/app.js#L623) | `updateSetupValidationNotice` — **twin B, an independent implementation of the same rule** |
| [app/docx_report.py](app/docx_report.py#L263) | one `_metadata` key, `engagement.network or "N/A"` |
| [app/docx_import.py](app/docx_import.py#L1105) | **newly identified** — the `retest` engagement literal, the **default** import mode |
| [app/docx_import.py](app/docx_import.py#L569) | `_editable_engagement`, the editable path; **no** `network` key, **no** `restored_engagement` entry |
| [tests/test_browser.py](tests/test_browser.py#L56) | `ready_report` one line, **plus four `/new`-driven tests**, plus a new required-field test |
| [tests/test_app.py](tests/test_app.py#L90) | **11** hand-built engagements (not 13), including L90 |
| [tests/test_app.py](tests/test_app.py#L1813) | three whole-list `setup_issues` equality assertions — **R16** |
| [tests/test_docx.py](tests/test_docx.py#L1016) | 7 of 8 `Engagement(...)` sites (L300 stays incomplete deliberately) |
| [tests/test_docx_import.py](tests/test_docx_import.py#L66) | one site |
| [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405) | one kwarg — **not covered by any suite** |
| `docs/DATA_MAP.md`, `docs/DOCX_TEMPLATE.md` | contracts, see Step 8 |

**Checked and confirmed not needed, so nobody spends time on them:** `docs/FORM_DEPENDENCIES.md`
(records cross-field dependencies only; `network` gates nothing and is gated by nothing),
`tests/test_docx_components.py`, `tests/test_docx_captions.py`, `tests/test_storage.py` (none
constructs an `Engagement`), `scripts/compose_component_test.py`, `scripts/generate_report.py`,
`updateReadinessPanel` (deliberately mirrors only finding-level rules from `generation_issues`, never
the setup block), and the seed/canonical-merge path (`network` is absent from
`reconcileCanonicalObject`'s skip list, so it reconciles like any scalar).

### 4. Data risks

| # | Failure mode | Verdict | Reasoning and control |
|---|---|---|---|
| **R1** | **Existing drafts on disk** | **RISK — accepted, not fixed** | **14 draft files**, none with a `network` key. They load, save and keep every value (nullable + default → no `ValidationError` → no `list_reports` skip, no `list_legacy_reports` demotion). But **100% become setup-incomplete on first load**: `/findings` and `/edit` bounce to Setup and generation 422s until a value is picked. Control: release note + `docs/DATA_MAP.md` §13. Deliberately **no** `load_path` back-fill. |
| **R2** | **First-autosave path** | clear **because of two deliberate choices** | `create_report` saves before the page renders. Clear only while the field stays `\| None = None` *and* the rule stays in tier 1. Control: Step 1's test creates a report and saves it untouched. |
| **R3** | **Stale write / `saved_at`** | clear | No new mutation path. The value rides the existing whole-report `PUT`, which already carries `saved_at`; nothing reads-then-writes outside `Workspace._locked`. |
| **R4** | **Python/JavaScript twins drifting** | **RISK** | Three hand-maintained sites for one rule: the `<option>` list vs the `Literal`, and `setup_issues` vs **two independent** JS implementations. Adding to one JS site only makes Next refuse with a notice that lists nothing. The issue string must be byte-identical across all three. Control: Step 5. |
| **R5** | **DOCX import lands `None`** | **RISK — widened** | **Two** hand-written engagement literals, not one. `_editable_engagement` ([app/docx_import.py](app/docx_import.py#L569)) covers `editable`; the dict at [app/docx_import.py](app/docx_import.py#L1105-L1115) covers `retest`, which is the **default** (`mode = docx_mode or "retest"`, [app/main.py](app/main.py#L635)). Round 1's warning would never have fired on the commoner path. And recovery is the trap: both cover blocks hold the same hardcoded `Internal`, `_labelled_value` de-duplicates through a set and returns it **without raising**, for every document generated from today's templates whatever the tester chose. Control: **do not recover.** Leave unset, warn **once for both modes**, keep `"network access"` out of `restored_engagement`. |
| **R6** | **Generation on templates without the token** | clear | `_replace_metadata` no-ops on an absent token by documented design — `mobile-thick` / `thick-mobile` already ships this way ([app/docx_report.py](app/docx_report.py#L290-L292)). Output bit-for-bit identical on all four templates. |
| **R7** | **`None` reaching the replacer** | **RISK — latent, arms at Step 9** | Downgraded from round 1. [`replace_pattern_across_text_nodes`](app/docx_components.py#L402-L441) does `if not match: return` **before** the `prefix + replacement + suffix` concatenation, so on today's templates a `None` is inert — `allow_incomplete` preview and `scripts/generate_report.py --allow-incomplete` cannot 500. The `TypeError` (a **500, not a 422**) becomes reachable the moment a template carries `{{network}}`. Control: `engagement.network or "N/A"` in `_metadata`, and **Step 6's unit assertion is the only verification this guard will ever receive** — see below. |
| **R8** | **Schema break / one-way door** | **RISK, permanent** | `model_config` appears nowhere in [app/models.py](app/models.py), so Pydantic's default `extra="ignore"` deletes the key with no error. A bundle or draft carrying `network` opened by a build without the field **loses it silently on the next save**. Control: once shipped the field stays declared forever even if abandoned — recorded in `docs/DATA_MAP.md` §13 beside `content_offer_resolved`. |
| **R9** | **Navigation trap** | clear | The gate redirects **to** `/setup`, which has no gate ([app/main.py](app/main.py#L716-L719)). The control that satisfies the requirement is on the page the user is sent to. No loop. |
| **R10** | **Derived-state fight** | clear | Tester-authored, never derived. `provision_report` iterates `report.vulnerabilities` only and never reads `engagement` ([app/main.py](app/main.py#L262-L267)). |
| **R11** | **Orphan reference / silent stranding** | clear | A two-value scalar with no dependent data. Changing it strands nothing and purges nothing, so **no confirmation dialog is owed**. |
| **R12** | **Backup exhaustion** | clear **conditional on R1** | True only while no back-fill exists. A back-fill would write on load and again on the tester's first edit, consuming the single `.bak` level. |
| **R13** | **Request/response asymmetry** | clear | Symmetric; `save_report` echoes it in the canonical dump ([app/main.py](app/main.py#L812-L813)). Not a `scope_text`-style request-only field. |
| **R14** | **Browser tests blocked** | **RISK — five tests, and every one is a timeout** | See below. Round 1 named one and over-credited `ready_report`. |
| **R15** | **Named script blocker** | **RISK — no suite catches it** | [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405) renders through `generation_issues`. Every showcase render raises the moment the gate lands, and nothing in `tests/` covers the script. Control: Step 2. |
| **R16** | **Whole-list equality assertions on `setup_issues`** | **RISK — new** | See below. |

**R7, restated because the downgrade changes where the risk lives, not whether it exists.** The
guard is correct and mandatory. What changed is that **nothing can demonstrate it on today's
templates** — the code path that would raise is unreachable until the Word edit lands, and the Word
edit can only be verified on Windows with Word. Therefore:

> **Step 6's unit assertion — `_metadata(report)["network"] == "N/A"` when `network is None` — is
> the only verification this guard will ever receive before it arms.** It is load-bearing, not a
> nicety, and it must not be dropped as "obvious". If Step 6 ships without it, the first time anyone
> learns whether the guard works is a 500 on a Windows machine after the templates changed.

**R14 in full — five tests, named, with what each needs.** Round 1 claimed `ready_report` covered
the field. It covers **one** of the five.

| Test | Drives Setup from | Crosses the gate at | Failure | Needs |
|---|---|---|---|---|
| `test_authoring_workflow_autosave_fragments_and_manager_grouping` | `/new` ([L174](tests/test_browser.py#L174)) | `wait_for_url("**/reports/*/findings")` ([L206](tests/test_browser.py#L206)) | **timeout** | `select_option` before the Next click at L205 |
| `test_segment_and_report_type_are_required` | `/new` ([L460](tests/test_browser.py#L460)) | `wait_for_url("**/findings")` ([L477](tests/test_browser.py#L477)) | **timeout** | `select_option` after the two existing selections, before the final Next. Its `assertIn` on the notice still passes, so the failure surfaces only at the wait |
| `test_a_second_component_row_lands_as_its_own_target` | `/new` ([L792](tests/test_browser.py#L792)) | `wait_for_url("**/findings")` ([L810](tests/test_browser.py#L810)) | **timeout** | `select_option` before `#next` at L809 |
| `test_a_component_needs_a_description_before_setup_will_let_you_leave` | `/new` ([L920](tests/test_browser.py#L920)) | `wait_for_url("**/findings")` ([L959](tests/test_browser.py#L959)) | **timeout** | `select_option` before the final `#next` at L958. Its three earlier `#next` clicks are *expected* to be blocked and its `assertIn` notice checks still pass |
| `test_browser_readiness_verdict_matches_server_generation_issues` | `ready_report` ([L3781](tests/test_browser.py#L3781)) | `/edit` redirect branch checks `"/findings" in url` | **timeout** at `wait_for_selector("#issue-count")` | the one `ready_report` line, which covers all 122 server-side call sites |

**I am widening the oracle here, on evidence from the lines it cited.** The verdict says two of the
four `/new` tests hang; I read all four and **every one crosses its gate through `wait_for_url`**, so
all four hang. With the fifth's `wait_for_selector` timeout that makes **five timeouts and zero
clean assertion failures**. That matters operationally: whoever runs `tests.test_browser` after
Step 4 without Step 2 sees five tests sitting at the Playwright default timeout, which reads as
environment flake rather than as "the gate you just added is doing its job". Say it in the commit.

Note the irony the oracle spotted: `test_segment_and_report_type_are_required` is the test Step 5 is
modelled on **and** one of the tests Step 4 breaks. The new `test_network_access_is_required` does
not replace it; both must exist and both must pass.

**R16 in full — a class of breakage, not three lines.** Three assertions compare the **whole**
`setup_issues` list:

```python
self.assertEqual(report_service.setup_issues(blank), ['production Thick Client description for "Acme.exe"'])
```

[tests/test_app.py](tests/test_app.py#L1813), same shape at [L1817](tests/test_app.py#L1817), and
`assertEqual(..., [])` at [L1822](tests/test_app.py#L1822). Their fixture `_component_scope_report`
([tests/test_app.py](tests/test_app.py#L1746)) is inside Step 2's engagement enumeration, so fixing
the fixture fixes them — **but only if the implementer notices what the assertion compares.** A
reader skimming Step 2 patches the engagement dict and moves on.

The general fact, worth writing into `docs/DATA_MAP.md` §12: **a whole-list equality assertion on
`setup_issues` breaks for everyone who ever adds a Setup rule, not just this change.** Three exist
today. The cheap fix here is the fixture; the cheap fix *in general* is `assertIn` /
`assertNotIn` for tests whose subject is a different rule. Converting them is **out of scope for
this change** — I am naming the class, not widening the diff.

### 5. The template asymmetry, spelled out

**Today, with un-edited templates.** `_metadata` supplies `network`; `_replace_metadata` compiles
`\{\{\s*network\s*\}\}`, matches nothing, returns. **Generation output is byte-identical to
today's.** What the tester sees: they pick *External*, pass the gate, generate — and the cover page
still reads **`Internal`**, in both blocks, because it is hardcoded template prose. **For the
duration of the gap, a chosen value of `External` produces a document that contradicts it.** That is
a wrong document, not a missing feature — hence Q1.

**Once the templates are edited.** Both cover `Internal` cells become `{{network}}`; the chosen value
prints; **no further code change**. Split Word runs are handled, the first touched run's formatting
wins, and `txbxContent` is reached because `_replace_metadata` iterates `w:p` via lxml `.iter()`.

**If a template is edited before the code lands.** `_unresolved_placeholders` raises and
`test_every_shipped_template_renders_without_unresolved_placeholders` goes red on all four subtests —
loud, immediate, correctly aimed. **So: code first, templates second.**

**Eight edits, not four.** `Application Type` / `Internal` appears **twice per template**, once
before `Prepared By` and once before `Table of Contents`, in all four files. Editing only one
means the second block keeps printing a hardcoded `Internal` on a cover that now also prints the
real value — two contradictory statements on one page — and it poisons any future import recovery,
because `_labelled_value` **raises on two differing values for one label** and would reject the
entire import. Both blocks move together: that is a correctness requirement, not tidiness.

**Two things the template editor must not do**, both on evidence rather than caution: no
document-wide find-and-replace of `Internal` (the third occurrence is the Remediation Timelines
column header sitting beside `External`; with `External` chosen that policy row becomes
`External | External` in a document delivered as evidence of a standard being applied), and
**`network` must never join `PLAIN_METADATA_TOKENS`** (the bare word appears three times in body
prose — *"…must reside on the same network…"* — which would render as *"…the same Internal…"*).
Braced-only is the only correct form.

**Verification is a Word-only item.** Generation needs Windows with Word, so nobody on a Mac can
confirm the cover renders correctly. Step 9 assigns it.

### 6. Open questions for the user

**Q1 — What happens during the gap between the code shipping and the eight template cells being
edited?** During that window a tester who picks **External** generates a report whose cover page
says **Internal**, because the word is still hardcoded prose. Options: **(a)** ship the code now and
treat the Word edit as an immediate follow-up, accepting that any report generated in between is
wrong on the cover if `External` was chosen; **(b)** hold the Setup field out of the release until
the four `.docx` files are edited, so the dropdown and the printed value arrive together; **(c)**
ship the code and block generation while `network == "External"` until the token is present.
**Recommendation: (b) if any real report will be generated before the templates are edited,
otherwise (a).** (c) is rejected — it encodes a template's state into a validation rule that would
have to be found and removed later. This is the only question that changes what a reader of a
delivered report sees.

**Q2 — Nullable-and-required, or defaulted?** **(a)** `network: NetworkAccess | None = None` plus the
`setup_issues` line — genuinely required, and **all 14 reports on disk become setup-incomplete on
their next open** until a value is picked (Findings/Content bounce to Setup, generation 422s).
**(b)** `network: NetworkAccess = "Internal"` — no draft is ever disturbed, nothing to re-pick, but
a value **nobody chose** is stored in every report and printed on every cover once the templates
carry the token, and the dropdown is then not really required at all. **Recommendation: (a).** The
field's entire purpose is to record a fact about the engagement; a default silently asserts that
fact on the tester's behalf, and `Internal` being the commoner answer is exactly what makes the
wrong ones invisible. The cost is one dropdown per existing report, once.

**Decided rather than asked, and recorded here so it is not mistaken for an omission.** Whether
`retest`-mode imports warn: **yes, both modes warn**, one `warnings.append` placed after the mode
branch in `parse_report_docx` rather than inside `_editable_engagement`. Retest is the default mode
and its warnings already surface through the `elif warnings:` branch
([app/docx_import.py](app/docx_import.py#L1166)); a silent `None` on the commoner path is the one
outcome R5 exists to prevent. And whether to recover `network` from a finished DOCX later: **a
separate plan, gated on the templates carrying the token in both blocks** — not this change, and not
never.

### 7. Plan

Ordered so the app is never left in a state where a save or a suite fails. **Fixtures move before
the gate** — reversing Steps 2 and 4 leaves five browser tests timing out, the whole DOCX suite red,
and the showcase script broken, for no gain.

- [ ] **Step 1 — Declare the field.** [app/models.py](app/models.py#L32): add
  `NetworkAccess = Literal["Internal", "External"]` beside `Segment`/`ReportType`, and
  `network: NetworkAccess | None = None` to `Engagement` after `report_type`. No `Field(...)`, no
  validator, no `schema_version` bump, **no `load_path` repair, no back-fill.** Do not add `""` to
  the `Literal` (§1).
  *Test:* `tests/test_app.py` — a new report saves untouched, and an existing `draft.json` with no
  `network` key still loads and round-trips with every other value intact.
  *Invariant:* all 14 drafts on disk load and save unchanged, and the first autosave of a new report
  succeeds with `network` absent (**R1**, **R2**).

- [ ] **Step 2 — Unblock every fixture and the script, before the gate exists.** Five groups:
  1. [tests/test_browser.py](tests/test_browser.py#L56) `ready_report` — one line,
     `report.engagement.network = "Internal"`. Covers all 122 server-side call sites and fixes
     `test_browser_readiness_verdict_matches_server_generation_issues`
     ([L3781](tests/test_browser.py#L3781)).
  2. **The four `/new`-driven browser tests** — a `select_option` before each one's final Next:
     [L205](tests/test_browser.py#L205), [L477](tests/test_browser.py#L477),
     [L809](tests/test_browser.py#L809), [L958](tests/test_browser.py#L958). **All four hang rather
     than fail** if missed (**R14**).
  3. [tests/test_app.py](tests/test_app.py#L90) — **11** hand-built engagements, not 13. Enumerate
     with `grep -n '"report_type"\|report_type =' tests/test_app.py` rather than working from a
     copied line list; L90 (`test_report_management_lifecycle`) is absent from round 1's list.
     Three of these sites are the **R16** whole-list assertions at
     [L1813](tests/test_app.py#L1813), [L1817](tests/test_app.py#L1817) and
     [L1822](tests/test_app.py#L1822) — fixing the shared `_component_scope_report` fixture
     ([L1746](tests/test_app.py#L1746)) fixes all three, but check what each assertion compares
     before assuming it.
  4. [tests/test_docx.py](tests/test_docx.py#L1016) — 7 of 8 `Engagement(...)` sites.
     `_component_report` covers both template tests in one edit;
     `Engagement(app_name="Northstar Banking")` at L300 **stays incomplete**, it is the deliberate
     fixture for `test_template_without_the_findings_anchor_is_rejected`.
     [tests/test_docx_import.py](tests/test_docx_import.py#L66) — one site.
  5. [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L405) — add
     `network="Internal"` (**R15**). Nothing in `tests/` covers this script; it is the one item here
     no suite will tell you about.
  *Test:* `tests.test_docx`, `tests.test_docx_import`, `tests.test_browser`, and the named
  `tests/test_app.py` setup tests — green before and after, since the field is not yet required.
  (Round 1 listed `tests.test_docx_components`; it constructs no `Engagement` and finds nothing.)
  *Invariant:* no fixture that renders through `generation_issues` or walks the Setup gate lacks the
  field when Step 4 lands.

- [ ] **Step 3 — Add the control.**
  [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L7): a
  `<label>Network Access<select data-path="engagement.network"><option value="">Select network
  access</option><option value="Internal">Internal</option><option value="External">External</option></select></label>`
  in the Application card, after **Report Type**. **No JavaScript:** the `[data-path]` loop seeds
  `null → ""` onto the blank option and writes back `"" → null`. `setupSectionSummary`'s `N of M`
  counter updates itself and no test pins the number.
  *Test:* covered by Step 5's browser test.
  *Invariant:* an unchosen select persists as `null`, never `""` (§1); the control renders before it
  is required, so no user can meet a gate they cannot satisfy. **This is a visual change to the
  Setup grid — screenshot the Application card and compare against the current layout before calling
  it done, per the repo's visual rule.**

- [ ] **Step 4 — Close the gate, on all three surfaces in one commit.**
  [app/report_service.py](app/report_service.py#L746) `setup_issues`:
  `if not engagement.network: issues.append("network access")` after the `report type` check.
  [app/web/static/app.js](app/web/static/app.js#L2714) `validateSetupPage` — add
  `root.querySelector('[data-path="engagement.network"]')` to `requiredMetadata`.
  [app/web/static/app.js](app/web/static/app.js#L623) `updateSetupValidationNotice` — add
  `if (!root.querySelector('[data-path="engagement.network"]')?.value) missing.push("network access");`.
  The string is `"network access"` in both languages, byte-identical.
  *Test:* Step 5.
  *Invariant:* **R4** — the gate and the notice never disagree. Nothing is added to
  `setup_input_issues` (**R2**; and note the tiers are nested, so a tier 2 line would appear here
  anyway), and nothing to `updateReadinessPanel`, which deliberately does not mirror `setup_issues`.

- [ ] **Step 5 — Prove the requirement, in the shape the existing one uses.**
  New `tests/test_browser.py::test_network_access_is_required`, modelled on
  [`test_segment_and_report_type_are_required`](tests/test_browser.py#L458-L477): assert the exact
  option text `["Select network access", "Internal", "External"]`, fill everything else, click
  **Next: Findings**, assert the URL is still `/setup` and `#setup-validation-note` contains
  `network access`, then select `Internal` and assert Next passes. Add a `setup_issues` assertion in
  `tests/test_app.py` for the server half — **membership, not whole-list equality** (**R16**).
  *Test:* `tests.test_browser` (this test plus the five from **R14**), and the named
  `tests/test_app.py` setup tests.
  *Invariant:* the option list, the gate and the notice wording are pinned together, so **R4** fails
  loudly instead of drifting.

- [ ] **Step 6 — Register the token, and assert the guard that nothing else will ever exercise.**
  [app/docx_report.py](app/docx_report.py#L263) `_metadata`: `"network": engagement.network or "N/A"`,
  beside `"segment"`. **Nothing else** — not `PLAIN_METADATA_TOKENS`, no `_find_table`, no
  find-and-replace of `Internal`.
  *Test:* `tests.test_docx` — `test_every_shipped_template_renders_without_unresolved_placeholders`
  still passes on all four templates (proving the no-op, **R6**), **plus a unit assertion that
  `_metadata(report)["network"] == "N/A"` when `network is None`.** That assertion is not optional
  and not a nicety: per **R7** the `TypeError` it guards is unreachable on today's templates and
  becomes reachable only at Step 9, on a Windows machine, so **this assertion is the guard's only
  verification for the entire life of the gap.**
  *Invariant:* the replacer never receives `None`, including on the `allow_incomplete` preview path
  and `scripts/generate_report.py --allow-incomplete`. Output on today's templates is byte-identical.

- [ ] **Step 7 — Tell the truth on editable import *and* retest import.** `parse_report_docx` builds
  the engagement **twice**: the `retest` literal at
  [app/docx_import.py](app/docx_import.py#L1105-L1115) and `_editable_engagement` at
  [app/docx_import.py](app/docx_import.py#L569) — and `retest` is the **default**
  (`mode = docx_mode or "retest"`, [app/main.py](app/main.py#L635)). Append the warning **once,
  after the `if mode == "editable":` branch**, so it fires on both paths: *"Network access was not
  read from the DOCX; choose Internal or External in Setup."* Retest-mode warnings surface through
  the `elif warnings:` branch ([app/docx_import.py](app/docx_import.py#L1166)). Add **no** `network`
  key to either literal and **no** `"network access"` entry to `restored_engagement`
  ([app/docx_import.py](app/docx_import.py#L1158-L1161)) — that list is shown to the user and a false
  entry is worse than a missing one. `finalize_editable_import` stays as it is: it gates on tier 2
  only ([app/main.py](app/main.py#L601)), so the import still succeeds and lands setup-incomplete,
  which is correct.
  *Test:* `tests.test_docx_import` — **two** cases, one per mode: the import succeeds, `network` is
  `None`, and the warning is in `summary["warnings"]`. One case would pass while the default path
  stayed silent, which is exactly the round 1 mistake.
  *Invariant:* **R5** — no value is ever fabricated into a field that then looks filled, and no
  import path drops the field silently.

- [ ] **Step 8 — Move the documentation contracts, in this same change.**
  `docs/DATA_MAP.md`: the `Engagement` field row in §6; a `setup completeness` twin entry in §12
  naming **all three** sites **and** noting that `setup_issues` returns `setup_input_issues`'s output
  as its tail (the map presents them as separate rules, which is what produced round 1's
  sibling framing); and a §13 entry carrying **R1** (all 14 drafts become setup-incomplete, no
  back-fill, and why), **R8** (`extra="ignore"` — the field must stay declared forever) and **R16**
  (whole-list `setup_issues` assertions break for every future Setup rule). Required by
  `.github/instructions/data-layer.instructions.md`, which applies to `app/models.py`,
  `app/report_service.py` and `app/web/static/app.js`. `docs/DOCX_TEMPLATE.md`: a
  `network → Internal or External network access` row in the *Engagement fields* table, marked
  **braced-only**, plus a short note that the token is registered ahead of the templates
  deliberately so the next reader does not take it for dead code. This plan file: status to
  `shipped`, date, commit, and the deviations paragraph.
  *Test:* none — documentation only.
  *Invariant:* no code fact ships without the contract that describes it.

- [ ] **Step 9 — Hand over the Word edit (not a code step).** In each of `resources/MAIN.docx`,
  `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx`, `MAIN_THICK_MOBILE_ASIA.docx`, replace **both**
  `Internal` value cells beside `Application Type` — the block before `Prepared By` **and** the block
  before `Table of Contents` — with `{{network}}`, styled like the word it replaces. **Eight edits.**
  Do **not** touch the `Internal` in the Remediation Timelines header. Then render one report per
  template on a Windows machine with Word and look at the first page — **this is also the first
  moment R7's `or "N/A"` guard is on a live code path**, so a preview render with `network` unset
  belongs in the same session.
  *Test:* `tests.test_docx` —
  `test_every_shipped_template_renders_without_unresolved_placeholders` is the guard that the edit
  did not outrun the code; run it **after** Step 6 is merged, never before.
  *Invariant:* both occurrences move together, or the cover contradicts itself and future import
  recovery is poisoned.

### 8. What I would not do

- **Back-fill `network` in `load_path` so existing drafts stay complete.** It writes a value nobody
  chose into all 14 reports on disk, on *load*, burning the single `draft.bak.json` level before the
  tester has typed anything — and it prints on the cover as if it were an assertion about the
  engagement. The honest cost is one dropdown per existing report (**R1**, Q2).
- **Find-and-replace the literal word `Internal`.** Rejected on evidence: the third occurrence is a
  reproduced Manulife policy table header, and with `External` chosen that row becomes
  `External | External` in a document delivered as evidence of a standard being applied. Nothing in
  the pipeline would catch it — a legal replacement producing a legal document.
- **Add `network` to `PLAIN_METADATA_TOKENS`.** The bare word appears three times in body prose;
  every existing member of that set is hyphenated and report-specific for exactly this reason.
- **Recover the value on DOCX import now.** Both cover blocks read `Internal` on every document
  today, and `_labelled_value` de-duplicates identical values without raising — so recovery would
  succeed, look right, and be wrong for every tester who chose `External` (**R5**).
- **Put the rule in `setup_input_issues` because "it is a save-time validation".** It 422s the first
  autosave of every new report and makes every existing draft unsavable — and since the tiers are
  nested, it would land in the Setup notice anyway, so it buys nothing it does not already have.
- **Convert the three whole-list `setup_issues` assertions to membership while I am in there.**
  Correct in general, out of scope here; **R16** names the class and §12 records it, which is what a
  future Setup rule actually needs.
- **Bump `schema_version`.** Nothing branches on it, and every draft on disk would stop loading.
- **Fold `network` into `report_export_filename`.** It would rename every export, and nothing asked
  for that.
- **Add `""` to the `NetworkAccess` Literal "so the blank option has a value".** The generic
  `[data-path]` writer never delivers `""` for a select, so the member would be unreachable from the
  browser while `if not engagement.network` still called it missing.

## Answers

Two questions were put to the user, one at a time. Both were answered on 2026-09-21.

### Q1 — the gap before the Word templates are edited

**Asked:** the four templates hardcode `Internal` on the cover and carry no `{{network}}` token, so
until someone edits them by hand a tester who picks `External` still generates a cover reading
`Internal`. Ship anyway, hold the field, or block generation while `External` is selected?

**Answered: (a) — ship the code now, edit the templates as an immediate follow-up.**

Accepted consequence: between this change landing and the Word edit, **every** generated cover prints
the hardcoded `Internal`, whatever the tester chose. This is invisible in the app — the dropdown will
look like it is working, because it saves correctly and the renderer's silence on an absent token is
deliberate, existing behaviour. Option (c) was rejected by the planner and the coordinator alike: it
would encode today's template state into a validation rule nobody would remember to remove.

### Q2 — default value, and what happens to the 14 drafts on disk

**Asked:** make the field genuinely required with no default (all 14 existing drafts become
setup-incomplete until someone picks a value), or default every report to `Internal` (nothing is
disturbed, but an unchosen value prints on every cover)?

**Answered: (b) — default every report to `Internal`.** This went against the recommendation of both
the planner and the coordinator, and it is the user's call to make. It is recorded here with its
consequences rather than re-argued.

**This answer is the single largest influence on the agreed plan, and it cuts the work roughly in
half.** A field that always holds a valid value can never be empty, so:

| Round 2 step | Fate under (b) | Why |
|---|---|---|
| Step 4 — close the Setup gate on three surfaces | **dropped entirely** | `if not engagement.network` can never be true, so the `setup_issues` line, the `validateSetupPage` entry and the `updateSetupValidationNotice` entry would all be dead code |
| Step 2 — repair every fixture and the showcase script | **dropped entirely** | nothing becomes incomplete, so the 11 `tests/test_app.py` sites, the 8 `tests/test_docx.py` sites, `tests/test_docx_import.py`, `ready_report` and `scripts/generate_showcase_reports.py` all keep passing untouched |
| **R14** — five browser tests, four of which *hang* | **evaporates** | no new gate to walk |
| **R16** — three whole-list `setup_issues` assertions | **evaporates** | `setup_issues` gains no line |
| **R4** — gate and notice drifting apart | **evaporates** | no Python/JavaScript completeness twin is created at all |
| **R7** — the `None` reaching the replacer | **evaporates** | the field is non-nullable, so `_metadata` needs no `or "N/A"` guard and no unit assertion to verify one |

What survives from Q2 is one genuinely new risk, which the user has accepted:

> **Accepted residual risk — the invisible default.** A tester running an **External** engagement who
> never notices the new dropdown will generate a cover that reads `Internal`, and nothing in the app
> will say so. This is precisely the failure the rejected option (a) was designed to prevent, and
> there is no automatic mitigation: the code cannot distinguish "deliberately chose Internal" from
> "never looked at the field". The only mitigation available is **placement** — the control must be
> visibly present in the Application card, not tucked below the fold (Step 2 below).

**"Required" is satisfied structurally, not by a validation rule.** The user asked for a required
dropdown; under (b) it is required in the sense that it can never hold an empty or absent value. The
control therefore ships **without** a blank `<option value="">`, because a blank option is the only
way a user could put the field into a state the model rejects.

## Agreed plan

Add `Engagement.network`, a two-option value (`Internal` / `External`) defaulting to `Internal`,
edited from a dropdown in the Setup Application card and printed into the Word cover page through a
new braced `{{network}}` token. The token is registered in code **now**, ahead of the templates
carrying it (Q1a); the renderer's existing silence on an absent token means generation is
byte-identical until the `.docx` files are edited by hand.

The field is **not** wired into Setup completeness, because with a default it can never be empty
(Q2b). No navigation gate changes, no save-time validation changes, no Python/JavaScript twin is
created, and no existing draft, fixture, test or script needs repair.

Three decisions carried from the rounds above, each on evidence rather than caution:

- **Braced token only.** `network` is **not** added to `PLAIN_METADATA_TOKENS` — the bare word
  already appears three times in body prose ("…must reside on the same network…"), so a plain-text
  token would corrupt a sentence in every report.
- **No find-and-replace of the literal `Internal`.** Verified: the word appears **three** times per
  template — twice on the cover and once as a column header in the Remediation Timelines policy
  table, beside `External`. A document-wide replacement would rewrite that policy row to
  `External | External` and nothing in the pipeline would catch it.
- **Import does not recover the value.** `_labelled_value` collapses candidates through a set and
  returns the single member without error, so on today's covers it would return `Internal` for every
  import including `External` engagements. Deferred; a warning is emitted instead.

- [x] **Step 1 — Declare the field.** [app/models.py](../../app/models.py): add
  `NetworkAccess = Literal["Internal", "External"]` beside `Segment`/`ReportType`, and
  `network: NetworkAccess = "Internal"` to `Engagement` immediately after `report_type`. Non-nullable
  and no `""` member. No `Field(...)`, no validator, no `schema_version` bump, no `load_path` repair.
  *Test:* `tests/test_app.py` — a `draft.json` on disk with no `network` key loads, reports
  `"Internal"`, and round-trips with every other value intact; a report saved as `"External"` reloads
  as `"External"`.
  *Invariant:* all 14 drafts on disk load and save unchanged, and no existing fixture, test or script
  becomes invalid — the default is what buys that.

- [x] **Step 2 — Add the control.**
  [app/web/templates/page1_setup.html](../../app/web/templates/page1_setup.html): a
  `<select data-path="engagement.network">` with exactly two options, `Internal` and `External`, in
  the **Application card directly after Report Type**. **No blank option** — the field can never be
  empty, and a blank option is the only way to reach a value the model rejects. No JavaScript: the
  existing generic `[data-path]` loop seeds and writes back a plain string select without help.
  *Test:* new `tests/test_browser.py::test_network_access_defaults_to_internal_and_persists_external`
  — assert the option text is exactly `["Internal", "External"]`, that a fresh report shows
  `Internal` selected, then choose `External`, save, reload, and assert it survives.
  *Invariant:* the control can only ever hold a value the `Literal` accepts, so it cannot 422 a save.
  **This is a visual change to the Setup grid — screenshot the Application card and compare it
  against the current layout before calling it done, per the repo's visual rule.** Placement is the
  only mitigation the accepted residual risk above has, so it must be plainly visible.

- [x] **Step 3 — Register the token.** [app/docx_report.py](../../app/docx_report.py) `_metadata`:
  add `"network": engagement.network` beside `"segment"`. **Nothing else** — not
  `PLAIN_METADATA_TOKENS`, no `_find_table`, no find-and-replace of `Internal`. No `or "N/A"` guard
  is needed or wanted: the field is non-nullable, so the `None` that guard existed for is now
  unreachable by construction.
  *Test:* `tests.test_docx` — `test_every_shipped_template_renders_without_unresolved_placeholders`
  still passes on all four templates, proving the absent token is a silent no-op; plus a unit
  assertion that `_metadata(report)["network"]` is `"Internal"` by default and `"External"` once set.
  *Invariant:* output on today's un-edited templates is byte-identical, and the value is correct the
  moment the templates gain the token.

- [x] **Step 4 — Tell the truth on both import paths.** `parse_report_docx` builds the engagement
  **twice**: the `retest` literal at [app/docx_import.py](../../app/docx_import.py#L1105) and
  `_editable_engagement` at [app/docx_import.py](../../app/docx_import.py#L569) — and `retest` is the
  **default** mode (`mode = docx_mode or "retest"`). Append the warning **once, after the
  `if mode == "editable":` branch**, so it fires on both: *"Network access was not read from the
  DOCX; it defaults to Internal — change it in Setup if this engagement was External."* Add **no**
  `network` key to either literal and **no** entry to `restored_engagement`, which is shown to the
  user and must not claim a field it did not recover. This warning matters more under Q2b than it
  would have under a blank default: there is no empty state left to signal "unknown".
  *Test:* `tests.test_docx_import` — **two** cases, one per mode: the import succeeds, `network` is
  `"Internal"`, and the warning appears in `summary["warnings"]`. One case would pass while the
  default path stayed silent.
  *Invariant:* no import path fabricates a recovered value or drops the field silently.

- [x] **Step 5 — Move the documentation contracts, in the same change.** `docs/DATA_MAP.md`: the
  `Engagement` field row in §6, recording the default and that it is deliberately **not** part of
  Setup completeness; a §13 sharp-edge entry for the invisible default named in *Answers* above.
  `docs/DOCX_TEMPLATE.md`: a row in the *Engagement fields* table for `{{network}}`, noting it is
  braced-only and **why**, and that the code registers it ahead of the templates on purpose.
  *Test:* none — documentation only, per the repo scope map.
  *Invariant:* the contracts describe the code that shipped, including the deliberate gap.

- [ ] **Step 6 — Hand over the Word edit (not a code step).** In each of `resources/MAIN.docx`,
  `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx` and `MAIN_THICK_MOBILE_ASIA.docx`, replace the cover
  value cell reading `Internal` with `{{network}}`. **That is 8 cells, not 4: the cover block occurs
  twice in every template** (verified — paragraphs 10-13 and 18-21 in `MAIN.docx`). Do **not** touch
  the third `Internal`, the Remediation Timelines column header. Until this lands, Q1a's accepted
  consequence stands and every cover prints `Internal`.
  *Test:* after the edit, `tests.test_docx` unresolved-placeholder test on all four templates, and
  one render asserting the cover prints `External` for a report set to `External`.
  *Invariant:* both cover blocks carry the token. If only one is edited they disagree, and a future
  import recovery would raise `ReportImportError` on conflicting values for the same label.
