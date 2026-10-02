Run the app from this folder:

```powershell
py -3 app/init.py
```

Use `python app/init.py` if `py` is not available on your machine (`python3 app/init.py` on macOS).

The first run creates `.venv`, installs dependencies, and opens the app in your
browser. Every run after that opens the browser straight away. When
`requirements.txt` changes, the next run reinstalls on its own. Nothing else to
set up.

Close the console window to stop the app.

## Generating reports

Report generation requires Windows with Microsoft Word installed. Everything
else - drafting, saving, import, and export - runs anywhere.

## Running it from Burp Suite

`report_generator_burp.py`, at the top of this folder, adds a **Report Generator** tab to Burp
with Start, Stop and Open buttons and the app's output. It starts and stops the same app
described above and shows it in its own window. The tab prints the folder, the exact
commands and the address.

1. In Burp: Extensions, Add, extension type **Python**, and choose
   `report_generator_burp.py` from this folder. Burp's Python environment must already
   point at a Jython standalone JAR.
2. Open the Report Generator tab and press **Start**. It runs your Python 3 (`py -3`,
   then `python`, on Windows; `python3` elsewhere). Type a path into the *Python* field
   to use another interpreter.
3. When the status line says *Running at http://127.0.0.1:...*, the app opens in its own
   window, in Microsoft Edge or, when Edge is missing, Google Chrome. The window has no
   address bar and no tabs. The app listens only on this computer, and its traffic stays
   out of Burp's Proxy history. **Open** adds another window.

Things worth knowing:

- **The window and the app stop together.** Stop, Force stop or unloading the extension
  closes the window, and closing the window stops the app. A report being generated
  finishes first, as with Stop.
- The window opens only on Windows, and needs Microsoft Edge or Google Chrome. Without
  either, the tab prints the address and opens nothing.
- If Burp ends without unloading the extension, for example when it is closed by force, the
  window stays open on its own. The next Start asks you to close it, then press **Open**.
- **Stop** asks the app to finish what it is doing and exit, including a report that is
  being generated, and can take a while. **Force stop** ends it at once. After a Force
  stop a page may show *Save conflict* for a change the app had already saved but could
  not confirm; if that report was open in only one tab, choose *Save my version*. A Force
  stop in the middle of an import or a duplicate can leave the new report pointing at
  screenshots that were not written: delete it and import again.
- Keep `report_generator_burp.py` in the folder Burp loaded it from. If you move the
  folder, add the extension again.
- One copy runs per folder. A second Start says where the first is running.
- Changes you had not saved yet are kept by the window, in `app-window-profile` in this
  folder, under the address the app was served from, port included. If the app comes back
  on a different port they wait there and reappear when it runs on that port again. Moving
  to a new release leaves them behind.
- If setup was interrupted and Start keeps failing, delete the `.venv` folder and press
  Start again.

## Moving to a new release

Reports live in the `data` folder at the top of this folder, so a new release starts empty.
Unzip each release into a new folder, not over an old one.

1. Unzip the new release, and load its `report_generator_burp.py` in Burp (remove the
   previous release's extension first).
2. Press **Start**. On a folder with no reports the tab asks once: **Bring reports over**
   or **Start fresh**.
3. For *Bring reports over*, stop the previous release first (Stop in Burp, or close its
   console window), then choose its folder. The previous `data` folder (and `generated`)
   is **moved**, not copied, so there is one store; the previous `.venv` is copied so
   packages are not downloaded again, and removed again if the copy does not work. The
   previous folder then refuses to start and says where its reports went.

To do it by hand, for example when the two folders are on different drives: stop the
previous release, move its `data` folder (and `generated`) into the new folder, then
Start. If the new folder already has a `data` folder without reports, rename that one
first. If it has reports, move the previous `data/apps` folders into its `data/apps`
one by one instead.
