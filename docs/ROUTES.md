# VulnReport Route Contract

Companion to [PLAN.md](PLAN.md). Keep this file and `app/main.py` aligned: every
live application route appears below, and new routes must be added here in the
same change.

## Route Rules

- Every route handles success, validation failure where input is accepted, a
  missing report, unmet workflow preconditions, and unexpected failures without
  leaking a traceback to the tester.
- Server-side gates control workflow entry; disabled buttons are only a UI
  courtesy.
- Every workflow page has a visible route to the report manager. Browser-facing
  404 and 500 responses include a working home link.
- Autosave keeps an unsaved local recovery draft, attempts a normal save when
  the page becomes hidden, and preserves recovery locally during page unload.
  Navigation controls await the active save before moving to the next page.
- A save includes `saved_at`. Writes use a cross-process compare-and-swap. A
  stale browser tab receives `409`, retains its recovery draft, and offers
  **Save my version** or **Load latest**. Retrying rebases onto the returned
  latest revision and still uses compare-and-swap, so a second race is detected.
- API failures include an `error` object with a reference ID, status/code,
  endpoint function, method/path, and timestamp. Unexpected exceptions also
  include their exception type and local rotating-log path; report payloads and
  evidence contents are never included in diagnostics.

## Live Route Map

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Report manager; does not create a report |
| GET | `/new` | Create a report and redirect to Setup |
| GET | `/reports` | List valid local reports as JSON; browser visits redirect to the manager |
| GET | `/reports/legacy` | List invalid local reports and supported repair status |
| GET | `/reports/{id}` | Open a report at Setup; missing IDs receive the standard 404 page |
| GET | `/reports/{id}/setup` | Setup workflow page |
| GET | `/reports/{id}/findings` | Findings workflow page |
| GET | `/reports/{id}/edit` | Content workflow page |
| PUT | `/reports/{id}` | Validate, provision, and atomically save report JSON |
| DELETE | `/reports/{id}` | Delete a report and its evidence |
| POST | `/reports/{id}/duplicate` | Copy a report and its evidence with a fresh ID |
| PATCH | `/reports/{id}/name` | Rename the application label in the manager |
| POST | `/reports/{id}/repair` | Repair duplicate fragment IDs in a legacy draft |
| GET | `/reports/{id}/export` | Download a ZIP containing draft JSON and evidence |
| GET | `/reports/{id}/generate` | Render and download a completed DOCX report |
| POST | `/reports/{id}/generate` | Render and save a completed DOCX into `generated/` at the repository root; the response names the file rather than opening a folder |
| POST | `/reports/import` | Validate/import a ZIP or evidence-free legacy JSON with a new report ID |
| GET | `/library/search?q=` | Search the offline vulnerability library |
| POST | `/reports/{id}/library/{library_id}` | Insert a library finding |
| POST | `/reports/{id}/evidence` | Validate, normalize, and store an image |
| GET | `/reports/{id}/evidence/{evidence_id}` | Serve stored evidence |

DOCX generation uses `resources/MAIN_TEST.docx` as the canonical template, then
composes severity-title, finding-type, and fragment documents. A template
without an exact `{{findings}}` anchor paragraph is rejected; there is no second
renderer. The route rejects incomplete content or missing environment evidence
with `422`.

## Entry Gates

| Route | Server-side requirement | Outcome when unmet |
|---|---|---|
| `/reports/{id}/*` | Report exists and is valid | Missing: `404`; invalid legacy draft: navigable `422` |
| `/reports/{id}/findings` | Segment, app name, report type, tester, selected environments, complete dates, and a target per environment | 303 to Setup with an explanatory banner |
| `/reports/{id}/edit` | Findings gate plus at least one complete finding | 303 to Findings with an explanatory banner |
| `PUT /reports/{id}` | Valid schema and no unsafe state transition | `422` naming the validation or repair action |
| `PUT /reports/{id}` | `saved_at` matches persisted version | `409` directing the tester to reload |

A complete finding has a title, likelihood, impact, severity, status, and at
least one selected or custom affected location. CI and BSN numbers are optional.
Two findings may not share a finding number.

## State Safety

- Removing a Setup scope target referenced by a custom finding is rejected.
  The response names the linked findings so the tester can restore the target
  or unlink it first. Findings scoped by mode rather than by target ID are
  covered by the same rule: deselecting an environment or narrowing the test
  surface is rejected when it would leave such a finding with no location at
  all, and Setup names those findings before the change is committed.
- Deleting a finding confirms first when it holds written content or uploaded
  screenshots, and releases its evidence so the images stop travelling in
  every export.
- Changing a finding status confirms before content blocks would be discarded
  or resolved status would replace recommended remediation.
- In Conclusion starts with one editable title/status sentence. It synchronizes
  while untouched and is preserved verbatim after tester edits; additional
  fragments remain supported.
- Evidence remains owned by the report and cannot be requested across report
  folders.
- Image fragments record their Production or Non-Production environment. The
  editor requires at least one uploaded image for each environment affected by
  the finding and permits additional images for either environment. One
  affected environment is assigned automatically; the two-environment selector
  has no unassigned option.
- Report bundles require exact evidence paths, hashes, dimensions, and bounded
  compressed/uncompressed sizes. Evidence-free legacy JSON remains importable.
- Export download names use the selected segment, application name, report type,
  and report-date year.
- Library insertion and evidence upload require/reconcile the current report
  revision before committing related browser state.
- Direct URLs and stale bookmarks are handled by the same server gates as UI
  navigation.

## Acceptance Checks

Run these after navigation or persistence changes:

1. Open `/`; verify it creates no report.
2. Open `/new`; verify the redirect is a real Setup URL.
3. Directly open Findings for an incomplete report; verify redirect to Setup and
   its visible explanation.
4. Directly open Content without a complete finding; verify redirect to Findings
   and its visible explanation.
5. Request a missing report in a browser; verify the 404 page links home.
6. Save concurrently through two workspace instances; verify exactly one stale
  writer receives `409` and retains browser recovery state.
7. Attempt to remove a referenced scope target; verify `422` and no draft data
   is silently orphaned.
8. Verify a duplicate-fragment legacy draft appears in the manager with its
  concise reason and repair action.
9. Export/import a report containing evidence; verify the PNG survives and a
  tampered archive is rejected.
10. Run `py -3 -m unittest discover -s tests -v`.
