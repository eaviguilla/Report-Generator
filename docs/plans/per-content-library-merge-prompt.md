# Per-content library merge prompt

> **Status:** shipped · 2026-09-15 · `acd047a`

## Request
For data consistency fixes:

when a finding is already initiated. meaning the contents are already edited and filled, then changed in name to a vuln library finding, this will prompt the user to retain the content data or use the saved in library one right. what if we did not do that. we did not prompt the user to change the contents in the contents page. BUT prompts them per content, meaning one prompt for the description, one prompt in the recommended remediation, to retain the fragments in the content, or replace with what is saved in the vuln library, or add the fragments from the vuln db to the current one.

so this will work like how the POC works.

## Round 1 - Oracle: how it works today

# Report: Per-Section Library Content Prompts (Modeled on the Proof-of-Concept Offer)

## 1. How the current "apply library entry to an existing finding" flow works today

This flow is **entirely client-side** — there is no server route for "apply a library entry to an existing finding." The only server route touching the library, `insert_library` ([app/main.py](../../app/main.py#L711-L729)), creates a **brand-new** `Vulnerability` and appends it to the report; it is never called for an existing finding.

The existing-finding path lives in [app/web/static/app.js](../../app/web/static/app.js#L1370-L1397):

- **Trigger:** the finding-row title `<input>` is a combobox over the library (app.js#L1595, the row search-results click handler) and also fires on plain `onchange` when the typed title exactly matches a library entry's title (app.js#L1598-L1603). Both call `replaceFromLibrary(finding, entry, titleBeforeEdit)`.
- `replaceFromLibrary` (app.js#L1370-L1387) is a **single `window.confirm`-style dialog for the whole finding**, not per-section: "Replace this finding with the library version? … Using it will erase everything written for this finding on the Content page, including any screenshots that were uploaded." Two buttons only: *Use the library version* / *Keep the current content*. There is no third "merge" option and no per-field granularity.
  - **Decline:** the title is rolled back to `previousTitle`, findings are re-rendered, save is scheduled, returns `false`. Nothing else changes.
  - **Accept:** captures `evidenceIdsIn(finding)` (the images currently referenced), calls `applyLibraryEntry(finding, entry)`, then `dropUnreferencedEvidence` to delete any evidence file that ceases to be referenced.
- `applyLibraryEntry` (app.js#L1388-L1397) does one `Object.assign` that overwrites `title`, `likelihood`, `impact`, `severity`, `library_ref`, and **`contents` wholesale** (`JSON.parse(JSON.stringify(entry.contents || []))`) — every fragment in every section (`description`, `recommended_remediation`, `previous_proof_of_concept`, `proof_of_concept`, `in_conclusion`) is replaced, no exceptions. Preserved by omission: `uid`, `display_id`, `status`, `scope`. All copied fragments get fresh `frag_id`s. `poc_variant`/`poc_variant_declined` are reset to null/empty (the whole-body replace invalidates any memory of which proof-of-concept variant was installed), then `provision`, `syncEvidenceImageSlots`, and — if the derived app type matches a library proof-of-concept variant — `applyPocVariant` run again to reseed the proof of concept from the library entry's `proof_of_concept` map.

So today: **one confirm, whole-finding, all-or-nothing.** No per-section prompt exists, and no server-side counterpart exists at all — this logic must be re-implemented client-side regardless of what shape the new flow takes, unless a server route is added.

## 2. The proof-of-concept offer/apply mechanism (the model to mimic)

This is a two-function pair, twinned in Python and JavaScript, plus a state-derived (not event-driven) banner.

**Selection — `applicable_poc_variant`** (app/report_service.py#L273-L285) / `applicablePocVariant` (app.js#L896-L903):
Reads the finding's affected app types (`affected_channels`/`affectedChannels`, itself derived from `scope` + `report.scope_targets`) and maps them to one of the library's four `TestType` keys (`web`, `api`, `mobile`, `web_api`) by **exact set match only** — `{web,api}` → `web_api`, anything else (including no match, or `{web,mobile}`) → `None`/`null`. No synthesis, no partial credit.

**State read for the offer:** `pocStepsFor(finding, variant)` (app.js#L954-L957) looks up `finding.library_ref.library_id` in the loaded library and pulls `entry.proof_of_concept[variant]`. **The offer is library-linked only** — it requires `library_ref` to already be set, which only happens via `insert_library` or `applyLibraryEntry`/`replaceFromLibrary`. A tester-authored finding that merely resembles a library entry gets no offer.

**Rendering:** purely derived, computed fresh on every `render()` inside the Content page (app.js#L2365-L2385), when rendering the `proof_of_concept` content block:
```
steps && finding.poc_variant !== variant && !(finding.poc_variant_declined || []).includes(variant)
```
i.e., steps exist for the derived variant, that variant isn't already installed, and it wasn't previously refused. Button labels adapt to whether the section already has content (`written = content.fragments.some(f => f.type !== "image" && fragmentHasContent(f))`): "Use saved steps" / "Keep mine" if something's there, "Fill from library" / "Dismiss" if empty. There is no dialog modal — it's an inline banner (`poc-offer`), and nothing is written until a button is clicked; a page reload never auto-applies or auto-declines.

**Install — `apply_poc_variant`** (app/report_service.py#L359-L372) / `applyPocVariant` (app.js#L941-L951): finds the `proof_of_concept` content block only, keeps every `image` fragment exactly as-is (`images = proof.fragments.filter(f => f.type === "image")`), deep-copies the variant's fragment list, **remints every `frag_id`** on the copies, sets `proof.fragments = copied + images`, runs `ensure_proof_steps`/`ensureProofSteps` to guarantee a `numbered_list` still exists, then records `vulnerability.poc_variant = variant` and **clears** `poc_variant_declined = []` (a stale refusal referred to steps that no longer exist, so it must not suppress a legitimate future mismatch).

**Decline:** the refuse button pushes the current `variant` onto `poc_variant_declined` (app.js#L2384, mirrored server-side wherever declines are persisted via the normal PUT) and leaves `poc_variant`/content untouched. Declining is per-variant, not global — a different variant (e.g. scope later narrows from `web_api` to `web`) will offer again.

**"Installed" vs "declined" tracking** lives entirely on `Vulnerability`, not on `LibraryRef`: `poc_variant: TestType | None` (which variant's steps are currently installed, `None` if tester-authored or never offered) and `poc_variant_declined: list[TestType]` (variants explicitly dismissed) (app/models.py#L141-L142). Because it's on the finding rather than `LibraryRef`, this memory survives a library replace (well — `applyLibraryEntry`'s whole-body replace explicitly *resets* it, since the fragments driving it are gone) and works even for findings that were never library-sourced (it stays `None`/`[]` and the offer never fires because `pocStepsFor` requires `library_ref`).

**Fragment merging model:** *replace-non-image, keep-image, remint-all-remaining* — never a true append/merge of steps; the "merge" concept the user wants (append library fragments to current ones) does **not exist anywhere in the current proof-of-concept flow**. It only ever knows *replace* and *decline*, exactly like `replaceFromLibrary`. The user's request to add a third "merge/append" choice is new to both the whole-finding flow and the proof-of-concept flow.

**Invariants constraining this (`Report.validate_references`, app/models.py#L215-L233):** `frag_id` values must be unique across the **entire report** — this is why every install remints every copied fragment's `frag_id`, never reusing the library's stored ids. Within one finding, `contents[].type` values must be unique — so an install/replace must always target the single existing `Content` block for that type, never append a second block of the same type. Section 12 of the map lists `apply_poc_variant`/`applyPocVariant` and `applicable_poc_variant`/`applicablePocVariant` as twinned rules that must change together, with `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` as the drift-catching test for the readiness side (not the offer itself — there is no automated test asserting Python/JS offer parity directly beyond the twin-function naming and code comments cross-referencing each other, e.g. "Twin of report_service.apply_poc_variant; keep both in step" at app.js#L940).

## 3. `Vulnerability.contents[]` structure (app/models.py#L18, #L85-L88, #L129-L143)

```python
ContentType = Literal["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]

class Content(BaseModel):
    type: ContentType
    fragments: list[Fragment] = Field(default_factory=list)
```
Exactly **five possible section names**, no others. `Vulnerability.contents` (app/models.py#L143) is a flat list of `Content` blocks; `Report.validate_references` enforces uniqueness of `type` within one finding's `contents` (app/models.py#L228-L230), so a finding has **at most one** block per section.

`Fragment` is a discriminated union on `type` (app/models.py#L79): `paragraph`, `numbered_list`/`bulleted_list`, `table`, `note`, `image`, `code_block`, `instance_title` — seven fragment types, each carrying its own `frag_id: StableId`.

**Which sections exist per finding depends on `status`**, per `provision` (app/report_service.py#L161-L167):
- `open_new` (and any status that isn't `open_new`... actually inverted): the base set is `["description", "recommended_remediation", "proof_of_concept"]`
- any non-`open_new` status: `["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]`

`ContentType` itself does **not** restrict which fragment types may appear in which section — the map notes this explicitly ("`Content.fragments` accepts any fragment type... Not enforced here: which fragment types may appear in which content section"). The soft convention enforced only by `provision`'s `required_fragments` table (app/report_service.py#L168-L174) is: `description`/`recommended_remediation` seed a `paragraph`; `previous_proof_of_concept`/`proof_of_concept` seed `numbered_list` + `image`; `in_conclusion` seeds nothing (it's populated by a generated status-conclusion paragraph, app/report_service.py#L192-L200). But a real draft on disk shows sections holding fragment types well outside that seed list — e.g. `previous_proof_of_concept` in [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](../../data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L121-L172) carries `numbered_list`, `instance_title`, `code_block`, `table`, and `image` fragments together, and `description` there (lines 71-104) carries `paragraph` + `note` + `bulleted_list`. The `allowed` map in the JS add-fragment menu is client-only UI guidance, not a schema constraint (per [docs/plans/import-docx-as-retest-draft.md#L427](import-docx-as-retest-draft.md#L427), it "gates only the add menu").

## 4. Invariants constraining a "keep / replace / merge-append" per-section flow

- **`frag_id` uniqueness is report-wide, not section-wide or finding-wide** (app/models.py#L221-L233, `Report.validate_references`). Any merge-append operation that copies library fragments into an existing section **must remint every copied fragment's `frag_id`**, exactly as `apply_poc_variant`/`applyPocVariant` and `assign_fresh_fragment_ids` already do — there is no exception for "keep the library's original id."
- **`Content.fragments` has no type-uniqueness constraint** — a section is free to hold two `paragraph` fragments, so "append" is schema-legal for every section, not just lists. (Contrast: `contents[].type` uniqueness is enforced across the finding, so you cannot have two `description` blocks — an append must go into the single existing block for that type, never create a second one.)
- **No `provision`/`apply_*_variant`-style function exists today for `description` or `recommended_remediation`.** Only `proof_of_concept` has an install function (`apply_poc_variant`/`applyPocVariant`) because only `proof_of_concept` has a library-provided per-variant payload (`LibraryEntry.proof_of_concept: dict[TestType, list[Fragment]]`). A `LibraryEntry`'s `description`/`recommended_remediation` content instead lives inside the entry's flat `contents` array (the same shape `insert_library` deep-copies wholesale, app/main.py#L717) — there is currently **no accessor that extracts "just the description fragments" or "just the remediation fragments" from a library entry**; that would need to be added (e.g., `entry.contents.find(c => c.type === "description")`) before a per-section prompt for those two sections could exist.
- **Image handling is section-specific and asymmetric.** `apply_poc_variant` explicitly preserves images and only replaces non-image fragments, because `proof_of_concept` images are evidence tied to `evidence_id`/uploaded screenshots (`sync_evidence_image_slots`, app/report_service.py#L191-L227) that must never be silently discarded. `description` and `recommended_remediation` currently seed only `paragraph` fragments and carry no such image-preservation logic — a "replace" or "keep" choice for those two sections is simpler (no evidence to protect), but a merge/append choice must still avoid duplicating evidence-bearing fragments if a tester ever put an image there (schema permits it, per point 3 above).
- **`dropUnreferencedEvidence`** (app.js#L1364-L1368) currently runs only from the whole-finding `replaceFromLibrary` path, keyed off "does any fragment anywhere in the finding still reference this `evidence_id`." A per-section flow that replaces only `description`/`recommended_remediation` would rarely intersect evidence (those sections seed no images today), but if a tester manually added an `image` fragment there, a per-section "replace" must still call the equivalent orphan-evidence cleanup, scoped correctly.
- **JavaScript duplication (DATA_MAP section 12):** `applicable_poc_variant`/`applicablePocVariant`, `apply_poc_variant`/`applyPocVariant`, and `provision` (twinned, plus **a third inline copy** in the status `onchange` handler around app.js line 1470) all exist in both languages and must change in pairs. `replaceFromLibrary` itself is listed as **client-only** (no Python equivalent) — the whole "apply library to existing finding" behavior is a JS-only concept today; extending it to per-section keep/replace/merge stays client-only unless a new server endpoint is deliberately introduced.

## 5. What draft.json shapes look like on disk

**No draft currently on disk has both a populated `library_ref` and edited content** — both real reports under `data/apps/` show `"library_ref": null` for their findings ([data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.json:87](../../data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.json#L87), [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json:64](../../data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L64)). This is a real gap: there is no fixture demonstrating the exact scenario the user describes (library-linked finding with tester-edited content). The planner should treat this as untested-in-practice ground, not as an edge case someone already handled.

What **does** exist on disk is the general shape a finding-with-content takes, e.g. [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json:55-172](../../data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L55-L172):
```json
{
  "status": "open_previously_discovered",
  "scope": { "mode": "custom", "target_ids": ["tgt_1acb9708"], "location_values": {}, "custom_locations": {} },
  "library_ref": null,
  "poc_variant": null,
  "poc_variant_declined": [],
  "contents": [
    { "type": "description", "fragments": [ {"frag_id": "f_cb4cd9db", "type": "paragraph", "runs": [...]}, {"frag_id": "f_98071d02", "type": "note", "runs": [...]}, {"frag_id": "f_e2185aa7", "type": "bulleted_list", "items": [...]} ] },
    { "type": "recommended_remediation", "fragments": [ {"frag_id": "f_867caba7", "type": "paragraph", "runs": [...]} ] },
    { "type": "previous_proof_of_concept", "fragments": [
        {"frag_id": "f_cf2bc232", "type": "numbered_list", "items": [...]},
        {"frag_id": "f_28b51ff9", "type": "instance_title", "text": "First instance"},
        {"frag_id": "f_f29cdfec", "type": "code_block", "caption": "Request", "text": "GET /accounts/123"},
        {"frag_id": "f_12b206b9", "type": "table", "caption": "Results", "header": [...], "rows": [...]},
        {"frag_id": "f_64a39244", "type": "image", "environment": "production", "evidence_id": "ev_fd29a2f7", "caption": "Production response", "width_mm": null}
    ] }
  ]
}
```
For comparison, a library entry's own shape (`resources/vuln_library.json`, e.g. entry `VDB-015` at resources/vuln_library.json#L24) carries `library_id`, `source_id`, `title`, `tags`, `default_likelihood`/`default_impact`/`default_severity`, a flat `contents[]` in the same `Content`/`Fragment` shape, and optionally `proof_of_concept: {web: [...], api: [...], web_api: [...]}`. `LibraryRef` on a finding, once populated (via `insert_library` at app/main.py#L717 or `applyLibraryEntry` at app.js#L1388), looks like `{"library_id": "VDB-015", "source_id": 15, "inserted_at": "<ISO datetime>"}`.

## 6. Rules duplicated in both Python and JavaScript (DATA_MAP section 12) relevant to this change

| Rule | Python | JavaScript | Relevance |
|---|---|---|---|
| library proof-of-concept selection | `applicable_poc_variant` (app/report_service.py:273) | `applicablePocVariant` (app.js:896) | Direct model for per-section eligibility logic |
| installing proof-of-concept steps | `apply_poc_variant` (app/report_service.py:359) | `applyPocVariant` (app.js:941) | Direct model for per-section "replace" |
| status to section list | `provision` (app/report_service.py:161) | `provision`, plus a third inline copy in the status `onchange` (~app.js line 1470) | Determines which sections exist/are eligible for a prompt at all |
| image slots | `sync_evidence_image_slots` (app/report_service.py:203) | `syncEvidenceImageSlots` (app.js:908) | Must be re-run after any section replace/merge touching images |

**Client-only, no Python counterpart:** `replaceFromLibrary` itself (app.js:1370), `applyLibraryEntry` (app.js:1388), and `dropUnreferencedEvidence` (app.js:1364) — the entire "apply library content to an existing finding" behavior lives only in the browser today. A per-section keep/replace/merge redesign built purely client-side would not violate the "twin" contract (nothing to keep in step, since there's no server twin), but it also means the server never validates or provisions this specific transition — `provision_report`/`provision` only run on the next `PUT`, after the client has already merged/replaced sections and reminted `frag_id`s locally.

## Invariants in play

- `frag_id` uniqueness is **report-wide** (app/models.py#L221-L233): any new merge/append operation must remint every copied fragment's id, or the next save fails validation and the draft is demoted to legacy/invalid on load.
- `contents[].type` uniqueness **within one finding** (app/models.py#L228-L230): a per-section append must add fragments into the existing single block for that type, never create a duplicate section.
- `ContentType` restricts section names to exactly five (app/models.py#L18); a new prompt cannot introduce a sixth section without a schema change.
- Section membership by `status` is decided only by `provision`/`provision_report`, which runs on `PUT` and library insert but **never** on `load_path` or `import_report` (docs/DATA_MAP.md#L128) — a per-section prompt firing before the next save could offer content for a section that provisioning would later add or remove.

## Both-sides warning

`applicable_poc_variant`/`applicablePocVariant` and `apply_poc_variant`/`applyPocVariant` are implemented in both Python and JavaScript and must change together if the new per-section flow reuses or generalizes them (e.g., turning `apply_poc_variant`'s replace-only behavior into a shared replace/merge helper for other sections). `provision`/`provision` (plus its third inline copy at ~app.js line 1470) must also stay in step with whatever section set a per-section prompt assumes. `replaceFromLibrary` and `applyLibraryEntry`, which this whole feature currently is, have **no Python counterpart at all** — extending them client-only introduces no new twin, but if any part of the new flow is pushed to the server (e.g., a new `insert_library`-style endpoint for "apply-to-existing"), that endpoint and its JS caller become a new pair requiring the same care.

## Map drift

None. Everything read from source matched docs/DATA_MAP.md section 7 ("Derived state, recomputed on every save"), section 12 ("Rules that exist twice") and the client-only/server-only callouts. No correction was needed.

## Round 1 - Planner: proposal and open questions

# Per-section library content offer — plan

## Understanding

Today, when a tester on the Findings page renames a finding's title to match a library entry (via the combobox commit or a search-result click), `replaceFromLibrary` fires one `window.confirm` for the whole finding and, on acceptance, `applyLibraryEntry` wholesale-replaces `title`, `likelihood`, `impact`, `severity`, `library_ref`, *and* the entire `contents` array (deep-cloned from the entry, with every `frag_id` reminted), then reprovisions and re-applies any proof-of-concept variant. The request is to stop copying `contents` at that moment. Instead, the title match should only apply the non-content fields immediately and silently, and defer the content decision to the Content page, where each library-sourced section (`description`, `recommended_remediation` — library entries never populate any other section) gets its own banner offering **keep**, **replace**, or **merge-append**, modeled on the existing proof-of-concept offer banner that already lives there.

## Blast radius

| File | Change | Why |
|---|---|---|
| [app/models.py](../../app/models.py) | Add a new optional field to `Vulnerability`, e.g. `content_offer_resolved: dict[ContentType, StableId] = Field(default_factory=dict)` | Persists, per content section, which `library_id` that section's offer has already been resolved against (kept, replaced, or merged), so the banner stops reappearing — the schema-side twin of how `poc_variant`/`poc_variant_declined` already track the proof-of-concept offer. |
| [app/web/static/app.js](../../app/web/static/app.js) | Rework `replaceFromLibrary` (drop the `window.vrDialog.confirm`, stop copying `contents`); trim `applyLibraryEntry` to non-content fields only; add banner rendering for `description` and `recommended_remediation` next to the existing `proof_of_concept` banner block in the Content-page `render()`; extract a small fragment-remint helper reused by replace/merge | This is where the whole trigger, both mechanisms being merged/replaced, and both new banners live. |
| [docs/DATA_MAP.md](../DATA_MAP.md) | Update §6 (new field on `Vulnerability`), §12 (add the new offer alongside the POC-offer row, marked client-only; revise the `replaceFromLibrary` bullet to describe its narrower role) | Required by the data-layer instructions whenever `app/models.py` or the save/navigation logic in `app.js` changes. |
| `tests/test_browser.py` | New test: title match → open Content page → banner appears once per section → each of keep/replace/merge resolves it and it does not reappear | Only client-side test needed; there is no Python twin function to contract-test against. |

**Not touched, and why:** [app/main.py](../../app/main.py)'s `insert_library` route and [app/library.py](../../app/library.py) — that route copies a library entry into a *brand-new* finding with nothing to protect, and is unaffected by how an *existing* finding's content is reconciled. `resources/vuln_library.json` — entries never carry `proof_of_concept` or `previous_proof_of_concept` inside `contents` (confirmed against the file and against `library_editor.py`, which only ever writes `description`, `recommended_remediation`, and the separate `proof_of_concept` dict), so this change has no library-authoring surface.

## Open questions

1. **Silent metadata replace.** `likelihood`, `impact`, `severity`, and `library_ref` are not "content" but are currently overwritten wholesale, immediately, with no prompt, by the same title-match trigger. Should that continue unchanged, or does removing the whole-finding confirm mean these now need their own prompt (or one combined "apply these fields?" prompt) too? Absent an answer, this plan leaves them exactly as they are today — silent and immediate — because the request was explicitly scoped to "the contents."
2. **When does the offer fire?** Immediately on the title match (so a tester never leaves the Findings page without knowing two offers are waiting), or only when the tester next opens that section on the Content page (matching how the proof-of-concept banner is purely derived from state at render time, with no separate "just matched" flag)? Absent an answer, this plan uses the lazy, derived approach — it's the same pattern already proven for the POC banner and needs no new "pending" bookkeeping beyond the resolution record — but that means a tester who never opens the Content page for that finding leaves the offer open indefinitely with no visible signal on the Findings page.
3. **Does `proof_of_concept` ever join this mechanism?** If it later does, what happens to `poc_variant`/`poc_variant_declined`, and to `apply_poc_variant`'s "images are always preserved" guarantee, which the new mechanism has no equivalent for? Absent an answer, this plan leaves `proof_of_concept` and `previous_proof_of_concept` entirely alone, since library entries have no path to populate them through `contents` today — there is nothing for the new banners to act on there without a separate schema change first.
4. **Merge de-duplication.** Should "add library content" check for near-duplicate fragments (by text) before appending, or always append regardless? Absent an answer, this plan always appends with no de-duplication — guessing at a similarity threshold risks silently dropping content the tester wanted duplicated on purpose, and the request doesn't specify one.
5. **Visibility of unresolved offers.** Does the Findings page need any indicator that a finding has offers still waiting on the Content page, or is the in-place banner the only signal, same as the POC offer today? Absent an answer, this plan adds no such indicator.

## Data risks

| Failure mode | Assessment | Reasoning |
|---|---|---|
| Stale write | clear | No new server route or PUT variant is introduced; the new field rides the existing full-report autosave PUT, which already sends `saved_at` in the body. |
| Lost update | clear | All new logic is client-only, mutating the in-memory `report` object; no new server-side read-modify-write path is added outside `Workspace._locked`. |
| Orphan reference | RISK | "Replace" discards a section's existing fragments. Neither `description` nor `recommended_remediation` is provisioned with images, but nothing in the schema stops a tester from having added one, and if replace drops such a fragment, its `evidence_id` becomes unreferenced. Mitigation: rely on the existing `Workspace._drop_orphan_evidence` sweep on save (same as today's whole-finding replace does), and keep calling the client's `dropUnreferencedEvidence` pattern for the replaced section so the UI reflects it before the next save, not just after. |
| Silent stranding | clear | This change does not touch `scope` or `custom_locations`; no path here can leave a finding with zero locations. |
| Schema break | clear, if the new field has a default | `content_offer_resolved` defaults to `{}` and is optional, so every existing `draft.json` still passes `Report.validate_references` unchanged and needs no entry in `Workspace.load_path`'s legacy-repair list. |
| Request/response asymmetry | RISK | The new field must be treated as an ordinary round-tripped field, not excluded from canonical reconciliation the way `scope_text` deliberately is. If `applyCanonicalReport`/`reconcileCanonicalObject` doesn't merge it back in after a save, a tester's just-made "keep/replace/merge" choice would appear to un-resolve itself and the banner would reappear. Mitigation: verify it merges like every other `Vulnerability` field, no special-case exclusion added. |
| Rule drift | clear | The apply logic (keep/replace/merge) has no server-side twin to drift from — the existing `replaceFromLibrary`/`applyLibraryEntry` pair has never had a server route either (already documented in DATA_MAP §12 as client-only), and this plan keeps it that way. |
| Navigation trap | clear | The new field is optional and doesn't participate in `setup_is_complete` / `finding_is_complete` / any redirect gate, so it can't block or loop navigation. |
| Derived-state fight | clear | `provision()` only ever seeds an *empty* content section (documented sharp edge in DATA_MAP §13); once a tester has kept, replaced, or merged a section, it is non-empty, so the next save's `provision_report` will not touch it. |
| Backup exhaustion | clear | Each of keep/replace/merge triggers exactly one `scheduleSave()`, same debounced autosave cadence as every other Content-page edit — no path here forces two rapid saves. |
| `frag_id` reminting for merge-append | RISK (new code path, no existing test coverage) | The global `frag_id` uniqueness invariant (`Report.validate_references`) means every fragment copied in from the library — for both replace and merge — must get a fresh id before being written into `content.fragments`; merge is new code, unlike replace which reuses the already-working remint pattern from `applyLibraryEntry`/`apply_poc_variant`/`assign_fresh_fragment_ids`. Mitigation: extract one shared remint helper used by both paths, and cover it with the new browser test. |
| `Content.fragments` type-uniqueness for merge-append | clear | No such constraint exists for `description` or `recommended_remediation` — the "keep exactly one of this type" rule (`deletionBlockedReason`'s `requiresFragment` check) only applies to the two proof-of-concept sections, and it guards deletion, not addition. Appending extra paragraph/list fragments to these two sections is schema-legal today. |

## Proposed flow

**Trigger — unchanged.** Still the title-combobox match on the Findings page (`titleInput.onchange` and the search-result click in `renderRowResults`). What changes is what happens after the match, not how it's detected.

**Immediately, silently (unchanged from today):** `title`, `likelihood`, `impact`, `severity`, and `library_ref` are set from the matched entry, exactly as `applyLibraryEntry` does now. `contents` is left completely untouched at this point — no confirm dialog, no wholesale copy.

**On the Content page, per section, a banner (not a modal):** For each of `description` and `recommended_remediation`, rendered inside that content block exactly where the existing proof-of-concept banner sits inside `proof_of_concept` — a banner because it's non-blocking and, like the POC banner, purely derived from current state at render time, so it can never be silently dismissed by navigation the way a modal could, and it survives a reload without needing a separate "was this shown yet" flag.

*Show condition:* a library entry is found for `finding.library_ref?.library_id`, that entry has non-empty fragments for this section, `finding.content_offer_resolved?.[content.type] !== finding.library_ref.library_id`, and — for `recommended_remediation` only — `finding.status !== "resolved"` (mirroring the existing "Locked for resolved findings" rule, which already suppresses editing that section).

*Three choices, all setting `content_offer_resolved[content.type] = finding.library_ref.library_id` when clicked:*
- **Keep mine** — no fragment change.
- **Use library version** — `content.fragments` replaced with the entry's fragments for that section, deep-cloned with every `frag_id` reminted, followed by the same orphaned-evidence cleanup `replaceFromLibrary` already performs today (defensive, since neither section is normally provisioned with images).
- **Add library content** — the entry's fragments for that section, deep-cloned with fresh `frag_id`s, appended after the tester's existing fragments; nothing removed, so no evidence impact. No de-duplication (open question 4).

**`proof_of_concept` / `previous_proof_of_concept` — out of scope.** `previous_proof_of_concept` is never library-sourced at all (it's a historical record). `proof_of_concept` keeps its existing, separate `poc_variant`/`poc_variant_declined` mechanism unchanged — it already has an image-safe replace-or-decline offer, just not a third "append" option, and folding it into this new mechanism would need its own schema and code changes (open question 3).

**Whole-finding `replaceFromLibrary` prompt — removed, not kept as a fallback.** The function itself survives in trimmed form (non-content fields only, no dialog); there is no wholesale-replace path left to fall back to, per the request's explicit "what if we did not do that."

**Server-side twin — none needed.** `replaceFromLibrary`/`applyLibraryEntry` have never had a server route; the mutation rides the existing autosave PUT like any other Content-page edit. `insert_library` (server-side, brand-new-finding-from-library) is unaffected — that finding has no prior content to protect, so its wholesale copy remains correct.

## Plan

1. **[app/models.py](../../app/models.py)** — add `content_offer_resolved: dict[ContentType, StableId] = Field(default_factory=dict)` to `Vulnerability`. Test: existing report fixtures still `Report.model_validate` unchanged. Invariant: must not require a `Workspace.load_path` legacy-repair entry — the default must make every existing `draft.json` parse as-is.
2. **[app/web/static/app.js](../../app/web/static/app.js)** — extract the inline `fragment.frag_id = id("f")` remint loop (currently duplicated in `applyLibraryEntry` and `applyPocVariant`) into one small helper that returns freshly-cloned, freshly-id'd fragments, so the new merge path reuses it instead of a fourth inline copy. Test: no behavior change for existing POC/whole-finding paths; covered by existing manual/browser flows.
3. **[app/web/static/app.js](../../app/web/static/app.js)** — trim `replaceFromLibrary` to drop `window.vrDialog.confirm` and stop calling into the content-copying half of `applyLibraryEntry`; `applyLibraryEntry` itself is trimmed to the non-content fields only. Invariant: `title`/`likelihood`/`impact`/`severity`/`library_ref` still change immediately and silently; `contents` must be provably untouched by this function afterward.
4. **[app/web/static/app.js](../../app/web/static/app.js)** — add the per-section banners in the Content-page `render()`, wired to keep/replace/merge as described above. Test (new, in `tests/test_browser.py`): title match → open Content page → both banners render once → each resolution type makes its banner disappear and does not reappear on re-render. Invariant: the `recommended_remediation` banner never renders while `finding.status === "resolved"`.
5. **[app/web/static/app.js](../../app/web/static/app.js)** — verify `applyCanonicalReport`/`reconcileCanonicalObject` merges `content_offer_resolved` like an ordinary field (not excluded the way `scope_text` is). Invariant: a resolution set client-side survives the next post-save canonical merge.
6. **[docs/DATA_MAP.md](../DATA_MAP.md)** — update §6 for the new field, and §12 to list this offer as client-only alongside the POC-offer row, and to revise the bullet currently describing `replaceFromLibrary` as a whole-finding confirm guard.

## What I would not do

- Would not build a generic "content offer" abstraction that also handles `proof_of_concept`/`previous_proof_of_concept` speculatively — library entries have no path to populate those sections through `contents` today, and shipping unreachable capability is exactly the kind of untested branch that rots.
- Would not add a server-side route/twin for the per-section apply logic — the existing equivalent has never had one, the mutation already rides the ordinary autosave PUT, and inventing a second implementation of the same three rules is a drift risk with no offsetting benefit.
- Would not implement fragment de-duplication for "merge/append" without a specified similarity rule — a guessed threshold risks silently discarding content the tester wanted kept, which is the one class of outcome this kind of change must never produce.

## Round 2 - Oracle: verdict on the proposal

## Verdict: Data risk table, missed files, and disk-safety check

### 1. Data-risk table corrections

Every row checked against source. One row is misclassified.

| Row | Planner's call | Verdict | Evidence |
|---|---|---|---|
| Stale write | clear | **Correct.** No new route; rides the existing autosave PUT. | [app/main.py](../../app/main.py) has no new endpoint proposed or needed for this flow. |
| Lost update | clear | **Correct.** All new state lives on the in-memory `report` object, mutated only through the same `scheduleSave()` path every other Content-page edit uses. | [app/web/static/app.js](../../app/web/static/app.js#L2378-L2392) (existing POC banner pattern the new banners copy) |
| Orphan reference | RISK | **Correct, and probably undersold.** `description`/`recommended_remediation` are seeded with only `paragraph` (`required_fragments` in `provision`), but nothing stops a tester or an "Add library content" merge from adding an `image` fragment there, and `Report.validate_references` requires every `evidence_id` to resolve. The mitigation (reuse `dropUnreferencedEvidence`) is sound, but the plan should call out that a **merge-append** (not just "replace") can also orphan evidence if the tester later deletes the fragment it lives on — the same cleanup needs to run after merge, not just replace. | [app/models.py](../../app/models.py#L215-L233) `Report.validate_references`; [app/web/static/app.js](../../app/web/static/app.js#L1364-L1368) `dropUnreferencedEvidence` |
| Silent stranding | clear | **Correct.** Nothing here touches `scope`/`custom_locations`. | [app/models.py](../../app/models.py#L91-L96) `Scope` |
| Schema break | clear, if defaulted | **Correct**, confirmed against a real file on disk (see §3 below). | [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](../../data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L64) shows `"library_ref": null` and no `content_offer_resolved` key at all, i.e. today's real shape |
| Request/response asymmetry | RISK | **Correct, and verified low-effort.** `reconcileCanonicalObject` ([app/web/static/app.js](../../app/web/static/app.js#L342-L391)) excludes only a hardcoded list (`saved_at`, `app_id`, `_folder_name_hint`, `scope_text`) at line 347. `content_offer_resolved` is a plain object (dict), so it falls into the generic `isRecord(sentValue) && isRecord(canonicalValue) && isRecord(liveValue)` branch (line 379) and recurses key-by-key automatically — **no code change needed**, only the verification step the plan already lists (Plan step 5). Confirmed correct as a "verify, don't add" item. |
| Rule drift | clear | **Correct.** `replaceFromLibrary`/`applyLibraryEntry` have no server twin today (confirmed: `grep` for these names in `app/*.py` returns nothing), so there is nothing to drift from. | — |
| Navigation trap | clear | **Correct.** No redirect/gate function (`setup_is_complete`, `finding_is_complete`, or equivalent) reads `contents` shape in a way this field could affect. | — |
| Derived-state fight | clear | **Correct.** `provision()` ([app/report_service.py](../../app/report_service.py#L161-L167)) only fills a content block when `content.fragments` is empty (`if content.fragments: continue`); once a tester resolves an offer the section is non-empty and `provision` will not touch it again. | [app/report_service.py](../../app/report_service.py#L161-L184) |
| Backup exhaustion | clear | **Correct.** Each resolution triggers one `scheduleSave()`, same debounce as every other edit; no double-save path introduced. | — |
| `frag_id` reminting for merge-append | RISK | **Correct, and this is the plan's most solid risk row.** `Report.validate_references` ([app/models.py](../../app/models.py#L221-L226)) enforces `frag_id` uniqueness across the **whole report**, not per finding or per section — confirmed by reading the validator directly, which accumulates `frag_ids` in one set across all vulnerabilities. Every existing remint path (`applyLibraryEntry` app.js:1391, `apply_poc_variant`/`applyPocVariant`, `assign_fresh_fragment_ids`) reassigns every copied fragment's id; merge-append is new code with no existing analog to copy from mechanically (it's structurally similar to replace but is genuinely unexercised). | [app/models.py](../../app/models.py#L221-L226) |
| `Content.fragments` type-uniqueness for merge-append | clear | **Correct.** No such constraint exists in `Report.validate_references` — the only uniqueness check on `contents` is `content_types` per finding (line 202: `if len(content_types) != len(set(content_types))`), which is about the `Content.type` field, not repeated fragment types inside one `Content.fragments` list. Two `paragraph` fragments in one section is schema-legal today. | [app/models.py](../../app/models.py#L200-L203) |

**No row is wrongly marked `clear` when it's actually a risk, and no row is wrongly marked `RISK` when it's already fully handled.** The table is accurate; only the "Orphan reference" row's mitigation should be widened to explicitly cover merge (not just replace).

### 2. Files the planner did (and didn't) miss

- **`resources/vuln_library.json` / `library_editor.py` claim — confirmed true.** A `grep` for `"type": "proof_of_concept"` and `"type": "previous_proof_of_concept"` inside `resources/vuln_library.json`'s `contents` arrays returns zero matches; every `contents[].type` in that file is `description`, `recommended_remediation`, or a fragment-level `type` (`paragraph`, `numbered_list`, etc.), never a `Content.type` of `proof_of_concept`. [library_editor.py](../../app/library_editor.py#L87-L97) only ever writes to the entry's separate top-level `proof_of_concept` dict (keyed by `TestType` variant), never into `contents`; its `create_entry` handler ([library_editor.py](../../app/library_editor.py#L106-L124)) initializes new entries with `"contents": []` and `"proof_of_concept": {}` as two independent keys. The planner's justification for leaving those two sections out of scope is correct.
- **`applyCanonicalReport`/`reconcileCanonicalObject` claim — confirmed true, no explicit update needed.** See the "Request/response asymmetry" row above: the exclusion list is a fixed array of four string keys, `content_offer_resolved` isn't on it, and dict-valued fields recurse generically. The plan's step 5 ("verify... not excluded") is the right-sized action; adding code here would be unnecessary.
- **`content_offer_resolved: dict[ContentType, StableId]` type-fit — confirmed compatible**, with one gap: `ContentType` ([app/models.py](../../app/models.py#L18)) and `StableId` ([app/models.py](../../app/models.py#L19)) both exist exactly as the plan assumes, and Pydantic v2 (`pydantic==2.13.5`, [requirements.txt](../../requirements.txt#L3)) supports a `Literal` union as a dict key type. **Gap the plan doesn't mention:** there is no JSDoc/TypeScript-shape doc of the report's client-side object anywhere in the repo (`app/web/static/app.js` has no type annotations, and `docs/DATA_MAP.md` describes fields in prose tables, not a typed schema) — so "would it need a matching type note" has one concrete answer: yes, in `docs/DATA_MAP.md` §6, which the plan's step 6 already covers. No separate JSDoc/TS artifact exists to update.
- **Other references to `replaceFromLibrary`/`applyLibraryEntry`/the whole-finding confirm — the planner's file list is complete.** A workspace-wide search for these three names plus `window.vrDialog.confirm` (the whole-finding dialog) turns up matches only in [app/web/static/app.js](../../app/web/static/app.js) (definitions and the two call sites at line 1595's search-result click and line 1602's `onchange`) and the two plan documents themselves. **No hits in `tests/test_app.py`, `tests/test_browser.py`, `tests/test_storage.py`, or any template** — there is currently no automated test coverage of `replaceFromLibrary`/`applyLibraryEntry` at all, confirming the plan's own claim ("Only client-side test needed... there is no Python twin function to contract-test against") and its Plan step 4 (add the first such test). Nothing was missed here.
- **Second half of both-sides rules — the planner's table is complete.** `applicable_poc_variant`/`applicablePocVariant` ([app/report_service.py](../../app/report_service.py#L273-L285) / [app/web/static/app.js](../../app/web/static/app.js#L896-L903)) and `apply_poc_variant`/`applyPocVariant` ([app/report_service.py](../../app/report_service.py#L359-L372) / [app/web/static/app.js](../../app/web/static/app.js#L941-L951)) are correctly cited both-sides. The "status to section list" (`provision`) rule has **three** copies, not two: the Python `provision` ([app/report_service.py](../../app/report_service.py#L161-L167)), the JS `provision` function ([app/web/static/app.js](../../app/web/static/app.js#L849)), and a third inline duplicate of the same `open_new` ternary inside the status-`<select>`'s `onchange` handler, confirmed at [app/web/static/app.js](../../app/web/static/app.js#L1621) — [docs/DATA_MAP.md](../DATA_MAP.md) §12 already tracks this correctly as three copies, only its line-number estimate for the third copy ("~line 1470") had drifted from the code's current line 1621. The plan's blast-radius table doesn't list this third copy as a file to touch, and correctly doesn't need to — the new banners' *show condition* only reads `finding.status !== "resolved"` and `content_offer_resolved`, not the `provision` section-list logic, so this duplicate is relevant context but not an edit site for this specific change.

### 3. Disk safety of `content_offer_resolved`

**Confirmed schema-safe against the real files in `data/apps/`.** Both drafts on disk — [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](../../data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L64) and `data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.json` — have no `content_offer_resolved` key at all today. Pydantic v2's `Field(default_factory=dict)` fills a **missing** key with a fresh `{}` at validation time with no error, so `Report.model_validate` (called by `Workspace.load_path`, [app/workspace.py](../../app/workspace.py#L269-L284)) continues to load both files unchanged. `Workspace.load_path`'s legacy-repair block only rewrites `engagement.tested_channels`; it does not need a new entry for this field, matching the plan's claim.

**One case the plan doesn't address: `null` vs. `{}` vs. missing are not equivalent for this field's proposed type.** Because the plan's proposed annotation is `dict[ContentType, StableId]` (not `dict[ContentType, StableId] | None`), Pydantic v2 treats a **missing** key and an explicit **`{}`** identically (both valid, both become `{}`), but an explicit **`null`** in the JSON would raise a `ValidationError` ("Input should be a valid dictionary") rather than being coerced to `{}`. This is not a risk today — no file on disk has the key at all, so no existing draft can contain a stray `null` — but it is a forward-looking sharp edge worth one line in the DATA_MAP entry: if any future code path ever writes `content_offer_resolved: null` (e.g., a naive `Object.assign` reset, mirroring how `applyLibraryEntry` resets `poc_variant = null` today, which is valid only because that field is `TestType | None`), the next load would fail validation. The plan's own step 3 (trim `applyLibraryEntry` to non-content fields) does not reset `content_offer_resolved`, so this does not fire in the proposed design — flagging it only so the DATA_MAP note names the guard explicitly rather than leaving it implicit.

## Invariants in play

- `frag_id` uniqueness is report-wide ([app/models.py](../../app/models.py#L221-L226)), confirmed by direct read of `Report.validate_references`: violated by any merge/replace path that reuses a library fragment's stored id instead of reminting.
- `contents[].type` uniqueness is per-finding, not per-section fragment-type uniqueness ([app/models.py](../../app/models.py#L200-L203)): violated only if a new code path ever created a second `Content` block of the same type; not at risk from merge-append, which only appends fragments inside the existing block.
- `content_offer_resolved`, if added as `dict[ContentType, StableId]` with `default_factory=dict`, must never be explicitly set to `null`: violated only by code that doesn't exist in the current plan, but worth naming so it stays that way.

## Both-sides warning

`applicable_poc_variant`/`applicablePocVariant` and `apply_poc_variant`/`applyPocVariant` remain twinned and are correctly identified as the model to mimic; they are not modified by this plan but any future generalization of their remint logic into a shared helper touches both languages. The "status to section list" rule has a confirmed **third** copy at [app/web/static/app.js](../../app/web/static/app.js#L1621), which `docs/DATA_MAP.md` §12 already tracks — not an edit site for this plan.

## Map drift

`docs/DATA_MAP.md` §12's "status to section list" row already correctly listed three copies (`provision`, `provision`, plus a third inline copy), but its line-number estimate for the inline copy ("~line 1470") had drifted from the code's current location. Corrected to line 1621. No other section needed correction. Last verified: 2026-09-15.

## Round 2 - Planner: revised plan

# Per-section library content offer — final plan (agreed)

## Understanding

Today, when a tester on the Findings page renames a finding's title to match a library entry, `replaceFromLibrary` fires one whole-finding confirm dialog and, on acceptance, `applyLibraryEntry` wholesale-replaces `title`, `likelihood`, `impact`, `severity`, `library_ref`, and the entire `contents` array. This plan stops that. The title match will still apply the non-content fields immediately and silently, but the content decision moves to the Content page, where each library-sourced section (`description`, `recommended_remediation`) gets its own banner offering **keep**, **replace**, or **merge-append**, modeled on the existing proof-of-concept offer banner.

## Blast radius

| File | Change | Why |
|---|---|---|
| [app/models.py](../../app/models.py) | Add `content_offer_resolved: dict[ContentType, StableId] = Field(default_factory=dict)` to `Vulnerability` | Tracks, per section, which `library_id` that section's offer has been resolved against, so the banner stops reappearing. |
| [app/web/static/app.js](../../app/web/static/app.js) | Rework `replaceFromLibrary` (drop the confirm dialog, stop copying `contents`); trim `applyLibraryEntry` to non-content fields only; add per-section banners in the Content-page `render()`; extract a shared fragment-remint helper used by both replace and merge-append | This is where the trigger, both mechanisms being replaced/merged, and both new banners live. |
| [docs/DATA_MAP.md](../DATA_MAP.md) | Update §6 (new field on `Vulnerability`) and §12 (new offer listed as client-only alongside the POC-offer row; revised `replaceFromLibrary` bullet) | Required whenever `app/models.py` or Content-page save/navigation logic changes. |
| `tests/test_browser.py` | New test: title match → open Content page → banners appear once per section → each of keep/replace/merge-append resolves it and it does not reappear | Only client-side test needed; there is no Python twin function to contract-test against. |

**Not touched:** [app/main.py](../../app/main.py)'s `insert_library` (creates brand-new findings with nothing to protect) and `resources/vuln_library.json`/[app/library_editor.py](../../app/library_editor.py) (entries never populate `proof_of_concept`/`previous_proof_of_concept` through `contents`, confirmed against source).

## Open questions

1. **Silent metadata replace.** `likelihood`, `impact`, `severity`, `library_ref` continue to be overwritten wholesale and silently by the title match, unchanged from today, since the request was scoped to "the contents." Absent a different answer, this stands.
2. **When does the offer fire?** This plan uses the lazy, derived approach (banner computed at render time on the Content page, same as the POC banner) rather than firing immediately on the title match. A tester who never opens the Content page for that finding leaves the offer open indefinitely with no signal on the Findings page.
3. **Does `proof_of_concept` ever join this mechanism?** Out of scope for this plan — library entries have no path to populate `proof_of_concept`/`previous_proof_of_concept` through `contents` today.
4. **Merge de-duplication.** "Add library content" always appends, with no near-duplicate detection — a guessed similarity threshold risks silently dropping content the tester wanted duplicated on purpose.
5. **Visibility of unresolved offers.** No Findings-page indicator is added; the in-place banner is the only signal, same as the POC offer today.

## Data risks

| Failure mode | Status | Reasoning |
|---|---|---|
| Stale write | clear | No new server route; rides the existing autosave PUT, which already sends `saved_at`. |
| Lost update | clear | All new state lives on the in-memory `report` object, mutated only through the existing `scheduleSave()` path; no new server-side read-modify-write outside `Workspace._locked`. |
| Orphan reference | RISK | Neither section is normally provisioned with images, but nothing stops a tester (or an "Add library content" merge) from adding an `image` fragment there, and `Report.validate_references` requires every `evidence_id` to resolve. **Mitigation, widened per oracle verdict: the orphan-evidence cleanup (`dropUnreferencedEvidence`) must run after both "Use library version" (replace) and "Add library content" (merge-append)** — a merge-added image fragment can later be deleted by the tester, orphaning its evidence exactly like a replace can. It is not enough to scope this cleanup to replace only. |
| Silent stranding | clear | Nothing here touches `scope` or `custom_locations`. |
| Schema break | clear | `content_offer_resolved` defaults to `{}` via `default_factory`; both real drafts on disk have no such key today and load unchanged; no `Workspace.load_path` legacy-repair entry is needed. |
| Request/response asymmetry | RISK, verify-only | `reconcileCanonicalObject` excludes only a fixed list (`saved_at`, `app_id`, `_folder_name_hint`, `scope_text`); `content_offer_resolved` is a plain dict and falls into the generic recursive-merge branch automatically. No code change needed — only the verification step in Plan step 5. |
| Rule drift | clear | `replaceFromLibrary`/`applyLibraryEntry` have no server-side twin today; nothing to drift from. |
| Navigation trap | clear | The new field participates in no redirect/gate function (`setup_is_complete`, `finding_is_complete`, or equivalent). |
| Derived-state fight | clear | `provision()` only fills a content block when it's empty; once an offer is resolved the section is non-empty, so `provision` won't touch it again. |
| Backup exhaustion | clear | Each resolution (keep/replace/merge) triggers exactly one `scheduleSave()`, the same debounced cadence as any other edit. |
| `frag_id` reminting for merge-append | RISK | `frag_id` uniqueness is report-wide, not per-finding or per-section. Every fragment copied in — for both replace and merge-append — must get a fresh id before being written into `content.fragments`. Merge-append is new code with no existing analog to copy mechanically. Mitigation: one shared remint helper used by both paths, covered by the new browser test. |
| `Content.fragments` type-uniqueness for merge-append | clear | No such constraint exists for `description`/`recommended_remediation`; the only uniqueness rule (`contents[].type` per finding) governs section blocks, not fragment types within one section. Appending extra fragments of an existing type is schema-legal. |

## Proposed flow

**Trigger — unchanged.** Still the title-combobox match on the Findings page.

**Immediately, silently (unchanged from today):** `title`, `likelihood`, `impact`, `severity`, `library_ref` are set from the matched entry. `contents` is left completely untouched — no confirm dialog, no wholesale copy.

**On the Content page, per section, a banner (not a modal):** For each of `description` and `recommended_remediation`, rendered inside that content block exactly where the existing proof-of-concept banner sits.

*Show condition:* a library entry is found for `finding.library_ref?.library_id`, that entry has non-empty fragments for this section, `finding.content_offer_resolved?.[content.type] !== finding.library_ref.library_id`, and — for `recommended_remediation` only — `finding.status !== "resolved"`.

*Three choices, all setting `content_offer_resolved[content.type] = finding.library_ref.library_id` when clicked:*
- **Keep mine** — no fragment change.
- **Use library version** — `content.fragments` replaced with the entry's fragments, deep-cloned with every `frag_id` reminted, followed by orphaned-evidence cleanup (`dropUnreferencedEvidence`-style sweep).
- **Add library content** — the entry's fragments deep-cloned with fresh `frag_id`s, appended after the tester's existing fragments. **This path also runs the same orphaned-evidence cleanup as "Use library version," not just at merge time but as a standing cleanup after any later deletion in that section** — a merge-added image fragment can be deleted by the tester after the fact, orphaning its evidence exactly like a replace can, so the cleanup cannot be scoped to replace alone. No fragment de-duplication (open question 4).

**`proof_of_concept` / `previous_proof_of_concept` — out of scope**, unchanged, per open question 3.

**Whole-finding `replaceFromLibrary` prompt — removed, not kept as a fallback.**

**Server-side twin — none needed.** The mutation rides the existing autosave PUT like any other Content-page edit; `insert_library` (brand-new finding from library) is unaffected.

## Plan

1. **[app/models.py](../../app/models.py)** — add `content_offer_resolved: dict[ContentType, StableId] = Field(default_factory=dict)` to `Vulnerability`. Test: existing report fixtures still `Report.model_validate` unchanged. Invariant: no `Workspace.load_path` legacy-repair entry required; every existing `draft.json` parses as-is.
2. **[app/web/static/app.js](../../app/web/static/app.js)** — extract the inline fragment-remint loop (duplicated today in `applyLibraryEntry` and `applyPocVariant`) into one shared helper returning freshly-cloned, freshly-id'd fragments, reused by the new merge-append path. Test: no behavior change to existing POC/whole-finding paths.
3. **[app/web/static/app.js](../../app/web/static/app.js)** — trim `replaceFromLibrary` to drop the confirm dialog and stop calling the content-copying half of `applyLibraryEntry`; trim `applyLibraryEntry` to non-content fields only. Invariant: `title`/`likelihood`/`impact`/`severity`/`library_ref` still change immediately and silently; `contents` provably untouched by this function afterward.
4. **[app/web/static/app.js](../../app/web/static/app.js)** — add the per-section banners in the Content-page `render()`, wired to keep/replace/merge-append as described above, with the orphan-evidence cleanup running after **both** replace and merge-append. Test (new, in `tests/test_browser.py`): title match → open Content page → both banners render once → each resolution type makes its banner disappear and does not reappear on re-render → an image fragment added via merge-append and later deleted has its evidence cleaned up, matching replace's behavior. Invariant: the `recommended_remediation` banner never renders while `finding.status === "resolved"`.
5. **[app/web/static/app.js](../../app/web/static/app.js)** — verify `applyCanonicalReport`/`reconcileCanonicalObject` merges `content_offer_resolved` like an ordinary field (not excluded the way `scope_text` is). Invariant: a resolution set client-side survives the next post-save canonical merge.
6. **[docs/DATA_MAP.md](../DATA_MAP.md)** — update §6 for the new field, and §12 to list this offer as client-only alongside the POC-offer row and to revise the `replaceFromLibrary` bullet to describe its narrower role. **Include an explicit guard line: `content_offer_resolved` is typed `dict[ContentType, StableId]`, not `Optional` — a missing key or `{}` both validate to an empty dict, but an explicit JSON `null` for this field fails Pydantic validation. No code in this plan ever writes `null` here (unlike `applyLibraryEntry`'s reset of `poc_variant`, which is valid only because that field is `TestType | None`), but any future reset logic for this field must assign `{}`, never `null`.**

## What I would not do

- Would not build a generic "content offer" abstraction that also handles `proof_of_concept`/`previous_proof_of_concept` speculatively — library entries have no path to populate those sections through `contents` today.
- Would not add a server-side route/twin for the per-section apply logic — the existing equivalent has never had one, the mutation already rides the ordinary autosave PUT, and a second implementation of the same three rules is a drift risk with no offsetting benefit.
- Would not implement fragment de-duplication for merge-append without a specified similarity rule — a guessed threshold risks silently discarding content the tester wanted kept.

## Answers

1. **Metadata replace behavior (likelihood/impact/severity/library_ref):** Keep silent, as today. The title match continues to overwrite these fields immediately with no prompt; only content sections get the new offer.
2. **When the offer appears:** Lazy, Content-page only — the banner is purely derived at render time, same pattern as the existing proof-of-concept banner. No new indicator is added to the Findings page.
3. **Proof-of-concept sections:** The user wants the **same three-way treatment (retain / replace / add) extended to `proof_of_concept` as well**, not left on its existing two-way (replace/decline) mechanism alone. This changes the Round 2 plan, which had scoped `proof_of_concept`/`previous_proof_of_concept` out entirely. `previous_proof_of_concept` stays out of scope regardless — the oracle established it is never library-sourced (it's the historical record of a prior engagement, not something `applicable_poc_variant`/`apply_poc_variant` ever touches) — but `proof_of_concept` now gets the same keep/replace/merge-append offer as `description` and `recommended_remediation`, generalizing the existing `poc_variant`/`poc_variant_declined` two-way mechanism into a three-way one and reusing (not duplicating) `apply_poc_variant`/`applyPocVariant`'s existing image-preserving logic for the "replace" and now "merge-append" choices. Because these functions are a twinned Python/JavaScript pair (DATA_MAP §12), extending them requires changes on **both** sides, unlike the description/recommended_remediation offer, which stays client-only.
4. **Merge de-duplication:** Always append, no de-duplication — for every section, including the newly in-scope `proof_of_concept`.

## Agreed plan

The offer applies to three sections: `description`, `recommended_remediation`, and `proof_of_concept`. `previous_proof_of_concept` is excluded — it is never library-sourced and no code path populates it from a library entry.

### 1. `description` and `recommended_remediation` — new, client-only mechanism

1. **[app/models.py](../DATA_MAP.md)** ([app/models.py](../../app/models.py)) — add `content_offer_resolved: dict[ContentType, StableId] = Field(default_factory=dict)` to `Vulnerability`.
   - **Test:** existing report fixtures still `Report.model_validate` unchanged; both real drafts under `data/apps/` load with no key present, defaulting to `{}`.
   - **Invariant protected:** schema stays backward-compatible — no `Workspace.load_path` legacy-repair entry needed. The field must never be assigned an explicit `null` (only `{}` or a populated dict) since it is typed `dict[...]`, not `Optional`.
2. **[app/web/static/app.js](../../app/web/static/app.js)** — trim `replaceFromLibrary` to drop the whole-finding confirm dialog and stop invoking the content-copying half of `applyLibraryEntry`. Trim `applyLibraryEntry` itself to set only `title`, `likelihood`, `impact`, `severity`, `library_ref` — `contents` is left untouched by this function from now on.
   - **Test:** a title match no longer changes `contents`; `likelihood`/`impact`/`severity`/`library_ref` still change immediately with no dialog.
   - **Invariant protected:** the non-content metadata fields keep changing silently and immediately (Answer 1); nothing about the save/navigation flush path changes.
3. **[app/web/static/app.js](../../app/web/static/app.js)** — extract the fragment-remint loop (currently duplicated inline in `applyLibraryEntry` and `applyPocVariant`) into one shared helper that deep-clones a fragment list and assigns each a fresh `frag_id`. Reuse it for every "replace" and "merge-append" path below, including the generalized `proof_of_concept` one.
   - **Test:** no behavior change to any existing caller.
   - **Invariant protected:** `frag_id` uniqueness is report-wide (`Report.validate_references`); every fragment copied from a library entry into a finding must get a fresh id, with no exceptions.
4. **[app/web/static/app.js](../../app/web/static/app.js)** — add per-section banners for `description` and `recommended_remediation` in the Content-page `render()`, positioned the same way the existing proof-of-concept banner is.
   - **Show condition:** a library entry exists for `finding.library_ref?.library_id`, it has non-empty fragments for that section, `finding.content_offer_resolved?.[content.type] !== finding.library_ref.library_id`, and — for `recommended_remediation` only — `finding.status !== "resolved"`.
   - **Three choices**, each setting `content_offer_resolved[content.type] = finding.library_ref.library_id`:
     - *Keep mine* — no fragment change.
     - *Use library version* — `content.fragments` replaced with the entry's fragments (reminted), then the orphaned-evidence cleanup runs.
     - *Add library content* — the entry's fragments (reminted) appended after the existing ones, no de-duplication (Answer 4), then the same orphaned-evidence cleanup runs.
   - **Test (new, `tests/test_browser.py`):** title match → open Content page → both banners render once → each of keep/replace/merge-append resolves its banner and it does not reappear → an image fragment introduced via merge-append and later deleted has its evidence cleaned up, matching replace's behavior.
   - **Invariant protected:** orphan-evidence cleanup must run after **both** replace and merge-append, not replace alone (a merge-added image fragment can be deleted later just like a replaced one, per Round 2 oracle verdict); the `recommended_remediation` banner must never render while `finding.status === "resolved"`.
5. **[app/web/static/app.js](../../app/web/static/app.js)** — verify `applyCanonicalReport`/`reconcileCanonicalObject` merges `content_offer_resolved` generically (it is not on the fixed exclusion list that currently holds only `saved_at`, `app_id`, `_folder_name_hint`, `scope_text`).
   - **Test:** a resolution set client-side survives the next post-save canonical merge and the banner stays resolved.
   - **Invariant protected:** request/response symmetry for the new field — it must round-trip like any ordinary `Vulnerability` field.

### 2. `proof_of_concept` — generalize the existing twinned mechanism (per Answer 3)

6. **[app/report_service.py](../../app/report_service.py)** and **[app/web/static/app.js](../../app/web/static/app.js)** — extend the `apply_poc_variant`/`applyPocVariant` twin pair with a third mode, "merge-append," alongside today's replace. Merge-append must, like replace, preserve every `image` fragment untouched, remint every copied non-image fragment's `frag_id` (via the shared helper from step 3), then append the copies after the finding's existing non-image fragments (rather than replacing them), and still run `ensure_proof_steps`/`ensureProofSteps` afterward to guarantee a `numbered_list` exists.
   - **State tracking:** `poc_variant` and `poc_variant_declined` (already on `Vulnerability`, [app/models.py](../../app/models.py)) are reused, not replaced — `poc_variant` records the last-applied variant for replace *or* merge-append (both count as "installed" against that variant, so the offer stops reappearing for the same variant), `poc_variant_declined` continues to record "keep mine" refusals per variant exactly as it does today.
   - **Test:** extend the existing proof-of-concept coverage (wherever `apply_poc_variant`/`applyPocVariant` are exercised today) with a merge-append case verifying images are preserved, non-image fragments are appended not replaced, and `frag_id`s are fresh.
   - **Invariant protected:** this is a twinned rule (DATA_MAP §12) — the Python and JavaScript implementations must change together, or `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`-style drift becomes possible. `frag_id` uniqueness and the image-preservation guarantee that already protects `proof_of_concept` evidence must hold for merge-append exactly as they do for replace.
7. **[app/web/static/app.js](../../app/web/static/app.js)** — update the existing proof-of-concept banner's button set to offer three choices (keep / replace / merge-append) instead of two (fill from library / dismiss), reusing the same `written` (section-has-content) check that already drives its current label text.
   - **Test:** covered by the same browser test extension as step 6.
   - **Invariant protected:** the banner's show condition (`steps && finding.poc_variant !== variant && !poc_variant_declined.includes(variant)`) is unchanged; only the action set offered when it's visible grows from two to three.

### 3. Documentation

8. **[docs/DATA_MAP.md](../DATA_MAP.md)** — update §6 (new `content_offer_resolved` field on `Vulnerability`, with the explicit `null`-vs-`{}`-vs-missing guard: a missing key or `{}` both validate to an empty dict, but an explicit JSON `null` fails Pydantic validation, and no code in this plan ever writes `null` there); update §12 to list the `description`/`recommended_remediation` offer as client-only alongside the now-generalized `apply_poc_variant`/`applyPocVariant` row (still twinned, now three-way instead of two-way); revise the `replaceFromLibrary` bullet to describe its narrower, metadata-only role.
   - **Invariant protected:** the data-layer instructions require DATA_MAP to stay accurate whenever `app/models.py` or the save/navigation logic in `app.js` changes.

### Explicitly out of scope

- `previous_proof_of_concept` — never library-sourced; no code path today populates it from a library entry, so there is nothing for a keep/replace/merge offer to act on there.
- Any server-side route for the `description`/`recommended_remediation` offer — this mutation continues to ride the existing autosave PUT, exactly as `replaceFromLibrary`/`applyLibraryEntry` do today; only the `proof_of_concept` extension touches server code, because that mechanism already has a server-side twin.
- Fragment de-duplication for any "add library content" / merge-append choice, in any section (Answer 4).
- A Findings-page indicator for unresolved offers (Answer 2).
- A prompt for the silently-replaced metadata fields — `likelihood`, `impact`, `severity`, `library_ref` (Answer 1).
