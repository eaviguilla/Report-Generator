Run Report Generator from this folder:

```powershell
python run.py
```

If `python` is not available, use `py -3 run.py`.

Report Generator opens in your browser. The first run takes about a minute, because it
creates `.venv` and installs the dependencies. No other setup is needed.

Close the console window to stop Report Generator.

## Additional info

- To use a new release, copy everything inside its folder and paste it into the folder you
  already use. Replace the files when Windows asks. Close the console window before you
  paste. If the new release needs more packages, the next run installs them.
- Your reports are in the `data` folder and your finished Word documents are in the
  `generated` folder. A release contains neither, so pasting a release leaves them alone.
