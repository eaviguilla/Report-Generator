# Data Map

The single reference for how report data is shaped, saved, and moved through this app.

> **Maintenance contract.** This file is the source of truth consulted by the `data-oracle` agent. Any change to `app/models.py`, `app/storage.py`, `app/workspace.py`, `app/report_service.py`, or the save/navigation paths in `app/web/static/app.js` must update the affected section here in the same change. Line numbers are hints only; function and field names are the durable identifiers.
>
> Last verified against source: **2026-09-14**, after making `previous_proof_of_concept` a historical record, aligning the Python and JavaScript proof-of-concept seeds, and renaming report folders after the application and its report type.

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
  engagement        : Engagement          app_name, ci/bsn, tester, dates, test_type, tested_environments
  scope_targets     : [ScopeTarget]       the authoritative list of locations, each carrying its own channel
  vulnerabilities   : [Vulnerability]     display_id, title, likelihood, impact, severity, status, scope,
                                          poc_variant, poc_variant_declined, contents[]
  evidence          : {evidence_id: EvidenceItem}
```

`Scope.custom_locations` is keyed **environment then channel** (`{production: {web: [...]}}`), mirroring `scope_text`, so a typed-in endpoint carries an app type just as a selected `ScopeTarget` does. Without that, a finding's app types could not be resolved and the proof-of-concept offer could never fire for it.

**Cross-object invariants enforced by `Report.validate_references`:**

- `scope_targets[].target_id` values are unique
- `vulnerabilities[].uid` values are unique
- **two findings may not share a `display_id`** (finding number); `None` is exempt
- within one finding, `contents[].type` values are unique
- a finding's `scope.target_ids` must all exist in `scope_targets`, **checked only when `scope.mode == "custom"`** — stale `target_ids` under any other mode pass validation
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
| `provision` | `provision_report` | each finding has its required content sections and seed fragments; both proof-of-concept sections seed `numbered_list` then `image` |
| `sync_evidence_image_slots` | `provision_report` | at least one image slot exists in `proof_of_concept` for every affected environment |
| `reconcile_targets` | the PUT handler, only when `scope_text` is present | rebuilds `scope_targets` from the submitted `scope_text`, and rejects the change with 422 `referenced_scope_removed` if it would strand a finding |
| `assign_fresh_fragment_ids` | `insert_library` | library inserts never reuse a `frag_id` |
| `ensure_proof_steps` | `provision`, `apply_poc_variant` | both proof-of-concept sections always hold a `numbered_list`, first in the section |
| `parse_report_docx` | `import_report`, when the upload is a generated report | a DOCX becomes a retest draft: every retained finding is `open_previously_discovered`, the document's Proof of Concept becomes the draft's **previous** one, and a fresh empty `proof_of_concept` is built with one image slot per affected environment |

`sync_evidence_image_slots` **only ever adds**. It never deletes a slot for an environment the finding stopped affecting — a stale image keeps its `environment` and stays in the draft. Two further details matter to any new caller: coverage is measured against `proof_of_concept` images **only**, so a carried `previous_proof_of_concept` image never suppresses a new slot; and appended slots go into `proof_of_concept` only, so a finding with no `proof_of_concept` section gets nothing. It never reads or relabels `previous_proof_of_concept`.

`fragment_applies(fragment, vulnerability, report, content_type)` is the **single owner** of the "does this fragment belong to an environment this finding actually affects" rule. Both the renderer and the readiness panel must go through it — it is what hides a stale slot, since nothing removes one. **`previous_proof_of_concept` always applies**, whatever the environment: it records the engagement that found the finding, and a retest is usually narrower than the test before it, so gating history on the current scope would silently drop evidence from the document.

### Proof-of-concept steps from the library

A `LibraryEntry` may carry `proof_of_concept`, keyed by `TestType` (`web`, `api`, `web_api`, `mobile`). A missing key means no steps for that app type; an empty list is rejected, so "no steps" has exactly one representation.

`applicable_poc_variant` maps a finding's app types onto one of those keys by **exact set match** (`{web}` to `web`, `{api}` to `api`, `{web, api}` to `web_api`, `{mobile}` to `mobile`). Anything else, including a finding whose locations resolve to no app type at all, returns `None`. Variants are never synthesised or concatenated.

`apply_poc_variant` replaces only the non-image fragments of the `proof_of_concept` section, keeps every image exactly as it was, remints `frag_id`s, and never touches `previous_proof_of_concept`. It records `poc_variant` on the finding and clears `poc_variant_declined`, because a refusal referred to steps that no longer exist.

Nothing is written without a click. The Content page renders an offer, derived purely from current state, when steps exist for the derived app type and they are neither installed (`poc_variant`) nor refused (`poc_variant_declined`).

---

## 8. Legacy repair on load

`Workspace.load_path` silently upgrades old drafts and rewrites them:

- `engagement.tested_channels` (a set) becomes `engagement.test_type` (a single enum)
- a `numbered_list` / `bulleted_list` fragment with no `items` gets one empty item

`repair_duplicate_fragment_ids` is opt-in from the manager UI for drafts that fail validation only because of repeated `frag_id`s.

Any new legacy shape must be repaired here, not in the route handlers.

---

## 9. Client state

`app/web/static/app.js` is one IIFE. The mutable object named `report` is the client's source of truth.

- **Seeding:** the server renders the whole report into a `data-report` attribute on `<main>`; the client does `JSON.parse(root.dataset.report)`. There is no fetch-on-load and no router.
- **Shadow copies:** `serverReport` (pristine seed), `previousReport` (undo baseline), `activeTextTransaction.before` (per-field transaction).
- **After every successful save** the server's canonical response is merged back in by `applyCanonicalReport` / `reconcileCanonicalObject`, so server-side provisioning appears in the browser without a reload.

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

These are implemented in both Python and JavaScript and **must be changed in pairs**. `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` is the contract test that catches drift.

| Rule | Python | JavaScript |
|---|---|---|
| per-field character sets, identical wording | `setup_input_issues`, `CHARACTER_NAMES` | `characterRule`, `setupRules`, `characterNames` |
| username shape | `USERNAME_PATTERN` | `setupRules.username` |
| test window start ≤ end | `TestWindow.validate_order`, `setup_input_issues` | `validateDateOrder` |
| setup completeness | `setup_issues` / `setup_is_complete` | `validateSetupPage`, `updateSetupValidationNotice` |
| finding completeness | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` |
| scope resolves to a location | `scope_has_location`, `_scope_reaches_a_location` | `scopeHasLocation`, `scopeTargetIds` |
| affected environments | `affected_environments` | `affectedEnvironments`, `scopeEnvironments` |
| affected app types | `affected_channels` | `affectedChannels` |
| library proof-of-concept selection | `applicable_poc_variant` | `applicablePocVariant` |
| installing proof-of-concept steps | `apply_poc_variant` | `applyPocVariant` |
| generation readiness | `generation_issues` | `updateReadinessPanel`, `fragmentIssues` |
| placeholder text regex | `PLACEHOLDER_TEXT` | `placeholderPattern` (byte-identical) |
| environment gating for fragments | `fragment_applies` | inline check in `updateReadinessPanel` |
| image slots | `sync_evidence_image_slots` | `syncEvidenceImageSlots` |
| status to section list | `provision` | `provision`, **and a third inline copy** in the status `onchange` (~line 1470) |

**Previous proof of concept is historical, and that rule lives in five places.** `fragment_applies`, `sync_evidence_image_slots` and the evidence-coverage check in `generation_issues` all exempt it on the Python side. The browser mirrors it in `syncEvidenceImageSlots` and `fragmentIssues`, and two client-only paths must respect it as well: `settleScopeChange` must not **delete** a historical image when an environment leaves the scope, and the image editor must not **overwrite** a historical `environment` while rendering. A historical image offers every environment and starts unset, because only the tester knows where a carried screenshot came from.

Python's `required_fragments` and the JavaScript `required` now seed identically — `["numbered_list", "image"]` into both proof-of-concept sections. They were out of step until 2026-09-14; anything that asks "is this section empty?" can now trust either side.

**Client-only:** the `window.confirm` guards (`confirmScopeLoss`, `settleScopeChange`, `replaceFromLibrary`), finding-deletion confirmation, and `deletionBlockedReason`, which disables Delete on the fragments provisioning guarantees — the last `numbered_list` in either proof-of-concept section, the last `image` in `previous_proof_of_concept`, and the last `proof_of_concept` image for an affected environment. The server would recreate each on the next save, so the block exists to stop the editor looking like it discarded the change.
**Server-only:** `Report.validate_references`, the `referenced_scope_removed` 422, and all upload size limits.

---

## 13. Known sharp edges

Recorded so they are not rediscovered as bugs.

- **The comment above `scheduleSave` says "30-second cadence"** (line 574); the actual default is 5000 ms.
- **Template context key differs by page:** setup and findings receive `library`, the editor receives `library_entries`.
- **`find_path` and `list_reports` scan every `draft.json` on disk** for each call. Correct, but O(number of reports) per lookup. It is also why folder names are free to change: nothing resolves a report through one.
- **Folder segments are provisional until the value that names them exists.** `app_folder_name` gives `unnamed` while `app_name` is blank and `report_folder_name` gives `Report` while `report_type` is `None`. `_save_unlocked` renames on the save that supplies the missing value and freezes afterwards, so a later rename leaves the folder alone. The manager groups by `engagement.app_name`, not by the folder, so that drift never shows.
- **One backup only.** `draft.bak.json` is overwritten on every save.
- **`scope_text` asymmetry** (section 9): present in requests, absent from responses. Code that assumes request and response shapes match will break here.
- **`provision` seeds only into an *empty* section.** The `present` set it computes is dead code, because the loop has already skipped any section with fragments. A finding whose `previous_proof_of_concept` already holds steps but no image will never gain the image slot, so the seed reaches new sections only, never existing drafts.
- **`generation_issues` validates the images that exist; it does not require one to exist.** Only `affected_environments` coverage forces an image into being, and that is measured against `proof_of_concept` alone. A `previous_proof_of_concept` holding steps and no image is therefore generation-clean.
