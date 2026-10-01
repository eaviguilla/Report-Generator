# Generator (VulnReport)

Local-only pentest report writer: a tester fills Setup, Findings and Content pages and the app builds a Word report from `resources/MAIN*.docx`. FastAPI, vanilla JS, no database, no build step. **Generating a report needs Windows with Microsoft Word** (`pywin32`); everything else runs on macOS. On this Mac see `CLAUDE.local.md`.

## Commands (bash/zsh; on Windows use `py -3` for `.venv/bin/python`)
- Start: `python3 app/init.py` (creates `.venv`, installs `requirements.txt`, serves on the first free port 8765-8799)
- Dev setup: `.venv/bin/python -m pip install -r requirements-dev.txt` then `.venv/bin/python -m playwright install chromium`
- Tests while building: `.venv/bin/python scripts/relevant_tests.py --run`
- Tests before done: `.venv/bin/python scripts/relevant_tests.py --affected --run`
- One test: `.venv/bin/python -m unittest tests.test_browser -k conclusion`. Always `tests.MODULE` or the script; `discover -s tests` writes into the real `data/`.
- Full suite (`--full`) only when I ask; it needs my approval.
- Lint: `.venv/bin/python -m pyflakes app scripts tests report_generator_burp.py run.py`
- Generate a report (Windows + Word only): `py -3 -m scripts.generate_report REPORT_ID`

## Where things are
- How it works: `docs/ARCHITECTURE.md`. Data contract: `docs/DATA_MAP.md` (§12 rules that exist twice, §13 sharp edges). Routes: `docs/ROUTES.md`. Word tokens: `docs/DOCX_TEMPLATE.md`.
- `data/` holds real drafts: never delete or edit anything under it. The Word masters are `resources/*.docx`.
- Traps load by file path from `.claude/rules/`. Those files are generated from `.github/instructions/*.instructions.md` (the Copilot rules): edit the `.github` file, then run `.venv/bin/python scripts/sync_ai_rules.py`. `tests/test_ai_rules_sync.py` fails when they drift.

## Rules
- Every bug fix gets a regression test. Before each test run, state its scope in one line; `relevant_tests.py` prints it.
- Do not modify `resources/*.docx` or other binary templates without asking.
- Word automation (`pythoncom`, `win32com`) stays in `app/docx_captions.py`; `msvcrt` stays behind its existing guards in `app/workspace.py` and `app/init.py`.
- `docs/plans/` is 25 files of up to 3,400 lines each. Never Read one whole: `grep -n '^## '` it, then Read only `## Answers` and `## Agreed plan`. A plan is a dated record: trust the code and `docs/DATA_MAP.md` over it, and run `git log -S` on a symbol the plan adds before believing a `shipped` status.
- Implementing a plan: update its status and deviations in the same change, and mark it `shipped` only with the commit that contains the change.
- More process rules: `.github/copilot-instructions.md` ("Implementing a plan", "Running tests in this repo", "Pushing changes"). Ignore its "Talking to me" section; my global style applies.
- `docs/FORM_STATE_PLAN.md` is superseded research, not the shipped design.

## Code structure
- Why something is built a given way: grep `docs/plans/` for the topic and read only that plan's `## Answers`.
- Code structure: use `graphify query`, `graphify path` and `graphify explain` (pass `--graph app/graphify-out/graph.json`), and read `app/graphify-out/GRAPH_REPORT.md`, before grepping the codebase.
- Before changing a function, class or route in `app/`: run `graphify explain NAME --graph app/graphify-out/graph.json` for its callers and neighbours, then grep `app/web/`, `tests/`, `scripts/` and `docs/DATA_MAP.md` for the name. A rule with a Python/JS twin (`docs/DATA_MAP.md` §12) changes on both sides in the same change.
- Graph blind spots: it covers `app/` only, misses calls made through an instance (every `Workspace` method looks uncalled), has no Python-to-JS twin edges, and knows nothing about tests. "No callers" never means dead: grep before deleting.
- The graph is gitignored and not refreshed automatically. After code changes in `app/`, run `graphify update app --force` (no API cost, about 2 s; `--force` is needed after deletions). To check staleness, compare `built_at_commit` in `app/graphify-out/graph.json` with `git rev-parse HEAD`.

## Compact instructions
When compacting, keep: the files changed and why, the last test command and its result, open plan steps, decisions made this session, and anything I said not to do. Drop file listings, search output and code that was explored but not used.

## Agent skills

### Issue tracker

Local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`GLOSSARY.md` + `docs/adr/` at the repo root). See `docs/agents/domain.md`.
