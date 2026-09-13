# VulnReport - Current Project Plan

## Status

VulnReport is a local vulnerability-report authoring application. The implemented
scope is structured report drafting, JSON persistence, evidence storage, report
management, and Word report generation through the supplied canonical template.

- Owner: Elias Angelo Viguilla
- Schema version: 1.4
- Runtime: local FastAPI app on `127.0.0.1`; `run.py` selects the first
  available port from `8765` through `8799` (the manual command below uses
  `8770`)
- Setup: `py -3 run.py` is the only command a user needs. It creates `.venv`,
  installs `requirements.txt` into it when the file's sha256 differs from the
  stamp in `.venv/.requirements-sha256`, then relaunches itself with the
  virtual-environment interpreter.
- Distribution: plain project folder with Python dependencies; no hosted service
- Persistence: JSON drafts and PNG evidence under `data/apps/`
- Platform: drafting, saving, import, and export are cross-platform. **Report
  generation requires Windows with Microsoft Word installed** - see
  [Platform requirements](#platform-requirements).
- Last verified: 2026-09-11; all 70 automated tests pass

## Platform requirements

Every code path that produces a finished report ends in Microsoft Word COM
automation, and there is no opt-out on the web route:

- `finalized_report` in `app/main.py` calls `update_docx_bytes_with_word`
  unconditionally after `render_report_docx`.
- `scripts/generate_report.py` does the same.
- `app/docx_captions.py` raises
  `RuntimeError("Microsoft Word automation requires the existing pywin32 package")`
  when `pythoncom` / `win32com.client` cannot be imported. The route converts
  that into HTTP 422.

Word supplies what python-docx cannot: repagination, Table of Contents and Table
of Figures rebuild, and field refresh. Word calls are serialized by
`WORD_AUTOMATION_LOCK`.

Only `scripts/postprocess_captions.py` accepts `--skip-word-update`, and it
operates on an already-generated document.

On macOS or Linux the application runs, saves, imports, and exports normally;
Generate fails with a 422. That is expected, not a defect.

## Configuration

All limits are read from the environment at import time through
`configured_limit`, which silently falls back to the default when a value cannot
be parsed. Changing one requires a restart.

| Variable | Default |
|---|---|
| `VULNREPORT_MAX_JSON_BYTES` | 10 MB |
| `VULNREPORT_MAX_BUNDLE_BYTES` | 100 MB |
| `VULNREPORT_MAX_EXPANDED_BUNDLE_BYTES` | 250 MB |
| `VULNREPORT_MAX_BUNDLE_FILES` | 1000 |
| `VULNREPORT_MAX_IMAGE_BYTES` | 20 MB |
| `VULNREPORT_MAX_IMAGE_PIXELS` | 40000000 |
| `VULNREPORT_MAX_REPORT_EVIDENCE_BYTES` | 250 MB |

Two browser-side values are read off `window` rather than the environment:
`VULNREPORT_AUTOSAVE_IDLE_MS` and its older alias
`VULNREPORT_AUTOSAVE_INTERVAL_MS` (default 5000 ms, floor 100 ms).

The vulnerability library path comes from `prefs.library_path`. A relative value
resolves against the project root. When that path is not a file the loader falls
back to `resources/vuln_library.json`, creating the directory and seeding the
file if it is missing.

## Implemented Features

### Report management

The home page (`/`) is a report manager. It provides:

- Application-folder groups, sorted alphabetically and collapsed by default.
- App-folder search. Matching folders are expanded while searching.
- Report rows with report name, ID, last saved timestamp, finding count, and
  Open, Export, and Delete actions.
- Portable ZIP export through `/reports/{report_id}/export`, containing
  `draft.json` and all referenced PNG evidence.
- Export filenames use `<segment> - <application name> - <report type> <report
  year>.zip`, for example `JH - Payments - Annual Pentest 2026.zip`.
- ZIP import through `/reports/import`, with evidence hash/dimension checks.
  Evidence-free legacy JSON exports remain importable. Imports are
  schema-validated and assigned a new report ID, so they cannot overwrite an
  existing draft.
- Invalid legacy drafts remain isolated from valid reports. The manager can
  repair duplicate fragment IDs when the resulting draft fully validates.
- Inline application-name rename through `/reports/{report_id}/name`.
- Report duplication through `/reports/{report_id}/duplicate`, including all
  evidence files, under a fresh report ID.
- Report deletion, including evidence in that report folder. Expanded app
  folders remain expanded after a report list refresh.

Invalid legacy drafts are skipped by the manager rather than breaking the list.
Repairable drafts are discovered dynamically through `/reports/legacy`; local
report IDs are runtime data and are not tracked in this plan.

### Three-step workflow

1. Setup (`/reports/{report_id}/setup`)
   - Engagement metadata: segment, application name, report type, CI/BSN,
     owner, tester, and report date. CI and BSN are both optional.
   - Required segments: JH, GWAM, or Asia.
   - Required report types: Annual Pentest, Retest, Deployment Pentest, or New
     Test.
   - Selected environments, test surface, test windows, free-text test time,
     and scope targets. Environment time defaults to `Any time`; letters,
     numbers, spaces, colons, slashes, and hyphens are accepted.
   - Start and end dates may be the same day. Each native date picker updates
     the other picker's inclusive `min`/`max` bound so reversed ranges cannot
     be selected; the backend independently enforces the same rule.
   - An optional test-account table stores user role and username pairs. New
     reports begin with one `N/A` / `N/A` row and support additional rows.
   - Optional testing limitations default to `N/A` and accept hyphens alongside
     the documented punctuation.
   - Scope targets are one entry per line and are stored as stable target IDs.
     Mobile targets are names/identifiers rather than URLs: they accept letters,
     numbers, spaces, and `:'"/.,-_&`. Comment lines beginning with `#` are
     ignored. Web and API targets retain their independent behavior.
   - Browser and server validation both require segment, application name,
     report type, tester, at least one environment, complete dates, and a
     target for every selected environment before advancing.
   - Invalid-character messages identify only the offending unique characters,
     including both symbol and name, such as `"_" (underscore)`.

2. Findings (`/reports/{report_id}/findings`)
   - Create manual findings or insert from `vuln_library.json`.
   - Edit likelihood, impact, severity, Vuln ID, status, and affected locations.
   - Finding column uses 50% of the table width; titles wrap at word boundaries.
   - Likelihood, impact, and severity remain native selects with compact
     severity-colored chip styling.
   - A finding requires a title, all assessment fields, status, and at least one
     selected or custom location before advancing.
   - Each environment has one compact additional-endpoints textbox. Every
     non-empty line is stored as one affected endpoint, and the field grows for
     new lines or wrapped text while selected Setup scope targets remain linked.
     A synchronized left gutter displays one bullet per endpoint.
   - Library insertion copies configured default values and content fragments.
   - An invalid Findings page cannot navigate either forward or backward; the
     first incomplete finding is highlighted.

3. Content (`/reports/{report_id}/edit`)
   - Sidebar is ordered by severity, then title.
   - One selected finding is edited at a time alongside a readiness/review panel.
   - Finding titles can be clicked to edit. Blur saves and returns them to text
     without scrolling the page. Long titles wrap at word boundaries.
   - Assessment values are displayed as static metadata; edit them on Findings.
   - Supported fragments: paragraphs, numbered and bulleted lists, notes, code
     blocks, images, instance titles, and tables.
   - Paragraphs have bold, italic, and underline controls positioned beside the
     fragment title. Numbered and bulleted
     lists use one compact textbox where each non-empty line is stored as one
     item; it grows for new lines or wrapped text, and a synchronized left
     gutter displays numbers or bullets. Notes are editable but intentionally
     have no formatting controls.
   - Fragment cards support pointer drag reordering, keyboard-accessible Move
     up/down controls, deletion, and content-specific add controls.
   - Image fragments are assigned to Production or Non-Production. Every
     environment affected by a finding requires at least one uploaded image;
     testers may add any number of additional images for either environment.
     A single affected environment is assigned automatically; when both are
     affected, image cards offer only Production and Non-Production choices.
   - Auto-growing text fields wrap by word rather than splitting words.
   - For Open (Previously Discovered) and Resolved findings, In Conclusion
     starts with one editable paragraph containing the status-based sentence.
     The sentence tracks title/status while untouched; after a tester modifies
     it, saves preserve their wording. Additional paragraphs or notes can still
     be added through the fragment control. The editor displays a tester-only
     reminder to include a brief justification or explanation; that reminder is
     not stored in or exported with the report.
   - Content readiness blocks report generation, but never Previous navigation:
     a tester on their way back to fix gaps is not held on the page.
     Generate first saves and acknowledges every pending edit, then starts the
     generation request; duplicate clicks cannot start parallel generations.

### Persistence and safety

- Browser changes remain locally recoverable and save to the backend after a
  trailing five-second idle delay, when the page becomes hidden, before valid
  workflow navigation, before generation, or immediately through the top-right
  Save button. Page unload persists local recovery and warns while the current
  edit revision is newer than the acknowledged server revision.
- Explicit save states are `unsaved`, `saving`, `saved`, `failed`, `conflict`,
  and `recovered`; successful acknowledgements display their save time.
- Local recovery uses versioned, per-tab `localStorage` envelopes containing the
  base server revision, capture time, edit revision, and report snapshot. A
  local draft is never silently applied: Restore/Discard is required, and stale
  drafts are identified as based on an older server version.
- If browser recovery storage is unavailable, the UI keeps server saving active
  while displaying a persistent warning. Restore, Discard, undo, and redo avoid
  reload/data loss when their required storage operation fails.
- Saves are serialized within one browser tab. The server performs a locked
  compare-and-swap on `saved_at` across threads and local app processes, so a
  stale request cannot overwrite a newer revision.
- PUT requests use immutable snapshots and reconcile canonical backend changes
  into existing browser objects without overwriting edits made while the request
  was in flight. Transient network/5xx failures retry automatically up to three
  times with exponential delay.
- Library insertion and evidence upload flush pending edits, return their saved
  revision, reconcile browser state, and immediately save resulting references.
- Recovery storage is cleared only after the current revision saves
  successfully. A `409` conflict preserves the local draft and undo history
  until the tester explicitly confirms a reload.
- JSON drafts use unique same-directory temporary files, atomic replacement,
  bounded retries for transient Windows locks, cleanup on failure, and a
  `.bak.json` backup.
- Pydantic validates saved and imported data, including safe and unique IDs,
  target/evidence references, content uniqueness, evidence metadata, and date
  ordering.
- Evidence uploads are size/pixel/quota bounded, decoded, EXIF-normalized,
  converted to PNG, and atomically stored within the owning report folder.
  Evidence writes, folder migration, metadata persistence, and cleanup share
  one per-report lock.
- Undo/redo uses compact reversible JSON patches, persists for the browser
  session, coalesces continuous text typing, and rolls back in memory if its
  recovery snapshot cannot be persisted.
- Import parsing, image processing, report preparation, and disk persistence in
  async FastAPI routes run in the worker threadpool. Generation holds the report
  lock through validation, DOCX rendering, Word finalization, and output write.

## Architecture

```text
app/main.py                  FastAPI routes and report/evidence operations
app/docx_report.py           DOCX placeholder, fragment, image, and block renderer
app/report_service.py        Provisioning, scope reconciliation, workflow gates
app/workspace.py             Draft discovery, creation, import, delete, save
app/storage.py               Atomic JSON read/write helpers
app/library.py               Offline vulnerability library lookup
app/models.py                Pydantic schema version 1.4
app/tester_identity.py       Local tester identity and preferences
app/web/templates/           Jinja pages: manager, Setup, Findings, Content
app/web/static/app.js        Workflow UI state, validation, autosave, editor
app/web/static/manager.js    Report manager interactions
app/web/static/app.css       Legacy base styles
app/web/static/overrides.css Active workflow styling overrides
app/web/static/manager.css   Report manager styling
resources/vuln_library.json  Offline vulnerability library
resources/MAIN_TEST.docx     Canonical Word report template
resources/severity_titles/   Severity grouping components
resources/finding_types/     Status-specific finding components
resources/fragments/         Content fragment components
scripts/generate_report.py   Command-line DOCX generator
scripts/postprocess_captions.py DOCX caption post-processor
scripts/compose_component_test.py DOCX component proof generator
docs/                        Architecture, routes, form-state, and DOCX notes
resources/fixtures/          Test-only document fixtures
requirements-dev.txt         Test-only HTTP and Playwright dependencies
```

Frontend is Jinja2 plus vanilla JavaScript and hand-written CSS. There is no
Node.js, npm, framework, CDN, or build step.

## Data Layout

```text
data/
  prefs.json
  .locks/
  apps/
    <app-folder>/
      <report-folder>/
        draft.json
        draft.bak.json
        evidence/
          ev_*.png
```

Folder names are not identities. `report_id` inside `draft.json` is the report
identity; discovery scans drafts. `app_id` is derived from CI number, then BSN,
then application name, then `unnamed` when none is set. Existing unnamed drafts
move into the derived app folder when their application identity becomes
available.

## API Surface

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Report manager |
| GET | `/new` | Create report and redirect to Setup |
| GET | `/reports` | List valid reports for the manager |
| GET | `/reports/legacy` | List invalid drafts and repair eligibility |
| GET | `/reports/{id}/setup` | Setup page |
| GET | `/reports/{id}/findings` | Findings page |
| GET | `/reports/{id}/edit` | Content editor |
| GET | `/reports/{id}` | Redirect a direct report URL to Setup |
| PUT | `/reports/{id}` | Validate, provision, and save a draft |
| DELETE | `/reports/{id}` | Delete report and its evidence |
| GET | `/reports/{id}/export` | Download report and evidence ZIP |
| GET | `/reports/{id}/generate` | Generate the completed Word report |
| POST | `/reports/{id}/generate` | Save the generated Word report into `generated/` at the repository root |
| POST | `/reports/import` | Validate/import ZIP or evidence-free JSON |
| PATCH | `/reports/{id}/name` | Rename the report application label |
| POST | `/reports/{id}/duplicate` | Duplicate a report and its evidence |
| POST | `/reports/{id}/repair` | Repair duplicate fragment IDs |
| GET | `/library/search` | Search the local vulnerability library |
| POST | `/reports/{id}/library/{library_id}` | Insert library finding |
| POST | `/reports/{id}/evidence` | Upload and normalize evidence image |
| GET | `/reports/{id}/evidence/{evidence_id}` | Serve evidence image |

## Verification

Run the server:

```powershell
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8770
```

Run isolated regression tests:

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -m playwright install chromium
py -3 -m unittest discover -s tests -v
```

Generate a completed report from the command line:

```powershell
py -3 -m scripts.generate_report <report_id>
```

Use `--allow-incomplete` only for layout previews; missing evidence is rendered
as a visible placeholder rather than silently omitted.

The automated suite currently contains 70 tests and uses temporary workspaces.
API tests cover report lifecycle,
atomic stale-write rejection, schema and request validation, all scope modes,
portable evidence round trips, limits, legacy migration/repair, preferences, and
library validation. Storage tests force a transient Windows replacement failure
and verify automatic retry/cleanup. DOCX tests render and reopen the supplied
template with repeated findings, tables, formatted fragments, embedded images,
and one bullet paragraph per Production/Non-Production Web/API scope line.
Playwright tests cover required choices, character messages, date bounds, Mobile
scope rules, account rows, limitations, save-state/retry/recovery races,
transactional undo/redo, two-tab conflicts, validation-gated navigation,
save-before-generate request ordering, helper mutations, per-environment image
requirements, every fragment renderer, keyboard interactions, readiness checks,
and manager actions. Converter tests cover rich text, notes, malformed list/table
recovery, placeholders, and severity mapping.

## Engineering Review - Completed 2026-09-11

- Added cross-process compare-and-swap persistence and monotonic revisions.
- Reconciled library/evidence mutations with browser revisions and preserved
  recovery data through conflicts.
- Unified Setup and scope-mode validation across server and browser.
- Added typed evidence, safe IDs, structural validation, bounded uploads, and
  portable ZIP report bundles with evidence integrity verification.
- Normalized malformed request and invalid legacy-draft responses.
- Validated/indexed the vulnerability library, validated preferences, honored
  configured library paths, and regenerated fragment IDs on library copies.
- Removed quadratic report discovery, coalesced typing/history and recovery
  work, and replaced unsupported `Object.groupBy` usage.
- Added escaped shared library rendering, keyboard combobox controls, semantic
  workflow/edit buttons, keyboard fragment movement, and accurate deferred-scope
  UI wording.
- Split runtime/test dependencies and expanded API, browser, and converter
  regression coverage.
- Added explicit save-state/recovery contracts, immutable request snapshots,
  canonical response reconciliation, autosave retries, and per-tab local drafts.
- Added current-page validation gates for Previous and Next, channel-specific
  Mobile scope validation, same-day date windows, and named invalid-character
  feedback.
- Hardened Windows atomic writes, moved blocking FastAPI work to worker threads,
  and locked evidence/generation operations across folder migration and output.
- Reorganized runtime code under `app/`, developer tools under `scripts/`,
  documentation under `docs/`, and test fixtures under `resources/fixtures/`.

## Future Optimization

These are optional scaling/maintenance improvements, not known correctness
defects for the current local workload:

- Replace full Findings-table rerenders after structural location changes with
  keyed row updates if reports routinely grow to hundreds of findings.
- Consolidate the minified legacy stylesheet and override layer after adding
  screenshot-based visual regression coverage.

## Deferred Scope

Do not implement these items unless the owner explicitly resumes them:

- Segment-specific report templates and requirements beyond storing the selected
  segment; these will be defined when the owner provides the rules.
- Retest/new-engagement workflow beyond the existing JSON authoring model.
- Authentication, shared hosting, database storage, or external network calls.

