# 03: Scope refusals are caught by the same rules before the save

Status: ready-for-agent

Blocked by: [02: Scope issues read the typed scope, not the text boxes](02-scope-issues-read-the-typed-scope.md)

**What to build:** A scope the server would refuse is caught by the same rules in the browser before the save. The rules are: no app type selected, the same component typed twice in one scope box, and a character a component or its description does not allow. The browser and the server agree on every one, and the save refuses with today's message and in today's order.

The rules in this ticket, all refusals: no app type; duplicate component (environment, app type, component); invalid characters in a scope box (field, environment, app type, which box, the characters found).

- [ ] In Python, a pure helper lists every scope-text refusal in order. `reconcile_targets` raises the first one with the same message as today, so `acceptance.check` refuses exactly as before.
- [ ] The Python Setup function and `setupResults` both return these refusals before any issue, in the order the spec sets.
- [ ] Character checks apply to component app types only, and a description paired with a blank or `#` component is not checked, on both sides.
- [ ] The duplicate-component check in the scope rows and the scope-box character check (`componentScopeInvalidCharacters`) take their answer from the rules file. The messages do not change.
- [ ] Cases cover each refusal, a duplicate URL on a web or API app type (dropped, not refused), and a report with both a refusal and an issue, to pin the order.
- [ ] Break one refusal on one side and watch a case fail, then restore it.
- [ ] The existing scope and refusal tests pass without changes to what they assert.
- [ ] `docs/DATA_MAP.md` §12: the component-description row's duplicate-name note and the component-scope character row name the new functions.

## Next steps

1. `/implement`: The refusal messages and their order are fixed by today's `reconcile_targets`.
