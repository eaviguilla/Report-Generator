---
description: "Keeps docs/DATA_MAP.md accurate when the data layer changes, and lists the traps in these files."
applyTo: "app/models.py, app/storage.py, app/workspace.py, app/report_service.py, app/acceptance.py, app/main.py, app/library.py, app/web/static/app.js"
---

# Data layer change contract

You are editing a file that [docs/DATA_MAP.md](../../docs/DATA_MAP.md) describes. That file is what the `loremaster` and `tactician` agents rely on, so a change here that is not reflected there makes both of them confidently wrong.

## Update the map in the same change

Update `docs/DATA_MAP.md` when you change any of:

- a field, type, or validator on a model, including anything in `Report.validate_references`
- how or where a file is written, named, backed up, or located
- locking, `saved_at`, or any concurrency path
- derived state: `provision`, `sync_evidence_image_slots`, `reconcile_targets`, `fragment_applies`
- what `acceptance.check` refuses, or the order it checks in
- legacy repair in `load_path`
- client state shape, the save or autosave path, or a navigation gate
- a rule that exists in both Python and JavaScript

Refresh the "Last verified" line at the top when you do. Section 13 collects known sharp edges; add to it when you find one, and delete the entry when you fix it. A new route also goes in `docs/ROUTES.md`.

You do not need to touch the map for changes with no data consequence, such as wording, formatting, or a pure refactor that preserves names and behaviour.

## Invariants to preserve

- **Every read-modify-write goes through `Workspace._locked`.** A new mutating method without it is a race.
- **Every mutating route carries `saved_at`**, in the body for the full save and in `X-Report-Saved-At` for delta endpoints, and returns 409 on mismatch.
- **The server owns derived state.** `acceptance.provision` runs on every PUT; do not have the browser assert a value the server recomputes.
- **A rule that exists on both sides changes on both sides.** The Setup rules in `setup_results` and `rules.js` are held to one case table in `tests/test_rule_cases.py`; generation readiness and finding completeness have the contract tests in `test_browser.py`; the other twins have no guard. Which sections a status prints is `content_types_for_status` and `contentTypesForStatus`.
- **Never discard user content without a prompt.** Scope changes, environment deselection, library replacement, and finding deletion are the paths where this has gone wrong before.
- **An existing `draft.json` must still load.** Migrate an old shape in memory, in the `Report` before-validator `normalise_legacy_shapes` (see `normalise_scope_modes`). `load_path` rewrites a draft only for its two existing repairs: the manager calls it once per draft per render, and every rewrite spends the single `draft.bak.json`.

## Traps

- Pydantic ignores unknown keys, so a new field must be declared or it disappears on load, and an export from a newer build loses it in an older one.
- Widening a `Literal` needs no repair, but an older build cannot open a draft that stores the new value. A draft that fails validation silently moves to the manager's Legacy list.
- `frag_id` is unique report-wide (`Report.validate_references`): remint every copied fragment (`remintFragments` in `app.js`).
- `reconcile_targets` runs on the raw payload before validation, and only when the payload carries `scope_text` (the Setup page).
- `provision` seeds only empty sections. A section a status change drops is kept when it holds work (not `in_conclusion`). A new section type goes in `content_types_for_status` and the `required_fragments` table inside `provision`.
- `sync_evidence_image_slots` measures coverage on `proof_of_concept` alone; previous-PoC images are history. It removes only empty, uncaptioned slots and never relabels an uploaded screenshot.
