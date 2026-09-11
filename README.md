Run the app from this folder:

```powershell
py -3 run.py
```

Use `python run.py` if `py` is not available on your machine.

The first run creates `.venv`, installs dependencies, and opens the app in your
browser. Every run after that opens the browser straight away. When
`requirements.txt` changes, the next run reinstalls on its own. Nothing else to
set up.

Close the console window to stop the app.

## Generating reports

Report generation requires Windows with Microsoft Word installed. Everything
else - drafting, saving, import, and export - runs anywhere.

See [docs/PLAN.md](docs/PLAN.md), [docs/ROUTES.md](docs/ROUTES.md), and
[docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) for implementation details.
