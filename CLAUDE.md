# Generator (VulnReport)

Local-only pentest report writer: a tester fills Setup, Findings and Content pages and the app builds a Word report from `resources/MAIN*.docx`. FastAPI, vanilla JS, no database, no build step. **Generating a report needs Windows with Microsoft Word** (`pywin32`); everything else runs on macOS. On this Mac see `CLAUDE.local.md`.

## Commands (bash/zsh; on Windows use `py -3` for `.venv/bin/python`)
- Start: `python3 app/init.py` (creates `.venv`, installs `requirements.txt`, serves on the first free port 8765-8799)
- Dev setup: `.venv/bin/python -m pip install -r requirements-dev.txt` then `.venv/bin/python -m playwright install chromium`
- Tests while building: `.venv/bin/python scripts/relevant_tests.py --run`
- Tests before done: `.venv/bin/python scripts/relevant_tests.py --affected --run`
- One test: `.venv/bin/python -m unittest tests.test_browser -k conclusion`. Always `tests.MODULE` or the script; `discover -s tests` writes into the real `data/`.
- Full suite (`--full`) only when I ask; it needs my approval.
- Lint: `.venv/bin/python -m pyflakes app scripts tests report_generator_burp.py`
- Generate a report (Windows + Word only): `py -3 -m scripts.generate_report REPORT_ID`

## Layout
- `app/`: `main.py` routes, `report_service.py` provisioning and gates, `workspace.py` locking and folders, `storage.py` atomic writes, `models.py` schema, `docx_*.py` Word pipeline, `web/` templates and `static/app.js`
- `resources/`: Word masters (`MAIN*.docx`), `fragments/`, `finding_types/`, `severity_titles/`, `vuln_library.json`
- `scripts/` tools and the test selector, `tests/` unittest plus Playwright (`test_browser.py`), `docs/` contracts and `plans/`
- `data/`: real drafts. Never delete or edit anything under it.

## Rules
- Every bug fix gets a regression test. Before each test run, state its scope in one line; `relevant_tests.py` prints it.
- Do not modify `resources/*.docx` or other binary templates without asking.
- Word automation (`pythoncom`, `win32com`) stays in `app/docx_captions.py`; `msvcrt` stays behind its existing guards in `app/workspace.py` and `app/init.py`.
- Changing `app/models.py`, `storage.py`, `workspace.py`, `report_service.py`, `main.py` or `app/web/static/app.js`: update `docs/DATA_MAP.md` in the same change. A new route goes in `docs/ROUTES.md`; a template or token change goes in `docs/DOCX_TEMPLATE.md`.
- Implementing a `docs/plans/` document: update its status and deviations in the same change.
- Fuller rules live in `.github/copilot-instructions.md` ("Implementing a plan", "Running tests in this repo", "Pushing changes"), `.github/instructions/data-layer.instructions.md` (before data-layer edits) and `tests.instructions.md` (before writing tests). Ignore its "Talking to me" section; my global style applies.
- `docs/FORM_STATE_PLAN.md` is superseded research, not the shipped design.

## Project memory
- Durable notes (decisions, gotchas, architecture): `../brain/projects/Generator/`. Read `decisions.md` before changing architecture.
- Code structure: use `graphify query`, `graphify path` and `graphify explain`, and read `graphify-out/GRAPH_REPORT.md`, before grepping the codebase.
- Read nothing else in `../brain/`. Edit the vault only when I ask for notes.
