---
description: "Keeps docs/DATA_MAP.md accurate when the data layer changes."
applyTo: "app/models.py, app/storage.py, app/workspace.py, app/report_service.py, app/main.py, app/web/static/app.js"
---

# Data layer change contract

You are editing a file that [docs/DATA_MAP.md](../../docs/DATA_MAP.md) describes. That file is what the `loremaster` and `tactician` agents rely on, so a change here that is not reflected there makes both of them confidently wrong.

## Update the map in the same change

Update `docs/DATA_MAP.md` when you change any of:

- a field, type, or validator on a model, including anything in `Report.validate_references`
- how or where a file is written, named, backed up, or located
- locking, `saved_at`, or any concurrency path
- derived state: `provision`, `sync_evidence_image_slots`, `reconcile_targets`, `fragment_applies`
- legacy repair in `load_path`
- client state shape, the save or autosave path, or a navigation gate
- a rule that exists in both Python and JavaScript

Refresh the "Last verified" line at the top when you do. Section 13 collects known sharp edges; add to it when you find one, and delete the entry when you fix it.

You do not need to touch the map for changes with no data consequence, such as wording, formatting, or a pure refactor that preserves names and behaviour.

## Invariants to preserve

- **Every read-modify-write goes through `Workspace._locked`.** A new mutating method without it is a race.
- **Every mutating route carries `saved_at`**, in the body for the full save and in `X-Report-Saved-At` for delta endpoints, and returns 409 on mismatch.
- **The server owns derived state.** `main.provision_report` runs on every PUT; do not have the browser assert a value the server recomputes.
- **A rule that exists on both sides changes on both sides**, and the pair is covered by `test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`.
- **Never discard user content without a prompt.** Scope changes, environment deselection, library replacement, and finding deletion are the paths where this has gone wrong before.
- **An existing `draft.json` must still load.** If a new shape would fail validation, add the upgrade to `load_path` rather than requiring users to start over.
