# The Burp build opens the app window

> **Status:** in progress · 2026-10-03 · Built, and its checks pass on macOS. The Windows checks in step 5 are open.

## Request

"for the burp extension version of this, do not open a browser in the default browser. it should be the
browser from burp suite. and make it look like a node app with no way to edit the url but still run in edge
or chromium."

Then: "look up on the folder outside of this repo named repgen-web. this is a burp extension based and the
burp browser it creates has no way to edit the url or even see it".

## Answers

Reached through a grilling session (`/grill-with-docs`) on 2026-10-03. The decision is recorded in
`docs/adr/0003-burp-build-opens-an-app-window-in-edge-or-chrome.md`, and **App window** is in `GLOSSARY.md`.

Two findings shaped the questions. Burp's browser ships beside Burp's JAR (`burpbrowser/<version>/`), and
neither Burp extension API can open it. And repgen-web's window is not Burp's browser. Its Burp launcher
starts Edge or Chrome with `--app` and a profile of its own, because Burp's browser, started outside Burp on
Windows, fails its sandbox and comes up blank.

1. **Browser.** The window opens in Edge, then Chrome, with its own profile. Burp's browser is never used.
2. **Neither installed.** Nothing opens. The tab names where it looked and prints the address. The default
   browser is never used.
3. **Scope.** Only the Burp tab changes. A console start and the default release still open the default
   browser.
4. **Profile.** The window keeps its profile in `app-window-profile/` in the release folder. Bring over
   does not move it.
5. **Window and app.** They stop together. Stop closes the window, and closing the window stops the app.
6. **Switching over.** Unsaved edits a tester's usual browser holds are not offered in the window. The
   README does not describe recovering them.
7. **When the server ends** (Stop, Force stop, unload, crash), the extension ends the browser it started
   without asking it first. This was agreed on the claim that at most 150 ms of typing could be lost. The
   review found that claim wrong (see What deviated).
8. **Noticing the close.** The extension watches the browser process it started. It is Windows only, with
   no macOS or Linux browser paths.
9. **A window left from an earlier session.** Before opening a window, the extension checks the profile's
   lock file, and asks the tester to close a leftover window and press Open.
10. **Company rule.** It is unaffected, because the tab still prints the folder, the commands and the
    address.

Taken from repgen-web: a 1440 by 900 window, first-run screens skipped, and Open adding a window.

## Agreed plan

- [x] **1. The window.** In `report_generator_burp.py`: `browser_places` (Edge, then Chrome, under
  `ProgramFiles(x86)`, `ProgramFiles` and `LOCALAPPDATA`), `AppWindow` (`open`, `poll`, `close`, and the lock
  check) and `start_browser`. `Desktop.browse` is gone.
- [x] **2. The tab.** It opens the window at Running and on Open, on a worker thread. It stops the app when
  the window closes, and closes the window when the server ends or the extension unloads.
- [x] **3. Checks.** A new Jython self-check, `--self-check-window` (no server, fake browsers), and
  `--self-check-panel`, which now drives the window with a fake browser. Both run from
  `tests/test_launcher.py` when Java and `VULNREPORT_JYTHON_JAR` are available.
- [x] **4. Docs.** `README-burp.md`, `docs/ARCHITECTURE.md` (Starting from Burp), `docs/DATA_MAP.md` §13, a
  note on `docs/plans/burp-extension-launcher.md`, `.gitignore`.
- [ ] **5. Windows checks**, with Burp, on a scratch report only:
  - a. Edge opens the app window with no address bar and no tabs, titled and iconed by the page.
  - b. Closing the last app window ends the browser process, for Edge and for Chrome, so the app stops.
  - c. Stop, Force stop, unloading the extension and closing Burp normally each close the window, and
    Task Manager shows no Edge process left with `app-window-profile` on its command line.
  - d. With Burp killed while the window is open, the next Start reports the leftover window and opens
    nothing until it is closed. This is the `lockfile` check.
  - e. Open while the window is open adds a window, and closing both stops the app.
  - f. With the Windows proxy pointed at Burp, nothing from the app appears in Proxy history.
  - g. With Edge absent, Chrome opens. With neither, the tab lists the places it looked.
  - h. `tests.test_launcher` passes with the Jython checks run, not skipped.
  - i. Type into a finding's description, wait two seconds, press Stop, then Start: the page offers the
    unsaved edit. Repeat and press Stop at once, to see what the last second loses.

## What deviated

- **The loss on Stop is up to a second, not 150 ms.** Answer 7 was agreed on the claim that the page keeps
  each edit 150 ms after it is typed, so ending the browser loses at most that. The page does write to
  local storage after 150 ms, but Chromium writes local storage to disk in batches, five seconds apart by
  default and further apart in a long session (`ComputeCommitDelay`). Autosave waits five idle seconds, so
  an edit typed just before Stop is on neither the server nor the disk when the browser ends. The window
  is now started with `--enable-aggressive-domstorage-flushing`, which brings the batch delay to one
  second. Check 5i measures what remains.
- **Unloading closes the window at once**, not after the server exits. Burp may end before the server does,
  and the timer that watches the server stops with the extension, so waiting would leave the window open.
  A window still starting when the extension unloads is ended as soon as it starts.
- **A browser that ends within 3 seconds of starting** (`HANDOVER_MS`) is treated as having handed its
  window to a browser already running on the profile. The app keeps running, and the tab says to close any
  leftover window and press Open. Without this, a lock check that misses on some browser version would
  stop the app right after Start. A browser that crashes at launch, or restarts itself to update, gets the
  same message, and a restarted window is not watched.
- **The lock check removes a stale lock file.** Answer 9 says the extension checks the profile's lock file.
  It tries to delete it, which fails while a browser holds it. A file nothing holds is removed, and the
  browser writes a new one when it starts.
- **The window opens on a worker thread.** Starting a process and checking files must stay off Burp's
  Swing thread, as the launcher plan's Step 6 requires. The old `Desktop.browse` ran on that thread.

## Running the Jython checks on macOS

`.venv/.requirements-sha256` must match `requirements.txt`, or the checks that start the app skip. A dev
setup from `requirements-dev.txt` never writes it. Use a native arm64 Java, such as Homebrew's `openjdk`.
Burp Professional's bundled Java is x86_64, so the Python it starts runs under Rosetta and cannot load the
arm64 `pydantic_core`, and the app never prints its address.
