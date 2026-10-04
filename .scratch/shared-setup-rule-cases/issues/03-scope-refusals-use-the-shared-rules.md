# 03: Scope refusals are caught by the same rules before the save

Status: done (2026-10-04)

Blocked by: [02: Scope issues read the typed scope, not the text boxes](02-scope-issues-read-the-typed-scope.md)

**What to build:** A scope the server would refuse is caught by the same rules in the browser before the save. The rules are: no app type selected, the same component typed twice in one scope box, and a character a component or its description does not allow. The browser and the server agree on every one, and the save refuses with today's message and in today's order.

The rules in this ticket, all refusals: no app type; duplicate component (environment, app type, component); invalid characters in a scope box (field, environment, app type, which box, the characters found).

- [x] In Python, a pure helper lists every scope-text refusal in order. `reconcile_targets` raises the first one with the same message as today, so `acceptance.check` refuses exactly as before.
- [x] The Python Setup function and `setupResults` both return these refusals before any issue, in the order the spec sets.
- [x] Character checks apply to component app types only, and a description paired with a blank or `#` component is not checked, on both sides.
- [x] The duplicate-component check in the scope rows and the scope-box character check (`componentScopeInvalidCharacters`) take their answer from the rules file. The messages do not change.
- [x] Cases cover each refusal, a duplicate URL on a web or API app type (dropped, not refused), and a report with both a refusal and an issue, to pin the order.
- [x] Break one refusal on one side and watch a case fail, then restore it.
- [x] The existing scope and refusal tests pass without changes to what they assert.
- [x] `docs/DATA_MAP.md` §12: the component-description row's duplicate-name note and the component-scope character row name the new functions.

## What deviated

- The codes are `no_app_type`, `duplicate_component` (context `environment`, `app_type`, `component`) and `invalid_characters` (context `field: "component_scope"`, `environment`, `app_type`, `box` of `component` or `description`, `line`, `characters` in the order typed). `line` is not in the spec: it is the raw 0-based line index, and the browser needs it to find the row, since a description's result cannot be found by its component when the component repeats.
- Python has three functions: `scope_box_refusals` for one box, `scope_text_refusals` for the report (used by `setup_results`), and `scope_refusal_message` for the words. `reconcile_targets` calls `scope_box_refusals` inside its own loop and raises the first result, rather than calling the report-wide function, so a malformed value in a later box is still reported after an earlier box's refusal, as before. The JavaScript twins are `vrRules.scopeRefusals` and an internal `scopeBoxRefusals`.
- Within a box, every repeated component comes before any character refusal, because the save always raised a box's repeat first. A repeated name is listed once, in the order names repeat. A repeated row's own characters are still listed, so the page keeps flagging them on that row.
- `setup_issues` drops refusals: a hand-edited draft can store a target the save would refuse, and it used to add no Setup issue.
- `browserCharacterRule` in `app.js` now calls `vrRules.invalidCharacters`, so Setup's character check exists once in JavaScript. `componentScopeRule`, `componentScopeCharacters` and `componentScopeInvalidCharacters` are gone.
- The review found that JavaScript's `trim` and Python's `strip` differ: `trim` also strips U+FEFF and keeps U+001C to U+001F and U+0085. `rules.js` now has `strip`, matching `str.strip` exactly, and `scopeTargets` uses it too. `setupResults` still checks the app name and tester with `trim`; ticket 04 can move those.
- One browser change: a description that starts with `#` used to pass the page and be refused by the save. It is now flagged on the row.
- The breaking check: listing a repeated component every time it repeats in `rules.js` failed "each repeated component once, in the order it repeats" on the JavaScript side only.
