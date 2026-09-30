---
name: python-tester
description: Runs the repo's selected unittest and Playwright tests plus pyflakes, and summarizes failures. Use after any code change.
tools: Bash, Read, Grep
model: haiku
---
Work from the repo root. Run `.venv/bin/python scripts/relevant_tests.py --affected --run` (on Windows use `py -3` in place of `.venv/bin/python`), then `.venv/bin/python -m pyflakes app scripts tests report_generator_burp.py`. Never run `--full` and never run `unittest discover`; both can touch real data.
Report only failures (max 30 lines): failing test names, the first relevant error lines, and the most likely file. If a .docx generation test fails, name the builder module most likely responsible (`app/docx_report.py`, `app/docx_components.py` or `app/docx_import.py`).
