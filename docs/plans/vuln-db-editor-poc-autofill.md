# Vulnerability library editor with proof-of-concept autofill

## Request

> now, bring back the vuln db editor. lets edit the vuln_library.json in the resources directory. I want to be able to edit all the details and also, add a section for proof of concept. make it so that, when the vuln from vuln db is loaded in the findings tab which replaces the contents, if the vuln in vuln db has a value in the proof of concept, depending on the tested app, API, WEB, or web and api, mobile, then those will auto fill the poc steps. ONLY THE PROOF OF CONCEPT. The previous proof of concept will not be touched by this.
>
> in the specific vuln in the vuln db, they will have a proof of concept steps for each tested app type. one for api, one for web, and one for api and web, and one for mobile.
>
> now the rulings are
> WHEN THE USER CHANGES THE TESTED APP TYPE IN THE SETUP PAGE:
> if the poc is already filled, and the user changes the tested app type(api, web, api and web, mobile), AND the vulns that are created has a poc in the new tested app type, then the user will choose if they will keep the current poc or replace with the saved poc.
> WHEN THE USER ADDS AN AFFECTED LOCATION OF ANOTHER TESTED APP TYPE (I think this will only apply for API and WEB(combined) app type since this is the only way users can add an affected location that has another app type)
> If the poc is not empty, and the vuln on the vuln db has a poc for that app type, the the users will choose again if retain or replace with saved poc.
>
> also, when a tester selects the api and web in the setup/scope, the affected locations should still be considered separate app types. so that when a user selects an affected location of, for example, api, then goes next to the content page, fills up the poc, then goes back to the findings page, then selects web, they have the choice to replace the poc with the saved poc(for api and web) in vuln db or retain. and when the api affected location is unselected, they will again have a choice of replacing the poc with saved poc(for web only since the api is unselected) in vuln db or retain the current poc.
>
> but if the poc is empty, then there will be no choice as there will be no conflict in the data
>
> also, this is what i need help with. When will we notif or prompt the user to retain or replace. what I was thinking is to prompt them when they get back to the contents page. In the POC section, there is a notif there that a saved vuln is available and asking them to retain or replace for the specific app type. I think also, that after clicking next to contents page, the empty poc will already be filled if the poc is empty and the vuln has a poc for that app type.
>
> Also, I want the vuln db editor to not be pushed in github. I want this to be like a separate entity. I know that the vuln db will be edited and will be pushed to the github and that is okay. I just do not want to ship the vuln db editor.
>
> ask me for clarifications or considerations or if you have a recommendation or questions for better output.

---

## Round 1 - Oracle: how it works today

### A. Library entry shape

**A1.** `LibraryEntry` ([app/library.py](../../app/library.py)) has exactly ten fields: `library_id`, `source_id`, `title`, `tags`, `default_likelihood`, `default_impact`, `default_severity`, `requires_tester_input`, `status`, `contents`. Wrapped by `LibraryDocument` (`schema_version`, `source`, `entry_count`, `entries`). **No proof-of-concept field, no per-test-type field, no channel field exists anywhere on an entry.**

**A2.** 51 entries, all carrying all ten keys (510 key matches = 51 x 10). `default_likelihood` / `default_impact` / `default_severity` are `null` on the same 25 of 51. `requires_tester_input` true on 11. Every entry has exactly two content sections, `description` and `recommended_remediation`. **No entry has a `proof_of_concept` section, and no entry contains a single `numbered_list` fragment.**

**A3.** Validated by Pydantic at construction, then flattened: `self.entries = [entry.model_dump(mode="json") ...]`. Construction happens at **module import** in `main.py`, so an invalid library file is a startup crash across every report, not a request-time error.

### B. Content sections and the PoC

**B4.** Sections are identified by `type`, a closed `Literal` with five members: `description`, `recommended_remediation`, `previous_proof_of_concept`, `proof_of_concept`, `in_conclusion`. Which sections a finding has is **derived from `status`**, not stored: `provision()` rebuilds `contents` on every save from a fixed list, and **discards any section not in that list**.

**B5. The separation the request depends on already exists.** `proof_of_concept` and `previous_proof_of_concept` are independent first-class sections with distinct DOCX anchors (`poc-fragments-here` vs `prev-poc-fragments-here`). The selector `content.type == "proof_of_concept"` is already used verbatim on both sides. **Caveat:** today's library insert does not target sections at all, it replaces the whole `contents` array, so the isolation exists in the schema but not in the current insert path.

**B6.** A "step" is **one `ListItem` inside a `numbered_list` fragment** in a PoC section. There is no `step` fragment type. `provision()` seeds one `numbered_list` with one empty item into both PoC sections, and the readiness panel relabels list items to "step" only for those sections. The client restricts PoC sections to `numbered_list, image, bulleted_list, instance_title, note, code_block` — **client-only, the server accepts any fragment there**.

### C. Tested app type and locations

**C7.** `TestType = Literal["web", "api", "mobile", "web_api"]`, a **single** value, default `"web"`.

**C8.** `test_type` and `tested_environments` are orthogonal axes multiplied into the scope grid. `channels_by_type = {web:[web], api:[api], mobile:[mobile], web_api:[web,api]}`. `reconcile_targets` emits one `ScopeTarget` per environment x channel x line.

**C9. The user's premise holds — `ScopeTarget` carries its own channel.**

```python
class ScopeTarget(BaseModel):
    target_id: StableId
    environment: Environment
    channel: Channel        # Literal["api", "web", "mobile"]
    value: str
    order: int = 0
```

**Two gaps:**
1. `Scope.custom_locations` is keyed by **environment only**. A tester-typed custom location has **no channel at all**, and there is no field to hold one.
2. Non-`custom` scope modes hold no `target_ids`; channel must be re-derived. `affected_environments` returns **environments only**. **There is no `affected_channels` function in either language.**

**C10.** `Scope` = `{mode, target_ids, location_values, custom_locations}`. `mode` is `all | all_production | all_non_production | custom`. Only `custom` has its `target_ids` validated against `scope_targets`.

### D. Library insert today

**D11.** Three paths:
- **Path 1, "add from library" search box** — server-authored `POST /reports/{id}/library/{library_id}`, builds a brand-new `Vulnerability`, `assign_fresh_fragment_ids`, `provision`. Nothing overwritten, it is a new row. Scope defaults to `mode="all"`.
- **Path 2, finding-row title combobox** — client-authored and destructive. `replaceFromLibrary` confirms, then `applyLibraryEntry` does one `Object.assign` that overwrites `title`, `likelihood`, `impact`, `severity`, `library_ref`, and **`contents` wholesale**. Preserved by omission: `uid`, `display_id`, `status`, `scope`.
- **Path 3, editor-page title combobox** — rename only, by deliberate design, asserted by a test.

**D12. The DATA_MAP entry was wrong.** `applyLibraryEntry` is indeed defined twice, byte-identical, at 1247 (`setup()`) and 1961 (`continuousEditor()`) — but **the 1961 copy is dead code, never called**. The only call site is 1243, inside `replaceFromLibrary`, in `setup()` scope. It should be deleted, not kept in sync.

### E. Existing retain-or-replace machinery

**E13.**
- **`confirmScopeLoss`** — fires on Test Surface `<select>` change and on unchecking an environment. Lists findings that would be stranded, `window.confirm`, cancel reverts. **Proceed/abort only, counts locations, never touches content.** Closest existing hook to "user changes tested app type".
- **`settleScopeChange`** — fires from the three "affected locations changed" call sites. Diffs environments, and if a lost environment had an image with evidence or a caption, confirms. **Unit of decision is environment, never channel; subject is images, never PoC steps.**
- **`replaceFromLibrary`** — the only existing retain-or-replace prompt, all-or-nothing over the whole `contents` array.
- **`reconcile_targets` 422 `referenced_scope_removed`** — server-side, only when `scope_text` is in the payload. **Hard reject of the whole save**, no partial apply.

**E14.** `library_ref` = `{library_id, source_id, inserted_at}`. Read in exactly two places, both as an idempotence guard. It stores **no content hash, no section list, no test_type, and no record of which PoC variant was applied**. Nothing today can answer "was this PoC autofilled, and from which variant?"

### F. Migration reality

**F15.** A new key on an entry is **silently dropped twice over**: Pydantic v2 defaults to `extra="ignore"` (proved by the `_README` array that lives in the file and is invisible at runtime), and `Library.__init__` re-serializes through `model_dump`. Any new PoC data **must be a declared `LibraryEntry` field or it will not exist at runtime**. What *is* rejected, hard, at import: unknown `Content.type`, unknown fragment `type`, a list fragment with zero `items`, `entry_count` mismatch, duplicate `library_id`, duplicate `frag_id` within an entry.

**F16.** A new `Vulnerability` field with a default loads cleanly. A new `ContentType` member loads cleanly and is created on next save by `provision()` — but **a section added to `ContentType` and not to `provision()` is silently erased on the first save**. `Workspace.load_path` is the single correct place for legacy repair; it already handles two cases.

### G. Shipping exclusion

**G17.** `.gitignore` mentions the library once, `vuln_library.bak.json`. **Both `vuln_library.json` and `resources/vuln_library.json` are tracked, with the same blob SHA — byte-identical right now.** No library-editor route, template, asset, or write path exists in the repo today, so **there is no existing exclusion mechanism to extend**.

**Live bug found:** `Preferences.library_path` defaults to `"vuln_library.json"` (the root copy) and that value is written into a fresh `prefs.json` on first launch. `main.py`'s `resources/` fallback only applies when the key is **absent**. This machine's ignored `prefs.json` says `resources/`, so **a fresh clone reads the root file, not `resources/`.**

### Invariants in play

1. **`provision()` owns the section list; anything outside it is deleted on save.**
2. **Content types are unique per finding** — so "one PoC set per test type" **cannot** be modelled as four `proof_of_concept` blocks on a finding.
3. **`frag_id` is unique report-wide.** Any copy-in must remint, or the draft corrupts on save.
4. **`ListFragment.items` must be non-empty.** A PoC set stored as a `numbered_list` with zero steps fails validation, and the library has no repair hook.
5. **The library is validated once, at import.** A bad file is a boot failure.
6. **Extra keys on a library entry are dropped twice over.**
7. **`ScopeTarget` identity is the `(environment, channel, value)` triple.** Changing `test_type` destroys targets on dropped channels and remints IDs if they return, so **`scope.target_ids` do not survive a test-type round trip**.
8. **`scope_text` is request-only**, and the 422 guard only runs when it is present.
9. **`saved_at` is the only concurrency token.**
10. **Dropping an `evidence_id` from JSON is what deletes the image file.**

### Both-sides warning

| Rule | Python | JavaScript |
|---|---|---|
| status to section list | `provision` | `provision` **and a second inline copy** in the status `onchange` — three places total |
| required seed fragments | `required_fragments` | `required` — **these already disagree**: Python seeds `["numbered_list"]` for PoC sections, JS seeds `["numbered_list","image"]` |
| test_type to channels | `channels_by_type` | `testTypes` |
| library entry to finding | `insert_library` | `applyLibraryEntry` |
| affected environments | `affected_environments` | `affectedEnvironments` / `scopeEnvironments` |

### Map drift reported

1. Section 13 bullet on `applyLibraryEntry` is **materially wrong** — the second copy is dead code, not a parallel implementation.
2. Section 12 "provisioning and image slots" asserts a parity that does not exist (`required_fragments` already differs), and omits the third inline copy of the status-to-section mapping.
3. Section 1 says `resources/vuln_library.json` is what the app reads; that is true only because of this machine's ignored `prefs.json`. A clean clone reads the root copy.


## Round 1 - Planner: proposal and open questions

**Shape proposed:** `LibraryEntry.proof_of_concept: dict[TestType, list[Fragment]]`; new `affected_channels()` + `applicable_poc_variant()` in Python and JS; `apply_poc_variant()` replacing only non-image fragments in the `proof_of_concept` section; `LibraryRef` gains `poc_variant` + `poc_declined` as decision memory; both insert paths wired; a **state-derived banner on the Content page**; a gitignored editor behind a conditional mount; the `library_path` bug fixed first.

**Nine open questions raised:** channel for tester-typed custom locations; `web_api` fallback when the entry lacks that variant; whether "Keep" persists and at what granularity; whether the findings-row library replace also installs the variant; root vs `resources/` library copy; whether the editor may create/delete/re-key entries; concurrency for the library file; whether variants ship in the inlined per-page library payload; whether "the PoC is empty" counts auto-provisioned image slots.

**All ten data-risk rows marked RISK.**

**Key reasoning on the user's timing question — recommended a state-derived banner on the Content page, not an event-fired prompt at the moment of the scope change**, because: the triggering events happen on the wrong page and before `reconcile_targets` has produced the targets the decision depends on; there is no router, so a prompt queued on Findings is destroyed by navigating to Content; `confirmScopeLoss` and `settleScopeChange` already fire `window.confirm` on those exact interactions, so a third would turn one scope edit into N blocking modals; and a derived banner is idempotent, survives reload, survives a 409.

**On "fill on clicking Next":** do it on *arrival* at the Content page, not in the `#next` handler, because Next is only one of four ways in (stepper, back-link from a later page, direct URL, reload).

**What it refused to do:** store the four variants as four `proof_of_concept` entries in the library entry's existing `contents` array. It validates on the library side, but both insert paths copy `contents` wholesale, `provision()` collapses duplicates via `{content.type: content}` keeping only the last, and `Report.validate_references` then raises `duplicate content type for finding` at the save boundary, taking the tester's other edits in the same payload with it.

## Round 2 - Oracle: verdict on the proposal

Fifteen claims checked against source. **Confirmed:** the library has no content-type uniqueness check while `Report.validate_references` does raise on it; `provision()` really does collapse duplicates last-one-wins; the prefs test really does pin the buggy default; image slots really are appended into `proof_of_concept` in both languages; `.gitignore` semantics; `#next` really does navigate only on `saved`; `Fragment` and `TestType` are importable into `library.py`; **no existing draft breaks**.

**Corrections:**

- **`hasContent` is not reusable.** It is a local closure inside an `onclick`, per-fragment not per-section, with no Python twin (`_fragment_has_text` is paragraph-only).
- **The re-seed mechanism was wrong.** The copy needs *both* the configured path and `resources/` to be missing. Because a fresh `prefs.json` writes a **present** `library_path` key pointing at the root file, which exists, the `resources/` fallback **never fires**. The app reads the wrong file outright.
- **`continuousEditor()` mutates on load but marks nothing dirty and schedules no save.** That precedent works only because those functions have exact server twins. Autofill has none, so it would sit unsaved and vanish on tab close unless it calls `scheduleSave()` explicitly.
- **`library_ref` is rebuilt as a fresh three-key literal** by both insert paths, so decision memory stored there is destroyed on every library replace. Hand-added findings have `library_ref: null`.
- **There is no `APIRouter`/`include_router` anywhere in `app/`.** Every route is a decorator on the module-level `app`. Worse, `library = Library(...)` runs at import line 47, *before* `app` exists at line 49, and flattens once into `library.entries` — so **an editor writing the file on disk does not change what the app serves**.
- **The big miss: `scripts/html_to_fragments.py` is the generator that produces the library**, and the `_README` it writes says "DO NOT hand-edit -- edit the List and re-run the converter." Re-running it would wipe every hand-authored variant.
- **Other missed files:** `docx_report.py` L622 (same collapse at render time, owns both PoC anchors), `app.js` L94 `allowed` map (PoC forbids `paragraph` and `table`), `app.js` L1470 (third inline copy of the status-to-section list), `docs/FORM_DEPENDENCIES.md`, `docs/ROUTES.md`, `tests/test_app.py` L76 / `tests/test_browser.py` L375, `tests/test_app.py` L759.
- **`validate_fragment_ids` iterates `self.contents` only**, so a new sibling field is invisible to it; and `assign_fresh_fragment_ids` only walks `vulnerability.contents`.

**Risk rescoring.** Overstated, already handled by existing code: `frag_id` uniqueness (repair exists, both paths remint), `saved_at` (working guard end to end), evidence deletion (already mediated), extra-keys-dropped. **Understated:** library-validated-at-import is not a boot risk but an **unrecoverable startup crash with no route to the editor that would repair it**; a zero-item list inside a variant is the same crash and the library has **no repair hook**; the status-to-section map has **three** copies, not two.

**Existing data, all 11 drafts:** nothing breaks. But **every scope is `mode: "custom"`**, so the `all` / `all_production` / `all_non_production` branches of any new channel derivation have **zero coverage from real data**. Two drafts have channel-less `custom_locations`; the only `web_api` draft has a finding with one channel-bearing target **and** two free-typed endpoints simultaneously, and all five of its findings already hold tester PoC content.

## Round 2 - Planner: revised plan

**C1.** Emptiness predicate dropped entirely. Autofill fires **only at insert time**, where the section is empty by construction. No `hasContent` lift, no Python twin.

**C2.** Fix the prefs default rather than guard the re-seed: change `Preferences.library_path` to `resources/vuln_library.json`, migrate existing prefs holding the old value, update the pinning test.

**C3.** No load-time autofill, so no unsaved state. Only writers are the insert paths (which already save) and the banner's Replace button (a user action that calls `scheduleSave()`).

**C4.** Decision memory moves **off `LibraryRef`** onto `Vulnerability` itself: `poc_variant` and `poc_variant_declined`. Survives library replace and works for findings never sourced from the library.

**C5.** No router. A plain decorator on the module-level `app`, behind a module-level environment-variable check. Visibility solved by rebinding the module global `library` to a fresh `Library` after a validated write — one atomic name rebind, never an in-place mutation.

**C6.** **Variants move to a sidecar, `resources/poc_variants.json`.** The converter never learns about PoC and cannot wipe it; one `_README` line changes.

**C7.** `docx_report.py` needs no change (variants resolve into `contents` at insert, so the renderer never sees two PoC sections). Do **not** widen the `allowed` map; constrain the editor to the six types PoC already permits.

**C8.** The sidecar gets its own model and its own uniqueness loop; `validate_fragment_ids` untouched. Place the variant copy **before** `assign_fresh_fragment_ids` so the existing remint covers it with no new code.

**C9.** Accepted. Five rows drop to clear; the library-crash row becomes the top risk and is why the editor validates before writing and the sidecar degrades to skip-with-warning rather than fatal.

**C10.** Re-keyed variants from `TestType` to `Channel`, and ruled that a finding resolving to more than one channel gets **no variant at all**.

> **Coordinator note — this last decision contradicts the request.** The user asked for four variants including "api and web" combined, and described the combined case explicitly: selecting a web location alongside an api one should offer the saved combined PoC. The planner's Round 1 rule (exact set match: `{api}`->api, `{web}`->web, `{api,web}`->web_api, `{mobile}`->mobile) satisfies that; the Round 2 revision over-corrected and drops it. Put to the user as question 2 rather than settled here.

**Sidecar design:** root `vuln_library.json` stays the converter's output and its "do not hand-edit" warning stays true; `resources/vuln_library.json` is the bootstrap copy the app reads; `resources/poc_variants.json` is the editor's file, `{library_id: {variant: [fragments]}}`, never regenerated. `Library.__init__` merges the sidecar onto matching entries before flattening. Orphaned ids (entries the converter no longer emits) are **retained and surfaced as a count**, never silently dropped.

**Editor write sequence:** parse payload into the sidecar model, reject on failure; construct a throwaway `Library` against the would-be state and reject if it raises; `atomic_write_bytes`; rebind the global. Known accepted limitation: a report tab opened before the edit keeps the old inlined `data-library` until reloaded.

## Answers

1. **Variants live inside the library file itself** (`resources/vuln_library.json`), not a sidecar. A backup copy already exists.
2. **Keep the combined api+web variant.** Four variants.
3. **Give free-typed locations an app type** rather than staying silent. User asked for a better option if one exists.
4. **No silent autofill at all.** Even an empty PoC gets a confirm step, never a silent write.
5. **Remember the decision**, but show it again when the app type or affected locations change.
6. **Gitignored editor** accepted, with the tracked validation test as mitigation.
7. **Fix the path bug.** All library reads go to `resources/`; root stays an untouched pristine backup.

### Resolutions the answers produced

**Q1 is safe because of Q7.** The converter's default output was `-o vuln_library.json`, the **root** file, and it did a plain total-overwrite `out.write_text` with no read or merge of the existing file. That made storing PoC steps in the library safe, since the app and editor work on `resources/vuln_library.json`.

**Superseded by decision 8:** the converter is being deleted outright, so the question is moot. There is now exactly one library file the code knows about.

| File | Written by | Tracked | Holds PoC steps |
|---|---|---|---|
| `resources/vuln_library.json` | the editor | yes | yes |
| `vuln_library.json` (root) | nothing | **no, untracked** | irrelevant, unreferenced |

The root copy stays on disk purely as a local master to fall back on by hand.

**Q3 resolution — split the Findings-page location groups by channel.** The Findings page currently groups affected locations as `{production: [], non_production: []}` — environment only. Under `web_api` the Production group mixes web and api targets with no distinction, and "Add location" writes a channel-less string. The Setup page already builds its scope textareas per environment x channel, so this makes the two pages agree. Every location then carries an app type and variant derivation always resolves.

Rejected alternative (the user's first suggestion): inferring the finding's app type from which PoC variants the library entry happens to have. That conflates "the library has api steps" with "this finding affects the api", so every entry with an api variant would claim to be an api finding.

### Final decisions, round two

8. **The converter is deleted.** `scripts/html_to_fragments.py` goes, along with `tests/test_converter.py` (3 tests, suite 84 -> 81) and the [docs/PLAN.md](../PLAN.md) entry. The library is no longer sourced from SharePoint, and a future source may not be SharePoint either. Git history keeps it.
9. **The root `vuln_library.json` is untracked.** It stays on disk as the local master copy to fall back on, is added to `.gitignore`, and **no code references it any more**. The app touches `resources/vuln_library.json` and nothing else.
10. **The `_README` block inside the library file is rewritten.** It currently says "Generated by scripts.html_to_fragments ... DO NOT hand-edit", which inverts once the converter is gone and the editor arrives.
11. **No `custom_locations` repair.** Existing drafts are disposable, so old-shape drafts simply show as invalid until deleted.
12. **PoC steps are one per line, plain text.** No rich-text authoring inside a step.
13. **No special handling for placeholder text** in PoC steps. The existing readiness check already flags it, which is the wanted behaviour.
14. **Editor scope:** edit all fields and create entries; `library_id` is read-only once an entry exists; deletion is a `status` change to `retired`, never a removal. This keeps every `library_ref` in every saved draft pointing at something real.
15. **Editor entry point:** type the URL directly. No link in tracked code, so nothing dangles when the module is absent.
16. **`entry_count` is recomputed on every write**, never trusted from the browser. The now-meaningless `source` field is left alone rather than forcing a schema change.

## Agreed plan

**Step 1 — Fix the library path, and make `resources/` the only library. Own commit, before anything else.**
Files: `app/tester_identity.py` (`Preferences.library_path` default to `resources/vuln_library.json`), `app/main.py` (bootstrap stops referencing the root copy entirely), `tests/test_app.py` (the assertion at ~772 pins the old default), `.gitignore`.
Also in this step: migrate an existing `prefs.json` whose value is exactly `vuln_library.json`, and untrack the root copy with `git rm --cached` so it survives locally but leaves the repository.
Test: a fresh `prefs.json` resolves to the `resources/` copy; the existing prefs test updated.
Invariant: the file the editor writes is the file the app reads, and it is the only library the code knows about.

**Step 1b — Delete the converter.**
Files: remove `scripts/html_to_fragments.py` and `tests/test_converter.py`; drop the entry from [docs/PLAN.md](../PLAN.md); rewrite the `_README` block inside `resources/vuln_library.json`.
Test: the suite still collects and passes at 81.
Invariant: nothing under `app/` imports it, so this is a pure removal.

**Step 2 — Declare the variants on `LibraryEntry`.**
Files: `app/library.py`.
`proof_of_concept: dict[TestType, list[Fragment]] = Field(default_factory=dict)`, keyed on the existing `TestType` literal so `web_api` is expressible. A second validator loop, separate from `validate_fragment_ids`, enforcing `frag_id` uniqueness **within each variant** while allowing repeats across variants. Reject a variant whose list is empty, so "no variant" has exactly one representation.
Test: round-trip through `model_dump`; `{"api": []}` rejected; duplicate ids across `api` and `web` accepted, duplicates within one variant rejected.
Invariant: extra keys are dropped twice over, so an undeclared field does not exist at runtime.

**Step 3 — Channel-aware locations.**
Files: `app/models.py` (`Scope.custom_locations` gains a channel dimension), `app/web/static/app.js` (`locationGroups`, the add/remove handlers, and the render at ~1442).
The Findings page currently groups locations as `{production, non_production}`. It gains a channel dimension so a tester adds an endpoint under a specific app type and the app knows which it is.
**Refinement: only split visually when `test_type` is `web_api`.** For `web`, `api`, and `mobile` the channel is already unambiguous from the engagement, so the existing two-group UI stays and the channel is filled in implicitly. This adds the split only where it carries information.
Existing drafts are being discarded, so no `load_path` repair is strictly required. A three-line repair is still recommended so that any real report authored between now and then survives.
Test: adding a location under Production/API on a `web_api` report records `channel: "api"`; a `web` report's UI is unchanged and still records `web`.
Invariant: every affected location carries an app type, so variant derivation always resolves.

**Step 4 — Derive the variant, in both languages, in one commit.**
Files: `app/report_service.py` (`affected_channels`, `applicable_poc_variant`), `app/web/static/app.js` (`affectedChannels`, `applicablePocVariant`).
Exact set match: `{api}` to `api`, `{web}` to `web`, `{api,web}` to `web_api`, `{mobile}` to `mobile`, empty to none. Derive from `scope_targets` and channel-tagged custom locations, never from `scope_text` (request-only) and never from `engagement.test_type` alone.
Test: Python unit tests per scope mode including the three `all*` branches, which need a purpose-built fixture since no draft on disk exercises them. Browser test: a `web_api` report with only an API location resolves to `api`, then to `web_api` when a web location is checked.
Invariant: this is now a both-sides rule; it changes on both sides together.

**Step 5 — Apply a variant without disturbing anything else.**
Files: `app/report_service.py`, `app/web/static/app.js`.
`apply_poc_variant`: find `content.type == "proof_of_concept"`, keep every `image` fragment exactly as-is, replace the non-image fragments with deep copies of the variant, remint every `frag_id`, record `poc_variant` on the finding. Never touches `previous_proof_of_concept`. On the server path, place the copy **before** `assign_fresh_fragment_ids` so the existing remint covers it.
Test: replacing a PoC holding an uploaded screenshot leaves the `evidence_id` intact and the file referenced; `previous_proof_of_concept` is byte-identical before and after.
Invariant: `frag_id` unique report-wide; dropping an `evidence_id` is what deletes the image file.

**Step 6 — Decision memory on the finding, not on `library_ref`.**
Files: `app/models.py`.
`Vulnerability` gains `poc_variant: TestType | None = None` (which app type the steps currently in the PoC came from, `None` when tester-authored) and `poc_variant_declined: list[TestType] = Field(default_factory=list)`.

The rule, which satisfies both branches the user described:

> Prompt when a variant exists for the derived app type **and** `poc_variant != derived` **and** `derived not in poc_variant_declined`.
> **Use saved steps** sets `poc_variant = derived` and **clears** `poc_variant_declined`.
> **Keep mine** appends `derived` to `poc_variant_declined` and leaves `poc_variant` alone.

Clearing the declined list on replace is what makes api -> web_api -> api re-prompt: the earlier "keep mine" referred to content that has since been overwritten, so it is stale. Without the clear, a stale decline silently suppresses a genuine mismatch.

Both fields default, so existing drafts load unchanged with no repair. They live on the finding because both insert paths rebuild `library_ref` as a fresh three-key literal and would erase anything stored there, and because hand-added findings have `library_ref: null`.
Test: the full api -> web_api -> api sequence, once replacing at each step (re-prompts) and once keeping at each step (does not).
Invariant: `provision` owns sections, not fields, so these survive every provisioning pass.

**Step 7 — The confirm banner. No silent writes, ever.**
Files: `app/web/static/app.js` (`continuousEditor`), `app/web/templates/page2_editor.html`.
Rendered per finding inside the `proof_of_concept` section header, derived from current state only:

| Variant exists | PoC has tester work | Applied or declined | Behaviour |
|---|---|---|---|
| no | - | - | nothing |
| yes | no | no | banner: "Saved {label} steps are available." -> *Fill from library* / *Dismiss* |
| yes | yes | no | banner: "Saved {label} steps are available." -> *Keep mine* / *Use saved steps* |
| yes | - | yes | nothing |

Writes only on click, never during render, and the click calls `scheduleSave()` explicitly — `continuousEditor` mutates on load today but marks nothing dirty, and this has no server twin to recompute it. Suppressed while `saveConflict` is set. Emptiness now only picks the button label, so getting it wrong is cosmetic rather than destructive.
Test: all four rows; reload does not re-prompt; dismiss then return does not re-prompt; changing the derived variant does re-prompt.
Invariant: the banner reads state and writes only on an explicit click.

**Step 8 — The editor.**
Files: `app/library_editor.py` + template + static asset, all gitignored; `.gitignore`; `app/main.py`.
Route is a plain decorator on the module-level `app` behind an environment-variable check — there is no `APIRouter` anywhere in this codebase to follow. Reached by typing the URL; nothing in tracked code links to it.

**Write sequence — validate the actual bytes, then promote atomically:**

1. Serialize the new library to JSON bytes.
2. Write those bytes to a temp file beside the real one.
3. Run `Library(temp_path)` — the exact code path that runs at boot, against the exact bytes that will land on disk.
4. Raises: delete the temp file, return 422, the original is untouched.
5. Passes: `os.replace` the temp over the real file.
6. Rebind the module global `library` to the new instance. Never mutate `library.entries` in place.

This is the user's staging idea with the staging file made transient, so it cannot go stale or drift from the real file. `atomic_write_json` already implements steps 2 and 5; only the validation in step 3 is new.

**Second layer — make the boot load non-fatal.** Validation stops the *editor* writing a bad file, but corruption can arrive from a hand edit, a bad merge, or a disk fault. Wrap the import-time `Library(...)` so a failure degrades to an empty library that remembers why, instead of killing startup. Library search returns nothing and the pages say so; reports still open, save, and generate, and the editor still loads so the file can be repaired. Without this, a bad library is unrecoverable — it is constructed before the `app` object exists, so there is no route to the tool that would fix it.

**The editor must preserve the `_README` key.** It is not a declared field on `LibraryDocument`, so a naive round-trip through `model_dump` silently deletes it.

Tracked mitigation test: `Library(ROOT / "resources" / "vuln_library.json")` constructs without raising, and the app boots with the editor file absent.
Invariant: a write that would not load must never reach the real path.

**Step 9 — Docs.**
[docs/DATA_MAP.md](../DATA_MAP.md) (the drift the oracle found is already corrected; the library-file and PoC sections follow the code), [docs/FORM_DEPENDENCIES.md](../FORM_DEPENDENCIES.md) (new dependency row for app type and affected locations driving the PoC section), [docs/ROUTES.md](../ROUTES.md) (editor noted as intentionally unshipped), [docs/PLAN.md](../PLAN.md) (converter entry removed in step 1b).

These are written **as each step lands**, not in advance, so they never describe something that does not exist yet.

