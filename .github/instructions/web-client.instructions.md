---
description: "Traps in the browser client: file size, twinned rules, request-only fields, and what a save does to offer banners."
applyTo: "app/web/**, tests/test_browser.py"
---

# Browser client

- No framework and no build step: edit `app/web/static/*.js` directly. `app.js` is over 4,000 lines, so find a function with a code search or outline and read it by name or line range, never the whole file.
- A rule that exists in Python and JS changes in pairs (`docs/DATA_MAP.md` §12). The only drift guard is `test_browser_readiness_verdict_matches_server_generation_issues`, and it covers generation readiness alone. Do not add a third copy of a twinned rule; call the existing function.
- `scope_text` is request-only: it is in PUT bodies and never in responses.
- Every undo and redo ends in a full page reload (`restoreHistory`).
- Compare fragments through `sameFragments`: the client drops `false` run flags and the server writes them back, so a raw compare brings a dismissed offer banner back after a save.
- No stylesheet reinstates the browser's `[hidden]` rule, so a control that sets its own `display` needs its own `[hidden]` rule.
- In `tests/test_browser.py` read the harness at the top and one neighbouring test, not the whole file. No fixed sleeps.
