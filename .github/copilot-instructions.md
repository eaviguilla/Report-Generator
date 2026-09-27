# What this project is

VulnReport: a local-only pentest-report writer. A tester fills three pages — **Setup** (engagement,
environments, app types, scope targets), **Findings** (one row per vulnerability), **Content** (each
finding's description, remediation, proof of concept, screenshots) — and the app produces a Word
document matching the house template. No database, no frontend framework, no build step.

- **Start:** `py -3 run.py` (on macOS, `python3 run.py`; after the first run `.venv/bin/python run.py` works too). It creates `.venv`, installs
  `requirements.txt` when its hash changes, and serves `app.main:app` on the first free port 8765–8799.
- **Server:** `app/main.py` (FastAPI routes) → `app/report_service.py` (provisioning, scope
  reconciliation, page gates) → `app/workspace.py` (locking, folders, load/save) →
  `app/storage.py` (atomic JSON writes). Schema is `app/models.py` (Pydantic, schema 1.4).
- **Browser:** `app/web/templates/*.html` embed the report as JSON; `app/web/static/app.js` is the
  whole client — `setup()` for Setup/Findings, `continuousEditor()` for Content, plus autosave,
  undo, and the 409 conflict flow. `manager.js` is the home page.
- **Word pipeline:** `app/docx_report.py` picks one of four `resources/MAIN*.docx` masters and
  splices in the small component documents under `resources/`; `app/docx_captions.py` makes real
  caption fields and drives Word itself (Windows + Word + `pywin32` only);
  `app/docx_import.py` reads a finished report back into a draft.
- **Library:** `resources/vuln_library.json`, read by `app/library.py`; the editor at
  `/library-editor` (`app/library_editor.py`) mounts only when `VULNREPORT_LIBRARY_EDITOR` is set.
- **Data:** `data/apps/<app>/<month>_<type>_<id>/draft.json` + `draft.bak.json` + `evidence/*.png`.
  Real drafts — never delete anything under `data/`.
- **Tests:** `tests/` (unittest; `test_browser.py` is Playwright). Dev deps in `requirements-dev.txt`.

Read before changing these areas:

| Area | Reference |
|---|---|
| data shape, saving, locking, rules that exist in both Python and JavaScript | `docs/DATA_MAP.md` (§12 lists the twins) |
| routes and page gates | `docs/ROUTES.md` |
| Word templates and tokens | `docs/DOCX_TEMPLATE.md` |
| plain-language architecture | `docs/ARCHITECTURE.md` |
| one plan per change, with status | `docs/plans/*.md` |

`docs/FORM_STATE_PLAN.md` is superseded research, not a description of the app.

Specialist agents live in `.github/agents/`: `loremaster` (data layer questions), `scribe` (Word
pipeline questions), `tactician` (plans a change before code), `invader` (stress-tests new work).
`.github/prompts/plan-change.prompt.md` runs them together over a handoff file in `docs/plans/`.

Claude Code follows these same files. A local, gitignored `CLAUDE.md` imports this file and the
data-layer instructions, and `.claude/agents/` and `.claude/commands/` hold thin wrappers that point
back at `.github/agents/` and `.github/prompts/`. Edit rules here only. When you add an agent or a
prompt, add its wrapper and list it in `CLAUDE.md`.

## Codebase graph (graphify)

When `graphify-out/graph.json` exists (it is local, not in git), use it before raw searching:
`graphify query "<question>"` for codebase questions, `graphify path "<A>" "<B>"` for how two things
connect, `graphify explain "<concept>"` for one concept. They return a small scoped subgraph. Use
`graphify-out/wiki/index.md` for broad navigation if it exists, and `graphify-out/GRAPH_REPORT.md`
only for architecture-wide review. After changing code, run `graphify update .`, which is AST-only and costs no API calls.

# Talking to me

- **Open with a recap.** Before any summary, decision point, or question: 2–3 plain sentences on what we were just working on, why, and where it stands now.
- **Plain language.** No invented codenames, abbreviations, or callbacks like "the earlier fix" or "option B from before" — restate the thing in place, every time.
- **Self-contained questions.** When asking me to decide something, the question itself must carry everything needed to answer it: the background, the options, the tradeoffs, and your recommendation. Never require scrolling back.
- **One question at a time.** When a summary or decision point holds several open questions or next steps, say so up front ("three decisions are waiting; here's the first"), then present only the first and wait for the answer before raising the next. Never dump them all at once — it's too much mental load.
- **Always end with `Next action:`.** Every response ends with a final line naming what I do next. Not a summary — an instruction. Examples: `Next action: none.` / `Next action: review the output above.` / `Next action: consider the output above.` / `Next action: choose from the options above.` / `Next action: execute step 1.` Pick the one that actually fits; invent a better verb when none of those do.

# Changing how the app looks

When a change is visual — layout, spacing, colour, a component's appearance — **do not stop at
"looks done".** Without a check, "looks done" is the only signal available and the user becomes the
verification loop, noticing every mistake by hand.

Close the loop yourself:

1. Open the running app in the browser and screenshot the element or page you changed.
2. Compare it against the reference: the screenshot the user gave you, the design you were asked to
   match, or the same element before the change.
3. **List the differences explicitly** — position, size, weight, colour, spacing — then fix them and
   screenshot again. Repeat until the list is empty.

Eyeballing a screenshot finds the obvious faults and misses the rest. When the target is a precise
match, read computed styles out of the page and diff them against the reference numerically; that is
what turns "close enough" into actually correct.

Show the evidence — the screenshot, or the diff you ran — rather than asserting it matches.

# Implementing a plan

`docs/plans/` holds one document per change, each opening with a status line: `planning`, `agreed`,
`in progress`, `shipped`, `superseded` or `abandoned`.

**If you implement a plan, you update its document in the same change.** Nobody else will, and a
plan that still reads `agreed` after it shipped is indistinguishable from one that was never built.

- Tick the checkboxes in *Agreed plan* as each step lands.
- Set the status to `shipped`, with the date and the commit.
- Write one short paragraph on **what deviated** — a step dropped, a requirement discovered while
  building, a different solution than the one agreed. This is the part people read later; the
  agreed steps only tell them what was expected, not what happened.

If you implement something a plan covers without following that plan, say so there too. A plan
contradicted by the code is worse than no plan, because the `loremaster` and anyone reading it will
take it as fact.

# Running tests in this repo

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
| `app/web/static/*` (JS and CSS), `app/web/templates/*` | `tests.test_browser` — every browser test loads the page, and CSS can hide an element a test clicks |
| `app/models.py`, `app/report_service.py` | the named tests in `tests/test_app.py`, plus `tests.test_browser` — both files own rules with JavaScript twins |
| `app/workspace.py`, `app/storage.py` | the named tests in `tests/test_app.py` and `tests.test_storage` |
| `app/docx_*.py`, `resources/*.docx` | `tests.test_docx`, `tests.test_docx_components`, `tests.test_docx_captions`, `tests.test_docx_import` |
| `resources/vuln_library.json`, `app/main.py` routes, other `app/*.py` | the named tests in `tests/test_app.py` |
| `run.py` | `tests.test_launcher` |
| `docs/**`, `*.md`, `.github/**`, `.claude/**`, `scripts/**`, comments | nothing |

Two tests fail on macOS in every run and are not yours:
`test_complete_report_saves_generated_docx_to_generated_folder` and
`test_generate_docx_route_uses_template_and_report_filename`. Both need Microsoft Word and
`pywin32`. Do not investigate them, and do not describe a run as failing because of them.

# Pushing changes

When the user says `push`, stage every working-tree change, create a concise commit for any
uncommitted work, then push the current branch. Do not leave uncommitted changes behind.
