# Data Map

The single reference for how report data is shaped, saved, and moved through this app.

> **Maintenance contract.** This file is the source of truth consulted by the `data-oracle` agent. Any change to `app/models.py`, `app/storage.py`, `app/workspace.py`, `app/report_service.py`, or the save/navigation paths in `app/web/static/app.js` must update the affected section here in the same change. Line numbers are hints only; function and field names are the durable identifiers.
>
> Last verified against source: **2026-09-15**, after a stress pass on scope and affected locations fixed three faults, all in the "additional affected locations" box: a `#` line counted as the finding's location, opened the Content page, and printed in the document as a place that was tested; the same endpoint typed twice, or with stray spacing, printed twice; and a line left under an environment or app type the engagement does not cover still counted, because `reconcile_targets`' coverage filter only runs on a save that carries `scope_text`, which no page but Setup sends. `location_lines` is the new single owner of which typed lines name a real place, twinned as `locationLines`, and `scope_has_location`/`affected_environments`/`affected_channels` now ignore anything outside the engagement's coverage. Before that, after retiring `Scope.mode`'s three non-custom values. A finding's locations are now always the explicit `target_ids` it selected, so "no ticked location" and "blocked" are the same statement on both sides; `normalise_scope_modes` freezes any retired mode into the IDs it resolved to; and `reconcile_targets` now purges removed IDs rather than refusing the save, reserving its 422 for a finding left with no location at all. Before that, after a scope-mode audit: section 12's "scope resolves to a location" row paired two functions that answer different questions — `scope_has_location` returns `bool(scope.target_ids)` and never checks that those IDs resolve against `scope_targets`, while `_scope_reaches_a_location` intersects them against the surviving targets — so the row is now split, and `scope_has_location`'s honesty is recorded as resting on `Report.validate_references` plus the survivor filter in `reconcile_targets` rather than on anything it checks itself; `docx_report.CHANNEL_ORDER` is a `list()` copy of `models.CHANNELS`, not a re-export of it, so the two are value-identical but not the same object. Before that, after a stress pass on derived state fixed five faults: `provision` now carries a section the status does not print when it still holds tester work, instead of deleting last year's proof outright (`content_types_for_status` and `content_has_work` are the new shared owners, twinned in `app.js`); `sync_evidence_image_slots` no longer re-stamps an uploaded screenshot's `environment` when a finding narrows to one environment, and removes an untouched slot for a dropped environment rather than leaving a second demand behind; the same function now fills a blank `environment` on the `previous_proof_of_concept` slot it created, which `generation_issues` required and nothing else assigned; `reconcile_targets` now reports a `custom` finding stranded because its only typed locations were under a dropped app type, matching the mode-scoped case; and `generation_issues` skips sections the status does not print. Recorded in the same pass: `insert_library` pins a new finding to `scope.mode == "custom"` rather than the `Scope` default of `"all"`, and `scripts/package_release.py` ships `app/` and `resources/` while deliberately leaving `data/` and `generated/` behind. Before that, after correcting section 12's scope rows: the JavaScript twin of `_scope_reaches_a_location` is `scopeReaches`, which the map never named and which now takes a third `coverage` argument that Python gets instead by mutating `scope["custom_locations"]` before its second call; `docx_report._finding_locations` is a fourth `scope.mode` consumer the map never listed; the scope-text survival row pairs two functions that do **not** implement the same predicate; and the Findings page silently rewrites `target_ids` on every non-custom scope it renders. Before that, after correcting section 12, which called the client-side confirmation guards "the `window.confirm` guards" — there is no `window.confirm` in `app.js`; all seven sites use `window.vrDialog.confirm`, which does not block the thread. Same day, after documenting the undo/redo stacks and their reload in sections 9 and 10 (they were client state and a navigation path the map never recorded). Before that, after replacing `engagement.test_type` with `engagement.tested_channels: list[Channel]` (Setup now renders app-type checkboxes, so mixed and all-three coverage is expressible), retiring the `web_api` token from the type, the library, and the library editor, making proof-of-concept variants per-channel and multi-select (`poc_variants` plural, `merge_step_lists` collapsing appended steps into one numbered list), and moving app-type normalisation out of `load_path` into a `Report` `mode="before"` validator so `import_report` and `parse_import` are covered too. Earlier in the same pass: per-content-section keep/replace/add offers (`content_offer_resolved` on `Vulnerability`), requiring at least one fragment in `description` and `recommended_remediation` on both sides, making `previous_proof_of_concept` a historical record, and renaming report folders after the application and its report type.

---

## 1. Where data lives

No database. Everything is JSON and PNG files under `data/`.

```
data/
  prefs.json                                   app-wide preferences (library_path, tester)
  .locks/<sha256-of-report_id>.lock            OS advisory lock, one per report
  apps/
    <LETTER>_<app_id>/                          e.g. N_CI-78421, X_unnamed
      <YYYY-MM>_Report_<report_id-without-r_>/  e.g. 2026-09_Report_7edb3423a1bc
        draft.json                              the report
        draft.bak.json                          previous revision, written on every save
        evidence/<evidence_id>.png              uploaded images
resources/vuln_library.json                     the vulnerability library, and the only one the app reads
vuln_library.json                               untracked local backup; no code references it
generated/                                      finished .docx output
```

**Folder names are derived, not authoritative.** A report is located by scanning every `apps/*/*/draft.json` and matching the `report_id` field (`Workspace.find_path`). Renaming a folder by hand does not break lookup; editing `report_id` inside the file does.

**Report data never ships.** `scripts/package_release.py` builds `dist/<name>.zip` from `run.py`, `requirements.txt`, `README.md`, `app/`, and `resources/` only. `data/` and `generated/` are deliberately left behind, so a release zip carries the library but no drafts, no evidence, and no finished documents. `dist/` is a build output and gitignored.

**The library is resolved once, at import.** `prefs.library_path` (default `tester_identity.LIBRARY_PATH`, `resources/vuln_library.json`) is resolved against the repository root when relative. A prefs file still naming the bare root copy is migrated to the real path by `Preferences.validate_library_path`.

`Library.load_or_empty` is used instead of the constructor because the library is built **before the `app` object exists**. A missing, malformed, or invalid file would otherwise stop the app from starting, leaving no route to the tooling that would repair it. On failure the app serves an empty library, records why in `library.load_error`, and prints it at startup; reports still open, save, and generate.

---

## 2. Identity and derivation

| Value | Format | Derived from | Function |
|---|---|---|---|
| `report_id` | `r_` + 12 hex | random, assigned once at creation | `Workspace.create_report` |
| `app_id` | filesystem-safe string | `ci_number` or `bsn_number` or `app_name`, else `unnamed` | `app_id_for` |
| app folder | `<FirstLetter>_<app_id>` | first ASCII letter of `app_name`, else `X` | `Workspace._save_unlocked` |
| report folder | `<YYYY-MM>_Report_<report_id[2:]>` | save-time month | `Workspace._save_unlocked` |
| `evidence_id` | `ev_` + 12 hex | random at upload | `persist_uploaded_evidence` |
| evidence file | always `evidence/<evidence_id>.png` | enforced by validator | `Report.validate_references` |

**`app_id` is derived once, then frozen.** `app_id_for` is called from exactly two places, and both are guarded by `if report.app_id == "unnamed"` — `main.rename_report` and `main.save_report`. `save_report` also overwrites the submitted `app_id` with `prior.app_id` before validation, so the browser can never change it. Once `app_id` holds a real value, editing `ci_number`, `bsn_number`, or `app_name` does **not** re-derive it and does **not** move the folder. `Workspace.import_report` never calls `app_id_for` at all; it persists whatever `app_id` the payload carried, and `app_id` is a required field on `Report` with no default.

**Folder migration:** a report saved while `app_id` is `unnamed` lands in `X_unnamed/`. The *first* save after the CI, BSN, or app name is filled in moves the directory to its real home (`existing.parent.replace(desired.parent)`) — but only because `_save_unlocked` gates that move on `existing.parent.parent.name == "X_unnamed"`. There is no second migration. Anything caching the old path across that save is holding a stale path.

**`safe_name`** strips `<>:"/\|?*`, collapses whitespace to `_`, trims to 60 chars, and substitutes a fallback for Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).

---

## 3. The write path

`storage.atomic_write_json` is the only way report JSON reaches disk:

1. If the target exists, copy its current bytes to `<name>.bak.json` (itself written atomically).
2. Write new bytes to a unique temp file in the same directory (`mkstemp`).
3. `os.replace` temp over target.
4. On `PermissionError` (Windows virus scanners, open handles) retry at 20 ms, 50 ms, 100 ms, then raise.
5. `finally`: unlink the temp file.

Consequences worth knowing:
- There is exactly **one** level of backup. Two bad saves in a row lose the good copy.
- The temp file is a sibling, so the directory must be writable, and a partially written file never appears at the real path.

---

## 4. Locking

`Workspace._locked(report_id)` is a two-layer, reentrant lock held across every read-modify-write:

- **In-process:** a `threading.RLock` per `report_id`, cached in `self._report_locks`.
- **Cross-process:** an exclusive OS lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) on `data/.locks/<sha256(report_id)>.lock`.
- **Reentrancy:** a `threading.local` depth counter lets nested calls (`export_bundle` calling `load`) re-enter without deadlocking. The OS lock is taken only at depth 0.

Every mutating `Workspace` method takes this lock. If you add one that does not, you have introduced a race.

---

## 5. Concurrency control: `saved_at`

`saved_at` is the optimistic-concurrency token for the whole report. There is no per-field versioning.

- **Monotonic by construction:** `report.saved_at = max(now, report.saved_at + 1 microsecond)`. Two saves inside the same clock tick still produce increasing values, so equality comparison is safe.
- **Guarded write:** `save_if_current(report, expected_saved_at)` reloads from disk under the lock and raises `StaleReportError` if the stored value moved. `main.save_if_current` converts that to **HTTP 409**.
- **How the client sends it:**
  - full save (`PUT /reports/{id}`) puts `saved_at` in the **JSON body**
  - library insert and evidence upload send the **`X-Report-Saved-At` header** (read by `main.expected_revision`)
- **409 body** (`main.stale_report_detail`) carries `code: "stale_report"`, `recoverable`, and `latest_saved_at`.

**Client handling of 409** (`markSaveConflict`): sets `saveConflict`, forces `pendingSave`, persists the local draft, and switches the save button to a `resolve` action offering *Save my version* (adopt `latest_saved_at`, re-PUT) or *Load latest* (discard local, reload). While `saveConflict` is set, `save()` returns immediately without sending anything.

---

## 6. Server-side schema

Defined in `app/models.py`, Pydantic v2, `schema_version` is `"1.4"`.

```
Report
  report_id, app_id, app_version, schema_version, saved_at
  _folder_name_hint : FolderHint          alias, display convenience only
  engagement        : Engagement          app_name, ci/bsn, tester, dates, tested_channels, tested_environments
  scope_targets     : [ScopeTarget]       the authoritative list of locations, each carrying its own channel
  vulnerabilities   : [Vulnerability]     display_id, title, likelihood, impact, severity, status, scope,
                                          poc_variants, poc_variant_declined, content_offer_resolved, contents[]
  evidence          : {evidence_id: EvidenceItem}
```

`Vulnerability.content_offer_resolved: dict[ContentType, StableId]` records, per content section, which `library_id` that section's keep/replace/add offer has already been resolved against, so a title match to the same library entry does not keep re-offering a section the tester already decided. It defaults to `{}` via `default_factory`, so every existing `draft.json` loads unchanged with no legacy-repair entry needed. Because the field is typed as a plain `dict`, not `Optional`, a missing key or an explicit `{}` both validate as an empty dict, but an explicit JSON `null` for this field fails Pydantic validation — no code path in the app writes `null` here today (unlike `poc_variant`, which is `TestType | None` and is reset to `null` by design), and any future reset logic for this field must assign `{}`, never `null`.

`Scope.custom_locations` is keyed **environment then channel** (`{production: {web: [...]}}`), mirroring `scope_text`, so a typed-in endpoint carries an app type just as a selected `ScopeTarget` does. Without that, a finding's app types could not be resolved and the proof-of-concept offer could never fire for it.

**Cross-object invariants enforced by `Report.validate_references`:**

- `scope_targets[].target_id` values are unique
- `vulnerabilities[].uid` values are unique
- **two findings may not share a `display_id`** (finding number); `None` is exempt
- within one finding, `contents[].type` values are unique
- a finding's `scope.target_ids` must all exist in `scope_targets`. Every scope is `custom`, so this is now universal — and it is what makes `scope_has_location`'s treatment of `target_ids` as a presence check an honest answer
- `frag_id` values are unique across the entire report
- every `fragment.evidence_id` points at an existing `evidence` entry
- every `evidence.file` basename equals `<evidence_id>.png`

Not enforced here: which fragment types may appear in which content section, and which content sections a `status` requires. `ContentType` restricts the five section names and nothing more; `Content.fragments` accepts any fragment type. Section membership is `provision`'s job, and `provision` runs only on `PUT` and library insert — never on `load_path` or `import_report`.

A violation raises `ValidationError` on load, which demotes the draft to the *legacy/invalid* list on the manager page rather than crashing it (`Workspace.list_legacy_reports`).

---

## 7. Derived state, recomputed on every save

`main.provision_report` runs server-side on every PUT and calls the first two of these. The other two run on different paths: `reconcile_targets` from the PUT handler, `assign_fresh_fragment_ids` from `insert_library`. The server, not the browser, owns all four.

| Function | Runs from | What it guarantees |
|---|---|---|
| `provision` | `provision_report` | each finding has its required content sections and seed fragments; both proof-of-concept sections seed `numbered_list` then `image`; sections the status does not print are **carried, not dropped**, when they still hold tester work |
| `sync_evidence_image_slots` | `provision_report` | at least one image slot exists in `proof_of_concept` for every affected environment, and an untouched slot for an environment the finding stopped affecting is removed |
| `reconcile_targets` | the PUT handler, only when `scope_text` is present | rebuilds `scope_targets` from the submitted `scope_text`; **drops each finding's `target_ids` that no longer exist** rather than refusing the save, and rejects the change with 422 `referenced_scope_removed` only for a finding left with **no** location at all |
| `normalise_scope_modes` | the `Report` before-validator, `save_report` after `reconcile_targets`, and `repair_duplicate_fragment_ids` | a retired `scope.mode` becomes `custom` carrying the target IDs it resolved to, in channel order |
| `assign_fresh_fragment_ids` | `insert_library` | library inserts never reuse a `frag_id` |
| `ensure_proof_steps` | `provision`, `apply_poc_variant` | both proof-of-concept sections always hold a `numbered_list`, first in the section |
| `parse_report_docx` | `import_report`, when the upload is a generated report | a DOCX becomes a retest draft: every retained finding is `open_previously_discovered`, the document's Proof of Concept becomes the draft's **previous** one, and a fresh empty `proof_of_concept` is built with one image slot per affected environment |

`content_types_for_status(status)` is the **single owner** of which sections a status prints: `open_new` prints description, recommended remediation, and proof of concept; every other status adds previous proof of concept and in conclusion. `provision` builds those sections first and then appends any other section that `content_has_work` says is non-empty, so changing a finding to "open new" and back returns last year's proof intact. A carried section is invisible: the editor renders only the printed ones, `generation_issues` skips the rest, and `docx_report` was already gated the same way. `content_has_work` ignores fragments this app generated itself — a `generated` marker or a default status sentence — so untouched boilerplate never counts as something to lose.

**`Scope.mode` has one legal value, `"custom"`.** A finding's locations are always the explicit `target_ids` it selected, plus any typed-in `custom_locations`. The three retired values — `all`, `all_production`, `all_non_production` — resolved against the report's targets on every read, which meant a finding could silently widen when Setup grew, and which let `/edit` open on a finding showing no ticked location at all. `normalise_scope_modes` freezes any it finds into the IDs they stood for; `Scope.mode`'s before-validator coerces anything that reaches validation without passing it, because raising would demote the whole draft to the manager's legacy list instead of leaving one finding visibly incomplete. The field survives only so the migration can still recognise a retired token.

**A library-inserted finding starts with no targets**, so it is incomplete by design until a location is chosen.

**`location_lines(values)` is the single owner of which typed lines in the "additional affected locations" box name a real place.** It applies exactly the cleaning the scope textarea gets inside `reconcile_targets`: strip the line, drop it if blank, drop it if it starts with `#`, and drop a repeat of one already kept. The raw text is **not** rewritten in the draft, so a tester's `#` note survives editing; it simply never counts as a location and never reaches the document. Every consumer goes through it — `scope_has_location`, `affected_environments`, `affected_channels`, `_scope_reaches_a_location`, and `docx_report._finding_locations` — with `locationLines` as the JavaScript twin.

**A typed line counts only inside the engagement's coverage.** `scope_has_location`, `affected_environments`, and `affected_channels` all ignore a `custom_locations` entry whose environment is absent from `engagement.tested_environments` or whose channel is absent from `engagement.tested_channels`. Selected `target_ids` need no such filter, because `reconcile_targets` rebuilds the target list and `validate_references` rejects a dangling ID — but nothing ever revisits a typed line, so without this a finding could carry itself into the Content page on an endpoint the report does not test. This is why `scope_has_location` is a presence check for `target_ids` and a stricter one for typed lines.

`sync_evidence_image_slots` adds a slot for every affected environment, and removes a slot only when it is for an environment the finding no longer affects **and** carries no `evidence_id` and no caption. An uploaded screenshot is never removed and **never relabelled**: re-stamping it would file the tester's evidence under a heading it was not taken in, and would leave the finding demanding a second screenshot for the environment it already had. Two further details matter to any new caller: coverage is measured against `proof_of_concept` images **only**, so a carried `previous_proof_of_concept` image never suppresses a new slot; and appended slots go into `proof_of_concept` only, so a finding with no `proof_of_concept` section gets nothing. It does not relabel `previous_proof_of_concept`, but it does fill in a blank `environment` on one, because provisioning creates that slot empty and `generation_issues` then demands an environment that nothing else would ever assign.

`fragment_applies(fragment, vulnerability, report, content_type)` is the **single owner** of the "does this fragment belong to an environment this finding actually affects" rule. Both the renderer and the readiness panel must go through it — it is what hides a stale slot, since nothing removes one. **`previous_proof_of_concept` always applies**, whatever the environment: it records the engagement that found the finding, and a retest is usually narrower than the test before it, so gating history on the current scope would silently drop evidence from the document.

### Proof-of-concept steps from the library

A `LibraryEntry` may carry `proof_of_concept`, keyed by `Channel` (`web`, `api`, `mobile`). A missing key means no steps for that app type; an empty list is rejected, so "no steps" has exactly one representation. Of the 12 entries in `resources/vuln_library.json` that define `proof_of_concept`, 12 have `web`, 12 have `api`, and **none have `mobile`**, so a mobile-only finding gets no steps regardless.

The retired `web_api` token is gone from the type, the library, and the library editor. All 11 of its step lists were word-for-word copies of that entry's `web` list, so removing it lost no content. `LEGACY_TEST_TYPE_CHANNELS` in `models.py` survives as the single migration table that maps the old four tokens onto channel lists; nothing else in the app knows them.

`applicable_poc_variants(vulnerability, report, available)` returns **every** app type the finding touches that the entry actually carries steps for, in `CHANNELS` order. There is no exact-set match and no `None`: a finding spanning web and API is offered both.

`apply_poc_variant` takes a list of variants and a `mode`: `"replace"` (the default) overwrites the non-image fragments of the `proof_of_concept` section, `"merge"` keeps them and appends the library's steps after them. Either mode keeps every image exactly as it was, remints `frag_id`s, and never touches `previous_proof_of_concept`. **`merge_step_lists` then collapses every `numbered_list` into one**, because two list fragments each restart at `1.` in the generated document (`_remap_numbering` allocates a fresh `numId` per fragment and writes a `w:startOverride`). Installed app types are appended to `poc_variants`; only the app types just installed are removed from `poc_variant_declined`, because declining API and accepting Web are independent decisions.

Nothing is written without a click. The Content page renders an offer, derived purely from current state, listing the app types that have steps and are neither installed (`poc_variants`) nor refused (`poc_variant_declined`). With more than one on offer the tester ticks which to install; `POST /reports/{id}/library/{library_id}` auto-installs **only** when exactly one variant applies, leaving the ambiguous case to that choice.

---

## 8. Legacy repair on load

**App-type normalisation lives in a `Report` `model_validator(mode="before")`, not in `load_path`**, because `import_report` and both `parse_import` branches build a `Report` without ever going through the load path. That validator is the single hook every entry path shares. It maps the retired `engagement.test_type` onto `engagement.tested_channels`, and the retired `Vulnerability.poc_variant` onto `poc_variants`.

`models.resolve_tested_channels(report_mapping)` is the one function that answers "which app types does this report cover". Precedence tests key **presence**, never truthiness:

1. both `tested_channels` and `test_type` present (only reachable in a hand-edited file) — their **union**, the one rule that cannot silently drop a target
2. `tested_channels` present — used as given, deduped and ordered by `CHANNELS`; a bare string coerces to a one-element list. **The only branch that can return `[]`**
3. `test_type` present — expanded through `LEGACY_TEST_TYPE_CHANNELS`; an unrecognised token passes through so the `Channel` literal rejects it, which keeps the validator from ever raising on its own
4. neither — the channels present on the mapping's own `scope_targets`
5. neither, and no targets — `["web"]`

It returns `[]` **if and only if** the caller explicitly sent an empty list, which `Engagement.tested_channels`' `min_length=1` then refuses. That floor is the only gate on `import_report`, which skips `reconcile_targets` entirely.

**`normalise_scope_modes` sits in the `Report` before-validator**, beside the app-type normalisation and for the same reason: `import_report` and both `parse_import` branches never touch `load_path`, so the model is the only hook every entry path shares. It needs the whole report because it filters resolved IDs against `scope_targets`, which a `Vulnerability`-level validator cannot see. It **mutates in place and returns nothing**, because two of its three call sites hold a mapping that later reaches disk and would discard a fresh copy.

It runs from three places. Inside the before-validator, above the `engagement` guard so a caller passing a pre-built `Engagement` is still covered. From `save_report`, **after** `reconcile_targets` — so a legacy finding resolves against the targets that save just wrote, not the ones it replaced; before the relaxation of the stranding branch this call had to run earlier, and could not. And from `repair_duplicate_fragment_ids`, which validates and then persists the **raw** draft.

`Workspace.load_path` still silently upgrades and rewrites two shapes:

- a `numbered_list` / `bulleted_list` fragment with no `items` gets one empty item
- a `recommended_remediation` holding the single unlabelled sentence `RESOLVED_REMEDIATION`. On a **resolved** finding it gains `generated: "resolved_remediation"`; on any other status its runs are emptied. Without the marker `provision` cannot tell its own boilerplate from the tester's prose, so the sentence outlived the resolved status and the report claimed a fix that never happened. The resolved case is safe because the editor locks that section while resolved, so the text can only be ours; the reopened case is damage from before the marker existed.

`repair_duplicate_fragment_ids` is opt-in from the manager UI for drafts that fail validation only because of repeated `frag_id`s. Note it validates and then persists the **raw** draft, so it calls `normalise_scope_modes` itself; a legacy `test_type` still survives on disk there until the next ordinary save.

---

## 9. Client state

`app/web/static/app.js` is one IIFE. The mutable object named `report` is the client's source of truth.

- **Seeding:** the server renders the whole report into a `data-report` attribute on `<main>`; the client does `JSON.parse(root.dataset.report)`. There is no fetch-on-load and no router.
- **Shadow copies:** `serverReport` (pristine seed), `previousReport` (undo baseline), `activeTextTransaction.before` (per-field transaction).
- **After every successful save** the server's canonical response is merged back in by `applyCanonicalReport` / `reconcileCanonicalObject`, so server-side provisioning appears in the browser without a reload.

### Undo and redo

Client-only, with no Python counterpart. `undoHistory` and `redoHistory` hold `{changes}` actions produced by `diff(previousReport, report)` and replayed by `applyChanges`; both live in `sessionStorage["vulnreport-history:{reportId}"]` and survive the page loads that navigation and undo itself cause. `maxHistoryEntries` caps the undo stack at 20 and any new edit clears the redo stack (`scheduleSave`).

One focused field is one undo step: `scheduleSave` opens an `activeTextTransaction` on the first edit, skips pushing further actions while that field stays focused, and `finalizeTextTransaction` recomputes the action's `changes` on `focusout`, on `pagehide`, on the next non-text edit, and at the top of `undo`. A transaction whose net diff is empty is spliced back out of `undoHistory`.

**`restoreHistory` is a navigation event** (see section 10). `undo`/`redo` are also bound to Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z by a document-level `keydown` listener that calls `preventDefault()` regardless of focus, so native undo is suppressed inside `.rich` contenteditables, textareas, and inputs.

### `scope_text` is client-only

`report.scope_text` (`{environment: {channel: "newline separated"}}`) exists **only in the browser and in the PUT body**. The server pops it in `reconcile_targets`, converts it to `scope_targets`, and never echoes it back. It is deliberately excluded from canonical reconciliation. Treat `scope_targets` as the truth; `scope_text` is an editing buffer.

### Timers

| Timer | Delay | Purpose |
|---|---|---|
| backend autosave | 5000 ms idle | `queueBackendSave`, restarted by every edit |
| local draft | 150 ms | `persistLocalDraft` to `localStorage["vulnreport-pending:{reportId}:{tabId}"]` |
| `reportchange` event | 100 ms | recompute the readiness panel |

---

## 10. Navigation

Three server-rendered documents (`page1_setup`, `page2_findings`, `page2_editor`), each loading its own copy of `app.js`. Every transition is a full page load via `window.location.assign`.

**Flush-before-navigate is the whole safety story:**
- **Next** validates the page, `await save()`, and navigates **only if** the save button reports `data-save-state="saved"`.
- **Back** navigates only if `await save()` returned true.
- `save()` clears the autosave timer first so a queued debounce cannot fire mid-navigation.
- `pagehide` finalizes the open text transaction and writes the local draft synchronously.
- `beforeunload` prompts when `saveRevision > savedRevision` unless `allowUnsavedUnload` is set.
- `visibilitychange` to hidden forces an immediate save when one is pending.

**Undo and redo navigate too.** `restoreHistory` applies the change, forces `pendingSave`, persists the local draft and the history stacks, points `sessionStorage["vulnreport-recovery:{reportId}"]` at the local draft key, sets `allowUnsavedUnload`, then `await save()` and `window.location.reload()` — so the server judges the page gates against the undone state rather than the state before it. The resolved value of that save is not checked; a refused save still reloads, and the boot-time recovery selection re-adopts the undone draft. A storage failure anywhere in that sequence rolls the change back instead and leaves the page alone.

**Server-side gates can bounce a direct URL:** `/findings` redirects to `/setup?incomplete=setup` when setup is incomplete; `/edit` redirects to `/findings?incomplete=findings`. The client reads that query parameter to pre-open the validation notice. A client-side rule that disagrees with its server counterpart shows up here as a redirect loop or an unexplained bounce.

---

## 11. Evidence upload

1. Client flushes the whole report first (`await save("Uploading...")`) and aborts the upload if that fails.
2. `POST /reports/{id}/evidence` with `FormData{file}` and the `X-Report-Saved-At` header.
3. Server normalizes to PNG (EXIF transpose, RGB convert, pixel-count and 20 MB limits), then `save_evidence_if_current` writes image bytes **and** report metadata under one lock, with a 250 MB per-report cap.
4. On failure the just-written file is unlinked so no orphan is left.
5. Client stores only `evidence_id`; it never handles a path. Display is `GET /reports/{id}/evidence/{evidence_id}`, which rejects any resolved path whose parent is not that report's `evidence/` directory.

`Workspace._drop_orphan_evidence` deletes evidence files the draft no longer references on every save, so dropping an `evidence_id` from the JSON is what deletes the file.

---

## 12. Rules that exist twice

These are implemented in both Python and JavaScript and **must be changed in pairs**. `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` is the only contract test, and it covers **generation readiness alone** — it drives a browser and compares `#issue-count[data-state]` against `generation_issues`. It does not read any JavaScript constant, and it does not touch the app-type, scope-survival, or proof-of-concept rows below. Those have no drift guard.

| Rule | Python | JavaScript |
|---|---|---|
| per-field character sets, identical wording | `setup_input_issues`, `CHARACTER_NAMES` | `characterRule`, `setupRules`, `characterNames` |
| username shape | `USERNAME_PATTERN` | `setupRules.username` |
| test window start ≤ end | `TestWindow.validate_order`, `setup_input_issues` | `validateDateOrder` |
| setup completeness | `setup_issues` / `setup_is_complete` | `validateSetupPage`, `updateSetupValidationNotice` |
| finding completeness | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` |
| a finding claims a location at all | `scope_has_location` | `scopeHasLocation`, `scopeTargetIds` — `target_ids` is **presence only**, neither side checks that they resolve; a typed line is held to more, see below |
| which typed lines in the additional-locations box count | `location_lines` | `locationLines` |
| a scope still reaches a surviving target | `_scope_reaches_a_location` | `scopeReaches` — resolution-aware, intersects against the target list |
| which locations a finding prints | `docx_report._finding_locations` | none — generation is server-only |
| affected environments | `affected_environments` | `affectedEnvironments`, `scopeEnvironments` |
| affected app types | `affected_channels` | `affectedChannels` |
| canonical app-type order | `CHANNELS` in `models.py`; `docx_report.CHANNEL_ORDER` is a `list()` copy of it | `CHANNELS`, module scope in `app.js` |
| which app types a report covers | `resolve_tested_channels` | the `tested_channels` seed in `setup()`, which twins branches 4 and 5 only |
| which targets survive an app-type or environment change | the target loop in `reconcile_targets` | `findingsStrandedBy`, and `dropTargetsEverywhere` for the confirmed purge (`dropChannelEverywhere` wraps it) |
| which targets survive a scope-text edit | the same loop, reusing IDs by value | `survivingAfterScopeText`, `scopeTextStrandedFindings` — **not an exact twin**, see below |
| mobile scope character allowlist | `invalid_character_issue` call inside `reconcile_targets` | `mobileScopeRule` |
| library proof-of-concept selection | `applicable_poc_variants` | `applicablePocVariants` |
| installing proof-of-concept steps, replace or merge-append | `apply_poc_variant` (`mode="replace"`/`"merge"`) | `applyPocVariant` (`mode` param) |
| collapsing appended steps into one numbered list | `merge_step_lists` | `mergeStepLists` |
| generation readiness | `generation_issues` | `updateReadinessPanel`, `fragmentIssues` |
| description and remediation are never empty | `generation_issues` (`content.fragments` check) | `requiresFragment`, `fragmentIssues`, `deletionBlockedReason` |
| placeholder text regex | `PLACEHOLDER_TEXT` | `placeholderPattern` (byte-identical) |
| environment gating for fragments | `fragment_applies` | inline check in `updateReadinessPanel` |
| image slots | `sync_evidence_image_slots` | `syncEvidenceImageSlots` |
| status to section list | `content_types_for_status` | `contentTypesForStatus`, used by `provision`, the readiness panel, the editor's section render, and the status `onchange` |
| whether a section holds tester work | `content_has_work` | `contentHasWork` |
| resolved remediation boilerplate | `provision` (`RESOLVED_REMEDIATION`, `generated="resolved_remediation"`) | `provision` (`RESOLVED_REMEDIATION`) |

**Previous proof of concept is historical, and that rule lives in five places.** `fragment_applies`, `sync_evidence_image_slots` and the evidence-coverage check in `generation_issues` all exempt it on the Python side. The browser mirrors it in `syncEvidenceImageSlots` and `fragmentIssues`, and two client-only paths must respect it as well: `settleScopeChange` must not **delete** a historical image when an environment leaves the scope, and the image editor must not **overwrite** a historical `environment` while rendering. A historical image offers every environment and starts unset, because only the tester knows where a carried screenshot came from.

Python's `required_fragments` and the JavaScript `required` now seed identically — `["numbered_list", "image"]` into both proof-of-concept sections. They were out of step until 2026-09-14; anything that asks "is this section empty?" can now trust either side.

**Client-only:** the confirmation guards (`confirmScopeLoss`, `confirmScopeTextLoss`, `settleScopeChange`, the status-change and finding-deletion prompts) and `deletionBlockedReason`, which disables Delete on the fragments provisioning guarantees — the last fragment of any kind in `description` and `recommended_remediation`, the last `numbered_list` in either proof-of-concept section, the last `image` in `previous_proof_of_concept`, and the last `proof_of_concept` image for an affected environment. The server would recreate each on the next save, so the block exists to stop the editor looking like it discarded the change. The `description` and `recommended_remediation` rule counts fragments, not paragraphs: a library entry may supply a remediation that is a list and a note with no paragraph at all.

Every one of those guards is `await window.vrDialog.confirm(...)` (`dialog.js`), **not** `window.confirm` — there is no `window.confirm` anywhere in `app.js`. The difference is load-bearing for anything keyboard- or focus-related: a native `window.confirm` blocks the JavaScript thread, whereas a `vrDialog` is an ordinary DOM overlay that leaves timers, autosave, and document-level key handlers running underneath it. While one is open, `document.querySelector("[data-dialog]")` finds its backdrop; the evidence lightbox is a separate, native `<dialog>` opened with `showModal()` and carries no such attribute.

**`replaceFromLibrary` no longer confirms or copies content.** A title match on the Findings page now silently applies only `title`, `likelihood`, `impact`, `severity`, `library_ref` (`applyLibraryEntry`) — `contents` is untouched. Instead, each library-sourced content section (`description`, `recommended_remediation`, and `proof_of_concept`) offers its own client-only, state-derived banner on the Content page — same pattern as the pre-existing proof-of-concept offer — with three choices: keep, replace, or add (merge-append) the library's fragments for that section. `description`/`recommended_remediation` resolution is tracked in the new `content_offer_resolved` field (§6) and has no server-side twin, since the mutation rides the ordinary autosave PUT like any other Content-page edit. `proof_of_concept`'s offer reuses `poc_variant`/`poc_variant_declined` and, because `apply_poc_variant`/`applyPocVariant` already have a Python/JavaScript twin, its new merge-append mode had to be added to **both** sides (see the table above). `previous_proof_of_concept` is excluded from this mechanism entirely — it is never library-sourced. Every fragment copied in from a library entry, for replace or merge-append alike, gets a fresh `frag_id` (`remintFragments` client-side, `model_copy(deep=True)` + reassignment server-side) — `frag_id` uniqueness is report-wide, not per-section.
**The scope-text survival pair is asymmetric, and deliberately so far only by accident.** For a `mode == "custom"` finding the server appends to `removed_references` when **any** submitted `target_id` is missing from the new target set, whether or not the finding keeps other locations. The client's `scopeTextStrandedFindings` only reports a finding that ends up with **no** location at all. So removing one scope line from a finding that selected several is a silent 422 with no preceding dialog. The gap is invisible on a `mode: "all"` finding, which holds no `target_ids` for the server to miss.

**The Findings page rewrites non-custom scopes on render.** Before drawing the table it does `if (finding.scope?.mode !== "custom") finding.scope.target_ids = scopeTargetIds(finding.scope)`, filling in the ids the mode resolves to while leaving `mode` alone. It has no Python counterpart and no server guard: `validate_references` skips `target_ids` on non-custom modes, so the rewritten list rides out on the next ordinary autosave. The row markup then draws `selectedTargets` as `[]` for the same finding, so the boxes stay unticked over ids that are now on disk.

**Server-only:** `Report.validate_references`, the `referenced_scope_removed` 422, and all upload size limits.

---

## 13. Known sharp edges

Recorded so they are not rediscovered as bugs.

- **The comment above `scheduleSave` says "30-second cadence"** (line 574); the actual default is 5000 ms.
- **Template context key differs by page:** setup and findings receive `library`, the editor receives `library_entries`.
- **`find_path` and `list_reports` scan every `draft.json` on disk** for each call. Correct, but O(number of reports) per lookup. It is also why folder names are free to change: nothing resolves a report through one.
- **Folder segments are provisional until the value that names them exists.** `app_folder_name` gives `unnamed` while `app_name` is blank and `report_folder_name` gives `Report` while `report_type` is `None`. `_save_unlocked` renames on the save that supplies the missing value and freezes afterwards, so a later rename leaves the folder alone. The manager groups by `engagement.app_name`, not by the folder, so that drift never shows.
- **One backup only.** `draft.bak.json` is overwritten on every save.
- **A migrated scope is not written back on load.** `normalise_scope_modes` runs in memory; `load_path` rewrites the file only for the two repairs it already owns, and it writes *before* it validates, so a freshly rewritten draft can still read `"mode": "all"` on disk while the app holds the migrated version. Persisting it there would rewrite every draft twice on a single manager render, because `list_reports` and `list_legacy_reports` each call `load_path` per draft, spending every one-of-one backup to change one string per finding. The next ordinary save persists it.
- **`scope_text` asymmetry** (section 9): present in requests, absent from responses. Code that assumes request and response shapes match will break here.
- **`provision` seeds only into an *empty* section.** A finding whose `previous_proof_of_concept` already holds steps but no image will never gain the image slot, so the seed reaches new sections only, never existing drafts. Backfilling instead would add empty fragments that readiness then demands text for, which is why it stays this way.
- **`generation_issues` validates the images that exist; it does not require one to exist.** Only `affected_environments` coverage forces an image into being, and that is measured against `proof_of_concept` alone. A `previous_proof_of_concept` holding steps and no image is therefore generation-clean.
