# Running tests in this repo

The full suite boots a server and Chromium and takes roughly two and a half minutes. Most changes
cannot break most of it. Running it "to be safe" is not safe, it is just slow.

## Announce the scope before every test command

Immediately before running any test command, write one line naming the scope and the reason:

```
Tests: <what you are running> — <why that scope>
Tests: none — <why nothing needs to run>
```

No line, no test run. This is the rule, not a formality: the decision below is easy to skip
silently, and writing it down is what stops that.

## Let the script decide

`scripts/relevant_tests.py` maps the working tree's changed files to unittest targets using the
scope map below. Prefer it over deciding by hand, because deciding by hand is the step that gets
skipped:

```sh
.venv/bin/python scripts/relevant_tests.py          # print the targets
.venv/bin/python scripts/relevant_tests.py --run    # print and run them
```

It prints `Tests: none` when nothing changed that a test asserts on, and lists any path it has no
rule for so you can decide that one by hand rather than guessing at all of them.

## Two gates, in order

**Gate 1 — should anything run at all?**

Search the tests for what you touched. No hit and no behaviour change means run nothing and say so.
Editing docs, comments, plan files, prompts, CSS, or markup that no test asserts on needs no suite.
"I edited a file" is not a trigger. "I changed something a test asserts on" is.

**Gate 2 — if yes, run the narrowest thing that covers it.**

The specific test file, class, or method. The one browser flow touched. Prefer a handful of named
tests while iterating, and widen once at the end only if the change could affect boot.

Run the whole suite **only** when explicitly asked for a full or whole-app run.

## Scope map

| Changed | Run |
|---|---|
| `app/web/static/*.js`, `app/web/templates/*` | `tests.test_browser` — every browser test loads the page; nothing else does |
| `app/models.py`, `app/report_service.py`, `app/workspace.py`, `app/storage.py` | the named tests in `tests/test_app.py`, plus `tests.test_browser` only if a rule has a JavaScript twin |
| `app/docx_*.py`, `resources/*.docx` | `tests.test_docx`, `tests.test_docx_components`, `tests.test_docx_captions`, `tests.test_docx_import` |
| `app/main.py` routes | the named route tests in `tests/test_app.py` |
| `docs/**`, `*.md`, `.github/**`, comments, CSS | nothing |

Two tests fail on macOS in every run and are not yours:
`test_complete_report_saves_generated_docx_to_generated_folder` and
`test_generate_docx_route_uses_template_and_report_filename`. Both need Microsoft Word and
`pywin32`. Do not investigate them, and do not describe a run as failing because of them.
