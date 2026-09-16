# Data Map

The single reference for how report data is shaped, saved, and moved through this app.

> Latest verification: **2026-09-16**, after stress-testing serialized mutations, native history, recovery snapshots, repeated conflicts, evidence cleanup, and per-section library retain/add/replace behavior.

> **Maintenance contract.** This file is the source of truth consulted by the `data-oracle` agent. Any change to `app/models.py`, `app/storage.py`, `app/workspace.py`, `app/report_service.py`, or the save/navigation paths in `app/web/static/app.js` must update the affected section here in the same change. Line numbers are hints only; function and field names are the durable identifiers.
>
> Last verified against source: **2026-09-17**, after adding `thick_client` as a fourth app type. `Channel`/`CHANNELS` gained it, `COMPONENT_CHANNELS` and `CHANNEL_LABELS` are new, and `ScopeTarget` gained a defaulted `description`. Mobile and Thick Client are mutually exclusive, enforced **only** as a `setup_issues` line so no load path can raise and strand a draft. Those two channels are scoped as a Component/Description pair, both required, sharing one widened character set; §9 records the `scope_text` shape and §12 the five twins it creates. Generation now selects among four templates on two axes (component channel x Asia segment), fills the binaries table with cloned rows production-first, and on Asia fills a Section table whose number is a Word `REF` field pointing at the finding's own heading rather than a count taken in Python. Before that, after auditing the whole app-type (channel) surface ahead of a fourth channel. One correction: §12's canonical-app-type-order row named two homes for the channel list and there are **three** — `library_editor.html` carries its own `variants` array and three `poc_*` textareas, because the library editor is the one page not driven by `app.js`. Before that, after two Setup changes. `Engagement.non_production_label` stopped being a closed `Literal` and became validated free text defaulting to `NON-PROD`, with the four presets offered in a dropdown plus an **OTHERS** option that is never itself stored; §6 records the field and §12 the two twins it creates. `docx_import` now recovers the label from the evidence heading instead of assuming `UAT`, which repairs a live bug that already mislabelled non-production evidence for the two retired labels and would otherwise have hit almost every import. A single-environment retest is now **offered** a Limitations sentence naming the tester's own label; §12 records why that sentence is deliberately client-only. Before that, after adding numbered-list continuation. A `numbered_list` can now set `continue_numbering` to carry on from the nearest numbered list before it in its section instead of restarting at `1.`; §6 records the field, §7 corrects its own claim that two list fragments always restart, and §12 adds the renderer/gutter twin. The client fingerprint in `normalizedSection` deliberately **excludes** the flag: the library offer asks whether a section still matches its entry's content, and numbering presentation is not content, so including it would make ticking the box re-open an offer whose only remedy would undo the tick. Before that, after a read-only audit of numbered-list handling end to end (model, `provision`, `ensure_proof_steps`, `merge_step_lists`, `apply_poc_variant`, the DOCX list renderer, the editor's list textarea, and DOCX import). One correction: §7 claimed `merge_step_lists` collapses *every* `numbered_list` into one. It collapses only **consecutive** ones — any fragment of another type between two lists is a boundary, which §12 and `tests/test_browser.py::test_poc_add_below_does_not_cross_an_intervening_note` already stated correctly. Before that, after making the In Conclusion section something the tester owns outright. `provision` now creates it with an empty paragraph and never writes the standard sentence; the Content page offers it instead. A status change no longer carries the section — it is a statement about the status, so `open_new` drops it and switching back re-creates it empty, putting the offer in front of the tester. Accepting that offer clears `conclusion_offer_resolved`, so a step dismissed against an older conclusion is offered again. Before that, changing when the Content page offers library content. The offer now keys off the section's own content rather than a permanent latch, so it returns whenever a section differs from its entry, and is dismissed per-content through the new `content_offer_dismissed` fingerprint; `content_offer_resolved` became write-only on both sides. The comparison and the fingerprint share one coercing normaliser, without which a dismissal is undone by its own save. Banners are rebuilt by a read-only `reportchange` listener instead of waiting for a full re-render; an emptied proof of concept re-offers steps that were installed but not ones that were declined; and a rename or status change announces the new closing sentence instead of rewriting it silently. Before that, after a read-only audit of every Content-page and Findings-page offer.

---

## 1. Where data lives

No database. Everything is JSON and PNG files under `data/`.

```
data/
  prefs.json                                   app-wide preferences (library_path, tester)
  .locks/<sha256-of-report_id>.lock            OS advisory lock, one per report
  apps/
    <app_name>/                                 e.g. Northstar_Banking, unnamed
      <YYYY-MM>_<ReportType>_<report_id[2:]>/   e.g. 2026-09_Annual_Pentest_0931592e4fdd
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
| app folder | `safe_name(app_name)` | `engagement.app_name`, else `unnamed` | `app_folder_name` |
| report folder | `<YYYY-MM>_<ReportTypeLabel>_<report_id[2:]>` | `engagement.report_date` (else today) and `report_type`, else the label `Report` | `report_folder_name` |
| `evidence_id` | `ev_` + 12 hex | random at upload | `persist_uploaded_evidence` |
| evidence file | always `evidence/<evidence_id>.png` | enforced by validator | `Report.validate_references` |

**`app_id` is derived once, then frozen.** `app_id_for` is called from exactly two places, and both are guarded by `if report.app_id == "unnamed"` — `main.rename_report` and `main.save_report`. `save_report` also overwrites the submitted `app_id` with `prior.app_id` before validation, so the browser can never change it. Once `app_id` holds a real value, editing `ci_number`, `bsn_number`, or `app_name` does **not** re-derive it and does **not** move the folder. `Workspace.import_report` never calls `app_id_for` at all; it persists whatever `app_id` the payload carried, and `app_id` is a required field on `Report` with no default.

**Folder migration:** both segments are provisional, and `_save_unlocked` renames each independently. A report saved while `app_name` is blank lands in `unnamed/`, and the *first* save after a name is supplied moves it, gated on `app_folder == UNNAMED_APP_FOLDER`. A report saved before a `report_type` is chosen lands in `<YYYY-MM>_Report_<id>`, and the first save after a type is chosen renames it, gated on the folder still matching that provisional shape. Neither migration runs twice: once the folder holds a real value, later edits to `app_name` or `report_type` leave it alone. The move is `existing.parent.replace(target.parent)`, and a vacated app folder is removed when it is left empty. Anything caching the old path across that save is holding a stale path.

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
- **Client serialization:** `trackMutation` queues library inserts and evidence uploads. A queued operation starts only after the previous one settles, so it reads the updated in-memory `saved_at`; `pendingMutation` is the caught queue tail. `waitForMutations` drains that live tail in a loop, so Back or Next also waits for work appended after the navigation click.
- **Same-tab history handoff:** each successful `applyServerRevision` records the newest revision in `sessionStorage["vulnreport-saved-at:{reportId}"]`. Separate tabs keep separate values. A clean document restored by bfcache or a Navigation Timing `back_forward` load reloads when this tab saved a newer revision on another page.
- **409 body** (`main.stale_report_detail`) carries `code: "stale_report"`, `recoverable`, and `latest_saved_at`.

**Client handling of 409** (`markSaveConflict`): sets `saveConflict`, forces `pendingSave`, persists the local draft, and switches the save button to a `resolve` action offering *Save my version* (adopt `latest_saved_at`, re-PUT) or *Load latest* (discard local, reload). While `saveConflict` is set, `save()` restores the visible `conflict` state and returns immediately without sending anything, so an attempted upload or library insert cannot leave the header stuck at “Uploading” or “Adding.”

`read_json_object` treats Starlette `ClientDisconnect` while reading a PUT body as HTTP 400 `Request body was interrupted`. Accepting browser navigation can cancel a visibility-triggered save mid-body; that is a client-aborted request, not an unexpected server fault to log as 500. The synchronous `pagehide` recovery snapshot remains the fallback for that edit.

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
                                          poc_variants, poc_variant_declined, content_offer_resolved,
                                          content_offer_dismissed, conclusion_offer_resolved, contents[]
  evidence          : {evidence_id: EvidenceItem}
```

`ListFragment.continue_numbering: bool = False` asks a `numbered_list` to carry on from the nearest numbered list before it in the same section instead of restarting at `1.`. It is **inert on a `bulleted_list` and on the first numbered list of a section** — the model accepts it there rather than validating it away, because the fragment's type and its neighbours can both change after it is set, and a flag that survives a reorder is less surprising than one silently destroyed by it. A plain `bool` with a literal default, so a missing key validates as `False`; that default is the entire migration for every list already on disk, and no `load_path` repair exists for it (§8) because a repair would rewrite every draft to write a value nothing was missing. The reason it must stay declared even if it were ever abandoned is the same one that keeps `content_offer_resolved` alive: no model sets `model_config`, so Pydantic v2's default `extra="ignore"` drops undeclared keys on the next save without a word.

`Engagement.non_production_label: NonProductionLabel = "NON-PROD"` was a closed `Literal["UAT", "TEST/MO", "DEV"]` until 2026-09-17. It is now `Annotated[str, Field(min_length=1, max_length=40)]` with a stripping `field_validator`, because the picker gained an **OTHERS** option that swaps in a free text box. The widening is strictly permissive — every value that validated before still does — so there is **no `load_path` repair**, and adding one would be wrong: a repair rewrites the file, burning the single `draft.bak.json` level (§3) for a no-op. `NON_PRODUCTION_LABEL_PRESETS` holds the four offered values in dropdown order; `LEGACY_NON_PRODUCTION_LABELS` holds `TEST/MO` and `DEV`, kept only so reports generated before the change still round-trip through `docx_import`. **The token `OTHERS` is never stored** — it is a UI affordance, and whatever is stored *is* the label. Python deliberately does not reject it: the server cannot tell a sentinel from a tester who genuinely labels their environment OTHERS.

Two consequences worth stating. The widening is a **one-way door** — once any report stores `"NON-PROD"`, restoring the Literal makes that draft unloadable. And the character rule runs at **save**, not load, so a hand-edited draft with an illegal label loads fine and then 422s, which is how every other Setup field already behaves.

`Vulnerability.content_offer_resolved: dict[ContentType, StableId]` records, per content section, which `library_id` that section's keep/replace/add offer has already been resolved against. It is now **write-only on both sides** — `insert_library` still pre-answers it and the offer arms still set it, but nothing reads it. The offer keys off the section's content instead (§13). It is kept declared rather than deleted because no model sets `model_config`, so Pydantic v2's default `extra="ignore"` would silently drop the key from all 23 findings on their next save. It defaults to `{}` via `default_factory`. Because the field is typed as a plain `dict`, not `Optional`, a missing key or an explicit `{}` both validate as an empty dict, but an explicit JSON `null` fails Pydantic validation, and any future reset logic must assign `{}`, never `null`.

`Vulnerability.content_offer_dismissed: dict[ContentType, StableId]` records, per section, an opaque client-computed fingerprint of what that section held when its library offer was last answered — by **any** of the three buttons, including Keep mine. The offer returns the moment the section no longer matches. Same plain-`dict` rules as its sibling: missing and `{}` both validate, `null` does not.

The value is a 32-bit FNV-1a hash of the normalised section, prefixed with its length (`<decimal>-<hex>`), which fits `StableId`'s `^[A-Za-z0-9][A-Za-z0-9_.-]*$`. **Typing it as `StableId` makes the hash alphabet a save-blocking contract**: a client emitting any other character 422s every save. That is a one-way coupling, not a twin — Python validates a shape it never produces. A hash rather than the content itself because the content is unbounded tester prose, and it would be duplicated into `draft.bak.json`, a per-keystroke `clone(report)`, a debounced `localStorage` write against a 5 MB shared budget, and twenty deep of `sessionStorage` undo records.

A missing key means "never answered", which is the correct starting state for every draft on disk. **`load_path` needs no repair entry, and a back-filling one would be actively wrong** — it would pre-dismiss every banner on every existing draft, the opposite of the intent.

`insert_library` **pre-answers** this field for every section it copies out of the entry (`{content.type: library_id for content in vulnerability.contents}`, set immediately after construction and therefore before `apply_poc_variant` adds proof-of-concept steps). A finding inserted from the library already holds that entry's description and remediation, so without this it would open the Content page offering to install the text it was born with. Proof-of-concept is deliberately **not** this field's to mark — that offer is tracked by `poc_variants`/`poc_variant_declined`, and `pendingLibraryOffers` never consults `content_offer_resolved` for it.

`Vulnerability.conclusion_offer_resolved: list[str]` records which proof-of-concept last lines the In Conclusion offer has already put to the tester, whether they accepted or dismissed it, so an answered line stops coming back. It stores **the text itself**, not an id or a hash: a `ListItem` has no `frag_id`, the list textarea rewrites every item to a single plain run on any keystroke, and `remintFragments` reassigns ids on every copy, so there is nothing stable to point at; a hash would need a new synchronous Python/JavaScript twin for a value only the client reads. The stored text is also what the banner matches against the front of the conclusion paragraph to decide between **Use it** and **Update the quoted step**. It defaults to `[]` via `default_factory` and needs no `load_path` repair. Like `content_offer_resolved` it is a plain `list`, not `Optional` — a missing key and `[]` both validate, an explicit `null` fails validation, and every writer must assign a list. It is **client-only in meaning**: the server round-trips it like any other field and no Python code reads it. Because the banner is keyed off this list rather than off whether the section holds work, it re-offers whenever the last step's text changes — including a reworded step, which the app cannot distinguish from an appended one, since the textarea rewrites every item on any edit.

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

`apply_poc_variant` takes a list of variants and a `mode`: `"replace"` (the default) overwrites the non-image fragments of the `proof_of_concept` section, `"merge"` keeps them and appends the library's steps after them. Either mode keeps every image exactly as it was, remints `frag_id`s, and never touches `previous_proof_of_concept`. **`merge_step_lists` then collapses each run of *consecutive* `numbered_list` fragments into its first one** — a fragment of any other type between two lists is a boundary it will not cross — because two list fragments each restart at `1.` in the generated document **unless the second one sets `continue_numbering`** (§6). By default `_render_component_fragment` opens a fresh `numbering_ids` cache per `ListFragment`, so `_remap_numbering` allocates a new `numId` and `_restart_numbering_levels` writes a `w:startOverride` back to the abstract level's `w:start`. When the flag is set, `_render_component_content` passes the previous numbered list's cache back in, so both fragments resolve through **one** `numId` and Word continues the sequence. The carry is held across fragments of other types — an image or a note between two lists does not break a chain, which is deliberately unlike `merge_step_lists`, whose boundary rule above is about rewriting the model rather than rendering it. Anything that is not a numbered list leaves the carry untouched; a numbered list that does *not* continue resets it. Merging also drops blank items, falling back to the first item when every item is blank. Installed app types are appended to `poc_variants`; only the app types just installed are removed from `poc_variant_declined`, because declining API and accepting Web are independent decisions.

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

`report.scope_text` exists **only in the browser and in the PUT body**. The server pops it in `reconcile_targets`, converts it to `scope_targets`, and never echoes it back. It is deliberately excluded from canonical reconciliation. Treat `scope_targets` as the truth; `scope_text` is an editing buffer.

**Its value is shape-dependent.** A location channel holds a newline-separated string; a component channel (`COMPONENT_CHANNELS`) holds `{component, description}`, two newline-separated strings paired **by raw index before cleaning** so a blank or `#` component line still consumes its index. `reconcile_targets` accepts either shape for **any** channel, so a browser cached from before the pair existed degrades rather than 422ing. On the client, `componentText` / `descriptionText` / `setScopeTextField` are the only readers and writers; the seed in `setup()` is a **total normalisation** over every environment x channel rather than an `=== undefined` fill, because a restored local draft can carry the old string for a channel that now expects the pair.

`ScopeTarget.description` is the durable home for the second box. It is **not** part of target identity: the reuse key stays `(environment, channel, value)`, so retyping a description never remints a `target_id` and never strands a finding. A repeated component is **refused** with a named 422 on component channels, because two builds of one name would otherwise lose the second row and its description silently; web and API keep collapsing duplicates, where a repeat is the same URL typed twice.

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
- **Back** (`.back-link` — both the footer button and the completed stepper steps) drains the complete serialized mutation queue, including work appended while it waits, then navigates only if `await save()` returned true. It is **never** gated on completeness, on any page. Leaving is not the transition that needs a finished report: completeness is a forward requirement, enforced by `#next` and by the `/findings` and `/edit` route gates. The gate Back used to carry was also counterproductive, because it returned *above* the `save()` call — a refused Back skipped the flush entirely and left the edits to the autosave debounce. `validateCurrentPage` is a single `const` local to `setup()`, holding `validateSetupPage` or `validateFindingsPage`, and `#next` is its only reader; `continuousEditor()` no longer assigns it.
- `save()` clears the autosave timer first so a queued debounce cannot fire mid-navigation.
- `pagehide` finalizes the open text transaction and writes the local draft synchronously. Recovery keys are `vulnreport-pending:{reportId}:{tabId}:{documentId}`: `tabId` keeps ownership stable across full-page navigation, while the per-document suffix stops a later page's successful save from deleting an unresolved snapshot left by an earlier history entry. Cleanup also removes the legacy `{reportId}:{tabId}` key, and a restored snapshot is removed explicitly through `restoredDraftKey` after its successful save.
- `pageshow` compares a clean history-restored document with the newest revision saved in this tab and reloads stale cached HTML before it can create a false self-conflict. A restored page with pending edits is not reloaded into data loss; it retains the ordinary recovery/conflict path.
- `beforeunload` prompts when `saveRevision > savedRevision` unless `allowUnsavedUnload` is set.
- `visibilitychange` to hidden forces an immediate save when one is pending.

**Undo and redo navigate too.** `restoreHistory` applies the change, forces `pendingSave`, persists the local draft and the history stacks, points `sessionStorage["vulnreport-recovery:{reportId}"]` at the local draft key, sets `allowUnsavedUnload`, then `await save()` and `window.location.reload()` — so the server judges the page gates against the undone state rather than the state before it. The resolved value of that save is not checked; a refused save still reloads, and the boot-time recovery selection re-adopts the undone draft. A storage failure anywhere in that sequence rolls the change back instead and leaves the page alone.

**Server-side gates can bounce a direct URL:** `/findings` redirects to `/setup?incomplete=setup` when setup is incomplete; `/edit` redirects to `/findings?incomplete=findings`. The client reads that query parameter to pre-open the validation notice, and the findings branch also sets `data-validation-attempted` on `#findings`, so the notice carries the live count of what each finding is missing and clears itself as they are filled, rather than a fixed sentence that never updates. That flag is what `updateFindingSummary` early-returns on, and the only other writer is `validateFindingsPage(true)` — so the reveal is tied to forward intent alone. A client-side rule that disagrees with its server counterpart shows up here as a redirect loop or an unexplained bounce.

---

## 11. Evidence upload

1. Client enters `trackMutation`, waits for any earlier library insert or evidence upload to settle, then flushes the whole report (`await save("Uploading...")`) and aborts the upload if that fails.
2. `POST /reports/{id}/evidence` with `FormData{file}` and the `X-Report-Saved-At` header.
3. Server normalizes to PNG (EXIF transpose, RGB convert, pixel-count and 20 MB limits), then `save_evidence_if_current` writes image bytes **and** report metadata under one lock, with a 250 MB per-report cap.
4. On failure the just-written file is unlinked so no orphan is left.
5. Client stores only `evidence_id`; it never handles a path. Display is `GET /reports/{id}/evidence/{evidence_id}`, which rejects any resolved path whose parent is not that report's `evidence/` directory.

The hidden file input is cleared immediately after its `File` object is captured. A failed or conflict-blocked attempt can therefore select the identical screenshot again and still receive a native `change` event.

Empty evidence tiles are not highlighted on page load. The readiness panel records an in-memory reveal key containing the finding, section, environment, and `frag_id` only when the tester activates that row's **Go to** action, so multiple empty slots in one environment remain independently addressable. This reveal state is intentionally discarded on reload.

The shared client helpers `evidenceIdsIn` and `dropUnreferencedEvidence` remove registry entries whose fragment references were deleted by scope changes, finding deletion, or library content replacement. `Workspace._drop_orphan_evidence` then deletes PNG files absent from `report.evidence` on every save. The server sweep deliberately treats the registry as authoritative; dropping only a fragment's `evidence_id` without removing its registry entry does not delete the file.

---

## 12. Rules that exist twice

These are implemented in both Python and JavaScript and **must be changed in pairs**. `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` is the only contract test, and it covers **generation readiness alone** — it drives a browser and compares `#issue-count[data-state]` against `generation_issues`. It does not read any JavaScript constant, and it does not touch the app-type, scope-survival, or proof-of-concept rows below. Those have no drift guard.

| Rule | Python | JavaScript |
|---|---|---|
| per-field character sets, identical wording | `setup_input_issues`, `CHARACTER_NAMES` | `characterRule`, `setupRules`, `characterNames` |
| username shape | `USERNAME_PATTERN` | `setupRules.username` |
| test window start ≤ end | `TestWindow.validate_order`, `setup_input_issues` | `validateDateOrder` |
| the default test time | `TestWindow.test_time` | the `test_windows` seed in `setup()` |
| setup completeness | `setup_issues` / `setup_is_complete` | `validateSetupPage`, `updateSetupValidationNotice` — **and the count is taken from the DOM, not the model**: all four sites read `textarea[data-scope-field="component"]` inside a `#scope-grid .scope-panel`, the other two being `setupSectionSummary` and the scope textarea's own `oninput`. A component channel renders a second textarea (`data-scope-field="description"`), so every counter must stay narrowed to the component box or a Description-only entry passes the client gate and 422s on the server |
| a component must carry a description | the per-target loop in `setup_issues` | `missingDescriptionIssues`, read by `validateSetupPage` and `updateSetupValidationNotice`. Both sides pair the two boxes **by raw index before cleaning**, exactly as `reconcile_targets` does, so a blank or `#` component line cannot shift the descriptions below it onto the wrong binary. The strings must match verbatim |
| Mobile and Thick Client are mutually exclusive | the `COMPONENT_CHANNELS` check in `setup_issues` | `componentExclusionIssue`. **Deliberately nowhere else**: `validate_coverage` and `resolve_tested_channels` are both on the load path, and raising there demotes the draft to the manager's legacy list, which only marks `duplicate fragment id:` as repairable. As a completeness issue it gates Findings, Editor and generation while leaving the report loadable, savable, and fixable on the one page holding both checkboxes |
| finding completeness | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` |
| a finding claims a location at all | `scope_has_location` | `scopeHasLocation`, `scopeTargetIds` — `target_ids` is **presence only**, neither side checks that they resolve; a typed line is held to more, see below |
| which typed lines in the additional-locations box count | `location_lines` | `locationLines` |
| a scope still reaches a surviving target | `_scope_reaches_a_location` | `scopeReaches` — resolution-aware, intersects against the target list |
| which locations a finding prints | `docx_report._finding_locations` | none — generation is server-only |
| affected environments | `affected_environments` | `affectedEnvironments`, `scopeEnvironments` |
| affected app types | `affected_channels` | `affectedChannels` |
| canonical app-type order | `CHANNELS` in `models.py`; `docx_report.CHANNEL_ORDER` is a `list()` copy of it | `CHANNELS`, module scope in `app.js`, **and a third copy** — `variants` in `library_editor.html`, paired with one `poc_<channel>` textarea each. That page does not load `app.js`, so it cannot share the constant and is the copy a channel change forgets. `test_the_library_editor_offers_every_channel_the_model_knows` is the only thing guarding it, since no browser test loads that page |
| app-type display labels | `CHANNEL_LABELS` in `models.py` | `channelLabels` in `app.js`. Read by the checkbox labels, the removal and swap dialogs, and **both** sides of the scope character message and the missing-description issue. A channel present in one table and not the other prints `undefined` into a message the tester reads |
| which app types are scoped as a component | `COMPONENT_CHANNELS` in `models.py` | `COMPONENT_CHANNELS` / `isComponentChannel` in `app.js`. Decides four things at once: the mutual-exclusion rule, the two-box input, the character allowlist, and template selection |
| which app types a report covers | `resolve_tested_channels` | the `tested_channels` seed in `setup()`, which twins branches 4 and 5 only |
| which targets survive an app-type or environment change | the target loop in `reconcile_targets` | `findingsStrandedBy`, and `dropTargetsEverywhere` for the confirmed purge (`dropChannelEverywhere` wraps it) |
| which targets survive a scope-text edit | the same loop, reusing IDs by value | `survivingAfterScopeText`, `scopeTextStrandedFindings` — **not an exact twin**, see below |
| component scope character allowlist | `COMPONENT_SCOPE_SYMBOLS`, applied by `invalid_character_issue` inside `reconcile_targets` | `componentScopeRule`. One set for **both** boxes, applied to component channels only — a URL carries `?` and `=`, so web and API stay unvalidated. A strict superset of the retired mobile set, widened by `\ [ ]` so an install path is typable |
| library proof-of-concept selection | `applicable_poc_variants` | `applicablePocVariants` |
| installing proof-of-concept steps, replace or merge-append | `apply_poc_variant` (`mode="replace"`/`"merge"`) | `applyPocVariant` (`mode` param) |
| collapsing adjacent appended steps into one numbered list, without crossing an intervening fragment | `merge_step_lists` | `mergeStepLists` |
| generation readiness | `generation_issues` | `updateReadinessPanel`, `fragmentIssues` |
| description and remediation are never empty | `generation_issues` (`content.fragments` check) | `requiresFragment`, `fragmentIssues`, `deletionBlockedReason` |
| placeholder text regex | `PLACEHOLDER_TEXT` | `placeholderPattern` (byte-identical) |
| environment gating for fragments | `fragment_applies` | inline check in `updateReadinessPanel` |
| image slots | `sync_evidence_image_slots` | `syncEvidenceImageSlots` |
| status to section list | `content_types_for_status` | `contentTypesForStatus`, used by `provision`, the readiness panel, the editor's section render, and the status `onchange` |
| whether a section holds tester work | `content_has_work` | `contentHasWork` |
| resolved remediation boilerplate | `provision` (`RESOLVED_REMEDIATION`, `generated="resolved_remediation"`) | `provision` (`RESOLVED_REMEDIATION`) |
| the default In Conclusion sentence, and finding it inside its paragraph | `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN`, `default_conclusion_span`, `default_conclusion_start`, `is_default_status_conclusion` | `statusConclusionRuns`, `STATUS_CONCLUSION_PATTERN`, `defaultConclusionSpan`, `defaultConclusionStart`, `isDefaultStatusConclusion` |
| splitting a paragraph's runs at the sentence boundary | `_runs_up_to`, `_runs_after` | `runsUpTo`, `runsAfter` |
| which conclusion paragraph the app may write into | the two-arm selection in `provision`'s conclusion block | the same two arms in `syncConclusion` |
| a printed section that must never be empty | the `{description, recommended_remediation, in_conclusion}` set in `generation_issues` | `requiresFragment` |
| a conclusion still holding the app's own sentence | `generation_issues` | `fragmentIssues` |

The sentence now has **one builder and one recogniser per side**, named so the pair is visible: `status_conclusion_runs` / `STATUS_CONCLUSION_PATTERN` in Python, `statusConclusionRuns` / `STATUS_CONCLUSION_PATTERN` in JavaScript. It reads `The finding "<title>" is still ` / `is `, then a bold `Open`/`Resolved`, then `.`. The recogniser accepts embedded newlines and greedily selects the final status clause, so imported titles containing quotation marks or status-like text cannot truncate the match. It is the only thing linking builder to consumer: relax one without the other and every default on disk stops being recognised, freezing at the title and status it was stored with. `test_the_conclusion_recogniser_matches_what_the_builder_writes` feeds the builder's own output back to the recogniser and is the drift guard.

**The sentence can sit inside a larger paragraph.** An accepted proof-of-concept step sits in front of it in the *same* paragraph (§13), and a tester can append prose after it without having replaced it. `default_conclusion_span` / `defaultConclusionSpan` locates the sentence's exact bounds; `default_conclusion_start` / `defaultConclusionStart` returns its offset only when it remains the paragraph tail. Both ignore trailing whitespace and scan right to left, which keeps a title containing a quotation mark resolving correctly.

- `is_default_status_conclusion` / `isDefaultStatusConclusion` — start is exactly `0`, i.e. the paragraph is *nothing but* the app's sentence. This is the one `content_has_work` and the readiness/generation rule both use, so a paragraph carrying a quoted step counts as tester work and the section is carried through a status change instead of being dropped.
- **span is not `None`** — the paragraph still contains the sentence. This is what `provision`'s selection arm and both readiness rules use. Using the stricter predicate there would let surrounding prose hide the sentence and silently discharge "replace the default."

Rewriting replaces **only the recognized span**: `_runs_up_to` / `runsUpTo` and `_runs_after` / `runsAfter` keep the runs on both sides with their own formatting. The tester's quoted step and any appended explanation therefore survive every save.

**The app never writes that sentence on its own.** `provision` creates the `in_conclusion` section with a single **empty** paragraph and stops there; the Content page offers the sentence on a click (§13). The only case where either side writes it is a paragraph that carries `generated == "status_conclusion"` or **already contains** the recognised sentence — that is the re-derivation that keeps an accepted sentence tracking the finding's name and status. There is deliberately no arm for "a paragraph with no text": a paragraph the tester emptied is theirs, and refilling it wrote boilerplate above a conclusion they had just written, on a page load, because the client twin runs on editor boot.

**`in_conclusion` is the one section a status change does not carry.** Every other unprinted section holding work is kept out of sight so switching status and back brings it with it. The conclusion is excluded on both sides, because it is a statement *about* the status: carrying it would preserve a sentence the new status has just made false. Switching to `open_new` drops the section outright, and switching back re-creates it empty, which is what puts the restore offer in front of the tester rather than silently reinstating stale text.

Note that `generated = "status_conclusion"` is **read-only legacy** — `provision` clears it to `None` whenever it writes the sentence, `syncConclusion` does the same with `delete`, and no draft on disk carries it. Code that finds one prunes every sibling paragraph with no text, but the marker no longer forces the rewrite: the regex alone decides whether the sentence is still there, because a stored marker outlives the text it described and was overwriting conclusions the tester had already written.

**Previous proof of concept is historical, and that rule lives in five places.** `fragment_applies`, `sync_evidence_image_slots` and the evidence-coverage check in `generation_issues` all exempt it on the Python side. The browser mirrors it in `syncEvidenceImageSlots` and `fragmentIssues`, and two client-only paths must respect it as well: `settleScopeChange` must not **delete** a historical image when an environment leaves the scope, and the image editor must not **overwrite** a historical `environment` while rendering. A historical image offers every environment and starts unset, because only the tester knows where a carried screenshot came from.

**Numbered-list continuation is a twin.** Python renders it (`_render_component_content`'s `numbering_carry`) and JavaScript previews it (`numberingOffset` in `app.js`, which seeds the list textarea's gutter). Both walk backwards from the fragment through the same section, both stop at the first numbered list that is not itself continuing, and both ignore fragments of other types on the way. They differ in what they count, and must: Word counts rendered items, so the JavaScript sums **non-blank** items only, matching the renderer's own skipping of blank ones. A change to either side's walk direction, stop condition or blank handling silently desynchronises the gutter from the document; `tests/test_docx.py::test_a_continued_numbered_list_shares_one_numbering_with_the_list_above_it` and `tests/test_browser.py::test_a_continued_list_numbers_on_from_the_one_above_it` pin the two ends.

**The non-production label's character set is a twin.** `setup_input_issues` checks it with `invalid_character_issue("Non-Production name", value, "/-")`; `app.js` mirrors it as `setupRules.non_production_label`. Both are **gated on non-production being a covered environment**, and that gate is itself the rule: an unticked Non-Production leaves the field disabled, a disabled input is exempt from browser validation, so a Python check without the gate would 422 a save the client had no way to block. The allowed set is deliberately a **subset of the Limitations set**, because the retest suggestion below writes this label into `engagement.limitations` — a character legal here but not there would make an accepted suggestion fail the very next save. Colon is excluded: `docx_import` builds `f"{label.upper()}:"` to recognise the heading, so a colon in the label produces a doubled heading that collides with `INSTANCE_PREFIX`. `tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save` asserts the browser's `validationMessage` is byte-identical to the server's issue string, which is this twin's only drift guard.

**The preset list is a weak twin.** `NON_PRODUCTION_LABEL_PRESETS` in `models.py` is imported by `docx_import._detect_non_production_label`, which scans a generated document for a `<LABEL>:` heading and adopts whichever it finds; `app.js` repeats the four values to build the dropdown. Only the Python side has to be complete — it also carries `LEGACY_NON_PRODUCTION_LABELS` — because the evidence heading is the label's **only** appearance in a document. The scope table rows read "Non-Production Environment" from the template, not from the tester's label. Miss the heading and every image below it inherits the previous environment, so non-production evidence imports as production. A tester who types a fully custom label still gets that broken round trip; nothing can recover it without guessing.

**The retest Limitations sentence is deliberately *not* a twin.** `Retest only in PROD; no <LABEL> testing.` is generated in `app.js` alone, offered in a `#limitations-offer` banner, and written only on click. The banner has two modes, both live off `reportchange` so a rename updates them without a reload: **add** while the field still holds `N/A` or nothing, and **update** when the field holds a sentence this app generated whose environment name or direction no longer matches. The update mode matches `^Retest only in PROD; no .+ testing\.$` / `^Retest only in .+; no PROD testing\.$` with the label left **open** rather than built from the stored one, so a limitation written against an earlier name is still recognised as ours — and so prose the tester composed is never offered for rewriting. Nothing in Python generates, recognises or re-derives any of this: `provision_report` touches vulnerabilities only, and `docx_report` prints `engagement.limitations` verbatim. Contrast the In Conclusion sentence, which **is** a twin purely because `provision` re-derives it on every save and so must recognise its own wording. A Python copy here would be a rule with no enforcement point and no caller — pure drift surface added for symmetry with a situation that does not apply. The banner holds dismissals in a module-local `Set` rather than a persisted field, for the reason recorded above on `content_offer_resolved`: a declared field can never be dropped again without silently deleting it from every draft.

Two consequences of the repaint guard worth knowing. It blocks a redraw **only** when the Limitations textarea itself holds the caret, because that is the one field the banner sits above and would shift; typing a name into the coverage control keeps updating the offer live. And the name control is disabled unless non-production is a covered environment, so a **production-only** retest cannot reach the rename at all — its sentence only goes stale when the environment selection changes, which the same check catches.

**`refreshContentOffers` holds back only the caret's own block**, not every block. It used to return early whenever *any* field held focus, on the theory that a banner appearing in `description` would move its grid neighbour `recommended_remediation`. `.content-row` is `align-items: start`, so that never happens — the columns are top-anchored and a banner in one cannot shift the other. The blanket guard had a real cost: editing a proof-of-concept step left the In Conclusion banner quoting the step the tester had just replaced, and it only caught up when they clicked away. `tests/test_browser.py::test_the_conclusion_offer_follows_the_proof_step_while_it_is_still_being_typed` pins the live path, and asserts the field still holds focus so that blurring can never make it pass by accident.

Python's `required_fragments` and the JavaScript `required` now seed identically — `["numbered_list", "image"]` into both proof-of-concept sections. They were out of step until 2026-09-14; anything that asks "is this section empty?" can now trust either side.

**Client-only:** the confirmation guards (`confirmScopeLoss`, `confirmScopeTextLoss`, `settleScopeChange`, the status-change and finding-deletion prompts) and `deletionBlockedReason`, which disables Delete on the fragments provisioning guarantees — the last fragment of any kind in `description` and `recommended_remediation`, the last `numbered_list` in either proof-of-concept section, the last `image` in `previous_proof_of_concept`, and the last `proof_of_concept` image for an affected environment. The server would recreate each on the next save, so the block exists to stop the editor looking like it discarded the change. The `description` and `recommended_remediation` rule counts fragments, not paragraphs: a library entry may supply a remediation that is a list and a note with no paragraph at all.

Every one of those guards is `await window.vrDialog.confirm(...)` (`dialog.js`), **not** `window.confirm` — there is no `window.confirm` anywhere in `app.js`. The difference is load-bearing for anything keyboard- or focus-related: a native `window.confirm` blocks the JavaScript thread, whereas a `vrDialog` is an ordinary DOM overlay that leaves timers, autosave, and document-level key handlers running underneath it. While one is open, `document.querySelector("[data-dialog]")` finds its backdrop; the evidence lightbox is a separate, native `<dialog>` opened with `showModal()` and carries no such attribute.

**`replaceFromLibrary` no longer confirms or copies content.** A title match on the Findings page now silently applies only `title`, `likelihood`, `impact`, `severity`, `library_ref` (`applyLibraryEntry`) — `contents` is untouched. Instead, each library-sourced content section (`description`, `recommended_remediation`, and `proof_of_concept`) offers its own client-only, state-derived banner on the Content page — same pattern as the pre-existing proof-of-concept offer — with three choices: keep, replace, or add (merge-append) the library's fragments for that section. `description`/`recommended_remediation` resolution is tracked in the new `content_offer_resolved` field (§6) and has no server-side twin, since the mutation rides the ordinary autosave PUT like any other Content-page edit. `proof_of_concept`'s offer reuses `poc_variant`/`poc_variant_declined` and, because `apply_poc_variant`/`applyPocVariant` already have a Python/JavaScript twin, its new merge-append mode had to be added to **both** sides (see the table above). `previous_proof_of_concept` is excluded from this mechanism entirely — it is never library-sourced. Every fragment copied in from a library entry, for replace or merge-append alike, gets a fresh `frag_id` (`remintFragments` client-side, `model_copy(deep=True)` + reassignment server-side) — `frag_id` uniqueness is report-wide, not per-section.

For `description` and `recommended_remediation`, merge-append asks whether the existing section has any tester work via `fragmentHasContent`. A wholly blank provisioned section contributes no fragments, avoiding an empty block before copied library content. Once any fragment contains work, the complete existing sequence is retained, including unfinished neighboring fragments such as a table the tester added but has not filled yet.

Replace snapshots the finding's evidence IDs before swapping fragments, then calls the shared `dropUnreferencedEvidence` afterward. The helper scans all remaining fragments across all findings, so evidence removed with the section is dropped from `report.evidence` while shared and unrelated evidence survives for the server file sweep.

Changing `library_ref.library_id` through `applyLibraryEntry` keeps every existing content fragment but clears `content_offer_resolved`, `poc_variants`, and `poc_variant_declined`. Those answers belong to the prior source entry; retaining channel-only POC answers would suppress different steps from the new entry.

`pendingLibraryOffers` is the **single owner** of "which sections still have an unanswered offer" — the Content-page banners and the readiness panel both read it, so they can never disagree. It offers a section whenever the entry has content for it, the section does not already match that content, and the section does not match the fingerprint recorded when the offer was last answered. The `status === "resolved"` filter stays **first**: that block renders locked with no fragment editors, so a banner there would offer an action the tester cannot complete.

Comparison and fingerprint share one normaliser, `normalizedSection`, and that is not tidiness. Absent, `null` and `false` all read the same to a tester, but the server dumps every optional field explicitly while `runsFrom` deletes false flags client-side, so a freshly typed `{text:"x"}` comes back as `{text:"x",bold:false,italic:false,underline:false}` and `reconcileCanonicalObject` splices the canonical runs over the live ones. A fingerprint over a strict comparison would therefore be invalidated **by its own save**, un-dismissing the banner seconds later with the tester not touching anything. The normaliser coerces rather than strips, and emits arrays so key order cannot matter. If the trigger and the dismissal ever disagree about what "the same" means, banners self-dismiss or dismissals never take.

The proof-of-concept offer needs no fingerprint: library steps live in `LibraryEntry.proof_of_concept`, not in `contents`, so "differs from the library" is undefined there and the trigger is emptiness instead. `poc_variant_declined` is already a persisted dismissal. `pocHasWrittenSteps` overrides `poc_variants` but never `poc_variant_declined` — **a decline is permanent, an install is not**, because the record of installing describes content that is no longer there. Images are excluded from that predicate on purpose: a screenshot is not a step, and `applyPocVariant` lifts images out and re-appends them in both modes, which is the only thing standing between a widened offer and a deleted screenshot.

**Banners are rebuilt without redrawing the pane.** `contentOffersFor(finding, content)` returns nodes rather than appending them, so `render()` and a `reportchange` listener produce byte-identical output from one source. `render()` is the only thing that rebuilds the pane and typing never calls it — deliberately, since it would destroy the caret — so before this an offer earned by an edit waited for a section toggle or a reload. Three rules keep the refresh safe: it **returns immediately while any text field has focus**, which covers both the caret's own block and the sibling that shares its grid row; it **compares serialised markup before replacing**, so a button is never swapped out from under a click; and it **must never write to `report`**, because a write there calls `scheduleSave`, which dispatches `reportchange` again — an unbounded save loop consuming the single `draft.bak.json` each pass. `updateReadinessPanel` is the existing read-only precedent. The `focusout` handler dispatches one extra tick so leaving a field is the moment a banner can appear. There is **no wrapper element**: `.content-block` is a grid styled by child position in rules duplicated in `taste.css`, and a permanent slot would cost every section its heading gap.

**The In Conclusion section carries two more client-only banners**, both state-derived like the library offers and both writing nothing without a click. The first quotes `pocLastStep(finding)` — the last non-blank line of the last `numbered_list`, `bulleted_list` or `note` in `proof_of_concept`, scanning in reverse, with `previous_proof_of_concept` excluded so a retest conclusion never quotes last year's steps — and writes it **into the front of the paragraph that already holds the status sentence**, not into a paragraph of its own. That is why the sentence has to be recognised as a tail (§12); a quoted step and the sentence share one paragraph, reading as `Observe the balance of another user. The finding "X" is still Open.` It is suppressed once that text is in `conclusion_offer_resolved` (§6), and the primary button becomes **Update the quoted step** when the paragraph already starts with a previously offered line, so a corrected step replaces its predecessor via `runsAfter` rather than stacking in front of it. Once the tester edits the quoted text it no longer matches, and a later step goes in front of their words instead of overwriting them. Deliberate consequences: a proof of concept ending in an image, table or code block is offered the prose line *above* it, and the copied line is a **snapshot** — editing the step later does not update the conclusion, though it does re-offer. The second banner appears when the section holds a text-less paragraph and no paragraph ending with the sentence, and writes the sentence back **in place** into the last such paragraph, leaving the fragment count unchanged, and clears `conclusion_offer_resolved` — a conclusion returned to boilerplate holds nothing the tester chose, so an earlier "not that step" no longer describes anything and the step offer starts over. Accepting it swaps one readiness row for another (`text is required` becomes `still holds the default sentence`), which is why its copy says so; it is never a move from clean to blocked.

Both banners are built during `render()`, which does **not** run while the tester types — `scheduleSave` only queues `reportchange`, whose listeners are the readiness panel and the setup summaries. So a banner earned by an edit appears at the next render (finding switch, section toggle, fragment add or delete, any banner click, undo/redo, or reload), not mid-keystroke. That is what keeps the quoted text from churning character by character, and it is the reason neither banner needs a "finished typing" event, which the list textarea does not have.

`offerConclusionRewrite` is the shared replace-or-keep prompt. There are five client-side title and status writes, and it is awaited at **three** of them: the Findings row title `onchange`, the Findings row status `onchange`, and the editor's `finishTitle`. The other two — the Findings row title `oninput`, which renames per keystroke, and `applyLibraryEntry` — re-derive the sentence through `syncConclusion` without prompting. It fires **only** when the section's first paragraph is tester prose — boilerplate is re-derived silently, exactly as before — and it must be awaited strictly after the status dialog resolves, because `vrDialog` cancels whatever is already open. `applyLibraryEntry` gained a `syncConclusion` call as part of this: it was the only one of the five title writes that did not re-derive the sentence, which was harmless while the server fixed it on the next save but is not once the tester is being prompted about that sentence at that moment.

**List paste strips the markers the gutter already draws.** `onpaste` on the list textarea removes `^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+` per logical list line. Every pasted line after the first starts a new item; the first is stripped only when the selection begins at the start or indentation of the existing textarea line, so inserting `1. value` into the middle of prose cannot delete it. The trailing whitespace requirement is load-bearing — it is what keeps `1.2.3.4 is the host` intact — and roman and lettered markers (`a.`, `iv)`) are deliberately not stripped, being too close to prose to risk deleting text silently. It is **client-only with no Python owner, by decision, not omission**: this is a rule about the clipboard on its way into a field, not an invariant of the document, and a server-side stripper in `provision` would run on every save and permanently delete a `1.` a tester typed on purpose. Drafts arriving through `import_report` or `parse_report_docx` therefore bypass it, which is correct. The handler is bracketed by `finalizeTextTransaction()` so the paste is exactly one undo step rather than folding into the whole time the tester spent in that field, and `oninput` remains the only writer of `fragment.items`.

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
- **`ScopeTarget.description` is validated on the Setup path only.** The character allowlist lives inside `reconcile_targets`, which returns early when `scope_text` is absent, so a Findings or Content PUT carrying `scope_targets` with descriptions is unchecked. The same hole already existed for `value`; the second free-text field doubles its surface rather than opening it.
- **The app-type swap counts saved targets, not typed text.** `channelRemovalImpact` reads `report.scope_targets`, which only the server populates, so scope typed and not yet saved is invisible to the confirmation and is destroyed silently. The plain untick path has the identical gap; this is pre-existing behaviour, not something the component channels introduced.
- **A new export dropped into an older build loses every `description`.** Pydantic's default `extra="ignore"` deletes the undeclared key with no error. The reverse direction is safe, since `description` defaults to `""`.
- **`provision` seeds only into an *empty* section.** A finding whose `previous_proof_of_concept` already holds steps but no image will never gain the image slot, so the seed reaches new sections only, never existing drafts. Backfilling instead would add empty fragments that readiness then demands text for, which is why it stays this way.
- **`generation_issues` validates the images that exist; it does not require one to exist.** Only `affected_environments` coverage forces an image into being, and that is measured against `proof_of_concept` alone. A `previous_proof_of_concept` holding steps and no image is therefore generation-clean.
