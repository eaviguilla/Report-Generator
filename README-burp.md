# Running Report Generator from Burp Suite

`report_generator_burp.py`, at the top of this folder, adds a Report Generator tab to Burp
with Start, Stop and Open buttons. Start runs Report Generator in its own window.

1. In Burp, go to Extensions, press Add, set the extension type to *Python* and choose
   `report_generator_burp.py` from this folder. Burp's Python environment must already
   point at a Jython standalone JAR. If you later move the folder, add the extension again.
2. Open the Report Generator tab and press **Start**. It runs your Python 3, trying `py -3`
   and then `python`. To use another interpreter, type its path into the *Python* field.
   The first Start installs what Report Generator needs. This takes about a minute, and
   the status line says *Setting up* until it finishes. No other setup is needed. If Start
   fails, the area under the buttons shows why.
3. When the status line says *Running*, Report Generator opens in its own window. The
   Open button adds another window.
4. To stop Report Generator, close its window or press **Stop**. Report Generator first
   finishes any report it is generating, so this can take a while. While it waits, the Stop
   button becomes Force stop, which ends Report Generator at once. Press **Force stop** only
   if the wait does not end.

## Additional info

- To use a new release, copy everything inside its folder and paste it into the folder you
  already use. Replace the files when Windows asks. Press **Stop** before you paste, and
  reload the extension in Burp afterwards, because Burp keeps running the old
  `report_generator_burp.py` until you do. If the new release needs more packages, the next
  Start installs them.
- Report Generator saves your reports in the `data` folder and your finished Word documents
  in the `generated` folder. A release contains neither, so pasting a release leaves them
  alone.
- After a Force stop, Report Generator may show *Save conflict* for a change it had
  already saved but could not confirm. If that report was open in only one window, choose
  *Save my version*. A Force stop in the middle of an import or a duplicate can leave the
  new report pointing at screenshots that Report Generator had not written yet. Delete it
  and import again.
- The area under the buttons says when Report Generator is running or stopped, and shows
  any warning or error it reports. Report Generator also writes an unexpected error to
  `data/vulnreport-errors.log`.
- The window starts empty each time and keeps nothing when it closes. Closing it loses at
  most a few seconds of typing that Report Generator had not saved yet. The light or dark
  theme resets each time.
- One copy runs per folder. A second Start says that Report Generator is already running.
- If Burp closes without unloading the extension, for example when you force it to quit,
  the window stays open. The next Start asks you to close it. Then press **Open**.
- If setup was interrupted and Start keeps failing, delete the `.venv` folder and press
  **Start** again.
