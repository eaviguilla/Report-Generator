# 02: Scope issues read the typed scope, not the text boxes

Status: done (2026-10-04)

Blocked by: [01: Missing engagement details go through the shared rules on both sides](01-missing-engagement-details-use-the-shared-rules.md)

**What to build:** When the tester types or clears a scope target, the Setup notice and the Next button work from the report's `scope_text`, not from counting the page's text boxes. A tested environment with no scope target, and a component with no description, are reported the same way on both sides. The tester sees the same messages and highlights as today, including while typing before any save.

The rules in this ticket, both issues: missing scope target (environment), and missing component description (environment, app type, component).

- [x] Both functions work out scope targets from `scope_text` as `reconcile_targets` does: component and description lines paired by raw index before cleaning, blank and `#` lines skipped, and only tested environments and covered app types read.
- [x] `setup_issues` returns the same strings as before for these rules.
- [x] The four places in `app.js` that counted component text boxes (`validateSetupPage`, `updateSetupValidationNotice`, `setupSectionSummary`, and the scope box `oninput` handler) use the rules file. `missingDescriptionIssues` is a call to it or is removed.
- [x] The highlight still lands on the component box when a tested environment has no target, and on the description box when a named component has none.
- [x] Cases cover: a blank or `#` component line in the middle of a box; a description against a blank component; an untested environment with scope text; a whitespace-only value; and several components where one has no description.
- [x] Break the pairing on one side and watch a case fail, then restore it.
- [x] The existing Setup browser tests pass, including the one that checks the notice reads the same as `setup_issues`.
- [x] `docs/DATA_MAP.md` §12: the component-description row names the new functions, and the "the count is taken from the DOM, not the model" warning on the setup-completeness row is removed.

## What deviated

- The codes are `missing_scope_target` (context `environment`) and `missing_component_description` (context `environment`, `app_type`, `component`). Each environment's results come together, in the order `setup_issues` listed them: test dates, scope target, then descriptions in app type order.
- Both sides read targets through a second function: `report_service.scope_text_targets` and `vrRules.scopeTargets`. `setupSectionSummary` and the scope boxes' `clearScopeErrors` call `scopeTargets` directly, so the section count no longer counts a repeated component twice. `setup_issues` feeds `setup_results` the stored targets through `scope_text_from_targets`.
- `reconcile_targets` keeps its own pairing loop; ticket 03 moves its refusals into a shared helper.
- A repeated component is skipped by both sides, as the old JavaScript did. Ticket 03 adds it as a refusal.
- `setup_issues` now ignores a stored target under an app type the report does not cover, where it used to count it. No save or import stores one (`reconcile_targets` builds targets only for covered app types, and import derives the app types from the targets), so only a hand-edited draft differs, and the next Setup save would drop that target anyway.
- The "every issue, in order" case gained two `missing_scope_target` results: it covers Mobile and Thick Client only, so it never had a target.
- To find a description box from a result, a component group's `data-component-channel` now holds its app type instead of `"true"`. The highlight goes on the first row naming the component, where the old code also marked a repeated row.
- The breaking check: filtering blank component lines before pairing in `rules.js` failed "a blank component line mid-box does not pass its description on" on the JavaScript side only.
