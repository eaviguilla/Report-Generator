# 02: Scope issues read the typed scope, not the text boxes

Status: ready-for-agent

Blocked by: [01: Missing engagement details go through the shared rules on both sides](01-missing-engagement-details-use-the-shared-rules.md)

**What to build:** When the tester types or clears a scope target, the Setup notice and the Next button work from the report's `scope_text`, not from counting the page's text boxes. A tested environment with no scope target, and a component with no description, are reported the same way on both sides. The tester sees the same messages and highlights as today, including while typing before any save.

The rules in this ticket, both issues: missing scope target (environment), and missing component description (environment, app type, component).

- [ ] Both functions work out scope targets from `scope_text` as `reconcile_targets` does: component and description lines paired by raw index before cleaning, blank and `#` lines skipped, and only tested environments and covered app types read.
- [ ] `setup_issues` returns the same strings as before for these rules.
- [ ] The four places in `app.js` that counted component text boxes (`validateSetupPage`, `updateSetupValidationNotice`, `setupSectionSummary`, and the scope box `oninput` handler) use the rules file. `missingDescriptionIssues` is a call to it or is removed.
- [ ] The highlight still lands on the component box when a tested environment has no target, and on the description box when a named component has none.
- [ ] Cases cover: a blank or `#` component line in the middle of a box; a description against a blank component; an untested environment with scope text; a whitespace-only value; and several components where one has no description.
- [ ] Break the pairing on one side and watch a case fail, then restore it.
- [ ] The existing Setup browser tests pass, including the one that checks the notice reads the same as `setup_issues`.
- [ ] `docs/DATA_MAP.md` §12: the component-description row names the new functions, and the "the count is taken from the DOM, not the model" warning on the setup-completeness row is removed.

## Next steps

1. `/implement`: The pairing rule is already written down in `reconcile_targets` and in the spec.
