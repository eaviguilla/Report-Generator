# VulnReport

Local FastAPI application for drafting and generating vulnerability reports.

## Project layout

- `app/` - application code, domain models, storage, report generation, and web assets
- `scripts/` - offline converters, document utilities, and command-line report generation
- `tests/` - unit, API, browser, converter, and DOCX tests
- `docs/` - architecture, routes, form-state, and DOCX template documentation
- `resources/` - Word templates, fragments, finding types, and test fixtures
- `data/` - local preferences and report drafts
- `generated/` - disposable generated artifacts
- `run.py` - local application launcher
- `vuln_library.json` - configured offline vulnerability library

## Run

```powershell
python run.py
```

## Test

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Utilities

```powershell
python -m scripts.generate_report <report_id>
python -m scripts.html_to_fragments vulnerabilities.json -o vuln_library.json
python -m scripts.postprocess_captions generated-report.docx
python -m scripts.compose_component_test
```

See [docs/PLAN.md](docs/PLAN.md), [docs/ROUTES.md](docs/ROUTES.md), and [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) for implementation details.
