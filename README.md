Run the app from this folder:

```powershell
py -3 run.py
```

Use `python run.py` if `py` is not available on your machine (`python3 run.py` on macOS).

The first run creates `.venv`, installs dependencies, and opens the app in your
browser. Every run after that opens the browser straight away. When
`requirements.txt` changes, the next run reinstalls on its own. Nothing else to
set up.

Close the console window to stop the app.

## Generating reports

Report generation requires Windows with Microsoft Word installed. Everything
else - drafting, saving, import, and export - runs anywhere.

## Moving to a new release

Reports live in the `data` folder at the top of this folder, so a new release starts empty.
Unzip each release into a new folder, not over an old one.

Stop the previous release (close its console window), then move its `data` folder (and
`generated`) into the new folder, and Start. If the new folder already has a `data` folder
without reports, rename that one first. If it has reports, move the previous `data/apps`
folders into its `data/apps` one by one instead. This is a plain folder move, so it works
the same way when the two folders are on different drives.
