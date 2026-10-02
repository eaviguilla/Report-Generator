# Host the app from a Burp Suite extension

> **Paths moved after this was written** (`docs/plans/launcher-file-layout.md`): the launcher `run.py` is now
> `app/init.py`, and `burp/report_generator_burp.py` is now `report_generator_burp.py` at the repository root. Read
> `run.py` and `burp/` below as those two files. The Step 8 checklist is unchanged, and still open.

> **Browser replaced** (`docs/adr/0003-burp-build-opens-an-app-window-in-edge-or-chrome.md`,
> `docs/plans/burp-app-window.md`): the tab no longer opens the system default browser. It opens the app
> window in Edge or Chrome, and the window and the app stop together. The "Browser" choice below, and the
> advice to use the usual browser, describe the earlier design.

> **Status:** in-progress · 2026-09-30 · Steps 1–7 are built and their tests pass here (242 Python
> tests, 4 skipped); Step 8 (checks on Windows and inside a real Burp) and Step 9's close-out are still
> to do.
>
> **Not yet run:** the three Jython self-checks in `tests/test_launcher.py` skip on this Mac, which has
> no Java. `burp/report_generator_burp.py` has therefore never run under Jython. What did run: a
> Python 2.7 syntax check, a pyflakes pass, and the test that pins its two shared names. Run
> `VULNREPORT_JYTHON_JAR=<jython-standalone.jar> .venv/bin/python -m unittest tests.test_launcher`
> on a machine with Java before trusting it, then Step 6's checklist in a real Burp.
>
> **What deviated.**
> - The serve tests start `python -c "…run.main()"` instead of `python run.py`, so the browser can be
>   stubbed and no test ever opens one. `guard_start()` is its own function so the lock refusal is
>   tested without starting a server.
> - `--bring-over` also refuses when `VULNREPORT_DATA_DIR` is set (the data folder is then not inside
>   the release), and leaves the previous finished documents where they are when this folder's
>   `generated/` is not empty.
> - The `.venv` check imports `python_multipart` (the package's real name), not `multipart`.
> - `run.py`'s lock wait is a module constant (`LOCK_WAIT`) so tests can shorten it.
> - The extension came out at about 770 lines, not the estimated 400, mostly the first-run dialog, the
>   two self-checks and comments.
> - `scripts/relevant_tests.py` gained rules for `burp/` and `.gitignore` (no tests, all Python modules
>   still run), so neither is listed as "no rule".
> - Answer 5 stands: nothing under `app/` changed.

## Request

> I want to convert this project to be a burp suite extension. to clarify, I do not want to redevelop the app, but host it as a burp extension. The reason is that the company do not want a web app, but the bypass that I am thinking is to have this project go through as a burp extension. the burp extension will just be like a terminal output with buttons of start and stopping the app. when starting, a web instance will be spawned from burp where the users will be able to access the functions of report generation.

## Coordinator's framing, before round 1

**Size: large, so both rounds run.** It adds a new component (a Burp extension). It changes how the
server is started and stopped, including being stopped in the middle of a save, and very likely where
report data lives, so drafts already on disk must keep being found. No field or schema changes.

**Scribe is skipped.** Nothing in the finished `.docx` changes: not its content, its layout, or how a
document is read back. The one Word-adjacent risk is environmental. The Word automation pass
(`docx_captions.update_docx_bytes_with_word`, COM through `pywin32`) would run inside a Python process
that Burp's Java process launched rather than one started from a console. Only generating a real
report on Windows through the extension can settle that, so it belongs in the plan as a verification
step, not as a question for an agent.

**What the request already fixes.** The app is not rewritten. The extension is a launcher: a panel in
Burp with a terminal-style output area and Start/Stop buttons. Start spawns the existing web app;
the tester uses it in a browser exactly as today.

**Facts that shape the design, checked in source:**

- **Burp cannot run this app in-process.** Burp extensions are Java (the Montoya API), or Python 2.7
  through Jython. The app is Python 3 with FastAPI, uvicorn, pydantic, python-docx and Pillow. So the
  extension can only launch it as an external Python 3 process and manage that process.
- **`run.py` is two processes.** Run with the system interpreter, it creates `.venv`, installs
  `requirements.txt` when that file's hash changes (network access, about a minute the first time),
  then **relaunches itself** with the `.venv` interpreter via `subprocess.run` and waits. The child
  picks the first free port in 8765–8799, prints `Report Generator is running at <url>` and
  `Close this window to stop the application.`, opens the system browser after 0.5 s, and runs uvicorn
  on `127.0.0.1`. Stopping only the parent would orphan the server, so Stop must end the whole process
  tree.
- **That URL line is not flushed.** Through a pipe, which is how an extension would capture output,
  Python buffers stdout, so the line the launcher needs could be held back. `-u` or
  `PYTHONUNBUFFERED=1` fixes it.
- **Data already has an override.** `main.DATA` honours `VULNREPORT_DATA_DIR` (added 2026-09-28 for
  the tests); `GENERATED` does not and is fixed at `<project>/generated`.
- **Word generation still needs Windows, Word and `pywin32`.** That is unchanged: the launcher cannot
  make generation work on a machine where it does not work today.

**The reason given for the change is a question for the user, not for the agents.** The request
describes the extension as a way around a company rule against web apps. The extension would still
start the same local web server and the same browser page; only the thing that launches it changes.
Whether that meets the rule depends on what the rule protects against, which only the user can find
out. This plan will not hide the server or disguise what runs.

## Round 1 - Loremaster: how it works today

**Answer.** All user data except finished documents already follows `VULNREPORT_DATA_DIR`:
`prefs.json`, the report folders, the lock folder and the error log all sit under `main.DATA`, while
`generated/`, the vulnerability library, `.venv` and the templates are fixed to the app folder with no
setting. Nothing on disk records an absolute path, so a data folder moves by copying its whole tree
and every draft is found again. Saving survives a kill at any instant: no half-written draft, and no
lock left held. A kill does lose the in-flight save, can use up the single backup, and leaves temp and
orphan files that nothing sweeps at startup. The risks that are new with a launcher are elsewhere:
unsaved browser drafts are tied to the exact port; on Windows a second server can make a report look
invalid for a while; and `run.py` prints its URL before the app has loaded or bound its port.

---

### 1. Paths and state fixed when the app starts

All of these are computed once, when uvicorn imports `app.main`. Nothing re-reads them while the
process runs, so a change needs a restart.

| What | Decided at | Resolves to | Follows `VULNREPORT_DATA_DIR`? | Written at runtime? |
|---|---|---|---|---|
| data folder `DATA` | [app/main.py#L37](app/main.py#L37) | the variable, else `<app>/data` | it *is* the variable | — |
| `prefs.json` | [app/main.py#L40](app/main.py#L40), [app/tester_identity.py#L176-L204](app/tester_identity.py#L176-L204) | `DATA/prefs.json` | yes | only when missing, unreadable, or without a tester; read once |
| report folders | [app/workspace.py#L64](app/workspace.py#L64) | `DATA/apps/` | yes | yes |
| lock files | [app/workspace.py#L64](app/workspace.py#L64), [#L87-L89](app/workspace.py#L87-L89) | `DATA/.locks/` | yes | yes; one per report, never deleted |
| error log | [app/main.py#L65](app/main.py#L65), [#L71-L82](app/main.py#L71-L82) | `DATA/vulnreport-errors.log` (+ `.1`–`.3`) | yes | yes; opened at import and held open for the life of the process |
| finished documents | [app/main.py#L39](app/main.py#L39), [#L532-L536](app/main.py#L532-L536) | `<app>/generated/` | **no** | yes |
| vulnerability library | [app/main.py#L42-L44](app/main.py#L42-L44) | `prefs.library_path`; a relative value is joined to the **app folder**, not `DATA` | no | read once; rewritten in place only by the library editor ([app/main.py#L900-L908](app/main.py#L900-L908), [app/library_editor.py#L148-L167](app/library_editor.py#L148-L167)) |
| page templates, static files | [app/main.py#L49-L52](app/main.py#L49-L52) | `<app>/app/web/` | no | no |
| Word masters and components | [app/main.py#L527](app/main.py#L527) | `<app>/resources/` | no | no |
| Word pass scratch folder | [app/docx_captions.py#L101-L112](app/docx_captions.py#L101-L112) | the system temp folder (`TemporaryDirectory()` with no `dir`, so the process's `TMP`/`TEMP`) | no | yes; removed after each pass |
| `.venv` and its requirements stamp | [run.py#L12-L15](run.py#L12-L15), [#L47-L62](run.py#L47-L62) | `<app>/.venv/` | no | yes, by `run.py` |
| atomic-write temp files | [app/storage.py#L33](app/storage.py#L33) | a sibling of the file being written | follows its target | yes |

`ROOT` comes from `__file__` ([app/main.py#L34](app/main.py#L34), [run.py#L12](run.py#L12)), so the
process can start from any working directory and still find its own files.

Details that matter to a launcher:

- **Importing `app.main` writes to disk.** It creates the data folder, writes `prefs.json` when it is
  absent (after resolving the tester's name from the OS), and opens the error log
  ([app/tester_identity.py#L193-L202](app/tester_identity.py#L193-L202),
  [app/main.py#L73-L82](app/main.py#L73-L82)). If the data folder cannot be written, the import fails.
- **The variable is used exactly as typed.** `Path(os.environ.get(...))` is neither resolved nor
  `~`-expanded ([app/main.py#L37](app/main.py#L37)), so a relative value is read against the server
  process's working directory. `run.py` sets that to the app folder only for the relaunched child
  ([run.py#L69](run.py#L69)). When the app is started directly with the `.venv` interpreter, it is
  whatever directory the launcher gave. The variable does reach the child, because the relaunch copies
  the whole environment ([run.py#L67](run.py#L67)).
- **The library is an app-folder file that is also editable.** With `VULNREPORT_LIBRARY_EDITOR` set,
  edits are written back to `<app>/resources/vuln_library.json` through a sibling temp file
  ([app/library_editor.py#L156-L163](app/library_editor.py#L156-L163)). So the editor needs that folder
  to be writable, and replacing the app folder replaces the edits.
- **Two things shown to the tester assume the current layout.** After generating, the Content page
  says the report is "inside the app's "generated" folder", with the absolute path as a tooltip
  ([app/web/static/app.js#L878-L879](app/web/static/app.js#L878-L879)). Every error panel shows the log
  location as `ERROR_LOG_LABEL`, which becomes an absolute path once `DATA` is outside the app folder
  ([app/main.py#L67](app/main.py#L67), [#L125](app/main.py#L125), [#L228](app/main.py#L228)).
- **One script ignores the variable.** `scripts/generate_showcase_reports.py` builds
  `Workspace(ROOT / "data", …)`
  ([scripts/generate_showcase_reports.py#L551](scripts/generate_showcase_reports.py#L551)). Tests set
  the variable before import ([tests/__init__.py#L10-L13](tests/__init__.py#L10-L13)) and patch
  `GENERATED` separately ([tests/support.py#L25](tests/support.py#L25)), because it does not follow.
- **`run.py` never checks that `.venv` still works where it sits.** It treats `.venv` as current when
  the interpreter file exists and the stamp matches ([run.py#L38-L44](run.py#L38-L44)). Virtual
  environments cannot be moved; that is Python packaging behaviour, not something this repo tests.

**No absolute path is stored on disk.**

- `draft.json`: `_folder_name_hint` holds two folder *names*
  ([app/models.py#L272-L274](app/models.py#L272-L274), set at
  [app/workspace.py#L364](app/workspace.py#L364)). `evidence.file` must be
  `evidence/<evidence_id>.png`, and an absolute value is rejected
  ([app/models.py#L341-L342](app/models.py#L341-L342), [#L409-L410](app/models.py#L409-L410)). A
  search of all 14 `draft.json` and 8 `draft.bak.json` under `data/apps/` for absolute paths found none.
- `prefs.json`: the library path on disk is the relative `resources/vuln_library.json`.
- Lock files are named by a hash of the report id ([app/workspace.py#L88](app/workspace.py#L88)).
- Some responses carry absolute paths, but nothing keeps them. The client never reads the save
  response's `path` ([app/main.py#L817](app/main.py#L817)); it reads only `saved.report`
  ([app/web/static/app.js#L789-L790](app/web/static/app.js#L789-L790)). The generate response's `path`
  and `folder` ([app/main.py#L515](app/main.py#L515)) feed only the tooltip above. The browser's local
  draft stores the report object, not paths
  ([app/web/static/app.js#L313-L321](app/web/static/app.js#L313-L321)).
- No report is looked up by a stored location. `find_path` scans `DATA/apps/*/*/draft.json` and
  matches the `report_id` inside ([app/workspace.py#L243-L251](app/workspace.py#L243-L251)), and
  evidence is read relative to the draft's own folder ([app/main.py#L893-L894](app/main.py#L893-L894)).

### 2. Being stopped at an arbitrary moment

**How the process is ended decides whether a request in progress finishes.** The app has no shutdown
hook of its own: `app/main.py` has no lifespan, `atexit` or signal handling. Today the documented way
to stop it is "Close the console window" ([README.md#L14](README.md#L14)).

- *A catchable stop* (SIGINT, SIGTERM, and Ctrl+Break on Windows) reaches uvicorn 0.52.4's handlers
  ([uvicorn/server.py#L36-L41](.venv/lib/python3.14/site-packages/uvicorn/server.py#L36-L41)). uvicorn
  stops accepting connections and waits for running requests to finish
  ([#L272-L320](.venv/lib/python3.14/site-packages/uvicorn/server.py#L272-L320)). That wait has **no
  time limit**, because `run.py` does not set `timeout_graceful_shutdown` ([run.py#L91](run.py#L91);
  the default is `None`,
  [uvicorn/config.py#L231](.venv/lib/python3.14/site-packages/uvicorn/config.py#L231)). A save in
  progress completes. A generation holds the report lock for the whole Word pass
  ([app/main.py#L521-L537](app/main.py#L521-L537)), so a stop during generation waits for Word. A
  second SIGINT forces an exit; a second SIGTERM does not
  ([uvicorn/server.py#L342-L347](.venv/lib/python3.14/site-packages/uvicorn/server.py#L342-L347)).
- *An outright kill* runs nothing: no handler, no `finally` block. The outcomes listed below are for
  this case.
- *Ctrl+C in today's console, when `run.py` was started with the system interpreter,* reaches both
  processes. The parent's `subprocess.run` waits 0.25 s for the child, then kills it outright
  (CPython's `Popen.wait` allows `_sigint_wait_secs = 0.25`, then `subprocess.run` calls
  `process.kill()`; checked in the installed CPython 3.14.7). `relaunch()` then swallows the interrupt
  ([run.py#L68-L71](run.py#L68-L71)). So today's Ctrl+C already cuts the server's wait for running
  requests off after a quarter of a second.
- Ending only the parent leaves the child running. Nothing in `run.py` forwards a signal to the child
  or ties the child's lifetime to the parent ([run.py#L65-L71](run.py#L65-L71)).
- How a Burp Stop button reaches the process (a catchable signal or a kill, the parent only or every
  process) depends on launcher code that does not exist yet.

**What an outright kill leaves behind, per operation.**

A save runs in this order: copy the current `draft.json` to `draft.bak.json` (temp file, then
replace); write the new `draft.json` (temp file, then replace); delete evidence PNGs the draft no
longer lists; reply ([app/storage.py#L18-L22](app/storage.py#L18-L22),
[#L30-L47](app/storage.py#L30-L47); [app/workspace.py#L346-L369](app/workspace.py#L346-L369)).

| Killed | On disk afterwards | The save |
|---|---|---|
| while writing the backup's temp file | a stray `.draft.bak.json.<random>.tmp`; both real files untouched | lost |
| between the two replaces | `draft.bak.json` now **equals** `draft.json`: the older backup is gone and nothing new replaced it | lost, and the one level of backup is used up |
| while writing the draft's temp file | a stray `.draft.json.<random>.tmp`, possibly partial; `draft.json` is the old version | lost |
| after the draft's replace, before the reply | the new version is on disk | kept, but the browser never learns the new `saved_at`, so its next save from that page gets a 409 against its own write (§4) |
| during the first save that names a report | the folder may already be renamed ([app/workspace.py#L357-L363](app/workspace.py#L357-L363)), with the old content inside | lost; harmless, since reports are looked up by `report_id` |

What cannot happen is a half-written `draft.json` under its real name. The temp file is a sibling on
the same filesystem, and `os.replace` swaps it in whole. Nothing calls `fsync`, so this protects
against the process dying, not against a power cut or an OS crash. If a torn draft ever did appear, it
would vanish without a message. `find_path`, `list_reports` and `list_legacy_reports` all skip JSON
they cannot parse ([app/workspace.py#L127](app/workspace.py#L127),
[#L143-L144](app/workspace.py#L143-L144), [#L249-L250](app/workspace.py#L249-L250)). Nothing in the
app ever reads `draft.bak.json` back; the only line that mentions it is the one that writes it
([app/storage.py#L21](app/storage.py#L21)). Restoring from the backup is a manual copy.

An evidence upload writes the PNG first and then the draft, under one lock. If the draft write fails,
an `except` branch deletes the PNG, but a kill never reaches that branch
([app/workspace.py#L314-L344](app/workspace.py#L314-L344)).

- Killed before the PNG is in place: a stray temp file in `evidence/`.
- Killed between the PNG and the draft: a PNG the draft does not list. The next successful save of
  that report deletes it ([app/workspace.py#L368](app/workspace.py#L368),
  [#L371-L380](app/workspace.py#L371-L380)). Until then it counts toward the 250 MB cap, which adds up
  every `*.png` in the folder ([app/workspace.py#L331](app/workspace.py#L331)).
- Killed after the draft: the evidence list holds the new entry, but the browser never received its
  id, so no fragment points at it. The browser's next save gets a 409. If the tester chooses *Save my
  version*, the report sent back does not include that entry, and the PNG is deleted. Either way, no
  fragment is left pointing at a missing file.
- The browser does not keep the chosen file. The file input is cleared before the upload starts
  ([app/web/static/app.js#L2912-L2916](app/web/static/app.js#L2912-L2916)), so a lost upload has to be
  chosen again.

Adding a finding from the library and renaming a report are each one guarded save
([app/main.py#L849](app/main.py#L849), [#L715](app/main.py#L715)) and behave like a save. An import or
a duplicate writes `draft.json` and then its PNGs, and undoes that in an `except` branch
([app/workspace.py#L171-L179](app/workspace.py#L171-L179), [#L205-L213](app/workspace.py#L205-L213)).
A kill between the two leaves a new report with some PNGs missing. Nothing notices on load, because
`validate_references` checks the evidence list, not the files. Export later refuses the report with
"Evidence file is missing" ([app/workspace.py#L193-L194](app/workspace.py#L193-L194)). A generation
writes into `generated/` with the same temp-file-then-replace ([app/main.py#L536](app/main.py#L536)).
At most it leaves a stray temp file there, plus the Word scratch folder in the system temp folder. What
Word itself does when the process driving it dies is outside my territory.

**Lock files cannot block the next start.** Each `.locks/<hash>.lock` is an ordinary one-byte file
containing `0` ([app/workspace.py#L89-L93](app/workspace.py#L89-L93)). There are 76 of them in
`data/.locks/` for 14 drafts, because nothing deletes them. The lock is an OS lock on the open file
handle, not the file's existence ([#L95-L100](app/workspace.py#L95-L100)). On macOS and Linux, `flock`
is released when the last descriptor closes, and process exit closes them all. Python descriptors are
not inherited by child processes (PEP 446), and nothing in `app/` starts one with `subprocess`. On
Windows, the OS releases `LockFile` locks when the process ends. Microsoft's documentation adds that
how quickly depends on system resources; the next start's lock call keeps retrying for about ten
seconds (§3), which covers a short delay.

**Nothing at startup cleans up after a crash.** The only startup repair is for `prefs.json`: an
unreadable file is moved to `prefs.corrupt.json` and rebuilt
([app/tester_identity.py#L182-L191](app/tester_identity.py#L182-L191)). Its own write goes through a
fixed `prefs.tmp`, which the next start overwrites ([#L198-L202](app/tester_identity.py#L198-L202)).
Stray `.tmp` files are never cleaned up. No pattern the app searches with (`*/*/draft.json`,
`evidence/*.png`) matches them, so they are harmless and disappear only when their report folder is
deleted ([app/workspace.py#L156](app/workspace.py#L156)). PNGs no longer listed are deleted on that
report's next save. The two repairs in `load_path`
([app/workspace.py#L270-L299](app/workspace.py#L270-L299)) upgrade old draft shapes and have nothing to
do with crashes. None of this leftover debris exists in this checkout today.

In the browser, the unsaved edit survives a kill in `localStorage`. The page writes it 150 ms after
every change and again after every failed save
([app/web/static/app.js#L328-L331](app/web/static/app.js#L328-L331),
[#L815](app/web/static/app.js#L815)). Section 4 covers when that copy can be found again.

### 3. Two servers on one data folder

**Saves are safe across processes.** `_locked` takes an in-process `RLock`, then an exclusive OS lock
on the report's lock file ([app/workspace.py#L73-L110](app/workspace.py#L73-L110)). Every guarded write
re-reads `draft.json` from disk under that lock and compares `saved_at`
([app/workspace.py#L306-L312](app/workspace.py#L306-L312), [#L314-L326](app/workspace.py#L314-L326)).
No route keeps a report in memory between requests; each one loads it from disk. So one server's
write is seen by the other's next request. The 409 flow covers the full save, adding from the library,
evidence upload and rename ([app/main.py#L757-L764](app/main.py#L757-L764),
[#L806-L815](app/main.py#L806-L815), [#L849](app/main.py#L849), [#L875](app/main.py#L875),
[#L715](app/main.py#L715)). Whichever process wrote, the tester is told "This report changed in another
browser tab." ([app/main.py#L68](app/main.py#L68)). Delete and repair make no revision check, the same
as between two tabs today.

**On Windows, a second server can make a report look invalid.** `msvcrt.locking(…, LK_LOCK, 1)`
([app/workspace.py#L97](app/workspace.py#L97)) retries once a second and raises `OSError` after ten
failed attempts (Python's documentation for `msvcrt.locking`). This never happens within one process:
a second thread waits on the `RLock` first ([#L76](app/workspace.py#L76)) and reaches the OS lock only
once it is free. Between two processes it happens whenever one holds a report for more than about ten
seconds, and generation holds it for the whole Word pass
([app/main.py#L521-L537](app/main.py#L521-L537)). In the other server, that `OSError` shows up in
three places:

- Opening or saving the report: `report_or_404` turns it into a 422, "The draft is invalid. Return to
  the report manager to review available repair actions."
  ([app/main.py#L242-L243](app/main.py#L242-L243)). On a page load that is the "Report needs repair"
  page ([#L202-L203](app/main.py#L202-L203)). A save that got past that check and then timed out
  inside `save_if_current` is an unhandled error, so a 500 ([#L208-L233](app/main.py#L208-L233)).
- The home page first waits up to about ten seconds for each report the other server holds. Then
  `list_reports` leaves the report out ([app/workspace.py#L127](app/workspace.py#L127)), and
  `list_legacy_reports` lists it under "Legacy drafts", with the OS error as the reason and no repair
  offered ([#L139-L146](app/workspace.py#L139-L146)). That list has no Delete button
  ([app/web/static/manager.js#L72](app/web/static/manager.js#L72)), so nothing is lost. Once the lock
  is free, the next render shows the report normally.
- The tab: a 422 is not retried automatically
  ([app/web/static/app.js#L817](app/web/static/app.js#L817)), so the tab stays at "Save failed - Retry"
  until the next edit or click.

On macOS and Linux, `flock` waits without a limit ([app/workspace.py#L100](app/workspace.py#L100)), so
the other server just waits.

**Other state the two processes share or keep separately:**

- *Error log:* both open the same rotating log file ([app/main.py#L71-L82](app/main.py#L71-L82)).
  Python's logging documentation says one log file written by several processes is not supported. When
  the log rotates, Windows refuses to rename a file the other process has open, and logging prints the
  failure to stderr. On macOS and Linux, the other process keeps writing to the renamed file. This
  affects diagnostics only, not report data.
- *Library and prefs* are read once per process ([app/main.py#L40-L44](app/main.py#L40-L44)). A library
  edited through the library editor in one server stays unchanged in the other until it restarts.
  Nothing rewrites prefs after startup.
- *Word:* the lock that makes Word automation take turns is a `threading.Lock`, so it covers one
  process only ([app/docx_captions.py#L27](app/docx_captions.py#L27)). Two servers can drive Word at
  the same time. What Word does then is outside my territory.
- *`generated/`:* `unused_export_path` finds a free file name, and the write happens afterwards, with no
  lock that spans reports ([app/main.py#L544-L551](app/main.py#L544-L551)). The name is built from
  segment, application, report type and year
  ([app/report_service.py#L205-L217](app/report_service.py#L205-L217)). So two reports that share
  those values, generated at the same moment, can pick the same name, and the second overwrites the
  first. This can already happen between threads; a second process makes it more likely.

**How a second server can start without anyone noticing.** `free_port` counts a port as taken only when
something accepts a connection on it ([run.py#L74-L80](run.py#L74-L80)). A second start while the first
is running just takes the next port. Nothing records or checks whether another server already uses the
data folder.

### 4. The browser when the server disappears or comes back on another port

**Every request goes to the page's own origin**, for example
[app/web/static/app.js#L787](app/web/static/app.js#L787), [#L868](app/web/static/app.js#L868),
[#L2676](app/web/static/app.js#L2676), [#L2889](app/web/static/app.js#L2889) and
[app/web/static/manager.js#L48](app/web/static/manager.js#L48). A page only ever talks to the host and
port it was loaded from.

**When the server is gone, the page keeps the tester where they are.**

- The next save's `fetch` fails with no HTTP status. The page keeps the edit marked as unsaved,
  rewrites the local draft, and shows "Save failed - Retry" with a panel titled "Operation failed", the
  browser's own network-error text and the status "Client"
  ([app/web/static/app.js#L809-L821](app/web/static/app.js#L809-L821),
  [#L287](app/web/static/app.js#L287), [#L534-L539](app/web/static/app.js#L534-L539);
  [app/web/static/diagnostics.js#L20-L25](app/web/static/diagnostics.js#L20-L25),
  [#L91](app/web/static/diagnostics.js#L91)).
- It retries three times, waiting 5, 10 and 20 seconds
  ([app/web/static/app.js#L173](app/web/static/app.js#L173), [#L180](app/web/static/app.js#L180),
  [#L817-L820](app/web/static/app.js#L817-L820)). Then it stops until the next edit or a click on Save
  ([#L726](app/web/static/app.js#L726), [#L850](app/web/static/app.js#L850)).
- Next and Back refuse to leave the page unless the save succeeded
  ([app/web/static/app.js#L2781-L2789](app/web/static/app.js#L2781-L2789),
  [#L893](app/web/static/app.js#L893)). Upload and adding from the library save first and stop if that
  fails ([#L2675](app/web/static/app.js#L2675), [#L2888](app/web/static/app.js#L2888)). Generate stops
  at the failed save ([#L860-L865](app/web/static/app.js#L860-L865)).
- Closing the tab asks for confirmation and writes the local draft
  ([#L932-L943](app/web/static/app.js#L932-L943)).
- If the server comes back **on the same port**, the same tab carries on at its next retry, edit or
  click. The exception is a kill that landed after a save reached disk. Then the tester gets a "Save
  conflict" saying the report "changed in another browser tab", with *Save my version* and *Load
  latest* ([app/web/static/app.js#L492-L533](app/web/static/app.js#L492-L533)). *Save my version* is
  the right choice in that case, but nothing tells the tester so.

**How local recovery drafts are scoped.**

- Key: `vulnreport-pending:{reportId}:{tabId}:{documentId}` in `localStorage`
  ([app/web/static/app.js#L35](app/web/static/app.js#L35),
  [#L56-L57](app/web/static/app.js#L56-L57), [#L313](app/web/static/app.js#L313)). `tabId` is kept in
  `sessionStorage` under `vulnreport-tab-id` ([#L45-L55](app/web/static/app.js#L45-L55));
  `documentId` is new on every page load.
- Every time a report page loads, it scans **all** keys for that report, from any tab and any earlier
  session, and deletes malformed ones. It then offers the newest ("Unsaved changes found", with Restore
  or Discard), saying whether that draft was based on the current saved version
  ([#L62-L96](app/web/static/app.js#L62-L96), [#L348-L392](app/web/static/app.js#L348-L392),
  [#L947-L954](app/web/static/app.js#L947-L954)). So drafts belong to a report and an origin, not to a
  tab. The tab id only decides which keys a page removes after its own successful save
  ([#L339-L347](app/web/static/app.js#L339-L347)).

**A different port is a different origin, so the old drafts cannot be reached.** `localStorage` and
`sessionStorage` are per origin, and an origin is scheme, host **and port**. The scan at
[app/web/static/app.js#L63](app/web/static/app.js#L63) sees only keys written by pages from the same
origin, so `http://127.0.0.1:8766` cannot see anything written under `http://127.0.0.1:8765`. A server
that comes back on another port cannot see or offer any unsaved draft from the old port. Those drafts
are not deleted. They stay in the old origin's storage and reappear only if the app is served on that
exact port again and the report is opened there. `127.0.0.1` and `localhost` are also different
origins; `run.py` always uses the literal `127.0.0.1` ([run.py#L87](run.py#L87)).

A different origin also loses:

- undo and redo history (`vulnreport-history:{reportId}`, in `sessionStorage`, so also per tab;
  [#L58](app/web/static/app.js#L58), [#L104](app/web/static/app.js#L104),
  [#L574](app/web/static/app.js#L574));
- the newest-revision marker used when the tester goes Back or Forward
  (`vulnreport-saved-at:{reportId}`, [#L37](app/web/static/app.js#L37),
  [#L400-L406](app/web/static/app.js#L400-L406));
- the restore choice waiting for the next page load (`vulnreport-recovery:{reportId}`,
  [#L36](app/web/static/app.js#L36), [#L84-L85](app/web/static/app.js#L84-L85));
- the light or dark theme choice `vr-theme`
  ([app/web/static/theme.js#L14](app/web/static/theme.js#L14),
  [app/web/templates/_theme_boot.html#L1](app/web/templates/_theme_boot.html#L1)).

Nothing uses cookies, IndexedDB, a service worker or `BroadcastChannel` (searched `app/web/`).

Storage is also per browser profile. `run.py` opens the system default browser
([run.py#L90](run.py#L90)), and drafts written in one browser are invisible in another. This repo does
not show whether Burp's built-in browser keeps its storage between sessions.

**When the port actually changes.** `free_port` takes the first port from 8765 to 8799 with nothing
listening on it ([run.py#L74-L80](run.py#L74-L80)). A server that has fully stopped frees its port, so a
restart normally gets the same one. The port moves when something is still listening on the old one.
The likeliest cases are the child from an earlier run whose parent was ended, or a second instance.

**The URL line appears before the app exists.** `serve()` prints the URL and schedules the browser
([run.py#L88-L90](run.py#L88-L90)) *before* `uvicorn.run` imports `app.main` and binds the port
([#L91](run.py#L91)). Everything in §1's import-time list, and the bind itself, happens after that
line. The port was only checked as free at [run.py#L78](run.py#L78), not reserved. So even when the
import fails, or another process takes the port between the check and the bind, the URL is still
printed, and the browser still opens it half a second later. It lands on whatever is serving that port,
or on an error page. uvicorn reports a successful bind separately, by logging "Uvicorn running on …" to
stderr
([uvicorn/server.py#L198-L223](.venv/lib/python3.14/site-packages/uvicorn/server.py#L198-L223); its
default log handler writes to stderr,
[uvicorn/config.py#L100](.venv/lib/python3.14/site-packages/uvicorn/config.py#L100)). Also, a launch
with the `.venv` interpreter directly runs as **one** process: there is no relaunch, and the
requirements check is skipped entirely ([run.py#L95-L99](run.py#L95-L99)).

### 5. Drafts on disk today

A read-only look at this checkout's `data/`:

| | Count |
|---|---|
| app folders under `apps/` | 8 |
| `draft.json` | 14, of which 6 are still in folders with the provisional names `apps/unnamed/<month>_Report_<id>` |
| `draft.bak.json` | 8 (a backup exists only once a draft has been written twice) |
| evidence PNGs | 13 (`apps/` totals 1.2 MB) |
| `.locks/*.lock` | 76 |
| `prefs.json` | 1. The library path is relative. It also has an undeclared `defaults` key, which `Preferences` drops on read and which stays on disk, because prefs is rewritten only when it is missing, unreadable or has no tester ([app/tester_identity.py#L162-L165](app/tester_identity.py#L162-L165), [#L181-L198](app/tester_identity.py#L181-L198)) |
| error logs | 4 files, about 4.7 MB |
| stray `.tmp` files, `prefs.corrupt.json` | none |

`generated/` holds six PNG screenshots and `.gitkeep`, and no `.docx`.

**Where testers' drafts are.** Unless `VULNREPORT_DATA_DIR` is set, drafts are in `data/` inside
whichever folder `run.py` was started from ([app/main.py#L37](app/main.py#L37)). Finished documents are
in that folder's `generated/` ([#L39](app/main.py#L39)). The release zip deliberately leaves out both
folders ([scripts/package_release.py#L1](scripts/package_release.py#L1),
[#L21](scripts/package_release.py#L21)), and the README has no step for carrying `data/` into a new
release ([README.md#L1-L14](README.md#L1-L14)). So even today, a tester who unzips a new release into a
new folder starts with an empty report list. The old folder's drafts are left behind unless copied by
hand.

**What makes a draft findable again.** The scan looks exactly two levels below `DATA/apps/` and matches
the `report_id` inside each `draft.json`
([app/workspace.py#L119-L129](app/workspace.py#L119-L129),
[#L243-L251](app/workspace.py#L243-L251)). Folder names do not matter; depth does. Evidence and the
backup sit inside each report's folder and move with it. The files beside `apps/` matter less:

- `prefs.json` holds the tester name resolved from the OS at first start, which nothing in the app
  edits, and the library path. Without it, the next start resolves the name again
  ([app/tester_identity.py#L193-L196](app/tester_identity.py#L193-L196)).
- `.locks/` can be thrown away; it is recreated when needed
  ([app/workspace.py#L87](app/workspace.py#L87)).
- The logs are diagnostics only.

**The migration risk is duplicates, not loss.** The same report can end up in the scanned tree twice,
for example when it is copied twice or two data folders are merged. Then `find_path` returns whichever
copy the scan reaches first ([app/workspace.py#L245-L248](app/workspace.py#L245-L248)), while
`list_reports` lists both under one id. The home page links by id, so one copy can be opened and the
other cannot. Two separate data folders, each served by its own process, are simply independent
stores. A report copied into both then has two copies that each change separately.

### 6. Rules that exist in both Python and JavaScript

None. Data location, ports and startup are server-only; recovery keys, retry timing and origin scoping
are client-only. The one Python-to-JavaScript contract involved is the 409 body: `code`,
`recoverable` and `latest_saved_at`, built by [app/main.py#L163-L174](app/main.py#L163-L174) and read
by `markSaveConflict` ([app/web/static/app.js#L492-L533](app/web/static/app.js#L492-L533)). That is a
shape the client reads, not a rule written twice, and it does not depend on which process answers.

### Invariants in play

- **Every read-modify-write goes through `Workspace._locked`.** That is what makes a second process
  safe. A write path that skips it would race with the other process, not just with other threads.
- **`saved_at` is compared against the file on disk, under the lock.** If a report were kept in memory
  between requests, a second server's write could be silently overwritten instead of producing a 409.
- **Writes use a sibling temp file and then `os.replace`.** This works only while the temp file is on
  the same filesystem as the target, which today it always is. Whether replace and OS file locks keep
  their guarantees on a network share or a cloud-synced folder was not examined.
- **Never discard user content without a prompt.** After a kill, the local recovery draft is the only
  copy of unsaved edits, and it is tied to one origin and one browser profile.
- **An existing `draft.json` must still load.** Nothing stored depends on where the data folder is, so
  moving it needs no change to `load_path`.

### Both-sides warning

None (see §6).

### Map drift

I corrected and extended `docs/DATA_MAP.md` and moved "Latest verification" to 2026-09-30:

- The timer table in §9 gave the local-draft key without its per-page suffix. The source writes
  `vulnreport-pending:{reportId}:{tabId}:{documentId}`
  ([app/web/static/app.js#L57](app/web/static/app.js#L57)), which §10 already said.
- §3 now records what a kill between the two replaces leaves, and that nothing calls `fsync` or reads
  the backup back.
- §4 now records the Windows lock's ten-second limit, what the resulting error turns into, and that
  lock files are harmless.
- §13 has two new sharp edges: that Windows limit when two processes run, and recovery drafts being
  tied to the port.

## Round 1 - Tactician: proposal and open questions

### Understanding

The tester loads one small Java file into Burp. It adds a **Report Generator** tab with a
terminal-style output area, a status line, and Start and Stop buttons. Start runs the existing app the
way `py -3 run.py` does today: the tester's own Python 3 creates or updates `.venv`, the same FastAPI
server starts on `127.0.0.1`, and the tester works in their usual browser. Stop ends the server
without cutting off a save in progress. Nothing under `app/` changes: no field, route or page, and
nothing in the finished Word document. What changes is how the server is started, stopped and found
(`run.py` and the new Java code), which port it listens on, how a release is built, and how the
drafts in a tester's old release folder reach the new release that carries the extension. The app is
not moved into Burp, and nothing about it is hidden: Python must still be installed, the process list
still shows a Python web server, and the tab prints the command it ran and the address it serves.

**The Word side is unexamined.** There was no Scribe round, because the document itself does not
change. One environmental risk remains: Word automation running under a Python process that Burp
started, instead of one started from a console. Reading code cannot settle it, so Step 7 settles it
by generating a real report on Windows through the extension.

### Blast radius

| File | What changes |
|---|---|
| `run.py` | Fixed port 8765 with a `VULNREPORT_PORT` override, and a refusal that names the address when something already answers there (replaces `free_port`). The address line, `Report Generator is running at <url>`, is printed only after uvicorn has bound the port; a console start then opens the browser, replacing the 0.5 s timer. When `VULNREPORT_STARTED_BY_BURP=1`: the server shuts down gracefully when its stdin reaches end of file, the browser is left to the extension, "Close this window to stop the application." is not printed, and the setup and relaunch child processes are handed the launcher's stdin, stdout and stderr explicitly. |
| `burp/ServerProcess.java` (new) | JDK only. Starts `run.py` with the system Python, streams merged output, recognises the address line, stops gracefully by closing stdin, force-stops the process tree, stops with a deadline on unload. A `main` self-check that runs without compiling. |
| `burp/ReportGeneratorExtension.java` (new) | The Montoya entry point: the tab, the Python field, the buttons, the unloading handler. Finds the app folder from the JAR's own location. |
| `tests/test_launcher.py` | Port refusal; address line printed only once the server answers; end of stdin stops the server with exit code 0; child processes receive the launcher's streams; the Java source uses the same address line and variable name as `run.py`. |
| `scripts/package_release.py` | Compiles the two Java files against a pinned, hash-checked Montoya API jar and puts `ReportGenerator-Burp.jar` at the root of the release zip. |
| `README.md` | Loading the extension; Start, Stop, Force stop; what runs and where; use the usual browser; one copy per folder; bringing `data/` across; `VULNREPORT_PORT`. |
| `docs/DATA_MAP.md` | §3: how a stop from the extension reaches a save in progress. §13: the port and two-server sharp edges rewritten to say what now prevents them and what reopens them. "Latest verification". |
| `docs/ARCHITECTURE.md` | The uvicorn row, which says the app "picks a free port on startup so several copies can run side by side"; a short paragraph on starting from Burp. |
| `.github/copilot-instructions.md` | One line for `burp/` and how it is checked. |
| Not touched | `app/`, `app/web/`, `resources/`, the schema, `docs/ROUTES.md` (no new route), `scripts/relevant_tests.py`. A change under `burp/` lands in that script's "No rule for these — decide by hand" list, and the answer is the Java self-check in Step 4. |

**Both sides.** No rule is added in both Python and JavaScript. A smaller contract now crosses
Python and Java: the wording of the address line, and the variable name. Step 4 pins both with a test
on the Python side.

### Open questions

Four decisions wait on you, most consequential first. Each can be answered on its own.

**1. Does the company rule allow what this extension actually runs?**

- *Background.* The request describes the extension as a way around a company rule against web
  apps. The extension does not change what runs. Start launches the same Python web server on this
  computer only (`127.0.0.1`, unreachable from other machines, as today). The first Start still
  installs the same Python packages from the internet. Drafts and evidence are stored in the same
  folder. The tester still works in a browser. Only the button that starts it moves. So whether this
  meets the rule depends on what the rule protects against: network exposure, unapproved software or
  packages, where client data is kept, or the kind of tool. None of those change, and only the rule's
  owner can say which one it is.
- *Options.* (a) Ask the rule's owner before anything is built, describing it plainly: "a Burp
  extension that starts a local Python web server on 127.0.0.1 and opens it in the browser".
  (b) Build it and ask afterwards. (c) Build it and do not ask.
- *Trade-offs.* (a) costs one conversation and may end in a no, which saves the whole build.
  (b) and (c) risk you being in breach of a rule with a tool that is still, visibly, a web app: the
  process list shows a Python server, now started by Burp.
- *Recommendation.* (a). Whatever the answer, this plan does not hide or disguise the server: the tab
  prints the command, the folder and the address, and the README says what runs.
- *Why it matters.* It decides whether any step below should be built.
- *Absent an answer.* The plan stays at `planning`, and I would not start Step 1.

**2. Should the extension be a small launcher kept inside the Report Generator folder, or one file
that carries the whole app?**

- *Background.* Burp runs extensions on Java; Python inside Burp means Python 2.7 through Jython. So
  the extension is a small Java file, a JAR, that starts the existing Python app. That app is a folder:
  Python code, page templates, Word templates, and the vulnerability library.
- *Options.* (a) **Launcher inside the folder.** The release zip gains one file,
  `ReportGenerator-Burp.jar`. Testers unzip the release as today and load that JAR into Burp from the
  unzipped folder. It starts the `run.py` beside it, and drafts stay in that folder's `data/`, where
  they are today. (b) **Everything inside the JAR.** One file to load. On Start the JAR unpacks the app
  into a per-user folder and runs it from there.
- *Trade-offs.* (a) needs no unpacking code and moves no data. Its cost is that the JAR must stay in
  the folder: delete the folder and Burp can no longer load the extension. (b) is one file, but drafts
  could no longer live beside the app, because each new version would unpack over them. They would
  move to a separate per-user folder, and finished documents too, which needs an app change because
  `generated/` has no setting today. Every tester's existing drafts would be copied there once, which
  is the step where duplicate reports appear. It also puts the Python server out of sight inside a
  Burp extension, which is the wrong direction given question 1.
- *Recommendation.* (a).
- *Why it matters.* (b) turns this into a data-migration change.
- *Absent an answer.* (a), which the steps below assume. If the answer is (b), I would re-plan from the
  data folder up rather than patch these steps.

**3. Should the app always use port 8765 instead of taking the first free port?**

- *Background.* Today `run.py` takes the first free port from 8765 to 8799, and
  `docs/ARCHITECTURE.md` presents that as letting several copies run side by side. The browser keeps
  unsaved edits, undo history and the light or dark choice per address, and the port is part of the
  address. If the app comes back on 8766, edits the browser kept under 8765 are not offered. They are
  not deleted; they come back only when the app is served on 8765 again. Starting from Burp makes a
  moved port likelier. Testers often run two Burp windows, one per client, and each would have the
  tab. If both are started, two servers share one data folder. On Windows, while one of them generates
  a report, the other shows that report as needing repair for as long as the generation lasts
  (nothing is lost).
- *Options.* (a) **Always 8765**, with `VULNREPORT_PORT` to override. A second start stops with
  "already running at http://127.0.0.1:8765". (b) **Keep the scan and add a lock in the data folder**,
  so a second copy on the same folder refuses to start while copies of different folders can still run
  side by side. (c) **Keep today's scan.**
- *Trade-offs.* (a) is a few lines and removes both risks. Its cost: two copies side by side need the
  override, and if another program already owns 8765 the tester must set `VULNREPORT_PORT` where
  Burp can see it (a Windows environment variable, then restart Burp). (b) keeps side-by-side copies of
  different folders, but needs a lock taken without waiting on both Windows and macOS, held for the
  server's life, plus a file recording the address so the refusal can name it; and the port still
  moves when something else holds 8765. (c) costs nothing and keeps both risks.
- *Recommendation.* (a), for console starts as well. Otherwise a console `run.py` started after
  Burp's server would take 8766 and share the data folder.
- *Why it matters.* It decides whether an ordinary restart can hide a tester's unsaved edits.
- *Absent an answer.* (a), in Step 1. The extension reads the address from the server's own line and
  never assumes 8765, so every other step holds whatever the answer.

**4. How should a tester bring existing drafts into the new release folder?**

- *Background.* The extension arrives in a new release, and each release unzips into a new folder
  whose `data/` is empty. Drafts in the old folder are not lost, only not shown. That is already true
  of every upgrade, and the README has no step for it. The app finds a report by scanning
  `data/apps/<app>/<report>/draft.json`, and nothing inside `data/` records an absolute path, so
  moving the whole `data` folder is enough. What goes wrong is duplication. The same report twice in
  one `data/` (copied twice, or two folders merged) is listed twice, and only one copy can be opened.
  A copy left in the old folder becomes a second, separate store if the old app is ever run again.
- *Options.* (a) **A README step:** stop the old app, then move (not copy) the old `data` folder into
  the new release folder before pressing Start there for the first time; move `generated/` as well to
  keep earlier documents alongside. (b) **The extension finds the old folder and moves `data` itself.**
  (c) **Keep drafts in a per-user folder outside any release from now on**, so no future upgrade
  strands them.
- *Trade-offs.* (a) is no code and relies on the tester following one instruction. (b) is code that
  touches every tester's drafts, runs once, and is hard to test against real data. (c) fixes upgrades
  for good but is its own change: the extension would set `VULNREPORT_DATA_DIR`, `generated/` needs a
  setting of its own, and each tester moves their drafts once.
- *Recommendation.* (a) now; (c) as its own plan if stranded drafts keep coming up.
- *Why it matters.* This is the only point in the change where a tester's reports could be duplicated.
- *Absent an answer.* (a), in Step 6.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new route and no change to what carries `saved_at`. The one way the extension can cause a 409 is a kill that lands after a save reached disk, so the tab's next save conflicts with its own write (Loremaster, §2). Stop is graceful and cannot produce it; only Force stop or the unload deadline can. |
| Lost update | clear | No new code reads or writes a report; every write still goes through `Workspace._locked`. |
| Orphan reference | clear | A kill between an evidence PNG and its draft leaves a PNG the draft does not list, which the next save of that report deletes; no fragment ends up pointing at a missing file (Loremaster, §2). |
| Silent stranding | clear | Scope and environments are untouched. |
| Schema break | clear | No field changes and the data folder does not move, so `load_path` needs no repair. |
| Request/response asymmetry | clear | No request or response changes. |
| Rule drift | RISK | New Python-to-Java contract: the address line and the variable name. Step 4's test reads the Java source and fails if either differs from `run.py`. |
| Navigation trap | clear | No page gate changes. |
| Derived-state fight | clear | `provision_report` is untouched. |
| Backup exhaustion | RISK | A kill between a save's two file replacements leaves `draft.bak.json` equal to `draft.json`, so the one backup is used up (Loremaster, §2). Stop never kills. Force stop and the unload deadline do, but only after uvicorn has stopped accepting requests, and before the address line nothing is being served, so only a save already running is exposed, and a save takes milliseconds. A generation holds its report's lock through the Word pass but writes nothing of the draft during it; `load_path` can rewrite a legacy draft at the very start, before Word runs. |
| A port change hides unsaved edits | RISK | Edits the browser kept, undo history and theme are per address. Step 1 fixes the port, and Step 2 ends the server when Burp ends, so no leftover server holds 8765 and pushes the next start elsewhere. Depends on question 3. |
| Second server on one data folder | RISK | Two Burp windows, each with the tab, is a common set-up. On Windows the second server shows a report as needing repair while the first holds it for more than about ten seconds, which a generation does (Loremaster, §3). The fixed port refuses the second start. `VULNREPORT_PORT` reopens the risk, so the README says one copy per folder. |
| A different browser hides unsaved edits | RISK | Edits the browser kept belong to one browser profile. Opening the app in Burp's browser instead of the tester's usual one would stop them being offered. The extension opens the system default browser. |
| Report data recorded in a Burp project | RISK, unverified | If Burp's browser sends `127.0.0.1` traffic through Burp's proxy, every save's JSON and every evidence image would enter Proxy history and the open project file, possibly another client's, and Intercept would hold saves. Step 7f checks. The README says to use the usual browser either way. |
| Duplicates when drafts move to the new release | RISK | Copying twice or merging two folders lists a report twice with only one copy openable; a copy left in the old folder becomes a separate store (Loremaster, §5). Question 4. |
| Word left running after a Force stop | RISK, unexamined | The Word pass starts its own hidden Word through `DispatchEx` ([app/docx_captions.py#L64](app/docx_captions.py#L64)), and a kill mid-pass means its clean-up never runs. What Word does then is the scribe's ground. Step 7c checks. |
| Burp's exit kills the server outright | RISK, unverified | The design expects the server to stop gracefully when Burp's end closes its stdin. If Burp's own Windows launcher ends its child processes when Burp exits, a save running at that instant meets the kill outcomes instead. Step 7h checks. |

### Plan

**Choices the steps rely on.** Any of them can be reopened; none changes report data.

| Choice | Taken | Why |
|---|---|---|
| Extension language | Java, on Burp's current extension API (Montoya) | Python 3 cannot run inside Burp. Python there means Jython 2.7 on the legacy Extender API, and every tester would first have to download Jython and point Burp at it. The launcher is process handling, which the JDK does directly. Cost: building a release needs a JDK. |
| Where the app folder is | The folder the JAR was loaded from: `api.extension().filename()`, documented as the "absolute path name of the file from which the current extension was loaded" | No setting to get wrong. A JAR loaded from anywhere else says where it belongs and keeps Start disabled. |
| Python | The tester's installed Python 3, as today. Automatic: `py -3`, then `python`, on Windows; `python3` elsewhere. A field for an explicit interpreter path, kept in Burp's preferences | The requirement is unchanged. The field is for macOS, where an app started from the Dock does not see the shell's PATH and finds Apple's older `python3`. |
| Which interpreter starts | The system Python runs `run.py`, which sets up `.venv` and relaunches inside it, as today | Starting `.venv`'s interpreter directly skips the requirements check entirely (Loremaster, §4), and would copy `venv_python()` into Java. |
| Data | Unchanged: `<release folder>/data/` and `generated/`. The extension sets no `VULNREPORT_DATA_DIR` | Nothing moves, so the extension itself cannot duplicate anything. |
| Ready signal | `run.py` prints the address line once uvicorn has bound the port; the extension matches that one line | Our own sentence at the right moment. Today it is printed before the app is even imported (Loremaster, §4), and the console browser opens on that early line too. |
| Browser | The system default browser, opened by the extension when the line arrives, plus an **Open** button | The same browser profile as today, so edits the browser kept are still offered, and report traffic stays out of Burp. |
| Stop | Close the server's stdin; the server runs uvicorn's graceful shutdown, so running requests finish. While it waits, Stop becomes **Force stop**, which kills the process tree | Java cannot send Ctrl+C on Windows: there `Process.supportsNormalTermination()` is false and `destroy()` is an outright kill. |
| Unload and Burp exit | The unloading handler stops gracefully, waits up to 10 s, then force-stops. If Burp ends without calling it, the closed pipe stops the server gracefully on its own | Burp's documentation does not say whether the handler runs when Burp exits, so nothing depends on it. |
| When it has stopped | The root process's exit, never the end of its output | A leftover child can hold the output pipe open for minutes; `scripts/relevant_tests.py` hit exactly that with Chromium helpers and writes test output to a file for that reason. |
| Output | stdout and stderr merged; the area keeps the last 2,000 lines; the status line holds the address | uvicorn logs one line per request, and autosave sends a request every few seconds of editing. |
| Release build | `package_release.py` compiles with `javac` against a pinned, hash-checked Montoya API jar; the JAR goes at the zip's root; Burp supplies the API at runtime | No Gradle, and the script stays standard-library Python. |

Do not start Step 1 until question 1 is answered yes.

- [ ] **Step 1 — One fixed port, and a clear refusal when it is taken** (after question 3)
  - *Files:* `run.py`; `tests/test_launcher.py`; `docs/ARCHITECTURE.md` (the uvicorn row);
    `docs/DATA_MAP.md` §13 (both port-related sharp edges) and "Latest verification".
  - *What:* `PORT` is `VULNREPORT_PORT` or 8765. `serve()` first checks whether something answers on it
    (the connect test `free_port` does today) and, if so, exits with: "Port 8765 is in use. Report
    Generator may already be running at http://127.0.0.1:8765. Use that one, or stop it first. To run
    a second copy, set VULNREPORT_PORT." `free_port` is deleted. A bind that still fails, because two
    starts raced, ends in uvicorn's own startup failure, which is also a refusal.
  - *Test:* `PortTests.test_start_refuses_when_something_answers_on_the_port`: listen on a free port,
    patch `run.PORT` to it, and `assertRaisesRegex(SystemExit, r"already running at http://127\.0\.0\.1:<port>")`.
    Remove the check once and watch it fail with uvicorn's exit code instead of the message.
  - *Invariant:* a console start on a free 8765 behaves as today, and edits a browser kept under 8765
    are still offered.

- [ ] **Step 2 — Print the address only once the server answers, and let the extension stop it through stdin**
  - *Files:* `run.py`; `tests/test_launcher.py`; `docs/DATA_MAP.md` §3.
  - *What:* `serve()` runs `uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=PORT))`
    through a subclass whose `startup` prints the address line with `flush=True` after the bind
    (`Server.started` is set only after `create_server` succeeds). A console start then opens the
    browser, replacing the 0.5 s timer. The line's fixed part and the variable name are module
    constants. When `VULNREPORT_STARTED_BY_BURP=1`: a daemon thread reads stdin to end of file and then
    sets `server.should_exit`; the browser is not opened; "Close this window…" is not printed.
    DATA_MAP §3 gains: when started from the extension, Stop runs uvicorn's graceful shutdown, so
    running requests finish (a generation waits for its Word pass); Force stop and the unload deadline
    are the outright kill whose outcomes §3 lists.
  - *Tests,* in a new `StartedByBurpTests` class. Each starts `sys.executable run.py` with
    `VULNREPORT_STARTED_BY_BURP=1`, `VULNREPORT_BOOTSTRAPPED=1` (serve in this interpreter, never set up
    `.venv`), a free `VULNREPORT_PORT`, the temporary `VULNREPORT_DATA_DIR` from `tests/__init__.py`,
    and pipes. It reads output on a thread with a deadline, never a bare `readline`.
    - `test_address_line_is_printed_only_once_the_server_answers`: on reading the line, one request to
      the address, with no retry, returns 200. Move the print back before `server.run()` once and
      watch it fail.
    - `test_closing_stdin_stops_the_server_cleanly`: after the line, close stdin; the process exits
      with code 0 within 15 s and the port no longer answers.
  - *Invariant:* a console start keeps its console behaviour (browser, message, Ctrl+C). The stdin
    watcher exists only when the variable is set, because a console start whose stdin is empty would
    otherwise stop itself at once. Nothing under `app/` changes.

- [ ] **Step 3 — Hand the extension's pipes to every child process**
  - *Files:* `run.py`; `tests/test_launcher.py`.
  - *What:* when `VULNREPORT_STARTED_BY_BURP=1`, the `subprocess.run` calls in `bootstrap()` and
    `relaunch()` pass `stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr`. The server is a
    grandchild of the extension, and on Windows further down still: as I understand them, `py.exe` and
    the `.venv` interpreter are themselves small launchers. On macOS and Linux a child inherits the
    first three file descriptors anyway. On Windows, Python starts a child with handle inheritance
    switched off unless standard handles are passed to it (`close_fds` defaults to true). Whether the
    extension's pipe still reaches the server that way is what Step 7a checks; passing the three
    handles makes it certain either way.
  - *Test:* `test_children_receive_the_launchers_streams`, two `subTest` rows. With the variable set,
    a patched `run.subprocess.run` is called with the three streams; without it, with none of them, so
    a console start is unchanged.
  - *Invariant:* console starts are unchanged.

- [ ] **Step 4 — The process half of the extension, in plain Java**
  - *Files:* `burp/ServerProcess.java` (new); `tests/test_launcher.py`.
  - *What:* builds the command (the Python field, else the automatic choice) and runs it in the app
    folder. Adds `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8` and `VULNREPORT_STARTED_BY_BURP=1` to
    the environment and sets nothing else: no data folder, no port. Merges stderr into stdout and
    reads lines on its own thread. Takes the address from the address line. Treats the root process's
    exit (`onExit()`) as the end, never end of output. `stop()`: before the address line nothing is
    being served yet (setup, or the app importing), so force-stop; after it, close stdin.
    `forceStop()`: snapshot `descendants()` first, then `destroyForcibly()` each and the root.
    `stopWithin(Duration)`: `stop()`, wait, then `forceStop()`.
  - *Self-check:* `java burp/ServerProcess.java <app folder>` runs without compiling. It starts the app
    with a temporary `VULNREPORT_DATA_DIR` and a free `VULNREPORT_PORT`, waits up to 180 s for the
    address line (a first run installs packages), requests the address with no proxy, stops gracefully
    and expects exit code 0 within 15 s. Then it starts again, force-stops, and expects every process
    it saw to be gone and the port free. It exits non-zero on any failure.
  - *Test:* that self-check, on macOS now and on Windows in Step 7g. And
    `test_burp_launcher_uses_run_py_address_line_and_variable` in `tests/test_launcher.py`: it reads
    `burp/ServerProcess.java` and asserts that it contains the address line's fixed part and the
    variable name, both taken from `run` itself, never retyped. Rename either on one side and the suite
    fails.
  - *Invariant:* the extension never kills a process that was not the root, or one of its descendants
    when Stop was pressed. No kill by process name: that could end the tester's own Word or unrelated
    Python work. The self-check never touches the real `data/`.

- [ ] **Step 5 — The Burp tab**
  - *Files:* `burp/ReportGeneratorExtension.java` (new).
  - *What:* implements `BurpExtension`. `setName("Report Generator")`. The app folder is the parent of
    `api.extension().filename()`; without a `run.py` there, the tab says to load the JAR from the Report
    Generator folder and Start stays disabled. One suite tab (`registerSuiteTab`) in Burp's theme
    (`applyThemeToComponent`) with:
    - a status line: Stopped / Setting up / Running at `<address>` with **Open** / Stopping, waiting
      for a request to finish, for example a report being generated;
    - the Python field (blank means automatic), kept with `persistence().preferences()`;
    - **Start**, and **Stop**, which becomes **Force stop** while stopping;
    - an output area in Burp's editor font (`currentEditorFont()`), trimmed to the last 2,000 lines.
      Its first lines are the folder and the exact command.

    When the address line arrives, the tab opens the system default browser once (`Desktop.browse`).
    If the desktop cannot, it says so, and the address is in the status line to copy.
    `registerUnloadingHandler` calls `stopWithin` with 10 s, one named constant.
  - *Test:* this checklist, run once on macOS and once on Windows. Each line names the result that must
    be seen, so each can fail.
    1. Load the JAR from a release folder: a Report Generator tab appears.
    2. Load a copy from another folder: the message, and Start disabled.
    3. Start in a folder without `.venv`: setup output streams, then "Running at
       http://127.0.0.1:8765", and the default browser opens the home page.
    4. Edit a report and press Stop before the page says it has saved: the page shows "Save failed -
       Retry". Press Start: the same tab saves on its next retry or edit, with no restore prompt.
    5. Stop with nothing in progress: Stopped within a couple of seconds, and the port no longer
       answers.
    6. A second Burp window: Start while the first server runs is refused with the address, and no
       second server process appears.
    7. Unload the extension while running: the server process is gone within 10 s.
    8. Quit Burp while running: no Python process from this folder remains (Activity Monitor or Task
       Manager).
    9. Screenshot the tab in Burp's light and dark themes: the output is readable in both.
  - *Invariant:* the extension passes no data folder and no port of its own. Nothing is hidden: the
    command, folder and address are printed.

- [ ] **Step 6 — Release build and README**
  - *Files:* `scripts/package_release.py`; `README.md`.
  - *What:* the script downloads the Montoya API jar (`net.portswigger.burp.extensions:montoya-api`,
    a pinned version, from Maven Central) once into `dist/`, checks its SHA-256 against a pinned value,
    compiles `burp/*.java` with `javac --release <N>` where N matches that jar's class files, and
    writes `ReportGenerator-Burp.jar` into the staging folder beside `run.py`. It stops with a clear
    message when `javac` is missing, so a release never ships without the extension by accident. Pin a
    Montoya version no newer than the oldest Burp the testers run: a JAR built against a newer API can
    call methods an older Burp lacks. The README, which ships in the zip, covers: loading
    `ReportGenerator-Burp.jar` from the unzipped folder (Extensions, Add, type Java); Start, Stop and
    Force stop; "Start runs a local web server at http://127.0.0.1:8765, reachable only from this
    computer"; open it in your usual browser, not Burp's; one copy per folder; the step from
    question 4; `VULNREPORT_PORT`; and, if setup was interrupted and Start keeps failing, delete `.venv`
    and start again.
  - *Test:* run the script. `unzip -l dist/<name>.zip` lists `<name>/ReportGenerator-Burp.jar` and no
    `data/` or `generated/`. Load that JAR from an unzipped copy and repeat checklist lines 1 and 3.
  - *Invariant:* the zip still carries no drafts, evidence or finished documents, and the Montoya API
    jar is not in it (Burp supplies the API).

- [ ] **Step 7 — Check on Windows what reading code cannot settle**
  - *Files:* none. Record each result in this plan under this step.
  - *What:* on Windows with Word, from a release built in Step 6, with a scratch report only:
    - a. The server's output reaches the tab through `run.py`'s relaunch, and Stop ends every Python
      process with exit code 0. This is Step 3's reason.
    - b. Generate a real report from the Burp-started server: the `.docx` lands in `generated/` and
      Word's pass ran (the table of contents is filled in). This is the Word-adjacent risk from the
      framing; the document side is otherwise unexamined.
    - c. Force stop during a generation. Afterwards look in Task Manager for a hidden `WINWORD.EXE`
      still running, then generate again. If Word was left behind or the second generation fails,
      stop here and take it to the scribe. Do not add Word-killing to the extension.
    - d. Stop, then Start at once with the report's tab open: the server gets 8765 again, with no
      "address already in use" from connections still closing.
    - e. A console `run.py` started while the Burp-started server runs is refused: a second socket
      cannot share the port on Windows.
    - f. Open the address in Burp's own browser with a scratch report, and look in Proxy, HTTP history
      for `127.0.0.1:8765`. If it is there, report data would be recorded in whichever Burp project is
      open and Intercept would hold saves, so the README warning stays as written. If not, reduce the
      warning to the browser-profile reason.
    - g. `java burp/ServerProcess.java <release folder>` passes.
    - h. Quit Burp while a report is generating. If the document still appears in `generated/`, the
      server stopped gracefully. If the server vanished with Burp, Burp's exit kills its children:
      record that in DATA_MAP §3 as an outright kill at Burp exit.
  - *Invariant:* nothing here uses a tester's real drafts.

- [ ] **Step 8 — Close out**
  - *Files:* this plan (status `shipped`, date, commit, and what deviated);
    `.github/copilot-instructions.md` (one line: `burp/` is the Burp launcher, checked by
    `java burp/ServerProcess.java <folder>` and the checklist in Step 5); `docs/ARCHITECTURE.md`
    (a short paragraph on starting from Burp).
  - *Test:* `.venv/bin/python scripts/relevant_tests.py --affected --run`. For `run.py` it picks every
    Python module and no browser tests.
  - *Invariant:* the plan and the map describe what was built.

### What I would not do

- **Move drafts to a per-user folder while we are at it.** Setting `VULNREPORT_DATA_DIR` from the
  extension looks like one line, but copying drafts into the new folder is exactly where duplicates
  come from, and `generated/`, the library and `.venv` would still be tied to the release folder. It
  is question 4's option (c), and its own change.
- **An HTTP shutdown route.** It is one more route any web page could aim a request at, and its effect
  is to end the server. Closing stdin can only be done by the process that started the server.
- **Start `.venv`'s interpreter directly from Java.** One process instead of two, but it skips the
  requirements check, so a release with new requirements would start on old packages, and the `.venv`
  path rule would then exist in both Python and Java.
- **Kill by process name, or kill Word.** Ending `python.exe` or `WINWORD.EXE` by name can close the
  tester's own Word documents or unrelated Python work. The extension kills only the process it started
  and that process's descendants.
- **Bound uvicorn's graceful wait with `timeout_graceful_shutdown`.** It ends the wait, not the worker
  thread running the request, so a save in progress would be cut at an arbitrary instant with nobody
  choosing it. Force stop makes the same trade visibly, by the tester's hand.
- **Keep the port scan and read the address from uvicorn's "Uvicorn running on" log line.** That ties
  the extension to another project's log wording and keeps both port risks.
- **Serve the app inside Burp: in Burp's browser, as a page embedded in the tab, or through Burp's
  proxy.** Each one hides edits kept in the tester's usual browser, may record client data in a Burp
  project, and dresses the app up as part of Burp, which is the disguise question 1 rules out.

## Round 2 - Loremaster: verdict on the proposal

**Answer.** Nothing in the proposal moves a draft or changes what a draft records. Every `draft.json`
on disk still loads and every report is still found (§3). A fixed 8765 keeps the browser's recovery
drafts on the origin most of them were written under. One row of the Data risks table is wrong:
**Orphan reference is a risk, not clear.** Import and duplicate write `draft.json` before its PNGs, and
an outright kill skips their rollback. The stdin shutdown works on the installed uvicorn 0.52.4, but it
needs more than Step 2 names. Nothing reads stdin today. Dropping `uvicorn.run` also drops its Ctrl+C
guard. And the server stalls if nobody drains its output pipe. The blast radius misses
`.github/copilot-instructions.md`, `DATA_MAP.md` §1, the variable table in `ARCHITECTURE.md`, and two
variable names that the Java self-check shares with Python.

### 1. The Data risks table, row by row

| Row as proposed | Verdict | Evidence |
|---|---|---|
| Orphan reference, `clear` | **Wrong: RISK** | The row covers only the upload order (PNG first, then the draft). Import and duplicate run the other way. `import_report` saves `draft.json` and then writes each PNG ([app/workspace.py#L171-L179](app/workspace.py#L171-L179)), and `duplicate` does the same ([#L205-L213](app/workspace.py#L205-L213)). Both routes reach them ([app/main.py#L655](app/main.py#L655), [#L660](app/main.py#L660), [#L682](app/main.py#L682)). A kill between the two steps never reaches the `except` rollback, so the new report lists evidence ids, with fragments pointing at them, whose PNGs do not exist. Neither loading nor the readiness check notices: `generation_issues` checks that an image fragment has an `evidence_id`, not that a file exists ([app/docx_report.py#L141-L152](app/docx_report.py#L141-L152)). The image then 404s on the Content page ([app/main.py#L895-L896](app/main.py#L895-L896)). Generate returns 422 "Evidence file not found" ([app/docx_report.py#L1201-L1203](app/docx_report.py#L1201-L1203)). Export and Duplicate refuse with "Evidence file is missing" ([app/workspace.py#L193-L194](app/workspace.py#L193-L194)). Force stop, the unload deadline, and Burp's exit (if Burp's exit kills) can all cause it; a graceful Stop waits for the import to finish. To recover: delete that report and import the file again. |
| Rule drift, `RISK` | Right, but the contract is wider | It is more than "the address line and the variable name". The Step 4 self-check also names `VULNREPORT_DATA_DIR` and `VULNREPORT_PORT` in Java. `VULNREPORT_DATA_DIR` is a string literal in `app/main.py` ([#L37](app/main.py#L37)), not in `run`, so a test that takes names "from `run` itself" cannot pin it. If that name drifts, the self-check silently runs against the real `data/`. Importing `app.main` then creates the folder, writes `prefs.json` if it is missing, and opens the real error log ([app/main.py#L40](app/main.py#L40), [#L71-L82](app/main.py#L71-L82)). It reads no draft, because `GET /` renders the page without listing reports ([app/main.py#L443-L446](app/main.py#L443-L446)). The address line also matters for more than readiness. Step 4 force-stops until that line has been seen, so a drifted or unflushed line turns every Stop into an outright kill during normal use. |
| Second server on one data folder, `RISK` | Right, but only once the first server has bound | "The fixed port refuses the second start" is true only after the first server holds the port. The check sits at the start of `serve()`, which runs after `bootstrap()` and the relaunch ([run.py#L94-L99](run.py#L94-L99)). The bind comes only after `app.main` has been imported ([uvicorn/server.py#L87-L88](.venv/lib/python3.14/site-packages/uvicorn/server.py#L87-L88), [#L96](.venv/lib/python3.14/site-packages/uvicorn/server.py#L96)). A second Start during the first one's setup or import passes the check. It runs its own setup against the same `.venv`, imports `app.main` against the same data folder, and then loses the bind with exit code 3 ([uvicorn/server.py#L172-L183](.venv/lib/python3.14/site-packages/uvicorn/server.py#L172-L183)). No second server survives. The only data it can touch is `prefs.json` on a very first run, written through the fixed name `prefs.tmp` ([app/tester_identity.py#L198-L202](app/tester_identity.py#L198-L202)); both processes would write the same content. Step 5's checklist line 6 ("no second server process appears") cannot be met literally, because the second copy's processes start and then exit. |
| A port change hides unsaved edits, `RISK` | Right, with two additions | First, recovery drafts that today's scan already stored under ports 8766–8799 ([run.py#L74-L80](run.py#L74-L80)) become unreachable by default. They are not deleted, and they come back only if `VULNREPORT_PORT` is set to that port. Second, without the scan a leftover server no longer moves the port; it makes Start refuse. `VULNREPORT_PORT` becomes the only thing that changes the origin. If it is set where Burp can see it but not for a console start, or the other way round, one data folder is served under two origins. |
| Backup exhaustion, `RISK` | Right; the reasoning needs three corrections | (1) "A save takes milliseconds" is not always true. A save can wait on the report lock behind a generation's Word pass ([app/main.py#L521-L531](app/main.py#L521-L531), [app/workspace.py#L306-L312](app/workspace.py#L306-L312)), then start writing whenever that pass ends, so the unload deadline can land inside it. (2) `load_path` rewrites a legacy draft at the start of a generation, and also for every draft each time the home page lists reports: `list_reports` and `list_legacy_reports` both call it ([app/workspace.py#L119-L147](app/workspace.py#L119-L147), [#L297-L298](app/workspace.py#L297-L298)). (3) "Stop never kills" contradicts Step 4, where Stop before the address line is a force-stop. That kill does not harm drafts: before the bind, the process writes only `prefs.json` (through `prefs.tmp`) and opens the log ([app/main.py#L37-L82](app/main.py#L37-L82)); `Workspace()` touches no file ([app/workspace.py#L62-L67](app/workspace.py#L62-L67)). The one gap is the few milliseconds between the line being printed and the extension reading it, when a tab left open can already be saving. |
| Duplicates when drafts move, `RISK` | Right; there is one more way in | Under this design, the app folder is wherever Burp loads the JAR from, and `DATA` defaults to `<that folder>/data` ([app/main.py#L37](app/main.py#L37)). Suppose Burp keeps loading the JAR from the old release after `data/` was moved to the new one (whether Burp does that is outside my territory). Then Start serves the old folder, and importing `app.main` there creates an empty `data/` ([app/tester_identity.py#L198-L202](app/tester_identity.py#L198-L202), [app/main.py#L73](app/main.py#L73)). The tester sees no reports, and new work lands in a second store. |
| Stale write, `clear` | Right | A graceful stop still delivers the reply to a request that is already running. `shutdown()` closes the listener, closes only idle keep-alive connections, marks busy ones to close after their response, and waits with no time limit ([uvicorn/server.py#L272-L320](.venv/lib/python3.14/site-packages/uvicorn/server.py#L272-L320); [h11_impl.py#L341-L350](.venv/lib/python3.14/site-packages/uvicorn/protocols/http/h11_impl.py#L341-L350), [httptools_impl.py#L349-L356](.venv/lib/python3.14/site-packages/uvicorn/protocols/http/httptools_impl.py#L349-L356)). As the row says, the 409 against the tab's own write needs a kill. §4 point 4 adds one way a graceful stop turns into a kill. |
| Lost update, Silent stranding, Schema break, Request/response asymmetry, Navigation trap, Derived-state fight: all `clear` | Right | Nothing under `app/` changes. Every write still goes through `Workspace._locked` ([app/workspace.py#L73-L110](app/workspace.py#L73-L110)). No stored value holds a path or a port, so `load_path` needs no repair (§3). |
| A different browser hides unsaved edits, `RISK` | Right, as far as the repo goes | Recovery drafts belong to one origin and one browser profile ([app/web/static/app.js#L35](app/web/static/app.js#L35), [#L56-L57](app/web/static/app.js#L56-L57)). Today `run.py` opens the default browser ([run.py#L90](run.py#L90)). Which browser `Desktop.browse` opens is outside my territory. |
| Report data recorded in a Burp project; Word left running after a Force stop; Burp's exit kills the server outright | Outside my territory (Burp, Word, Windows process handling) | One repo fact for the last row. If Burp's exit only closes the pipes, the closed output pipe does not interrupt the graceful shutdown. uvicorn writes its output through `logging`, and a failed write to a closed stream is swallowed (CPython 3.14.7's `StreamHandler.emit` passes the error to `Handler.handleError`, which ignores `OSError`). The app itself prints only while it is being imported ([app/main.py#L46](app/main.py#L46), [app/tester_identity.py#L189](app/tester_identity.py#L189)). |

No row marked `RISK` is already handled by existing code.

### 2. Files the plan misses

| File | Why it has to change |
|---|---|
| [.github/copilot-instructions.md#L8-L9](.github/copilot-instructions.md#L8-L9) | It says `run.py` "serves `app.main:app` on the first free port 8765–8799". Step 1 makes that false. The plan touches this file only in Step 8, to add a line about `burp/`. |
| [docs/DATA_MAP.md#L40](docs/DATA_MAP.md#L40), §1 "Report data never ships" | It says the release zip holds `run.py`, `requirements.txt`, `README.md`, `app/` and `resources/` only. Step 6 adds `ReportGenerator-Burp.jar`. The plan's DATA_MAP edits name only §3, §13 and the verification line. |
| [docs/ARCHITECTURE.md#L172-L186](docs/ARCHITECTURE.md#L172-L186), Configuration | This table lists every `VULNREPORT_*` variable, so `VULNREPORT_PORT` and `VULNREPORT_STARTED_BY_BURP` would be missing. The plan edits only the uvicorn row ([#L24](docs/ARCHITECTURE.md#L24)) and adds a paragraph. Separately, [#L192-L194](docs/ARCHITECTURE.md#L192-L194) is already wrong today. It says the library loader "falls back to `resources/vuln_library.json`, creating the directory and seeding the file". The loader does neither; it serves an empty library ([app/library.py#L71-L79](app/library.py#L71-L79)), which DATA_MAP §1 already says correctly. |
| `tests/test_launcher.py`, Step 4's pin | The file is in the plan, but the pin as written covers two of the four names shared with Java (see the Rule drift row). |

These were checked and need nothing:

- Page templates, `app.js`, `manager.js` and `diagnostics.js` hold no text that names the console, `run.py`, a port or a restart (searched `app/web/`).
- The Content page's message about the "generated" folder ([app/web/static/app.js#L878](app/web/static/app.js#L878)) stays true, because `generated/` does not move.
- `tests/test_browser.py` binds its own free port and never runs `run.py` ([#L58-L62](tests/test_browser.py#L58-L62)).
- `docs/ROUTES.md`, the local `CLAUDE.md` and `.vscode/` mention no port.
- `scripts/generate_showcase_reports.py` is unaffected.
- [README.md#L14](README.md#L14) ("Close the console window") and [scripts/package_release.py#L19-L23](scripts/package_release.py#L19-L23) are already in the plan.

### 3. Existing drafts, and finding reports again

**No `draft.json` breaks.** No field, validator or `load_path` repair changes, and nothing stored holds a
path or a port:

- `_folder_name_hint` holds folder names only.
- `evidence.file` must be relative ([app/models.py#L341-L342](app/models.py#L341-L342)).
- The `library_path` in `prefs.json` is relative (`resources/vuln_library.json`).
- Lock files are named by a hash of the report id ([app/workspace.py#L88](app/workspace.py#L88)).

A read-only recount of `data/` matches Round 1: 14 `draft.json`, 8 `draft.bak.json`, 13 PNGs, 76 lock
files, no stray `.tmp` file, and no absolute path in any draft. Finding a report depends only on `DATA`
and the scan two levels below `apps/` ([app/main.py#L37](app/main.py#L37),
[app/workspace.py#L243-L251](app/workspace.py#L243-L251)); the port plays no part. Under choice 2(a),
the extension sets no data variable and starts in the app folder, and `relaunch()` sets `cwd=ROOT`
([run.py#L69](run.py#L69)). So a Burp start and a console start of one release serve the same `data/`.

**What a fixed default port does to the browser's local drafts.** The keys belong to one origin:
`vulnreport-pending:…`, `vulnreport-saved-at:…`, `vulnreport-recovery:…` and `vr-theme` (Round 1 §4).

- With 8765 fixed, console and Burp starts share one origin, so each offers the recovery drafts the other
  wrote.
- After an upgrade, drafts the old release left in the browser are offered again once `data/` has been
  moved into the new release. The keys carry the `report_id`, and the move keeps it.
- Drafts under 8766–8799 are left unreachable by default (Port-change row above).
- The host must be the literal `127.0.0.1` wherever the extension opens or prints the address, because
  `localhost` is a different origin ([run.py#L87](run.py#L87)).

**What question 4's move (a) does to the files beside `apps/`:**

- `prefs.json` moves whole.
  - The tester name is kept, not resolved again ([app/tester_identity.py#L193-L196](app/tester_identity.py#L193-L196)).
  - The relative `library_path` is resolved against the new release folder at import
    ([app/main.py#L42-L44](app/main.py#L42-L44)), so the new release's library is the one read.
  - Only a hand-edited absolute path would keep pointing into the old folder. If that folder were then
    deleted, the app would start with an empty library. It reports that only in its startup output
    ([app/library.py#L71-L79](app/library.py#L71-L79), [app/main.py#L45-L46](app/main.py#L45-L46)),
    which under this plan is the Burp tab.
  - The undeclared `defaults` key moves along untouched.
- `.locks/` moves and does nothing. The lock is held on the open file handle, not on the file itself
  ([app/workspace.py#L89-L100](app/workspace.py#L89-L100)), so no lock survives a stopped server. The 76
  files could equally be left behind.
- The error logs move. The new server opens `vulnreport-errors.log` for appending when it is imported and
  keeps rotating it ([app/main.py#L71-L82](app/main.py#L71-L82)). The label shown in error panels stays
  the relative `data/vulnreport-errors.log`, because `DATA` stays inside the app folder
  ([app/main.py#L67](app/main.py#L67)).
- The order of the steps matters, for two reasons the source shows:
  - A running server holds the error log open for its whole life ([app/main.py#L76](app/main.py#L76)),
    so stopping the old app first is required, not just advice. What Windows does when moving a folder
    that contains an open file is outside my territory. But a move that ends as a copy is exactly how
    duplicates appear.
  - A Start in the new folder before the move creates a fresh `data/` holding `prefs.json` and the log
    ([app/tester_identity.py#L198-L202](app/tester_identity.py#L198-L202), [app/main.py#L73](app/main.py#L73)).
    Replacing or merging that folder loses nothing unless reports were already created there. If the
    incoming folder ends up under another name, it is not scanned. Its reports are not lost; renaming
    the folder brings them back.
- Moving `generated/` in is safe. `unused_export_path` numbers a clashing name instead of overwriting
  ([app/main.py#L544-L551](app/main.py#L544-L551)).

If a per-user folder is chosen later (question 2(b) or 4(c)):

- `prefs.json`, `.locks/`, `apps/` and the logs follow `VULNREPORT_DATA_DIR`. `generated/` and the
  library do not ([app/main.py#L37-L44](app/main.py#L37-L44)).
- The label in error panels becomes an absolute path ([app/main.py#L67](app/main.py#L67)).
- A relative value is read against the process's working directory.
- Any start that does not set the variable, such as a console `run.py`, serves `<app>/data`, which is a
  second store.

### 4. The mechanism claims, checked in source

1. **Closing stdin to stop.**
   - Nothing reads stdin today: not `run.py`, not `app/` (searched), and not uvicorn when it runs as one
     process. uvicorn touches stdin only to hand it to reload or worker processes
     ([uvicorn/_subprocess.py#L36-L48](.venv/lib/python3.14/site-packages/uvicorn/_subprocess.py#L36-L48)).
   - So Step 2 has to add both halves: a thread that reads `sys.stdin` to end of file, and a handle on the
     `Server` object so the thread can set `should_exit`. That means replacing `uvicorn.run`
     ([run.py#L91](run.py#L91)).
   - Setting `should_exit` from another thread is what uvicorn's own signal handler does
     ([uvicorn/server.py#L342-L347](.venv/lib/python3.14/site-packages/uvicorn/server.py#L342-L347)).
     The main loop checks it every 0.1 s ([#L233-L263](.venv/lib/python3.14/site-packages/uvicorn/server.py#L233-L263))
     and then runs the graceful `shutdown()` from the Stale write row. `timeout_graceful_shutdown`
     defaults to `None` ([uvicorn/config.py#L231](.venv/lib/python3.14/site-packages/uvicorn/config.py#L231)).
   - This repo already stops a server exactly this way. The browser-test harness builds
     `uvicorn.Server(uvicorn.Config(...))`, waits on `server.started`, and stops it by setting
     `should_exit = True` from another thread ([tests/test_browser.py#L62-L71](tests/test_browser.py#L62-L71)).
   - No signal is involved, so `run()` returns normally and exit code 0 holds.
2. **What dropping `uvicorn.run` changes.**
   - `uvicorn.run` wraps `server.run()` in `except KeyboardInterrupt: pass`
     ([uvicorn/main.py#L611-L629](.venv/lib/python3.14/site-packages/uvicorn/main.py#L611-L629)).
     Called alone, `Server.run()` has no such guard. After Ctrl+C has triggered a graceful shutdown, it
     sends the captured SIGINT again ([uvicorn/server.py#L336-L340](.venv/lib/python3.14/site-packages/uvicorn/server.py#L336-L340)).
     So unless `serve()` catches `KeyboardInterrupt`, every Ctrl+C in a console start ends with a
     traceback. Step 2's promise that a console start keeps its Ctrl+C behaviour depends on that one
     `except`.
   - The browser tests never show this, because they run the server off the main thread, where uvicorn
     skips signal capture ([#L325-L327](.venv/lib/python3.14/site-packages/uvicorn/server.py#L325-L327)).
   - The early exits are covered either way. A failed app import or a failed bind already exits with
     code 3 inside `load_app` and `startup`
     ([uvicorn/config.py#L425-L431](.venv/lib/python3.14/site-packages/uvicorn/config.py#L425-L431),
     [uvicorn/server.py#L180-L183](.venv/lib/python3.14/site-packages/uvicorn/server.py#L180-L183)).
3. **`Server.started` is set only after `create_server` succeeds.** Confirmed
   ([uvicorn/server.py#L172-L196](.venv/lib/python3.14/site-packages/uvicorn/server.py#L172-L196)). So a
   `startup` subclass that prints once `super().startup()` returns prints only after the bind.
4. **The output pipe must keep draining.**
   - uvicorn writes one access-log line per response from the event-loop thread. It does this inside
     `send()`, before the response goes out
     ([httptools_impl.py#L463-L491](.venv/lib/python3.14/site-packages/uvicorn/protocols/http/httptools_impl.py#L463-L491)),
     through a handler on `sys.stdout` ([uvicorn/config.py#L102-L106](.venv/lib/python3.14/site-packages/uvicorn/config.py#L102-L106)).
   - Its other messages go to `sys.stderr` ([#L97-L101](.venv/lib/python3.14/site-packages/uvicorn/config.py#L97-L101)),
     which the extension merges into the same pipe.
   - A write to a full pipe blocks. If the extension stops reading, the whole server stops once the OS
     pipe buffer fills. Every response waits, including one for a save whose draft is already on disk.
   - A graceful Stop cannot act either, because the same blocked loop is the only thing that reads
     `should_exit`. That leaves Force stop, which gives Round 1 §2's "saved on disk, reply lost" outcome:
     a 409 against the tab's own write.
   - So the Java reader thread must never wait on Burp's UI. How Burp's UI thread behaves is outside my
     territory.
5. **Handles on Windows (Step 3).** The CPython half is right. When no stream is passed, `subprocess` on
   Windows hands over no standard handles and starts the child with handle inheritance switched off
   (CPython 3.14.7 `subprocess.py`, lines 1354–1355, 1490–1495 and 1556). What the child then gets
   instead is Windows behaviour, outside my territory. Passing the three streams explicitly makes CPython
   hand them over.
6. **Test selection (Step 8).** Confirmed. A path under `burp/` matches no rule and is listed under "No
   rule for these — decide by hand" ([scripts/relevant_tests.py#L310-L312](scripts/relevant_tests.py#L310-L312),
   [#L376](scripts/relevant_tests.py#L376)), and still runs every Python module
   ([#L303](scripts/relevant_tests.py#L303)). `run.py` maps to no browser test ([#L61](scripts/relevant_tests.py#L61)).
   The Step 2 tests inherit the temporary data folder, because `tests/__init__.py` sets it in
   `os.environ` itself ([#L10-L13](tests/__init__.py#L10-L13)).
7. **Why not `timeout_graceful_shutdown`, from "What I would not do".** The rejection stands, but for a
   different reason than the one given.
   - When the limit runs out, uvicorn cancels the waiting task
     ([uvicorn/server.py#L292-L298](.venv/lib/python3.14/site-packages/uvicorn/server.py#L292-L298)).
     The save itself runs in an anyio worker thread
     ([starlette/concurrency.py#L32-L34](.venv/lib/python3.14/site-packages/starlette/concurrency.py#L32-L34)).
     That thread is created without `daemon=`
     ([anyio/_backends/_asyncio.py#L1047-L1057](.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py#L1047-L1057)),
     so it takes its daemon setting from the event-loop thread, which here is the main thread and is not
     a daemon.
   - Python waits for non-daemon threads before exiting, so the save's write finishes rather than being
     cut at an arbitrary instant.
   - What the cancellation costs is the reply. Whether any reply still reaches the browser was not
     established.
8. **Outside my territory:**
   - the Montoya calls, and whether the unloading handler runs when Burp exits;
   - `Process.supportsNormalTermination()` and `destroy()` on Windows;
   - whether `py.exe` and the venv's `python.exe` add processes to the tree;
   - Windows port-reuse rules (Steps 7d and 7e);
   - Burp's proxy and built-in browser;
   - what Word does when the process driving it is killed;
   - whether Burp keeps an extension's file path across an upgrade.

### Invariants in play

- **Every read-modify-write goes through `Workspace._locked`.** This does not change, and it is what makes
  the second start that loses the bind harmless.
- **The reply must reach the browser for `saved_at` to stay in step.** The graceful path delivers it. A
  kill does not, and neither does a stalled output pipe (§4 point 4).
- **Never discard user content without a prompt.** After a stop, recovery drafts are the only copy of
  unsaved edits, and they belong to one origin. The fixed port keeps the main origin, and
  `VULNREPORT_PORT` becomes the only thing that moves it.
- **An existing `draft.json` must still load.** Nothing stored depends on the port or on where the folder
  sits.
- **Tests never touch real data.** The Python tests are protected by `tests/__init__.py`. The Java
  self-check is protected only by typing the variable name correctly.

### Both-sides warning

No rule shared between Python and JavaScript is involved. The contract between Python and Java has four
names, not two:

- the address line's fixed text, in `run.py`;
- `VULNREPORT_STARTED_BY_BURP`, in `run.py`;
- `VULNREPORT_PORT`, in `run.py`;
- `VULNREPORT_DATA_DIR`, a literal at [app/main.py#L37](app/main.py#L37).

The Java self-check sets the last two. All four must change on both sides together.

### Map drift

In `docs/DATA_MAP.md` §13, the entry on import being rollback-protected now covers `duplicate` as well.
It also records what a kill between the draft and its PNGs leaves behind, and where that shows up. The
"Latest verification" line now mentions it. Apart from that, the source did not contradict the map. The
error in `docs/ARCHITECTURE.md` about the library fallback (§2 above) is not mine to edit; the plan
already edits that file.

## Round 2 - Tactician: revised plan

### What changed after the loremaster's verdict

- **Import and duplicate write a new report's images before its draft.** This is a new Step 1 and
  the one change under `app/`. Today both write `draft.json` first and the PNGs after it, and a
  server killed between the two never reaches the rollback. What it leaves is a report that looks
  whole: its images fail to load on the Content page, Generate returns 422, and Export and Duplicate
  refuse it. With the PNGs written first, a kill leaves a folder with no `draft.json`, which nothing
  lists. A console Ctrl+C can already cause this today, because the parent `run.py` kills the server
  a quarter of a second after Ctrl+C. So the step stands on its own and does not wait for
  question 1.
- **Stop is graceful at every stage.** The proposal killed the process when Stop was pressed before
  the address line had been seen. That let one printed line decide between a graceful stop and a
  kill, so a reworded or unflushed line would have turned every Stop into a kill. Stop now always
  closes the server's standard input. Pressed during setup, it lets setup finish, and the server
  exits as soon as it has started: uvicorn 0.52.4 binds, sees the exit request, skips serving and
  shuts down (`Server._serve`). The address line now only sets the status line and opens the browser.
- **Unloading the extension no longer kills the server after 10 seconds.** Nobody chose that kill,
  and it could land in a save queued behind a report generation. The unloading handler now closes
  the server's input and returns. The server exits by itself once its running requests finish.
  Only two kills remain: Force stop, pressed by the tester, and Burp's own exit if Burp turns out to
  end its child processes (Step 8h).
- **Two names cross from Python into Java, not four.** Java contains the address line's fixed text
  and `VULNREPORT_STARTED_BY_BURP`, and a test pins both. `VULNREPORT_DATA_DIR` and
  `VULNREPORT_PORT` never appear in Java. A Python test runs the Java self-check, which inherits
  both from that test's environment, where `tests/__init__.py` already sets the data folder for
  every test.
- **The Java side reads the server's output all the time, and the reading thread never calls Burp's
  UI.** A full pipe stalls the whole server, including the reply to a save that is already on disk,
  and leaves only Force stop. Lines go into a buffer that the Java process object owns, and the tab
  copies that buffer on a timer. The self-check proves that about 200 KB of output that nobody reads
  does not stall the server.
- **`run.py` gains two pieces of new code the proposal understated.** One is a thread that reads
  standard input to its end; nothing reads standard input today. The other is an
  `except KeyboardInterrupt` around `Server.run()`. `uvicorn.run` used to provide that guard, and
  without it every console Ctrl+C would end in a traceback.
- **A second Start before the first server is listening is now described as it happens.** It passes
  the port check, runs setup and imports the app, then fails to bind and exits. No second server
  survives, but on a first run both can install packages into the same `.venv` at once. The checklist
  line that promised "no second server process appears" now names what can actually be seen.
- **Files the proposal missed now sit in the steps that make them wrong:**
  - Step 2: the start line in `.github/copilot-instructions.md`, and the Configuration table and
    library-fallback lines in `docs/ARCHITECTURE.md`. The library-fallback lines are already wrong
    today.
  - Step 7: `docs/DATA_MAP.md` §1, on what the release zip contains.
  - Step 1: `app/workspace.py`, `tests/test_app.py`, and `docs/ROUTES.md`, whose import passage
    says "JSON is written before PNGs".
- **The upgrade order is spelled out, in question 4 and the README:** stop the old app, remove the
  old extension from Burp, move `data` into the new folder before its first Start, then add the new
  JAR. Otherwise Burp keeps loading the old release's JAR, which then serves an empty `data/`. Unsaved
  browser edits kept under ports 8766–8799 get a README paragraph on how to get them back.

### Understanding

The tester loads one small Java file into Burp. It adds a **Report Generator** tab with:

- a terminal-style output area;
- a status line that names the folder being served and the address;
- Start and Stop buttons.

Start runs the existing app the way `py -3 run.py` does today. The tester's own Python 3 creates or
updates `.venv`, the same FastAPI server starts on `127.0.0.1:8765`, and the tester works in their
usual browser. Stop asks the server to finish what it is doing and exit. Force stop is offered only
while that wait lasts, and ends the server at once.

The app is not moved into Burp, and nothing about it is hidden. Python must still be installed, the
process list still shows a Python web server, and the tab prints the command it ran, the folder it
serves and the address.

What changes:

- how the server is started, stopped and found (`run.py` and the new Java code);
- which port it listens on;
- how a release is built;
- how a tester's drafts reach the new release folder.

One change reaches `app/`: import and duplicate write a new report's images before its draft
(Step 1). No field, route, page or Word output changes.

**The Word side is unexamined.** There was no scribe round, because the document itself does not
change. One environmental risk remains: Word automation running under a Python process that Burp
started. Step 8b settles it by generating a real report on Windows through the extension.

### Blast radius

| File | What changes |
|---|---|
| `app/workspace.py` | Step 1. `import_report` and `duplicate` hand their PNGs to the save. The save writes them into the folder it chose for the new report, then writes `draft.json`. The folder is chosen once. An ordinary exception still removes the new folder, as now. |
| `tests/test_app.py` | Step 1's test, in `ReportApiTests` beside the existing `import_report` tests. |
| `run.py` | Steps 2–4. Port 8765, with `VULNREPORT_PORT` as the override. When something already answers on that port, `run.py` refuses to start and names the address; this replaces `free_port`. `serve()` builds `uvicorn.Server` itself and prints the address line, flushed, only after the bind; a console start then opens the browser. When `VULNREPORT_STARTED_BY_BURP=1`: a thread reads standard input to its end and then asks the server to exit; no browser opens; "Close this window…" is not printed; and the setup and relaunch child processes get the launcher's three standard streams. In every mode, `except KeyboardInterrupt` wraps `Server.run()`. |
| `burp/ServerProcess.java` (new) | Step 5. JDK only. Starts `run.py`; drains merged output into its own bounded buffer; reads the address from the address line; stops by closing standard input; force-stops the process tree on request. Holds a `main` self-check. |
| `burp/ReportGeneratorExtension.java` (new) | Step 6. The Montoya entry point: the tab, the Python field, the buttons, and a UI timer that polls `ServerProcess`. Its unloading handler closes the server's input and returns. |
| `tests/test_launcher.py` (exists, holding `BootstrapDecisionTests`) | Steps 2–5. Checks: the port refusal; the address line printed after the bind; end of input stopping only a server started by Burp; a clean console Ctrl+C; child processes receiving the launcher's streams; the Java self-check; the two names shared with Java. |
| `scripts/package_release.py` | Step 7. Compiles `burp/*.java` against a pinned, hash-checked Montoya API jar, and puts `ReportGenerator-Burp.jar` at the root of the zip. |
| `README.md` | Step 7. Loading the extension; Start, Stop and Force stop; what runs and where; using the usual browser; one copy per folder; the upgrade order; `VULNREPORT_PORT`; unsaved changes kept under 8766–8799; a broken `.venv`. |
| `docs/DATA_MAP.md` | §13 import entry (Step 1). §13 port and two-server entries (Step 2). §3, how a stop reaches a save (Step 3). §1, the release zip's contents (Step 7). The verification line at the top, each time. |
| `docs/ROUTES.md` | Step 1. The import passage says "JSON is written before PNGs", which Step 1 reverses. |
| `docs/ARCHITECTURE.md` | Step 2: the uvicorn row ("picks a free port on startup so several copies can run side by side"). The Configuration table gains `VULNREPORT_PORT`, noting that `run.py` reads it, not `app/main.py`. The library-fallback lines are corrected to what `Library.load_or_empty` does: an empty library and a startup message, with no fallback and no seeding. Step 3: the table gains `VULNREPORT_STARTED_BY_BURP`. Step 9: a paragraph on starting from Burp. |
| `.github/copilot-instructions.md` | Step 2: the Start line's "first free port 8765–8799". Step 9: one line for `burp/`. |
| Not touched | `app/` apart from `workspace.py`; `app/web/`; `resources/`; the schema; `scripts/relevant_tests.py`. A change under `burp/` lands in that script's "No rule for these — decide by hand" list, and `--affected` still runs every Python module. By hand, the answer is `tests.test_launcher`. |

**Both sides.** No rule is added in both Python and JavaScript. Two names cross from Python into Java:
the address line's fixed text and `VULNREPORT_STARTED_BY_BURP`. Both are module constants in
`run.py`, and Step 5 pins them.

### Open questions

Four decisions wait on you, most consequential first. Each can be answered on its own. Questions 2, 3
and 4 gained facts from the loremaster's verdict. Question 1 is unchanged.

**1. Does the company rule allow what this extension actually runs?**

- *Background.* The request describes the extension as a way around a company rule against web
  apps. The extension does not change what runs. Start launches the same Python web server, on this
  computer only (`127.0.0.1`, unreachable from other machines, as today). The first Start still
  installs the same Python packages from the internet. Drafts and evidence are stored in the same
  folder. The tester still works in a browser. Only the button that starts it moves. So whether this
  meets the rule depends on what the rule protects against: network exposure, unapproved software or
  packages, where client data is kept, or the kind of tool. None of those change, and only the rule's
  owner can say which one it is.
- *Options.*
  - (a) Ask the rule's owner before anything is built, describing it plainly: "a Burp extension that
    starts a local Python web server on 127.0.0.1 and opens it in the browser".
  - (b) Build it and ask afterwards.
  - (c) Build it and do not ask.
- *Trade-offs.* (a) costs one conversation and may end in a no, which saves the whole build. (b) and
  (c) risk you being in breach of a rule with a tool that is still, visibly, a web app: the process
  list shows a Python server, now started by Burp.
- *Recommendation.* (a). Whatever the answer, this plan does not hide or disguise the server. The tab
  prints the command, the folder and the address, and the README says what runs.
- *Why it matters.* It decides whether the extension should be built at all.
- *Absent an answer.* The plan stays at `planning`, and I would not start Step 2. Step 1 fixes a gap
  in today's app, not in the extension, and can go ahead either way.

**2. Should the extension be a small launcher kept inside the Report Generator folder, or one file
that carries the whole app?**

- *Background.* Burp runs extensions on Java; Python inside Burp means Python 2.7 through Jython. So
  the extension is a small Java file, a JAR, that starts the existing Python app. That app is a
  folder: Python code, page templates, Word templates, and the vulnerability library.
- *Options.*
  - (a) **Launcher inside the folder.** The release zip gains one file, `ReportGenerator-Burp.jar`.
    Testers unzip the release as today and load that JAR into Burp from the unzipped folder. It
    starts the `run.py` beside it, and drafts stay in that folder's `data/`, where they are today.
  - (b) **Everything inside the JAR.** One file to load. On Start, the JAR unpacks the app into a
    per-user folder and runs it from there.
- *Trade-offs of (a).* It needs no unpacking code and moves no data. Its costs:
  - The JAR must stay in the folder.
  - Burp keeps each extension's file path and loads it from there on every start. After an
    upgrade, the tester must remove the old extension in Burp and add the new folder's JAR. If they
    forget, Burp keeps starting the old release. Once the drafts have been moved out of it, that
    release starts with an empty `data/`, and new work collects there. The tab names the folder it
    serves, which is how the slip shows.
- *Trade-offs of (b).* It is one file, but it has four costs:
  - Drafts could no longer live beside the app, because each new version would unpack over them.
    They would move to a separate per-user folder. Finished documents would move too, which needs an
    app change, because `generated/` has no setting today.
  - Every tester's existing drafts would be copied there once, which is the step where duplicate
    reports appear.
  - An old copy of the extension still loaded would open and save those same drafts with older code.
    The app drops fields its models do not declare (`app/models.py` sets no `extra`), so older code
    that saves a newer draft writes it back without them. `docs/DATA_MAP.md` §13 records this for
    imports, and opening a draft behaves the same way.
  - It puts the Python server out of sight inside a Burp extension, which is the wrong direction
    given question 1.
- *Recommendation.* (a).
- *Why it matters.* (b) turns this into a data-migration change.
- *Absent an answer.* (a), which the steps below assume. If the answer is (b), I would re-plan from
  the data folder up rather than patch these steps.

**3. Should the app always use port 8765, instead of taking the first free port?**

- *Background.* Today `run.py` takes the first free port from 8765 to 8799, and
  `docs/ARCHITECTURE.md` presents that as letting several copies run side by side. The browser keeps
  unsaved edits, undo history and the light or dark choice per address, and the port is part of the
  address. If the app comes back on 8766, edits the browser kept under 8765 are not offered. They are
  not deleted; they come back only when the app is served on 8765 again. Starting from Burp makes a
  moved port likelier. Testers often run two Burp windows, one per client, and each would have the
  tab. If both are started, two servers share one data folder. On Windows, while one of them
  generates a report, the other shows that report as needing repair until the generation ends.
  Nothing is lost.
- *Options.*
  - (a) **Always 8765**, with `VULNREPORT_PORT` to override. A second start stops with "already
    running at http://127.0.0.1:8765".
  - (b) **Keep the scan, and add a lock in the data folder**, so a second copy on the same folder
    refuses to start, while copies of different folders can still run side by side.
  - (c) **Keep today's scan.**
- *Trade-offs of (a).* It is a few lines, and it removes both risks once the first server is
  listening. It has three costs:
  - Running two copies side by side needs the override. If another program already owns 8765, the
    tester sets `VULNREPORT_PORT` as a Windows user environment variable, so that Burp (after a
    restart) and console starts see the same value. If it is set for only one of them, the same
    drafts are served under two addresses, each keeping its own unsaved edits.
  - Unsaved edits the browser kept under 8766–8799, from times two copies ran at once, are no
    longer offered by default. They come back if the app is started once with `VULNREPORT_PORT`
    set to that port; the README explains how.
  - The refusal works only once the first server is listening. A second Start during the first
    one's setup or startup passes the check, runs setup, imports the app, then fails to bind and
    exits. No second server survives, but on a first run both can install packages into the same
    `.venv` at once, which can leave it broken until it is deleted. No report data is involved.
- *Trade-offs of (b).* It keeps side-by-side copies of different folders. Taken at the very start of
  `run.py`, it would also close that setup window. But it needs a lock taken without waiting, on
  both Windows and macOS, held for the server's whole life. It needs a file recording the address,
  so the refusal can name it. And the port still moves whenever another program holds 8765.
- *Trade-offs of (c).* It costs nothing and keeps both risks.
- *Recommendation.* (a), for console starts as well. Otherwise a console `run.py` started after
  Burp's server would take 8766 and share the data folder.
- *Why it matters.* It decides whether an ordinary restart can hide a tester's unsaved edits.
- *Absent an answer.* (a), in Step 2. The extension reads the address from the server's own line
  and never assumes 8765, so every other step holds whatever the answer.

**4. How should a tester bring existing drafts into the new release folder?**

- *Background.* The extension arrives in a new release, and each release unzips into a new folder
  whose `data/` is empty. Drafts in the old folder are not lost, only not shown. That is already
  true of every upgrade, and the README has no step for it. The app finds a report by scanning
  `data/apps/<app>/<report>/draft.json`, and nothing inside `data/` records an absolute path, so
  moving the whole `data` folder is enough. Three things can go wrong:
  - The same report twice in one `data/` (copied twice, or two folders merged) is listed twice,
    and only one copy can be opened.
  - A copy left in the old folder becomes a second, separate store if the old release is started
    again. From the second extension release onward, Burp does exactly that, unless the old
    extension is removed from Burp. That old release then creates an empty `data/`, and new work
    lands there.
  - A running server keeps its error log open. Moving `data` while the old app runs can end as a
    copy, which is how duplicates appear.
- *Options.*
  - (a) **A README step, in this order:**
    1. Stop the old app.
    2. In Burp, remove the old Report Generator extension.
    3. Move (not copy) the old `data` folder into the new release folder before pressing Start there.
       Move `generated` too, to keep earlier documents alongside.
    4. Add the new folder's `ReportGenerator-Burp.jar`.
    5. Press Start, and check that the tab names the new folder.
  - (b) **The extension finds the old folder and moves `data` itself.**
  - (c) **Keep drafts in a per-user folder outside any release from now on**, so no future upgrade
    strands them.
- *Trade-offs.*
  - (a) is no code, and relies on the tester following the order. The tab naming its folder catches
    the likeliest slip.
  - (b) is code that touches every tester's drafts, runs once, and is hard to test against real data.
  - (c) fixes upgrades for good, but it is its own change. The extension would set
    `VULNREPORT_DATA_DIR`, `generated/` would need a setting of its own, and each tester would move
    their drafts once. A console start that does not set the variable would serve a second store.
    An old release still loaded would open and save the same drafts with older code, which drops
    fields that code does not know.
- *Recommendation.* (a) now; (c) as its own plan, if stranded drafts keep coming up.
- *Why it matters.* This is the one point in the change where a tester's reports could be duplicated
  or split between two folders.
- *Absent an answer.* (a), in Step 7.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new route, and no change to what carries `saved_at`. A graceful stop still delivers the reply to a running request, as the loremaster checked in uvicorn's `shutdown()`, and Stop is now graceful at every stage. Only two things make a tab get a save conflict against its own saved change. One is a kill: Force stop, or Burp's exit if Burp kills its children. The other is a stalled output pipe, which Step 5 prevents by draining it continuously. |
| Lost update | clear | Step 1 changes the order of the writes inside `import_report` and `duplicate`, under the same locks as today. Nothing new reads and then writes a report outside `Workspace._locked`. |
| Orphan reference | RISK, fixed by Step 1 | Today import and duplicate write `draft.json` and then the PNGs, and a kill between the two skips the rollback. The new report is left listing evidence ids that have no file: its image fails to load on the Content page, Generate returns 422, and Export and Duplicate refuse it. A console Ctrl+C can already cause this today. Through the extension, Force stop or Burp's exit can. Step 1 writes the PNGs first, so a kill leaves a folder with PNGs and no `draft.json`, which no scan lists. Nothing sweeps that folder, just as nothing sweeps the stray `.tmp` files a kill already leaves; it costs disk space only. |
| Silent stranding | clear | Scope and environments are untouched. |
| Schema break | clear | No field changes. Step 1 changes the write order only. The data folder does not move, and nothing stored holds a path or a port, so `load_path` needs no repair. |
| Request/response asymmetry | clear | No request or response changes. |
| Rule drift | RISK | Two names cross from Python into Java: the address line's fixed text and `VULNREPORT_STARTED_BY_BURP`. Step 5's test pins both against `run`'s own constants, and fails if `VULNREPORT_DATA_DIR` or `VULNREPORT_PORT` ever appears in Java; the self-check takes both from the test's environment. A drifted address line can no longer turn Stop into a kill, because Stop never depends on it. It would only leave the status at "Setting up" and the browser unopened, which the self-check and Step 6's checklist line 3 catch. |
| Navigation trap | clear | No page gate changes. |
| Derived-state fight | clear | `provision_report` is untouched. |
| Backup exhaustion | RISK | A kill between a save's two file replacements leaves `draft.bak.json` equal to `draft.json`, so the one backup is used up. Only Force stop and Burp's exit (if Burp kills its children) can cause it now: Stop is graceful even before the address line, and unloading no longer kills. Two windows remain exposed. A save queued behind a generation's Word pass writes when the pass ends, so a Force stop pressed while the tab waits on a generation can land in that write. And whenever the home page lists reports, `load_path` rewrites any legacy draft that needs repair, backup included, until it has been repaired once. Both windows last milliseconds. |
| A port change hides unsaved edits | RISK | Unsaved edits, undo history and the theme are kept per address. Step 2 fixes the port for Burp and console starts alike, so `VULNREPORT_PORT` is the only thing that moves it. The README says to set it as a user environment variable, so both kinds of start see the same value. A stopping server closes its listener first, so it never holds 8765 against the next Start. Edits kept under 8766–8799 by today's port scan are not offered by default; the README says how to get them back. Depends on question 3. |
| Second server on one data folder | RISK | Once the first server is listening, a second start is refused with the address. Before that, during setup or startup, a second start passes the check, runs setup against the same `.venv`, imports the app against the same data folder, fails to bind and exits with code 3. No second server survives, and the only file both write is `prefs.json` on a very first run, with the same content. Two first-run setups at once can break `.venv`; no report data is involved, and the README says to delete it. After a Stop, uvicorn closes its listener before waiting for running requests, so a console start or another Burp window can bind 8765 while the old process finishes a generation. On Windows, that one report shows as needing repair until the generation ends (`docs/DATA_MAP.md` §13). A different `VULNREPORT_PORT` reopens the risk fully, so the README says to run one copy per folder. |
| A different browser hides unsaved edits | RISK | Unsaved edits belong to one browser profile and one origin. The extension opens the system default browser at the address exactly as printed, with the literal `127.0.0.1`, never `localhost`. |
| Server stalls when its output is not read | RISK, prevented by Step 5 | uvicorn writes an access line for each response, from the event loop, before the response goes out. A full pipe blocks the loop, so every reply waits, including the reply for a save already on disk, and a graceful Stop cannot act. Step 5's reader thread waits on nothing but the pipe. The self-check sends about 200 KB of output that nobody reads, and expects every request answered. |
| Report data recorded in a Burp project | RISK, unverified | If Burp's browser sends `127.0.0.1` traffic through Burp's proxy, every save's JSON and every evidence image would enter Proxy history and the open project file, possibly another client's, and Intercept would hold saves. Step 8f checks. The README says to use the usual browser either way. |
| Duplicates when drafts move to the new release | RISK | Copying twice, or merging two folders, lists a report twice with only one copy openable. A copy left in the old folder becomes a separate store. New with the extension: from the second extension release onward, Burp keeps loading the old release's JAR until it is removed, and that release then serves an empty `data/` where new work lands. The README order (question 4) and the tab naming its folder address it. |
| Word left running after a Force stop | RISK, unexamined | The Word pass starts its own hidden Word through `DispatchEx` ([app/docx_captions.py#L64](app/docx_captions.py#L64)), and a kill mid-pass means its clean-up never runs. What Word does then is the scribe's ground. Step 8c checks. |
| Burp's exit kills the server outright | RISK, unverified | The design expects the server to stop gracefully when Burp's exit closes its input. A closed output pipe does not interrupt that, because uvicorn logs through `logging`, which swallows the failed write (the loremaster's check). But if Burp's Windows launcher ends Burp's child processes, a save running at that instant meets the kill outcomes instead. Step 8h checks. |

### Plan

**Choices the steps rely on.** Any of them can be reopened; none changes report data.

| Choice | Taken | Why |
|---|---|---|
| Extension language | Java, on Burp's current extension API (Montoya) | Python 3 cannot run inside Burp. Python there means Jython 2.7 on the legacy Extender API, which every tester would first have to download and configure. The launcher is process handling, which the JDK does directly. Building a release needs a JDK, and this Mac has none today: `/usr/bin/java` and `/usr/bin/javac` are macOS stubs that exist without one. Testers need no JDK, because Burp runs the JAR on its own bundled Java. |
| Where the app folder is | The folder the JAR was loaded from: the parent of `api.extension().filename()` | No setting to get wrong. A JAR loaded from anywhere else says where it belongs, and keeps Start disabled. |
| Python | The tester's installed Python 3, as today. Chosen automatically: `py -3`, then `python`, on Windows; `python3` elsewhere. A field takes an explicit interpreter path, kept in Burp's preferences | The requirement is unchanged. The field is for macOS, where an app started from the Dock does not see the shell's PATH and finds Apple's older `python3`. |
| Which interpreter starts | The system Python runs `run.py`, which sets up `.venv` and relaunches inside it, as today | Starting `.venv`'s interpreter directly skips the requirements check, and would copy `venv_python()` into Java. |
| Data | Unchanged: `<release folder>/data/` and `generated/`. The extension sets no data folder and no port | Nothing moves, so the extension itself cannot duplicate anything. |
| Ready signal | `run.py` prints the address line, flushed, once uvicorn has bound the port | It sets the status line and opens the browser. It decides nothing about how the server stops. |
| Browser | The system default browser, opened once when the line arrives while starting (never while stopping), plus an **Open** button | The same browser profile as today, so unsaved edits are still offered, and report traffic stays out of Burp. |
| Stop | Close the server's standard input, at every stage. Running requests finish. Pressed during setup, setup finishes and the server exits as soon as it starts. While it waits, Stop becomes **Force stop**, which kills the process tree | Java cannot send Ctrl+C on Windows. With one stop path, no printed line decides between a graceful stop and a kill. |
| Unload and Burp exit | The unloading handler closes the server's input, stops the tab's timer and returns: no deadline, no kill. If Burp ends without calling it, the closed pipe has the same effect | Burp's documentation does not say whether the handler runs when Burp exits, so nothing depends on it. The server exits by itself once its running requests end. |
| When it has stopped | The root process's exit, never the end of its output | A leftover child can hold the output pipe open for minutes. `scripts/relevant_tests.py` hit exactly that with Chromium helpers. |
| Output | stdout and stderr merged. `ServerProcess` keeps the last 2,000 lines in a buffer, filled by a thread that waits on nothing but the pipe. The tab copies the buffer on a Swing timer | A full pipe stalls the server, including replies to saves already on disk. Nothing Burp's UI does can block the reader. |
| Checking the Java | A `main` self-check in `ServerProcess.java`, run by `tests/test_launcher.py`, which supplies the data folder and a free port through the environment | Java never names either variable, and the self-check is kept away from real drafts the same way every Python test is. |
| Release build | `package_release.py` compiles with `javac` against a pinned, hash-checked Montoya API jar. The JAR goes at the root of the zip. Burp supplies the API at runtime | No Gradle, and the script stays standard-library Python. |

Step 1 fixes today's app and does not depend on question 1; it can ship on its own. Do not start
Step 2 until question 1 is answered yes.

- [ ] **Step 1 — Write a new report's images before its draft, in import and duplicate**
  - *Files:* `app/workspace.py`; `tests/test_app.py`; `docs/ROUTES.md`, the sentence "JSON is written
    before PNGs"; `docs/DATA_MAP.md`, rewriting §13's import entry and updating the verification line
    at the top. The new §13 entry says that the PNGs come first, and that a kill between the steps
    leaves an unlisted folder. The entry's clause that "another process can briefly observe the JSON
    before all PNGs exist" goes, because the draft now appears last.
  - *What:*
    - `import_report` and `duplicate` pass their evidence files to the save. The save writes each
      PNG into the folder it chose for the new report, then writes `draft.json`.
    - The folder is chosen once, inside the save. `report_folder_name` falls back to today's date,
      so computing the folder twice could split the images from the draft at a month boundary.
    - Only a report not yet on disk passes files.
    - An ordinary exception still removes the new folder, as now.
    - `save_evidence_if_current` already writes the PNG first and is unchanged.
  - *Test:* `test_an_import_or_duplicate_cut_off_midway_lists_no_new_report`, in `ReportApiTests`.
    - It has four `subTest` rows: import and duplicate, each killed at the first image write and
      at the draft write.
    - A test-local `BaseException` subclass stands in for the kill. The test raises it from a
      patched `app.workspace.atomic_write_bytes` or `app.workspace.atomic_write_json`. The
      `except Exception` rollback does not catch it, just as no handler runs after a kill.
    - The fixture holds at least one evidence file (`support.png_bytes`).
    - Each row asserts that `list_reports()` still returns exactly the reports it returned before.
    - On today's code, both rows killed at the first image write fail, because the new draft is
      already listed. Run them once before the change and watch them fail.
    - If this step ships alone, it gets its own `--affected` run. For `app/workspace.py`, that is
      every Python module and every browser test.
  - *Invariant:* an import or duplicate that completes leaves the same folder, draft and files as
    today. `test_editable_import_rolls_back_when_an_evidence_write_fails` still passes. The rollback
    removes only the new folder, never the source. Every existing `draft.json` loads unchanged.

- [ ] **Step 2 — One fixed port, and a clear refusal when it is taken** (after question 3)
  - *Files:*
    - `run.py`; `tests/test_launcher.py`.
    - `docs/ARCHITECTURE.md`:
      - the uvicorn row;
      - the Configuration table gains `VULNREPORT_PORT`, noting that `run.py` reads it, not the app;
      - the library-fallback paragraph is replaced with what `Library.load_or_empty` does. When the
        file is missing or invalid, the app starts with an empty library and records why. It prints
        the reason at startup, which is in the Burp tab when started from there. Reports still open,
        save and generate.
    - `.github/copilot-instructions.md`: the Start line.
    - `docs/DATA_MAP.md` §13, in two entries, plus the verification line at the top:
      - The port entry: 8765 is fixed, and `VULNREPORT_PORT` is the only thing that moves the
        origin. Set for Burp but not for a console start, it serves one data folder under two
        origins. Drafts kept under 8766–8799 return only when the app is served on that port.
      - The Windows two-server entry: the fixed port now refuses a second server once the first is
        listening. A different `VULNREPORT_PORT` still allows a second server. So does the time a
        stopping server spends finishing a generation, because its listener is already closed.
  - *What:*
    - `PORT` is `VULNREPORT_PORT` or 8765, and the variable's name is a module constant.
    - `serve()` first checks whether something answers on the port, as `free_port` does today. If
      something does, it exits with: "Port 8765 is in use. Report Generator may already be running
      at http://127.0.0.1:8765. Use that one, or stop it first. To run a second copy, set
      VULNREPORT_PORT."
    - `free_port` is deleted.
    - A bind that still fails, because two starts raced, ends in uvicorn's own startup failure
      (exit code 3). That is also a refusal.
  - *Test:* `PortTests.test_start_refuses_when_something_answers_on_the_port`. It listens on a free
    port, patches `run.PORT` to it, and runs
    `assertRaisesRegex(SystemExit, r"already running at http://127\.0\.0\.1:<port>")`. Remove the
    check once and watch it fail with uvicorn's exit code instead of the message.
  - *Invariant:* a console start on a free 8765 behaves as today, and edits a browser kept under 8765
    are still offered.

- [ ] **Step 3 — Print the address only once the server listens, stop at end of input, and keep
  Ctrl+C clean**
  - *Files:* `run.py`; `tests/test_launcher.py`; `docs/DATA_MAP.md` §3, and the verification line at
    the top; `docs/ARCHITECTURE.md`, where the Configuration table gains `VULNREPORT_STARTED_BY_BURP`.
  - *What:*
    - `serve()` replaces `uvicorn.run` with
      `uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=PORT))`, built through a
      subclass. The subclass's `startup` prints the address line with `flush=True` after
      `super().startup()` returns.
    - That timing is safe: uvicorn sets `started` only after the bind, and a failed bind exits with
      code 3 before the print.
    - A console start then opens the browser, replacing the 0.5 s timer.
    - The line's fixed part and `VULNREPORT_STARTED_BY_BURP` are module constants.
    - It adds two pieces of new code:
      - **The input reader.** When `VULNREPORT_STARTED_BY_BURP=1`, a daemon thread, started before
        `server.run()`, reads standard input to its end. It then sets `server.should_exit`, the same
        flag uvicorn's own signal handler sets. Input that has already ended when the server starts
        still stops it: uvicorn binds, skips serving, shuts down and returns. In this mode no
        browser opens, and "Close this window…" is not printed.
      - **The Ctrl+C guard.** In every mode, `server.run()` sits inside `try/except
        KeyboardInterrupt`, the guard `uvicorn.run` had. After a Ctrl+C, uvicorn shuts down
        gracefully and then raises the captured SIGINT again. Without the guard, every console
        Ctrl+C ends in a traceback.
    - `docs/DATA_MAP.md` §3 gains three facts:
      - From the extension, Stop runs uvicorn's graceful shutdown at every stage, so running
        requests finish; a generation waits for its Word pass.
      - Force stop, and Burp's exit if Burp ends its children, are the outright kill whose outcomes
        §3 lists.
      - The listener closes at the start of the wait.
  - *Tests:* in a new `ServeTests` class. Each test:
    - starts `sys.executable run.py` with `VULNREPORT_BOOTSTRAPPED=1`, so it serves in this
      interpreter and never sets up `.venv`;
    - sets a free `VULNREPORT_PORT`, and keeps the temporary data folder that `tests/__init__.py`
      already put in the environment;
    - reads output on a thread with a deadline, never with a bare `readline`.

    The tests:
    - `test_address_line_is_printed_only_once_the_server_answers`: on reading the line, one request,
      with no retry, returns 200. Move the print back before `server.run()` once and watch it fail.
    - `test_end_of_input_stops_only_a_server_started_by_burp`, with three `subTest` rows:
      - started by Burp, input closed after the line: exits with code 0 within 15 s, and the port
        stops answering;
      - started by Burp, input closed before it starts (Stop during setup): exits with code 0;
      - console start, input empty from the beginning: after the line, a request returns 200. This
        row fails if the reader also runs for console starts, because the server then never serves.
    - `test_ctrl_c_in_a_console_start_exits_cleanly`, on macOS and Linux only, because Windows cannot
      send Ctrl+C to one child without also sending it to the test runner. After the line, it sends
      SIGINT, and expects exit code 0 and no `Traceback` in the output. Remove the `except` once and
      watch it fail.
  - *Invariant:* a console start keeps its console behaviour: the browser, the message, and Ctrl+C.
    The input reader exists only when the variable is set. Nothing under `app/` changes.

- [ ] **Step 4 — Hand the extension's pipes to every child process**
  - *Files:* `run.py`; `tests/test_launcher.py`.
  - *What:*
    - When `VULNREPORT_STARTED_BY_BURP=1`, the `subprocess.run` calls in `bootstrap()` and
      `relaunch()` pass `stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr`.
    - On Windows, CPython hands a child no standard handles, and starts it with handle inheritance
      switched off, unless streams are passed (the loremaster checked the CPython half). Passing the
      three streams makes the pipe reach the server whatever Windows does otherwise.
    - Step 8a checks the result end to end.
  - *Test:* `test_children_receive_the_launchers_streams`, with two `subTest` rows. With the
    variable set, a patched `run.subprocess.run` is called with the three streams. Without it, the
    call gets none of them, so a console start is unchanged.
  - *Invariant:* console starts are unchanged.

- [ ] **Step 5 — The process half of the extension, in plain Java**
  - *Files:* `burp/ServerProcess.java` (new); `tests/test_launcher.py`.
  - *What:*
    - **Starting.** It builds the command from the Python field, or the automatic choice, and runs
      it in the app folder. To the environment it inherits, it adds `PYTHONUNBUFFERED=1`,
      `PYTHONIOENCODING=utf-8` and `VULNREPORT_STARTED_BY_BURP=1`, and nothing else. It merges stderr
      into stdout.
    - **Output.** One thread reads lines into a buffer of the last 2,000, which `ServerProcess`
      owns. That thread waits on nothing but the pipe: no listener, and no call into Swing. The tab
      reads the buffer on its own timer.
    - **The address.** It is the text after the address line's fixed part, kept exactly as printed.
    - **The end.** It is the root process's exit (`onExit()`), never the end of output.
    - **Stopping.** `stop()` closes standard input, at any stage. `forceStop()` first snapshots
      `descendants()`, then calls `destroyForcibly()` on each and on the root. Nothing kills on a
      deadline or automatically.
  - *Self-check:* `main(appFolder, python)` runs these checks in order:
    1. It starts the app, and waits up to 180 s for the address line, since a first run installs
       packages.
    2. It requests the address, with no proxy.
    3. It sends 50 requests with 4 KB paths, about 200 KB of access lines, without reading the
       buffer. It expects every one answered within 30 s.
    4. It stops the app, and expects exit code 0 within 15 s and the port closed.
    5. It starts the app again and force-stops it, and expects every process it saw to be gone and
       the port closed.

    It exits non-zero on any failure.
  - *Tests,* in `tests/test_launcher.py`:
    - `test_java_launcher_self_check`:
      - It runs `java burp/ServerProcess.java <ROOT> <interpreter>`. The interpreter is the one
        `.venv` was created from (`sys._base_executable`), so the run goes through `run.py`'s
        relaunch and there is a child process to force-stop.
      - It adds a free `VULNREPORT_PORT` to the environment the test already has, removes
        `VULNREPORT_BOOTSTRAPPED`, and sets a 240 s timeout.
      - It expects exit code 0, and prints the Java output on failure.
      - It is skipped, with the reason, in two cases. One is when `javac -version` fails: there is
        no JDK. On macOS, `/usr/bin/javac` exists without one, so the check runs the command
        instead of searching PATH. The other is when `run.needs_install` says `.venv` is not
        current, so the test never installs packages.
    - `test_java_launcher_shares_only_two_names_with_run_py`: reads every `burp/*.java`. It asserts
      that the address line's fixed part and `VULNREPORT_STARTED_BY_BURP`, both taken from `run`'s
      constants, appear, and that neither `VULNREPORT_DATA_DIR` nor `VULNREPORT_PORT` does. Rename
      either constant on one side, or write either variable into Java, and it fails.
  - *Invariant:*
    - The extension kills only the root process and the descendants it had when Force stop was
      pressed, and never kills by process name.
    - The self-check gets its data folder only from the test's environment. Run by hand, it would
      serve the real data folder for a few seconds, but still read no draft: `GET /` lists no
      reports, the 4 KB paths return 404, and `prefs.json` is written only if it is missing. So the
      docs name only the test.

- [ ] **Step 6 — The Burp tab**
  - *Files:* `burp/ReportGeneratorExtension.java` (new).
  - *What:*
    - It implements `BurpExtension`, with `setName("Report Generator")`.
    - The app folder is the parent of `api.extension().filename()`. Without a `run.py` there, the
      tab says to load the JAR from the Report Generator folder, and Start stays disabled.
    - It registers one suite tab (`registerSuiteTab`) in Burp's theme (`applyThemeToComponent`),
      holding:
      - a status line that names the folder and the state. The states are:
        - Stopped, with the exit code when it is not 0;
        - Setting up;
        - Running at `<address>`, with **Open**;
        - Stopping, waiting for running work to finish (for example a report being generated, or
          setup), with **Force stop**.
      - the Python field (blank means automatic), kept with `persistence().preferences()`;
      - **Start**, which stays disabled until the previous process has exited, and **Stop**, which
        becomes **Force stop** while stopping;
      - an output area in Burp's editor font (`currentEditorFont()`), copied from `ServerProcess`'s
        buffer by a `javax.swing.Timer`. Its first lines are the folder and the exact command.
    - When the address line arrives while starting, the tab opens the system default browser once
      (`Desktop.browse`), at the address exactly as printed. If the desktop cannot, the tab says so,
      and the address is on the status line to copy.
    - `registerUnloadingHandler` calls `stop()`, stops the timer and returns.
  - *Test:* this checklist, run once on macOS and once on Windows. Each line names the result that
    must be seen, so each can fail.
    1. Load the JAR from a release folder: a Report Generator tab appears, and its status line names
       that folder.
    2. Load a copy from another folder: the message appears, and Start stays disabled.
    3. Start in a folder without `.venv`: setup output streams, then "Running at
       http://127.0.0.1:8765", and the default browser opens the home page.
    4. In another fresh folder, press Stop during setup: the status says it is waiting. Setup
       finishes, the process exits with code 0 without opening the browser, and the next Start does
       not reinstall.
    5. Edit a report and press Stop before the page says it has saved: the page shows "Save failed -
       Retry". Press Start: the same tab saves on its next retry or edit, with no restore prompt.
    6. Stop with nothing in progress: Stopped within a couple of seconds, and the port no longer
       answers.
    7. In a second Burp window, Start while the first server runs: its output shows the refusal
       naming http://127.0.0.1:8765, and it returns to Stopped within a few seconds. The first
       window's server still answers.
    8. Unload the extension while it is running and idle: the server process is gone within a couple
       of seconds.
    9. Quit Burp while it is running and idle: no Python process from this folder remains.
    10. Screenshot the tab in Burp's light and dark themes: the output is readable in both.
  - *Invariant:* the extension passes no data folder and no port. Nothing the tab does can block the
    reader. The address is never rewritten, for example to `localhost`. Nothing is hidden: the
    command, the folder and the address are all printed.

- [ ] **Step 7 — Release build and README**
  - *Files:* `scripts/package_release.py`; `README.md`; `docs/DATA_MAP.md` §1, where "Report data
    never ships" gains `ReportGenerator-Burp.jar` in the zip's contents, and the verification line at
    the top.
  - *What:*
    - **The script.**
      - It downloads the Montoya API jar (`net.portswigger.burp.extensions:montoya-api`, a pinned
        version, from Maven Central) once into `dist/`, and checks its SHA-256 against a pinned
        value.
      - It compiles `burp/*.java` with `javac --release <N>`, where N matches that jar's class files.
      - It writes `ReportGenerator-Burp.jar` into the staging folder beside `run.py`.
      - It stops with a clear message when `javac -version` fails, which also catches the macOS
        stub, so a release never ships without the extension by accident.
      - Pin a Montoya version no newer than the oldest Burp the testers run: a JAR built against a
        newer API can call methods that an older Burp lacks.
      - Install a JDK on this Mac before the first release build.
    - **The README,** which ships in the zip, covers:
      - loading `ReportGenerator-Burp.jar` from the unzipped folder (Extensions, Add, type Java);
      - Start, Stop and Force stop:
        - "Start runs a local web server at http://127.0.0.1:8765, reachable only from this
          computer."
        - Stop waits for running work, such as a report being generated. Force stop ends it at
          once.
        - After a Force stop, a page may show "Save conflict" for a save the server finished but
          could not confirm. If that report was open in only that one tab, choose Save my version.
      - opening it in your usual browser, not Burp's; running one copy per folder;
      - upgrading, in the order from question 4. If Start was already pressed in the new folder and
        no report was made there, replace its `data` with the old one. If reports were made there,
        move the old `data/apps` folders into the new `data/apps` instead. If the moved folder
        arrives under another name, such as `data (2)`, rename it to `data`.
      - `VULNREPORT_PORT`, only when another program holds 8765. Set it as a user environment
        variable, so Burp (after a restart) and console starts see the same value.
      - unsaved changes from a second copy you used to run at the same time. The browser keeps them
        under that copy's address, for example http://127.0.0.1:8766. To get them back, start once
        with `VULNREPORT_PORT` set to that port, open the report, choose Restore, and save.
      - if setup was interrupted and Start keeps failing: delete `.venv` and start again.
  - *Test:* run the script. `unzip -l dist/<name>.zip` lists `<name>/ReportGenerator-Burp.jar`, and
    no `data/` or `generated/`. Load that JAR from an unzipped copy, and repeat Step 6's checklist
    lines 1 and 3.
  - *Invariant:* the zip still carries no drafts, evidence or finished documents, and the Montoya API
    jar is not in it (Burp supplies the API).

- [ ] **Step 8 — Check on Windows what reading code cannot settle**
  - *Files:* none. Record each result in this plan, under this step.
  - *What:* on Windows with Word, from a release built in Step 7, using a scratch report only:
    - a. The server's output reaches the tab through `run.py`'s relaunch. Stop ends every Python
      process (`py.exe`, the system Python, the `.venv` interpreter and the server) with exit code 0.
      This is Step 4's reason.
    - b. Generate a real report from the Burp-started server: the `.docx` lands in `generated/`,
      and Word's pass ran (the table of contents is filled in). This is the Word-adjacent risk from
      the framing; the document side is otherwise unexamined.
    - c. Force stop during a generation. Afterwards, look in Task Manager for a hidden
      `WINWORD.EXE` still running, then generate again. If Word was left behind, or the second
      generation fails, stop here and take it to the scribe. Do not add Word-killing to the
      extension.
    - d. Stop, then Start at once with the report's tab open: the server gets 8765 again, with no
      "address already in use" from connections still closing.
    - e. A console `run.py` started while the Burp-started server runs is refused, because a second
      socket cannot share the port on Windows.
    - f. Open the address in Burp's own browser with a scratch report, and look in Proxy, HTTP
      history for `127.0.0.1:8765`. If it is there, report data would be recorded in whichever Burp
      project is open, and Intercept would hold saves, so the README warning stays as written. If it
      is not, reduce the warning to the browser-profile reason.
    - g. From a checkout with a JDK installed, `.venv\Scripts\python -m unittest tests.test_launcher`
      passes, with the Java self-check run rather than skipped. The release carries no `tests/`, so
      this one check runs from a checkout.
    - h. Quit Burp while a report is generating. If the document still appears in `generated/`, the
      server stopped gracefully. If the server vanished with Burp, Burp's exit kills its children:
      record that in `docs/DATA_MAP.md` §3 as an outright kill at Burp exit.
    - i. Unload the extension while a report is generating: the document still appears in
      `generated/`, and every Python process from the folder exits once it has.
  - *Invariant:* nothing here uses a tester's real drafts.

- [ ] **Step 9 — Close out**
  - *Files:*
    - this plan: status `shipped`, the date, the commit, and what deviated;
    - `.github/copilot-instructions.md`: one line saying that `burp/` is the Burp launcher, checked by
      `tests/test_launcher.py` (including the Java self-check, when a JDK is installed) and by
      Step 6's checklist;
    - `docs/ARCHITECTURE.md`: a short paragraph on starting from Burp.
  - *Test:* `.venv/bin/python scripts/relevant_tests.py --affected --run`. For `run.py` it picks every
    Python module and no browser tests. If Step 1's `app/workspace.py` change ships in the same
    change, it also picks every browser test.
  - *Invariant:* the plan and the map describe what was built.

### What I would not do

- **Move drafts to a per-user folder while we are at it.** Setting `VULNREPORT_DATA_DIR` from the
  extension looks like one line, but it brings four problems:
  - Copying drafts into the new folder is exactly where duplicates come from.
  - `generated/`, the library and `.venv` would still be tied to the release folder.
  - A console start that does not set the variable would serve a second store.
  - An old release still loaded would open and save the same drafts with older code, which drops
    fields it does not declare.

  It is question 4's option (c), and its own change.
- **Report missing images instead of preventing them.** Checking files on load, or in the readiness
  verdict, looks like a smaller fix for the import gap. But the readiness verdict is a rule that
  exists in both Python and JavaScript, and the browser cannot see files, so the check would exist on
  one side only. Writing the images first (Step 1) removes the broken state instead of describing it.
- **An HTTP shutdown route.** It is one more route any web page could aim a request at, and its effect
  is to end the server. Only the process that started the server can close its input.
- **Start `.venv`'s interpreter directly from Java.** It would run one process instead of two. But it
  skips the requirements check, so a release with new requirements would start on old packages, and
  the rule for where `.venv`'s interpreter lives would then exist in both Python and Java.
- **Kill by process name, or kill Word.** Ending `python.exe` or `WINWORD.EXE` by name can close the
  tester's own Word documents or unrelated Python work. The extension kills only the process it
  started, and that process's descendants.
- **Kill on a deadline when the extension unloads**, as the proposal did after 10 seconds. It is a
  kill nobody chose. It can land in a save that waited behind a report generation and starts writing
  when the generation ends. Closing the input is enough: the server exits by itself once its running
  requests finish.
- **Kill when Stop is pressed before the address line**, as the proposal did. That let one printed
  line decide between a graceful stop and a kill. Closing the input is safe at every stage.
- **Write `VULNREPORT_DATA_DIR` or `VULNREPORT_PORT` in Java.** Each name written in both languages
  must change on both sides together, and a drifted data-folder name would aim the self-check at real
  drafts. Passing both through the environment that the test already controls keeps them out of Java.
- **Bound uvicorn's graceful wait with `timeout_graceful_shutdown`.** When the limit runs out, uvicorn
  cancels the task waiting on the request. But the save itself runs on a worker thread that is not a
  daemon, so Python finishes the write before the process exits anyway (the loremaster's check). The
  limit bounds nothing, and can cost the reply, which would leave the page with a save conflict
  against its own saved change.
- **Lock the setup window on its own.** Two first-run setups at once can break `.venv`. Guarding
  against that needs a lock taken without waiting, on both Windows and macOS, for a window of about a
  minute on a first run. It would protect a folder that holds no report data, and deleting that
  folder fixes it. If question 3 goes to its lock option, that lock covers this too.
- **Change today's console Ctrl+C here.** The parent `run.py` kills the server a quarter of a second
  after Ctrl+C, cutting its graceful wait short. The extension never sends Ctrl+C, and this change
  does not make that worse. Step 1 removes its worst outcome, for import and duplicate. It deserves
  its own small plan if console users lose saves to it.
- **Keep the port scan, and read the address from uvicorn's "Uvicorn running on" log line.** That ties
  the extension to another project's log wording, and keeps both port risks.
- **Serve the app inside Burp: in Burp's browser, as a page embedded in the tab, or through Burp's
  proxy.** Each one hides edits kept in the tester's usual browser, may record client data in a Burp
  project, and dresses the app up as part of Burp, which is the disguise question 1 rules out.

## Round 3 - Loremaster: the data move the answers added

Checked against the coordinator's draft design A–E (the lock, when the move is offered, the checks,
the move, the `.venv` copy). Read-only throughout; nothing under `data/` or `.venv/` was changed.

**Answer.** Renaming `data/` in one step keeps every report whole: the draft, its backup and its PNGs
share one folder, and reports are found only by a scan two levels below `apps/`. So nothing in A–E
can orphan a PNG, and no stored value breaks when the folder gets a new parent. The ways to split or
hide reports all come from around the move:

- a server still running on either folder, because C checks the lock on the old folder only, and on
  macOS and Linux a rename does not stop a running server;
- a data-folder rule that the extension does not share with `run.py`;
- a marker that no console start reads;
- a lock that, as drafted, is skipped by one documented kind of start and can be computed for a
  different folder from the one the server uses.

Two facts in the code count against E. Many `.venv` folders carry no stamp. The proposed import check
also skips two modules that `app.main` loads at startup, so a copy can pass the check, then fail
every Start, and `run.py` never rebuilds it. This round also corrects one claim in my Round 2.

### 1. What A–E can lose, duplicate or orphan

**The rename itself (D) keeps each report whole.**

- A report is `apps/<app>/<report>/` holding `draft.json`, `draft.bak.json` and `evidence/*.png`.
  The backup is written beside the draft ([app/storage.py#L18-L22](app/storage.py#L18-L22)).
  Evidence is read relative to the draft's own folder
  ([app/main.py#L893-L897](app/main.py#L893-L897)). Reports are found by `apps/*/*/draft.json` and
  nothing else ([app/workspace.py#L245](app/workspace.py#L245)).
- A report that an earlier kill left without its PNGs moves exactly as it is. Import and duplicate
  still write the draft first, because the write-order fix was declined. Nothing in D can create
  such a report.
- Every release since the first commit uses this layout: `DATA = ROOT / "data"` and `root / "apps"`
  (git `3ff8e45`, `app/main.py` line 33 and `app/workspace.py` line 42). So C's "has `data/apps`"
  test holds for all of them.
- A previous folder whose app never saved a report has no `apps/`, because the first save creates it
  ([app/storage.py#L32](app/storage.py#L32)). C rejects that folder, and it holds nothing to move.

**Five ways reports end up in two stores, or out of sight:**

1. **A server still running in the new folder.** C checks the lock on `<old>` only, and D then renames
   `<new>/data` aside. `<new>/data` exists only after something ran in the new folder. Under A, a
   console `run.py` running there holds `<new>/data/server.lock`. On macOS and Linux the rename
   succeeds anyway:
   - that server's lock handle and error-log handle follow the renamed folder;
   - its `DATA` path, which the scan reads on every request, now names the moved-in folder
     ([app/main.py#L37](app/main.py#L37));
   - the extension's own Start then locks the moved-in `server.lock`, which nobody holds.

   Two servers then serve one folder, which is the case A exists to prevent. Windows is covered in §2.
2. **An old server still running, on macOS or Linux.** A rename does not stop it.
   - Its tabs get 404 for every report. `find_path` scans a path that no longer exists, and
     `report_or_404` maps that to 404 ([app/workspace.py#L253-L258](app/workspace.py#L253-L258),
     [app/main.py#L236-L241](app/main.py#L236-L241)). Guarded saves fail the same way and write
     nothing.
   - *New report* and *Import* go through the unguarded `save()`, and its write creates missing
     parent folders ([app/workspace.py#L346-L369](app/workspace.py#L346-L369),
     [app/storage.py#L32](app/storage.py#L32)). Any lock call also recreates `.locks`
     ([app/workspace.py#L87](app/workspace.py#L87)). New work therefore lands in a recreated
     `<old>/data`, which is a second store.
   - Its open log keeps writing into the moved `<new>/data/vulnreport-errors.log`, which the new
     server opens too. That affects diagnostics only.

   For releases without the lock file, the tester's confirmation is the only guard.
3. **A console start in the old folder after the move.**
   - Only the Java launcher reads the marker. `run.py` never reads it, neither the old release's copy
     nor, under A, the new one ([run.py#L94-L99](run.py#L94-L99)).
   - Importing `app.main` there recreates the folder. It writes a fresh `prefs.json`, resolving the
     tester's name again, and opens a new log
     ([app/tester_identity.py#L181-L202](app/tester_identity.py#L181-L202),
     [app/main.py#L73](app/main.py#L73)). New reports then collect in that folder.
   - For the first extension release, the old folder has no launcher that could read the marker.
   - Under A, `run.py` creates the data folder first thing. A marker check placed after that line
     would itself recreate `<old>/data`.
4. **A data-folder rule the extension does not share.** B, C and D look at `<new>/data` and
   `<old>/data`, but the server serves `VULNREPORT_DATA_DIR` whenever it is set and not empty
   ([app/main.py#L37](app/main.py#L37); the `or` makes an empty value mean the default). The relaunch
   copies the whole environment into the server ([run.py#L67](run.py#L67)). Suppose the variable is
   set where Burp can see it:
   - the move puts the drafts into a folder the server never reads;
   - B keeps finding `<new>/data/apps` empty;
   - the `<old>/data` it moves may not be the folder the old app served.

   So the variable becomes a name shared between Python and Java again. Round 2's tactician recorded
   that it would never appear in Java.
5. **"Has reports" counted differently from the app.** The app's only definition of a report is a
   file matching `apps/*/*/draft.json` ([app/workspace.py#L122](app/workspace.py#L122),
   [#L134](app/workspace.py#L134), [#L245](app/workspace.py#L245)).
   - A draft that is not valid JSON is skipped by every listing, with no message.
   - A draft that parses but fails validation is listed under "Legacy drafts".
   - If B and D count only readable drafts, D renames aside a folder that holds a real but unreadable
     draft. The draft is hidden, not deleted.
   - Empty app folders are not reports, and Delete removes an app folder once it is empty
     ([app/workspace.py#L149-L158](app/workspace.py#L149-L158)).

**Nothing in A–E deletes report data.**

- `data.before-move-<timestamp>` is never scanned, because the scan starts at `DATA/apps`, and
  never deleted. Renaming it back brings its contents back.
- The `.venv` delete touches only a folder that did not exist before the copy.
- `generated/` moves only into a release that has none, and `unused_export_path` numbers a clashing
  name instead of overwriting it ([app/main.py#L544-L551](app/main.py#L544-L551)).
- A fresh release has no `generated/`. The zip leaves it out
  ([scripts/package_release.py#L19-L23](scripts/package_release.py#L19-L23)), and the app creates it
  only when it writes a document ([app/main.py#L533-L534](app/main.py#L533-L534)). Starting the app
  does not create it.

**What stays in the old folder after D, and is lost if the tester then deletes that folder:**

- `generated/`, whenever it was not moved (the new folder already had one, or the rename failed);
- the old `.venv`, which is copied, not moved, as the user asked;
- `data.before-move-*` folders left by earlier moves;
- edits to `<old>/resources/vuln_library.json`. This applies only to a developer checkout, because
  the release zip leaves the library editor out
  ([scripts/package_release.py#L25-L30](scripts/package_release.py#L25-L30)).

**A git checkout would publish the new files.**

- `.gitignore` names `data/` children one by one: `data/apps/`, `data/.locks/`, `data/prefs.json`
  and `data/vulnreport-errors.log*` ([.gitignore#L1-L6](.gitignore#L1-L6)).
- So `git check-ignore` shows that `data/server.lock`, every `data.before-move-*/` and
  `DATA-MOVED.txt` would appear as untracked files. A `data.before-move-*/` folder holds `prefs.json`,
  with the tester's name, and the error logs.
- This repo's push rule stages every working-tree change
  ([.github/copilot-instructions.md#L172](.github/copilot-instructions.md#L172)).
- Release folders are not git checkouts, so this affects anyone who runs the extension from a clone.
- The same is already true today of `data/prefs.corrupt.json`, and of `data/prefs.tmp` when a kill
  leaves it behind ([app/tester_identity.py#L186](app/tester_identity.py#L186),
  [#L200](app/tester_identity.py#L200)).

### 2. What moves together, what stays, and what a running server holds open

**Moves together:** each report folder, as a unit (§1). In practice that means all of `apps/` in one
rename. A partial move is how a report ends up in two stores, and two copies with the same
`report_id` are listed twice with only one openable (Round 1 §5).

**Can move or stay:**

- `prefs.json`: the tester's name and the library path (§3).
- `.locks/`: inert files. The lock lives on the open handle
  ([app/workspace.py#L89-L100](app/workspace.py#L89-L100)).
- The new `server.lock`: likewise, only a held handle means anything.
- The error logs: diagnostics only.

**Must stay with the release:**

- `app/`, `run.py`, and `resources/` (templates, Word masters and the library). A relative
  `prefs.library_path` resolves against the release folder (§3).
- `.venv` is copied, as the user chose.
- `generated/` is independent of `data/`: nothing in a draft points at a finished document.

**Held open while a server runs:**

| File | How long | Evidence |
|---|---|---|
| `DATA/vulnreport-errors.log` | from import for the whole life of the process, in every release since the first commit | [app/main.py#L71-L82](app/main.py#L71-L82); git `3ff8e45` `app/main.py` lines 49 and 58 |
| `DATA/server.lock` (new, A) | for the life of the top-level `run.py` | design A |
| `DATA/.locks/<hash>.lock` | during each request on that report; through the whole Word pass during a generation | [app/workspace.py#L89-L110](app/workspace.py#L89-L110), [app/main.py#L521-L537](app/main.py#L521-L537) |
| `draft.json`, `draft.bak.json`, their sibling `.tmp` files | milliseconds per read or write | [app/storage.py#L13-L47](app/storage.py#L13-L47) |
| an evidence PNG | while `FileResponse` streams it | [app/main.py#L897](app/main.py#L897) |
| `prefs.json` | only while it is read at import | [app/tester_identity.py#L181-L184](app/tester_identity.py#L181-L184) |
| `generated/*.docx` | not by the server once written; by Word if the tester has the document open (outside my territory) | [app/main.py#L536](app/main.py#L536) |

**On Windows.** The repo records two facts:

- An open error log stops its folder being deleted. `tests/__init__.py` passes
  `ignore_cleanup_errors` because "on Windows the error log is still open when the interpreter exits"
  ([tests/__init__.py#L11-L12](tests/__init__.py#L11-L12)).
- Windows refusals can be transient. Every `os.replace` is retried three times on `PermissionError`
  ([app/storage.py#L10](app/storage.py#L10), [#L38-L45](app/storage.py#L38-L45)).

The repo does not show two things, so I cannot establish them: whether an open handle anywhere under
`data` makes a *directory rename* fail, and whether a failed rename leaves the tree untouched. That
is Windows filesystem behaviour. Two things follow from the source either way:

- C's check opens `<old>/data/server.lock` itself, so it holds a handle inside the folder it is about
  to rename. If that handle has to be closed first, the old app can be started between the check and
  the rename.
- Nothing in the app or the design recognises or repairs a half-moved tree. The scan sees only what
  lies under `DATA/apps`.

**A running server cannot be asked which folder it serves.** No route returns `ROOT` or `DATA`. The
only absolute path the app sends is `GENERATED`, in the generate response
([app/main.py#L515](app/main.py#L515)). So for a release without the lock, nothing on disk or on the
network links a listening server to its folder.

### 3. Stored values after `data/` gets a new parent

None of them breaks because of the new parent:

- `_folder_name_hint` stores folder names only.
- `evidence.file` is relative.
- Lock files are named by a hash of the report id.
- `ERROR_LOG_LABEL` stays relative, because `DATA` stays inside the release folder
  ([app/main.py#L65-L67](app/main.py#L65-L67)).

Round 1 §1 and Round 2 §3 give the evidence. A read-only recount of this checkout's `data/` matches
both earlier rounds: 14 drafts, 8 backups, 13 PNGs, 76 lock files, no `.tmp` file, and no absolute
path in any draft.

**`prefs.json` is the one file whose meaning depends on the release it lands in.**

- A relative `library_path` is joined to the *new* release folder at import
  ([app/main.py#L42-L44](app/main.py#L42-L44)), so the new release's library is read. This checkout's
  value is `resources/vuln_library.json`.
- `vuln_library.json` was the default until git `059fe05` (2026-09-14), and it is mapped to
  `resources/vuln_library.json` ([app/tester_identity.py#L167-L173](app/tester_identity.py#L167-L173)).
- `library/vuln_library.json` is no longer handled. The first commit still redirected it through a
  special case (git `3ff8e45`, `app/main.py` lines 38–39).
  - Today it resolves to `<new>/library/vuln_library.json`, which no release contains.
  - The app then starts with an empty library and says so only in its startup output
    ([app/library.py#L71-L79](app/library.py#L71-L79), [app/main.py#L45-L46](app/main.py#L45-L46)),
    which under this plan is the Burp tab.
  - A fresh `prefs.json` would not have this problem. Prefs are rewritten only when missing,
    unreadable or without a tester, so a moved stale value stays
    ([app/tester_identity.py#L181-L198](app/tester_identity.py#L181-L198)).
  - Whether any tester's prefs holds this value is not established. It predates this repository's
    history.
- A hand-edited absolute `library_path` keeps pointing at the old folder's library. That works until
  the old folder is deleted, then gives the same empty library.
- The tester's name moves with the file and is not resolved again. The undeclared `defaults` key
  moves along, untouched.

**Browser recovery drafts carry over.** They are keyed by `report_id` and origin (Round 1 §4), and the
move keeps every `report_id`. Old and new releases both scan from port 8765
([run.py#L74-L80](run.py#L74-L80)). So when nothing else holds 8765, the new release comes up on the
old one's origin and offers the unsaved edits the old one left in the browser.

### 4. The copied `.venv` and `run.py`

**What `run.py` checks.** `needs_install` asks two things: that the interpreter file exists, and that
`.venv/.requirements-sha256` equals the hash of the new release's `requirements.txt`
([run.py#L38-L44](run.py#L38-L44), [#L49](run.py#L49)).

- `is_file()` follows symlinks. A copied relative `python -> python3.14` link counts as present
  exactly when the base interpreter it finally points at still exists.
- The stamp lives inside `.venv` ([run.py#L15](run.py#L15)), so a copy carries whatever stamp the old
  folder had.

**The stamp is often missing.**

- It was introduced on 2026-09-11 (git `3cc3357`). Before that, `run.py` imported uvicorn directly
  and never created `.venv` (git `3cc3357^:run.py`).
- A `.venv` from an older release, or one built by hand, has no stamp. This checkout's own `.venv`
  has none (checked).
- Then `needs_install` is true, and the first Start runs the copy's interpreter with
  `-m pip install -r requirements.txt` ([run.py#L53-L57](run.py#L53-L57)). The same happens whenever
  the two releases' `requirements.txt` differ.
- Whether pip then downloads anything is pip's behaviour, outside my territory.

**`inside_venv` does not matter on the Burp path.**

- The relaunch sets `VULNREPORT_BOOTSTRAPPED`, and the child enters `serve()` on that flag alone
  ([run.py#L67](run.py#L67), [#L95](run.py#L95)).
- `inside_venv` decides only for a direct `.venv/bin/python run.py` start
  ([.github/copilot-instructions.md#L8](.github/copilot-instructions.md#L8)).
- A copied interpreter might report a `sys.prefix` other than the new `.venv`; that is packaging
  behaviour I cannot judge. If it did, that direct start would fall to `bootstrap()`, find the stamp
  current and relaunch itself with the flag: one extra process, and the same result.

**The proposed check does not load everything startup loads.** I ran `import fastapi, uvicorn,
pydantic, docx, PIL` with this checkout's `.venv`, with `-B` so that nothing was written.

- It loads `pydantic_core`'s compiled module, `lxml.etree` and `python_multipart`.
- It does **not** load Pillow's compiled `PIL._imaging`, and it does **not** load `jinja2`.
- `app.main` needs both at import: `from PIL import Image` ([app/main.py#L20](app/main.py#L20)) and
  `Jinja2Templates` ([app/main.py#L19](app/main.py#L19), [#L50](app/main.py#L50)).
- It imports none of the `uvicorn[standard]` extras ([requirements.txt](requirements.txt)) either.

**A copy that passes the check but cannot import the app is never rebuilt.**

- uvicorn turns only a missing `app.main` module or attribute into its exit code 3. Any other import
  error, including a dependency's `ModuleNotFoundError`, is re-raised and ends in a traceback
  ([uvicorn/importer.py#L18-L23](.venv/lib/python3.14/site-packages/uvicorn/importer.py#L18-L23),
  [uvicorn/config.py#L425-L431](.venv/lib/python3.14/site-packages/uvicorn/config.py#L425-L431)).
- On every later Start, `run.py` sees a matching stamp and relaunches into the same `.venv`. Nothing
  in it deletes or repairs one.
- Checking with `import app.main` instead has side effects. That import creates the data folder, can
  write `prefs.json`, and opens the error log ([app/main.py#L37-L82](app/main.py#L37-L82)).

**No startup check reaches pywin32.** It is imported only inside the Word pass
([app/docx_captions.py#L53-L57](app/docx_captions.py#L53-L57)). If it fails to import in a copy,
Generate answers 422 "Microsoft Word automation requires the existing pywin32 package"
([app/main.py#L540-L541](app/main.py#L540-L541)). Nothing is written, and the draft is untouched.

**Absolute paths in this checkout's `.venv`** (macOS, read-only):

- `pyvenv.cfg`: `home` and `executable` name the base interpreter under
  `/Library/Frameworks/Python.framework/Versions/3.14/`, and `command` records the old venv's own
  absolute path.
- `bin/python3.14` is an absolute symlink to the base interpreter. `bin/python` and `bin/python3` are
  relative links to `python3.14`.
- Every console script (`pip`, `uvicorn`, `fastapi` and the rest) starts with
  `#!/Users/eli/Code/Generator/.venv/bin/python3.14`, and `bin/activate` hard-codes `VIRTUAL_ENV` to
  the old folder. In a copy, these scripts still run the *old* folder's interpreter. `run.py` never
  calls them: it runs `-m pip`, and relaunches `run.py`, through `venv_python()`
  ([run.py#L57](run.py#L57), [#L69](run.py#L69)).
- `site-packages` holds no `.pth` file here. The Windows entries (`Scripts\*.exe`, `pywin32.pth`)
  cannot be inspected on this machine.

Whether a copied virtual environment works at all is Python packaging, outside my territory.

**Nothing in A–E protects `<new>/.venv` while it is being copied.** A's lock sits in the data folder.
A console `run.py` in the new folder treats `.venv` as ready once the interpreter file exists and the
stamp matches ([run.py#L40-L44](run.py#L40-L44)). So the order in which the copy writes those two
files decides what such a start would see.

### 5. Where A–E does not match the code

**A. The lock**

- **The branch the design names also catches direct starts.** `serve()` runs when `inside_venv()`
  *or* the relaunch flag is set ([run.py#L95](run.py#L95)). A lock skipped on that branch is also
  skipped for `.venv/bin/python run.py`. The project documents that start
  ([.github/copilot-instructions.md#L8](.github/copilot-instructions.md#L8)), and it runs as one
  process with no relaunch. Only the flag marks a relaunched child.
- **The parent and the server can compute different folders.**
  - `app.main` uses the variable exactly as typed and never resolves it
    ([app/main.py#L37](app/main.py#L37)).
  - The server child runs with `cwd=ROOT` ([run.py#L69](run.py#L69)); the parent runs in whatever
    folder it was started from.
  - With a relative `VULNREPORT_DATA_DIR`, the parent locks one folder and the child serves another.
  - The planned test that pins `run.py`'s rule to `app.main.DATA` cannot see this. The tests set the
    variable to an absolute temporary path ([tests/__init__.py#L12-L13](tests/__init__.py#L12-L13))
    and run from the project root.
- **The lock holder is not the process that uses the data.** Nothing ties the child's lifetime to the
  parent's ([run.py#L65-L71](run.py#L65-L71), Round 1 §2). If only the parent is ended, the lock is
  released while the server still serves the folder.
- **`msvcrt.locking` locks from the current file position.** The app's own lock seeks to 0 first,
  because append mode opens at the end ([app/workspace.py#L89-L94](app/workspace.py#L89-L94)).
  Locking "byte 0" needs the same seek.
- **A lock taken without waiting gets no grace period on Windows.**
  - The only lock the app takes today uses `LK_LOCK`, which retries for about ten seconds
    ([app/workspace.py#L97](app/workspace.py#L97)).
  - Round 1 §2 recorded that Windows releases a dead process's locks "depending on system
    resources".
  - A lock taken without waiting has no retry, so a Start pressed right after a Stop can be refused.
    The refusal touches no data.
- **POSIX record locks belong to the whole process.** This is a POSIX rule, not repo code. A second
  `lockf` from the same process never conflicts, and closing *any* descriptor on the file drops the
  lock. So a test of the refusal needs a second process, and nothing in the parent may open
  `server.lock` again while it holds the lock.

**B, C and D**

- B and D need the app's own test for a report and the app's own data-folder rule (§1, items 4 and 5).
- C checks one lock, but D renames two folders. `<new>/data` can hold a new-release server's lock
  too (§1, item 1).
- Only the Java launcher is bound by the marker (§1, item 3).
- `.gitignore` has no entry for the new names (§1, last paragraph).

**E**

- "The stamp comes along with the copy" holds only for `.venv` folders built by `run.py` since
  2026-09-11 (§4).
- The import check misses `PIL._imaging` and `jinja2`, which `app.main` loads, and a failure there is
  never rebuilt (§4).

**Correction to my Round 2 (§4, point 2).** I wrote that a failed app import "already exits with code
3 inside `load_app`". That holds only when the `app.main` module or its attribute is missing. A
failure inside the import, such as a broken dependency, is re-raised by `import_from_string` and ends
the process with a traceback, not code 3
([uvicorn/importer.py#L18-L23](.venv/lib/python3.14/site-packages/uvicorn/importer.py#L18-L23)).

### Invariants in play

- **One data folder, one server.** Every guard in A–D exists for this. On macOS and Linux, a rename
  under a running server breaks it without any error.
- **Never discard user content without a prompt.** D keeps this by renaming aside instead of
  deleting. That holds only while "has reports" matches the app's own scan.
- **Reports are found by `DATA/apps/*/*/draft.json` and their `report_id`, and by nothing else.**
  That is why moving `data/` whole is enough. It is also why anything outside that path, such as a
  folder renamed aside or a recreated old folder, is out of sight rather than lost.
- **An existing `draft.json` must still load.** Nothing moved depends on its parent folder. The new
  release's first home page runs `load_path`'s repairs on older draft shapes, as any start does
  (Round 2 §1).

### Both-sides warning

No rule shared between Python and JavaScript is involved. The contract between Python and Java
grows. Besides Round 2's address line and `VULNREPORT_STARTED_BY_BURP`, the extension now also
needs:

- the data-folder rule: `VULNREPORT_DATA_DIR`, with an empty value meaning the default
  ([app/main.py#L37](app/main.py#L37)), plus the copy of that rule A adds to `run.py`;
- the test for a report, `apps/*/*/draft.json` ([app/workspace.py#L245](app/workspace.py#L245));
- the lock file's name and the byte range locked (A);
- the `.venv` layout `run.py` expects: `Scripts/python.exe` or `bin/python`, and the stamp's name
  ([run.py#L13-L23](run.py#L13-L23)).

Each must change on both sides together.

### Map drift

- `docs/DATA_MAP.md` §1 said `main.DATA` is "resolved once at import". The source reads it once and
  uses it as typed, never `Path.resolve()`d, so a relative value is read against the process's
  working directory. I reworded it.
- §1's library paragraph now records that the older `library/vuln_library.json` value is no longer
  redirected.
- §13 gains one sharp edge: `.gitignore` names `data/` children one by one, so
  `prefs.corrupt.json`, `prefs.tmp` and any new file at the root of `data/` are not ignored.
- "Latest verification" is updated.


## Revision: Jython instead of Java

> update the Burp launcher plan. Use jython instead of java since the users already has jython setup.

**Coordinator's framing.** Only the launcher's language changes. Steps 1–4 (`run.py`), the data
layer, the Windows checks and every accepted risk stand as agreed, so no loremaster round runs. The
extension becomes a Jython 2.7 file on Burp's legacy Extender API (Montoya is Java-only). It still
only launches the Python 3 app as a separate process. The user states every tester already has
Jython configured in Burp, so the per-tester setup cost is zero.

### Round 4 - Tactician: Jython instead of Java

**What stays, what is re-planned.** Steps 1-4 (`run.py`), the data layer, the accepted risks and the
Windows checks stand. The launcher is still "start the tester's Python 3 on `run.py`, show its output,
stop it by closing its input". Only the language of the two extension halves changes, so Steps 5, 6
and 7 are rewritten below, Steps 8 and 9 and the decisions table get replacement wording, and nothing
under `app/` changes. Nothing here was executed: this Mac has no Java runtime (`java -version` fails),
so there is no Jython to run. Every "unverified" below is a fact I could not check from docs or
source, and Step 8 settles it on a machine that has Burp.

#### The legacy API pieces the launcher needs

Checked on 2026-09-30 against PortSwigger's legacy Extender API pages
(`IBurpExtenderCallbacks`, `IBurpExtender`, `ITab`, `IExtensionStateListener`).

| Piece | What the docs say | Use here | Verdict |
|---|---|---|---|
| `IBurpExtender.registerExtenderCallbacks(callbacks)` | "invoked when the extension is loaded"; implementations "must be called BurpExtender", public, with a public no-argument constructor. That sentence is written for Java (it adds "in the package burp") | class `BurpExtender` in the file; the entry point | verified for Java; that a Jython file needs the same class name is PortSwigger's Python example convention, not on these pages. Thread it runs on: not stated |
| `ITab` | `getTabCaption()`, `getUiComponent()`: "the component that should be used as the contents of the custom tab" | caption "Report Generator"; the panel | verified |
| `callbacks.addSuiteTab(tab)` | "add a custom tab to the main Burp Suite window" | once, after the panel exists | verified |
| `callbacks.setExtensionName(name)` | display name in Extender | "Report Generator" | verified |
| `IExtensionStateListener.extensionUnloaded()` via `callbacks.registerExtensionStateListener` | "called when the extension is unloaded"; extensions "that start background threads or open system resources should register a listener and terminate threads / close resources" | close the server's input, return at once | verified. Which thread calls it, any time limit, and whether Burp calls it when Burp itself exits: not stated (same doubt as round 2, so nothing depends on it) |
| `callbacks.getExtensionFilename()` | "the absolute path name of the file from which the current extension was loaded" | the app folder is its parent | verified as a string. That it is the `.py` file for a Jython extension (not a Jython or temp path) is not stated; Step 8 checks it |
| `saveExtensionSetting(name, value)` / `loadExtensionSetting(name)` | persistent, "survives reloads of the extension and of Burp Suite"; a `null` value removes the setting; load returns `null` if unset | the Python field; "Start fresh" per folder | verified. Whether they are stored per Burp project or per user is not stated (matters: see risk table) |
| `callbacks.customizeUiComponent(component)` | styles a component "in line with Burp's UI style, including font size, colors ... recursively on any child components" | called once on the whole panel | verified. Whether it makes a `JTextArea` readable in Burp's dark theme: unverified, Step 6 line 10 |
| `callbacks.printOutput(text)` / `printError(text)` | one line to "the current extension's standard output / error stream" | the launcher's own diagnostics and caught exceptions | verified. Thread safety not stated, so only the timer (Swing thread) calls them, never the reader |

Two round-2 Montoya calls have no legacy twin. `applyThemeToComponent` and `currentEditorFont()`
become `customizeUiComponent` plus a monospaced font chosen in the file. `persistence().preferences()`
becomes `saveExtensionSetting`. There is no legacy theme API, so light and dark are only what
`customizeUiComponent` gives.

#### Jython 2.7 rules for the file

These apply to Steps 5 and 6. A Jython file has no compile step, so a typo in a rarely used branch
fails only when someone reaches it; Step 5's tests exist mostly to make that impossible.

1. **Python 2.7 syntax only.** No f-strings, annotations, `nonlocal`, `yield from`, `raise ... from`,
   keyword-only arguments, and no `print` at all (`callbacks.printOutput` or the tab's own buffer).
2. **Text.** Java strings arrive as `unicode`. Literals that meet Java or `run.py`'s output are `u""`.
   Paths go through `java.io.File`, not `os.path`, so a folder with a non-ASCII character in a Windows
   user name survives. Environment values are put as unicode.
3. **Threads.** Jython has no GIL, so Python-level updates from two threads can interleave. The line
   buffer and its counter change under one `threading.Lock`. The address and the exit state are single
   assignments read by the Swing timer.
4. **Java listeners.** `Runnable` and `ActionListener` are small classes. Whether Jython 2.7 accepts a
   plain Python function where Java wants an interface is unverified, so none is passed. Each `run` and
   `actionPerformed` wraps its body in `try/except` that writes the traceback into the tab's output,
   because an exception inside a Java callback otherwise lands only in Burp's Errors pane. Loop
   variables used inside a callback are bound through a class attribute, not captured late.
5. **Java exceptions.** Handlers list `java.io.IOException` and `java.lang.Throwable` next to
   `Exception`. Whether a bare `except Exception` catches Java exceptions in 2.7 is unverified; the
   self-check has a row (a Python path that does not exist) that fails if one escapes.
6. **Blocking work.** `waitFor`, `--data-status`, `--bring-over` and the interpreter probes run on a
   `java.lang.Thread` worker and return their result with `SwingUtilities.invokeLater`. Nothing that
   waits ever runs on the Swing thread.

#### Steps 5-7, rewritten

- [ ] **Step 5 — The process half of the extension, in `burp/report_generator_burp.py` (section 1 of the file)**
  - *Files:* `burp/report_generator_burp.py` (new; the only extension file); `tests/test_launcher.py`.
  - *What:* the file is one module with three sections. Section 1 (this step) imports only `java.*`,
    `javax.*` and the Python stdlib, never `burp`, so it runs under any Jython.
    - **Starting.** `java.lang.ProcessBuilder` on a `java.util.ArrayList` (not a Python list, to avoid
      overload guessing): the interpreter words, then the absolute `run.py`.
      `redirectErrorStream(True)` merges stderr, `directory(File(appFolder))` sets the working
      directory, and `environment().put` adds exactly `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`,
      `VULNREPORT_STARTED_BY_BURP=1`. The interpreter is the tab's field, else the first of `py -3`,
      `python` (Windows) or `python3` that answers `--version` with text starting `Python 3`, probed on a
      worker.
    - **Output.** A `java.lang.Thread` running a `Runnable` reads
      `BufferedReader(InputStreamReader(process.getInputStream(), "UTF-8"))` with `readLine()`. Each
      line goes into `collections.deque(maxlen=2000)` under the lock, and the counter grows. The address
      is `line[len(FIXED_PART):]` when a line starts with the address line's fixed part, kept exactly
      as printed. That thread waits on nothing but the pipe: no `callbacks`, no Swing, no lock held
      while reading.
    - **Stopped.** The root process's exit, read by polling `process.isAlive()` and `exitValue()` from
      the tab's timer. No waiter thread, no `onExit()` lambda, and the end of output never means
      stopped (a leftover child can hold the pipe open).
    - **Stop.** `process.getOutputStream().close()`, at any stage, harmless when repeated.
    - **Force stop.** `process.toHandle().descendants().iterator()` is drained into a list first, then
      `destroyForcibly()` on each handle and then the root. `ProcessHandle` needs Java 9 or newer, and
      it is the JVM Burp runs on that matters, not Jython's own Java support. If `toHandle` is missing
      or throws, it kills the root only and adds a line to the output saying the child processes could
      not be listed. Never by process name.
    - **Commands.** `run_command(words)` (`ProcessBuilder`, merged output, `waitFor`, returns the exit
      code and text) serves `run.py --data-status` (one JSON line, read with the stdlib `json`) and
      `--bring-over`. Worker threads only.
    - **The self-check.** `java -jar <jython-standalone.jar> burp/report_generator_burp.py --self-check
      <app folder> <python>` runs when `__name__ == "__main__"` and `sys.argv[1] == "--self-check"`
      (the argv part because it is unverified whether Burp runs the file as `__main__`). In order:
      0. It runs `run.py --data-status` and **refuses, changing nothing, unless it reports zero
         reports**. This is how it never touches real data without naming the data-folder variable: a
         tester's `data/` has reports, so the check stops; the test hands it an empty temporary folder
         through its environment.
      1. Start, and wait up to 180 s for the address line (a first run installs packages).
      2. Request the address, no proxy.
      3. 50 requests with 4 KB paths, about 200 KB of access lines, without reading the buffer; every
         one answered within 30 s.
      4. Stop; exit code 0 within 15 s; the port closed.
      5. Start again, force-stop; every process seen gone; the port closed.
      6. A Python path that does not exist: a message in the buffer, no exception out of the file.
      It exits non-zero on any failure.
  - *Tests,* in `tests/test_launcher.py`:
    - `test_jython_launcher_self_check` (the one test for this step's behaviour). It runs the command
      above with the interpreter `.venv` was created from (`sys._base_executable`), so `run.py`'s
      relaunch gives a child to force-stop. The environment gets a temporary `VULNREPORT_DATA_DIR` and
      loses `VULNREPORT_BOOTSTRAPPED`; timeout 240 s; the Jython output is printed on failure. **Skipped,
      with the reason, when** `java -version` does not run (the macOS `/usr/bin/java` stub exists
      without a runtime, so the command is run, not searched for), or the environment variable
      `VULNREPORT_JYTHON_JAR` does not name an existing file, or `run.needs_install` says `.venv` is not
      current. The variable is named only in the test, never in the file. A tester's Burp already has a
      Jython jar, so a developer can point the variable at that one.
    - `test_burp_file_uses_only_python_2_7_syntax`. It always runs, without Java: `ast.parse` the file
      under the test's Python 3 and walk the tree for `JoinedStr`, `AnnAssign`, `NamedExpr`,
      `Nonlocal`, `YieldFrom`, `Await`, `AsyncFunctionDef`, argument annotations and `raise ... from`.
      Its floor: a probe snippet holding each construct must be flagged, so the walker cannot pass by
      checking nothing. This is what stands between a Python 3 habit and a load error in Burp on a
      machine with no Jython.
    - `test_burp_file_shares_only_two_names_with_run_py`. Reads the file. Asserts that the address
      line's fixed part and `VULNREPORT_STARTED_BY_BURP`, both taken from `run`'s constants, appear,
      and that neither `VULNREPORT_DATA_DIR` nor `VULNREPORT_PORT` does. Rename either constant on one
      side, or write either variable into the file, and it fails.
    - `test_self_check_refuses_a_data_folder_that_has_reports`. Same skip rule minus the `.venv`
      condition (it never starts a server). A temporary data folder with one planted `draft.json`:
      non-zero exit, the message says reports were found, no server started, and the folder's contents
      are byte-for-byte as planted.
  - *Invariant:* the reader thread waits on nothing but the pipe, so nothing the tab does can stall the
    server's output; the extension kills only the root and the descendants it had when Force stop was
    pressed; and the self-check can never run against a data folder that holds a report.

- [ ] **Step 6 — The Burp tab (sections 2 and 3 of the same file)**
  - *Files:* `burp/report_generator_burp.py`; `tests/test_launcher.py`.
  - *What:*
    - **Section 2, `LauncherPanel`,** plain Swing and no `burp` import, so the self-check can build it
      headless. It takes four injected things: `settings` (get and set a string), `open_browser(url)`,
      `dialogs` (the bring-over question) and `log(text)`. That is what lets the self-check drive it
      with fakes. It builds: the status line (Stopped with the exit code when not 0 / Setting up /
      Running at `<address>` with **Open** / Stopping with **Force stop**), the Python field, **Start**
      (disabled until the previous process has exited), **Stop** (becomes **Force stop** while
      stopping), and a `JTextArea` output whose first lines are the folder and the exact command. A
      `javax.swing.Timer` every 250 ms polls `isAlive()`, copies a snapshot of the buffer when the
      counter changed, moves the status, and, the first time the address appears after a Start, calls
      `open_browser(address)` once. Start's first-run question (Bring reports over / Start fresh /
      Cancel), the worker threads and the messages are as agreed in the round-3 wording of this step;
      only their mechanics change to Jython (rule 6).
    - **Section 3, `BurpExtender(IBurpExtender, ITab, IExtensionStateListener)`.** The `burp` imports
      sit in a `try/except ImportError` so the file still loads under a plain Jython for the
      self-check. `registerExtenderCallbacks`: `setExtensionName("Report Generator")`; the app folder
      is `File(callbacks.getExtensionFilename()).getParentFile()`, and without a `run.py` there the tab
      says to load the file from the Report Generator folder and Start stays disabled;
      `registerExtensionStateListener(self)` first (so unload works even if the UI fails); then
      `SwingUtilities.invokeLater` builds the panel, calls `customizeUiComponent` on it, sets a
      monospaced font on the output at the size `customizeUiComponent` gave it, and calls
      `addSuiteTab(self)`. `settings` is `saveExtensionSetting` / `loadExtensionSetting` (keys: the
      Python path; `fresh:<folder>`), `log` is `printError`, `open_browser` is `Desktop.browse`
      guarded by `Desktop.isDesktopSupported()`, with the address left on the status line when the
      desktop cannot. `extensionUnloaded` calls `stop()`, then schedules the timer's stop with
      `invokeLater`, and returns; it touches no other Swing object, because its thread is unknown.
  - *Tests:*
    - `test_jython_tab_starts_stops_and_opens_the_browser_once`, in `tests/test_launcher.py`, same skip
      rule as Step 5. It runs `... --self-check-panel <app folder> <python>` with
      `java.awt.headless=true`: build `LauncherPanel` with a dict as `settings`, a recording
      `open_browser`, and `dialogs` answering Start fresh. It presses Start through
      `SwingUtilities.invokeAndWait`, waits for "Running at", presses Stop, waits for "Stopped", and
      exits non-zero unless: the recording holds exactly one URL and it equals the printed address;
      the exit code was 0; `settings` holds the Start fresh mark; and a second Start asks nothing.
      Remove the once-only guard and watch it fail. It exists because a typo in the tab is otherwise
      found by a tester.
    - Round 2's ten-line checklist, on macOS and Windows, with line 1 now "Load
      `report_generator_burp.py` (type Python): a Report Generator tab appears, and its status line
      names that folder", line 2 "load a copy of the file alone from another folder: the message
      appears and Start stays disabled", and a new **line 11: after every other line, Extender's
      Errors pane holds nothing from this extension** (a swallowed Jython exception would sit there).
      Then the four bring-over and Start fresh lines already listed under this step.
  - *Invariant:* the extension passes no data folder and no port; no `waitFor`, subprocess or folder
    scan runs on the Swing thread; the address is never rewritten (never `localhost`); the folder, the
    command and the address are always printed.

- [ ] **Step 7 — Release: ship the file, no build**
  - *Files:* `scripts/package_release.py`; `tests/test_launcher.py`; `README.md`; `docs/DATA_MAP.md` §1
    (the zip's contents gain `report_generator_burp.py`) and the verification line.
  - *What:*
    - **The file.** `burp/report_generator_burp.py` in the repository, copied by `build_release` to the
      **root of the release folder, beside `run.py`**, under the same name. The app folder is the
      file's parent, so it must sit next to `run.py`. `package_release.py` no longer compiles anything,
      downloads nothing, pins no hash and needs no JDK or Montoya jar; the release's only extension
      code is that readable `.py`, which anyone can open before loading it. The `burp/` folder itself is
      not shipped.
    - **The README** (ships in the zip): what changes from the agreed list is the first bullet.
      "Extensions, Add, type Python, choose `report_generator_burp.py` in this folder. Burp's Python
      environment must already point at a Jython standalone JAR." Keep the file in the folder Burp
      loaded it from; if you move the folder, add it again. Everything else in the agreed Step 7 list
      stands: Start, Stop and Force stop with the two accepted risks, the local address from 8765 up
      and unsaved browser work tied to its port, Bring reports over and its manual form, deleting
      `.venv` after an interrupted setup.
  - *Test:* `test_release_zip_carries_the_burp_file_at_the_root`: build a release into a temporary
    `DIST`; the zip lists `<name>/report_generator_burp.py` and `<name>/run.py` (the positive case);
    the extension file is byte-identical to `burp/report_generator_burp.py`; and no member sits under
    `data/` or `generated/` or ends in `.jar`. Then by hand: load the file from an unzipped copy and
    repeat Step 6's checklist lines 1 and 3.
  - *Invariant:* the zip still carries no drafts, evidence or finished documents, and now no compiled
    or downloaded code either.

#### Steps 8-9 and the decisions table: replacement wording

- **Step 8.** Items a-f and h-l stand. Item g becomes: "from a checkout with Java and a Jython jar
  named by `VULNREPORT_JYTHON_JAR`, `.venv\Scripts\python -m unittest tests.test_launcher` passes with
  the Jython tests run, not skipped." Add three checks, results recorded in this plan:
  - m. **What Burp really does:** Burp's version, the Jython version and the Java version the Burp on
    that machine runs; `getExtensionFilename()` returns the `.py` with `run.py` beside it; Force stop's
    output shows no "could not list child processes" line (so `ProcessHandle` works); the tab is
    readable in light and dark (Step 6 line 10); and whether the saved Python field survives closing
    and reopening a Burp project.
  - n. **Non-ASCII path:** unzip a release into a folder whose name has an accented letter, load the
    file, Start, Stop. (Jython `str` and `unicode` is where this breaks first.)
  - o. **Oldest tester setup:** repeat lines 1, 3 and 6 of Step 6 on the oldest Burp and Jython the
    testers run (open question 2).
- **Step 9.** The `.github/copilot-instructions.md` line reads: "`burp/report_generator_burp.py` is
  the Burp launcher, one Jython 2.7 file on the legacy Extender API; checked by
  `tests/test_launcher.py` (its Jython self-checks run when `java` and `VULNREPORT_JYTHON_JAR` are
  available; a syntax test always runs) and by Step 6's checklist." Add `VULNREPORT_JYTHON_JAR` to
  `.github/instructions/tests.instructions.md` only if the author wants it documented there; the
  copilot line is enough. The `--affected` run still lists `burp/` under "No rule for these" and
  picks every Python module, and the answer by hand is unchanged: run `tests.test_launcher`.
- **Decisions table.** Replace these rows; the others stand.

  | Choice | Taken |
  |---|---|
  | Extension | One Jython 2.7 file on Burp's legacy Extender API; testers already have Jython set up in Burp; no JDK, no compile step, no release build |
  | App folder | The parent of `callbacks.getExtensionFilename()`, the file beside `run.py`; elsewhere, Start stays disabled |
  | Output | One `java.lang.Thread` drains the pipe into a 2,000-line buffer under a lock and never waits on Burp's UI; a `javax.swing.Timer` copies it into the tab |
  | Carrying data into a new release | `run.py` does the move and the `.venv` copy, following the app's own rules; the Jython tab only asks and shows the result |

- **Other sentences that name Java** in the agreed plan: in "What gets built", "A Java Burp extension,
  `ReportGenerator-Burp.jar`" becomes "A Jython Burp extension, `report_generator_burp.py`", and "Java
  thread" becomes "worker thread". In "Deliberately not done", "starting `.venv`'s interpreter directly
  from Java" becomes "from the extension". The Step 5 mention in the Data risks table of a Python-to-Java
  contract now reads Python-to-Jython; the same two names, pinned by the same test.

#### Costs and risks of the switch

| | Verdict | Reasoning |
|---|---|---|
| Legacy API longevity | RISK | PortSwigger's extension page says "the Extender API is no longer actively maintained" and "strongly recommend[s]" Java on Montoya. The file uses about eight stable calls (table above), and the app, `run.py` and its tests do not depend on the API, so if a future Burp drops it, only this one file is ported. Accepted with the switch |
| Python 2.7 and Jython's own support | RISK | jython.org: Jython 2.7.4 is supported on Java 8 and 11, and 2.7.5b1 adds 17 and 25. Which Java the testers' Burp runs was not verifiable here. Jython 2.7 on newer Java is widely used but outside the stated support. Step 8m records the versions |
| Testers without Jython | clear | You state every tester has it. A Burp with Jython missing shows its own load error in Extender, not our message, because our code never runs; the README says what is required |
| No compiler: errors show only at run time | RISK, reduced | The always-running syntax test, the headless panel drive and rule 4's traceback-to-tab wrapper cover it; a branch none of them reaches can still hide a typo. Step 6 line 11 (empty Errors pane) is the last net |
| Tests need Java and a Jython jar | RISK | Without them, the process half is only syntax-checked and the tests are skipped with the reason. This Mac has no Java today. The old Java plan needed a JDK on every developer machine; this needs a runtime and one jar path |
| `ProcessHandle` on the Burp JVM | RISK, unverified | Needs Java 9 or newer. If missing, Force stop kills the root only and says so in the tab, which can leave the server behind. Step 8m checks |
| Saved settings scope | RISK, unverified | The docs do not say per project or per user. If per project (and gone in a temporary project), the Python field and Start fresh do not carry over, so a tester sees the Start fresh question again in an empty folder. Nothing is lost |
| Non-ASCII paths, `str` vs `unicode` | RISK | Handled by rules 2 and `java.io.File`; Step 8n checks it |
| Shared state without a GIL | RISK, handled | One lock, one writer per value, rule 3 |
| Theme and look | RISK | No legacy theme call; `customizeUiComponent` only. Verified by screenshot in Step 6 line 10, in both themes |
| Release build and supply chain | clear, better than the Java plan | No JDK, no Maven download, no pinned jar or hash, nothing compiled; the shipped code is readable source |
| Data layer, saves, kill outcomes, port and lock behaviour | clear | Nothing changes: `run.py` is untouched by this switch, and the process guarantees are the same `java.lang.Process` calls |

#### Open questions

1. **Where does the Jython jar for the tests come from?**
   - *Background.* The process half now runs only under Jython, so the tests that exercise it need a
     Java runtime and a Jython standalone jar.
   - *Options.* (a) The tests read `VULNREPORT_JYTHON_JAR` and skip with a reason when it is missing.
     (b) The test downloads `jython-standalone-2.7.4.jar` from Maven Central into `dist/`, checked
     against a pinned hash. (c) Do not test the Jython half at all.
   - *Trade-offs.* (a) needs a one-time setting per developer machine and skips silently-ish elsewhere;
     the always-run syntax test still guards the file. (b) makes the tests run everywhere but adds a
     network fetch and a pinned hash to the test run, which the plan avoided in the release script. (c)
     leaves the process half untested.
   - *Recommendation.* (a).
   - *Absent an answer.* (a), which the steps above assume.
2. **Which Burp, Jython and Java versions do the testers actually run?**
   - *Background.* Jython 2.7.4 lists Java 8 and 11, and testers' Burp bundles a Java I could not
     confirm. The file avoids anything newer than Jython 2.7.0 syntax, but `ProcessHandle` needs Java 9
     or newer.
   - *Options.* (a) Record the versions in Step 8m and accept them. (b) You tell me now, and I fix a
     minimum in the README.
   - *Trade-offs.* (a) finds out at the end; (b) costs you a minute now and lets the README promise
     something.
   - *Recommendation.* (b) if you know them, else (a).
   - *Absent an answer.* (a).

Nothing else is waiting on a decision. One more note for the coordinator: the file is deliberately
one module, because Burp loads one file and extra modules would need path handling that I cannot
verify; expect roughly 400 lines.

## Answers

Asked one at a time on 2026-09-30.

1. **Company rule — cleared.** The user has confirmed the rule allows a local web server started by a
   Burp extension, so the whole plan proceeds. Nothing hides or disguises the server.
2. **Packaging — a small launcher inside the release folder** (a JAR when asked; answer 6 made it one
   Jython `.py` file, same place). The app and `data/` stay where they
   are today; testers add the JAR from the release folder in Burp. (Rejected: one JAR that unpacks the
   app into a per-user folder, which would need a draft move, a `generated/` setting, and would run
   the app from a folder testers never see.)
3. **Port — keep the first-free-port scan and add a lock in the data folder**, so a second copy of the
   app on the same data folder refuses to start. (Rejected, against the planners' recommendation: a
   fixed 8765. Accepted consequence: when another program holds 8765 the port shifts, and unsaved
   browser work saved under the previous port stays out of sight until the app runs on that port again.)
4. **Carrying drafts into a new release — the extension moves `data/` itself.** On the first Start with
   an empty `data/`, it asks for the previous release folder and moves that folder's `data/` in. The
   user added two requirements: **copy the previous `.venv` too**, so dependencies are not downloaded
   again; and when there is no previous folder, offer **Start fresh**. Coordinator's note recorded
   with the answer: a virtual environment is not guaranteed to work after being copied to another
   folder, so the copy is verified by importing the app's packages with it and, if that fails, deleted
   and rebuilt by `run.py` with a normal download.

5. **The import/duplicate write-order fix — declined.** Nothing under `app/` changes. Accepted risk,
   recorded so nobody rediscovers it as a surprise: a kill between an import's or duplicate's
   `draft.json` and its PNGs (Force stop, Burp's exit if it kills children, or a console Ctrl+C, as
   today) leaves a report listing screenshots that do not exist. The README says so beside Force stop.

6. **Extension language — Jython instead of Java** (a later request, same day): every tester already
   has Jython configured in Burp. The Java steps were re-planned in *Round 4* above.
7. **Jython tests — `VULNREPORT_JYTHON_JAR`, skip when missing.** No download. (Rejected: a pinned
   40 MB download on first test run.) The Burp, Jython and Java versions testers run are recorded in
   Step 8m rather than asked now.

## Agreed plan
Readable on its own. It combines round 2's revised plan, the five answers, and round 3's check of the
data move the answers added. Nothing under `app/` changes (answer 5).

**What gets built.** A Jython Burp extension, `report_generator_burp.py`, one file shipped beside
`run.py` in the release folder (answers 2 and 6). Its tab shows the app's output and has Start, Stop / Force stop and Open. Start runs
the tester's Python 3 on the folder's `run.py`, exactly as a console start does. The server, the
browser page and `data/` are unchanged, and nothing hides what runs: the tab prints the folder, the
command and the address (answer 1).

**Decisions the steps rely on** (reasoning in the rounds above):

| Choice | Taken |
|---|---|
| Extension | One Jython 2.7 file on Burp's legacy Extender API; testers already have Jython set up in Burp; no JDK, no compile step, no release build (answer 6) |
| App folder | The parent of `callbacks.getExtensionFilename()`, the file beside `run.py`; elsewhere, Start stays disabled |
| Python | The tester's own Python 3 (`py -3`, then `python` on Windows; `python3` elsewhere), or a path set in the tab |
| Port | Today's first-free-port scan from 8765, unchanged (answer 3) |
| One server per data folder | A lock file in the data folder, taken by `run.py` (answer 3) |
| Ready and address | `run.py` prints the address line, flushed, only after uvicorn has bound the port |
| Browser | The system default browser, opened once when the address line arrives, plus Open |
| Stop | Close the server's standard input at every stage; running requests, including a Word pass, finish. Force stop, pressed by the tester, kills the process tree. Nothing kills on a timer |
| Unload / Burp exit | Close the input and return; no deadline, no kill |
| Jython tests | The self-checks read the Jython JAR from `VULNREPORT_JYTHON_JAR` and skip, saying why, without it or Java; a Python 2.7 syntax test always runs (answer 7) |
| Output | One `java.lang.Thread` drains the pipe into a 2,000-line buffer under a lock and never waits on Burp's UI; a `javax.swing.Timer` copies it into the tab |
| Carrying data into a new release | `run.py` does the move and the `.venv` copy, following the app's own rules; the Jython tab only asks and shows the result (answer 4, round 3 finding 6) |

- [x] **Step 1 — `run.py`: one server per data folder, and a data folder that never splits**
  - *Files:* `run.py`; `tests/test_launcher.py`; `.gitignore`; `docs/DATA_MAP.md` §1 and §13 and the
    verification line; `docs/ARCHITECTURE.md` (Configuration table).
  - *What:*
    - `data_dir()` follows `app/main.py`'s rule: `VULNREPORT_DATA_DIR` when set and not empty, else
      `<app>/data`. A relative value is resolved once, against the directory `run.py` was started in,
      and written back to the environment as an absolute path, so the relaunched child (which runs from
      the app folder) serves the same folder the parent locked (round 3, finding 2).
    - `DATA-MOVED.txt` check first: if `<app>/DATA-MOVED.txt` exists and the variable is not set, print
      its contents (where the data went) and exit non-zero, before anything creates `data/`
      (finding 5).
    - The lock: create the data folder, open `<data>/server.lock`, `seek(0)`, and take a non-blocking
      exclusive lock on byte 0 (`msvcrt.locking` on Windows; `fcntl.lockf` elsewhere, the record lock
      the JVM's `FileChannel.tryLock` also uses). Retry for up to 5 s, so a Start right after a Stop is not
      refused. Held for the life of the process. Taken by every start except the relaunched child
      (`VULNREPORT_BOOTSTRAPPED` set), whose parent already holds it, so the direct
      `.venv/bin/python run.py` start is covered too (finding 1). Refusal: "Report Generator is already
      running on <data folder>. Use that one, or stop it first." and exit non-zero.
    - `.gitignore`: `data/server.lock`, `data.before-move-*/`, `DATA-MOVED.txt` (finding 7).
  - *Tests,* in `tests/test_launcher.py`:
    - `test_data_dir_follows_the_apps_rule`: rows for unset, empty, absolute and relative values;
      each equals what `app.main` would serve, with the relative row started from another directory.
    - `test_a_second_start_on_the_same_data_folder_is_refused`: a child process holds the lock; the
      second start exits non-zero with the message naming the folder. Remove the lock once and watch it
      fail.
    - `test_the_lock_is_released_when_its_process_dies`: kill the holder; the next start gets the lock.
    - `test_a_folder_whose_data_moved_refuses_to_start`: with `DATA-MOVED.txt` present, exit non-zero,
      and `data/` was not created.
  - *Invariant:* a console start on a machine with one server behaves as today. The lock is released by
    the OS on any death, so a killed server never blocks the next start. No draft is read or written.

- [x] **Step 2 — `run.py`: address line after the bind, stop at end of input, clean Ctrl+C**
  - *Files:* `run.py`; `tests/test_launcher.py`; `docs/DATA_MAP.md` §3; `docs/ARCHITECTURE.md`
    (`VULNREPORT_STARTED_BY_BURP` in the Configuration table).
  - *What:* round 2's Step 3, unchanged except the port stays scanned. `serve()` runs
    `uvicorn.Server` through a subclass whose `startup` prints the address line with `flush=True` after
    the bind. With `VULNREPORT_STARTED_BY_BURP=1`, a daemon thread reads standard input to its end and
    then sets `server.should_exit`; no browser opens and "Close this window…" is not printed. In every
    mode, `server.run()` sits inside `try/except KeyboardInterrupt`.
  - *Tests:* round 2's `ServeTests`: the address line is printed only once a request answers; end of
    input stops only a Burp-started server (three rows, including input already closed at start); a
    console Ctrl+C exits 0 without a traceback (macOS and Linux only).
  - *Invariant:* a console start keeps its browser, its message and its Ctrl+C.

- [x] **Step 3 — `run.py`: hand the extension's pipes to every child process**
  - *Files:* `run.py`; `tests/test_launcher.py`.
  - *What:* with `VULNREPORT_STARTED_BY_BURP=1`, `bootstrap()` and `relaunch()` pass
    `stdin/stdout/stderr` to `subprocess.run`, so the pipe reaches the server on Windows.
  - *Test:* `test_children_receive_the_launchers_streams`, two rows (with and without the variable).
  - *Invariant:* console starts are unchanged.

- [x] **Step 4 — `run.py`: carry drafts and `.venv` over from a previous release**
  - *Files:* `run.py`; `tests/test_launcher.py`; `docs/DATA_MAP.md` §1; `README.md` (manual steps).
  - *What:* two standard-library commands the extension calls with the system Python, before Start.
    `.venv` is not needed to run them.
    - `run.py --data-status` prints one JSON line: the data folder, its report count, whether its lock
      is held, and whether `.venv` exists. A report is any `apps/*/*/draft.json`, readable or not: the
      same rule as `Workspace.find_path` (finding 6).
    - `run.py --bring-over <old folder>` moves the previous release's data in:
      - *Checks, all before touching anything:* the old folder holds `run.py` and reports and is not
        this folder; it has no `DATA-MOVED.txt`; its lock, if it has one, can be taken; this folder's
        own lock can be taken (finding 3); this folder's data has no reports. Any failed check stops
        with a message and changes nothing.
      - *The move:* if this folder already has a `data/` without reports (a Start already made
        `prefs.json`, `.locks` and the log there), rename it to `data.before-move-<timestamp>`, never
        delete it. Then rename `<old>/data` to `<this>/data` in one `os.rename`. A different drive
        (`EXDEV`) stops with the README's manual steps instead of copying. On Windows a folder with an
        open file refuses the rename, which also catches an old server still running; the error is
        reported and nothing has moved. `<old>/generated/` moves the same way when this folder's
        `generated/` holds nothing but `.gitkeep`.
      - *Afterwards:* write `<old>/DATA-MOVED.txt` naming this folder and the date.
      - *`.venv` (the user's addition):* when this folder has none, copy `<old>/.venv` with symlinks kept
        as symlinks, then run the copy's interpreter with
        `-c "import fastapi, uvicorn, pydantic, jinja2, multipart, docx, PIL._imaging"` (plus
        `win32com.client` on Windows): the modules `app.main` loads at import, including compiled parts
        (finding 9). On failure, delete the copy (only the copy) so the next Start rebuilds it with a
        normal download. A copy without the requirements stamp gets a `pip install` over it on first
        Start, which finds everything already there (finding 8). Whether a copied virtual environment
        works is Python packaging, so Step 8 checks it on Windows.
    - Old releases have no lock file, and on macOS and Linux a rename does not stop an old server that
      is still running: its next save would recreate `<old>/data` (finding 4). The command cannot see
      that, so the tab asks the tester to confirm the old app is stopped (Step 6).
  - *Tests,* all with temporary folders, never `data/`:
    - `test_bring_over_moves_every_report_and_marks_the_old_folder`: both folders' contents before and
      after; no report exists twice; `DATA-MOVED.txt` names the new folder.
    - `test_bring_over_sets_aside_an_empty_data_folder_and_refuses_one_with_reports`: two rows.
    - `test_bring_over_refuses_while_either_folder_is_locked`: two rows; nothing moved.
    - `test_bring_over_keeps_a_working_venv_and_removes_a_broken_copy`: a real copy of the test
      interpreter's environment passes; a fake whose import fails is deleted.
    - `test_data_status_counts_reports_the_way_the_workspace_finds_them`: equals the drafts
      `Workspace` scans, including an unreadable one.
  - *Invariant:* never deletes or overwrites a report, a PNG, `prefs.json`, a log or a finished
    document; data is renamed, never copied, so there is one store; every failure before the rename
    leaves both folders exactly as they were.

- [x] **Step 5 — The process half of the extension, in `burp/report_generator_burp.py` (section 1 of the file)**
  - *Files:* `burp/report_generator_burp.py` (new; the only extension file); `tests/test_launcher.py`.
  - *What:* the file is one module with three sections. Section 1 (this step) imports only `java.*`,
    `javax.*` and the Python stdlib, never `burp`, so it runs under any Jython.
    - **Starting.** `java.lang.ProcessBuilder` on a `java.util.ArrayList` (not a Python list, to avoid
      overload guessing): the interpreter words, then the absolute `run.py`.
      `redirectErrorStream(True)` merges stderr, `directory(File(appFolder))` sets the working
      directory, and `environment().put` adds exactly `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`,
      `VULNREPORT_STARTED_BY_BURP=1`. The interpreter is the tab's field, else the first of `py -3`,
      `python` (Windows) or `python3` that answers `--version` with text starting `Python 3`, probed on a
      worker.
    - **Output.** A `java.lang.Thread` running a `Runnable` reads
      `BufferedReader(InputStreamReader(process.getInputStream(), "UTF-8"))` with `readLine()`. Each
      line goes into `collections.deque(maxlen=2000)` under the lock, and the counter grows. The address
      is `line[len(FIXED_PART):]` when a line starts with the address line's fixed part, kept exactly
      as printed. That thread waits on nothing but the pipe: no `callbacks`, no Swing, no lock held
      while reading.
    - **Stopped.** The root process's exit, read by polling `process.isAlive()` and `exitValue()` from
      the tab's timer. No waiter thread, no `onExit()` lambda, and the end of output never means
      stopped (a leftover child can hold the pipe open).
    - **Stop.** `process.getOutputStream().close()`, at any stage, harmless when repeated.
    - **Force stop.** `process.toHandle().descendants().iterator()` is drained into a list first, then
      `destroyForcibly()` on each handle and then the root. `ProcessHandle` needs Java 9 or newer, and
      it is the JVM Burp runs on that matters, not Jython's own Java support. If `toHandle` is missing
      or throws, it kills the root only and adds a line to the output saying the child processes could
      not be listed. Never by process name.
    - **Commands.** `run_command(words)` (`ProcessBuilder`, merged output, `waitFor`, returns the exit
      code and text) serves `run.py --data-status` (one JSON line, read with the stdlib `json`) and
      `--bring-over`. Worker threads only.
    - **The self-check.** `java -jar <jython-standalone.jar> burp/report_generator_burp.py --self-check
      <app folder> <python>` runs when `__name__ == "__main__"` and `sys.argv[1] == "--self-check"`
      (the argv part because it is unverified whether Burp runs the file as `__main__`). In order:
      0. It runs `run.py --data-status` and **refuses, changing nothing, unless it reports zero
         reports**. This is how it never touches real data without naming the data-folder variable: a
         tester's `data/` has reports, so the check stops; the test hands it an empty temporary folder
         through its environment.
      1. Start, and wait up to 180 s for the address line (a first run installs packages).
      2. Request the address, no proxy.
      3. 50 requests with 4 KB paths, about 200 KB of access lines, without reading the buffer; every
         one answered within 30 s.
      4. Stop; exit code 0 within 15 s; the port closed.
      5. Start again, force-stop; every process seen gone; the port closed.
      6. A Python path that does not exist: a message in the buffer, no exception out of the file.
      It exits non-zero on any failure.
  - *Tests,* in `tests/test_launcher.py`:
    - `test_jython_launcher_self_check` (the one test for this step's behaviour). It runs the command
      above with the interpreter `.venv` was created from (`sys._base_executable`), so `run.py`'s
      relaunch gives a child to force-stop. The environment gets a temporary `VULNREPORT_DATA_DIR` and
      loses `VULNREPORT_BOOTSTRAPPED`; timeout 240 s; the Jython output is printed on failure. **Skipped,
      with the reason, when** `java -version` does not run (the macOS `/usr/bin/java` stub exists
      without a runtime, so the command is run, not searched for), or the environment variable
      `VULNREPORT_JYTHON_JAR` does not name an existing file, or `run.needs_install` says `.venv` is not
      current. The variable is named only in the test, never in the file. A tester's Burp already has a
      Jython jar, so a developer can point the variable at that one.
    - `test_burp_file_uses_only_python_2_7_syntax`. It always runs, without Java: `ast.parse` the file
      under the test's Python 3 and walk the tree for `JoinedStr`, `AnnAssign`, `NamedExpr`,
      `Nonlocal`, `YieldFrom`, `Await`, `AsyncFunctionDef`, argument annotations and `raise ... from`.
      Its floor: a probe snippet holding each construct must be flagged, so the walker cannot pass by
      checking nothing. This is what stands between a Python 3 habit and a load error in Burp on a
      machine with no Jython.
    - `test_burp_file_shares_only_two_names_with_run_py`. Reads the file. Asserts that the address
      line's fixed part and `VULNREPORT_STARTED_BY_BURP`, both taken from `run`'s constants, appear,
      and that neither `VULNREPORT_DATA_DIR` nor `VULNREPORT_PORT` does. Rename either constant on one
      side, or write either variable into the file, and it fails.
    - `test_self_check_refuses_a_data_folder_that_has_reports`. Same skip rule minus the `.venv`
      condition (it never starts a server). A temporary data folder with one planted `draft.json`:
      non-zero exit, the message says reports were found, no server started, and the folder's contents
      are byte-for-byte as planted.
  - *Invariant:* the reader thread waits on nothing but the pipe, so nothing the tab does can stall the
    server's output; the extension kills only the root and the descendants it had when Force stop was
    pressed; and the self-check can never run against a data folder that holds a report.

- [x] **Step 6 — The Burp tab (sections 2 and 3 of the same file)**
  - *Files:* `burp/report_generator_burp.py`; `tests/test_launcher.py`.
  - *What:*
    - **Section 2, `LauncherPanel`,** plain Swing and no `burp` import, so the self-check can build it
      headless. It takes four injected things: `settings` (get and set a string), `open_browser(url)`,
      `dialogs` (the bring-over question) and `log(text)`. That is what lets the self-check drive it
      with fakes. It builds: the status line (Stopped with the exit code when not 0 / Setting up /
      Running at `<address>` with **Open** / Stopping with **Force stop**), the Python field, **Start**
      (disabled until the previous process has exited), **Stop** (becomes **Force stop** while
      stopping), and a `JTextArea` output whose first lines are the folder and the exact command. A
      `javax.swing.Timer` every 250 ms polls `isAlive()`, copies a snapshot of the buffer when the
      counter changed, moves the status, and, the first time the address appears after a Start, calls
      `open_browser(address)` once. Start's first-run question (Bring reports over / Start fresh /
      Cancel), the worker threads and the messages are as agreed in the round-3 wording of this step;
      only their mechanics change to Jython (rule 6).
    - **Section 3, `BurpExtender(IBurpExtender, ITab, IExtensionStateListener)`.** The `burp` imports
      sit in a `try/except ImportError` so the file still loads under a plain Jython for the
      self-check. `registerExtenderCallbacks`: `setExtensionName("Report Generator")`; the app folder
      is `File(callbacks.getExtensionFilename()).getParentFile()`, and without a `run.py` there the tab
      says to load the file from the Report Generator folder and Start stays disabled;
      `registerExtensionStateListener(self)` first (so unload works even if the UI fails); then
      `SwingUtilities.invokeLater` builds the panel, calls `customizeUiComponent` on it, sets a
      monospaced font on the output at the size `customizeUiComponent` gave it, and calls
      `addSuiteTab(self)`. `settings` is `saveExtensionSetting` / `loadExtensionSetting` (keys: the
      Python path; `fresh:<folder>`), `log` is `printError`, `open_browser` is `Desktop.browse`
      guarded by `Desktop.isDesktopSupported()`, with the address left on the status line when the
      desktop cannot. `extensionUnloaded` calls `stop()`, then schedules the timer's stop with
      `invokeLater`, and returns; it touches no other Swing object, because its thread is unknown.
  - *Tests:*
    - `test_jython_tab_starts_stops_and_opens_the_browser_once`, in `tests/test_launcher.py`, same skip
      rule as Step 5. It runs `... --self-check-panel <app folder> <python>` with
      `java.awt.headless=true`: build `LauncherPanel` with a dict as `settings`, a recording
      `open_browser`, and `dialogs` answering Start fresh. It presses Start through
      `SwingUtilities.invokeAndWait`, waits for "Running at", presses Stop, waits for "Stopped", and
      exits non-zero unless: the recording holds exactly one URL and it equals the printed address;
      the exit code was 0; `settings` holds the Start fresh mark; and a second Start asks nothing.
      Remove the once-only guard and watch it fail. It exists because a typo in the tab is otherwise
      found by a tester.
    - Round 2's ten-line checklist, on macOS and Windows, with line 1 now "Load
      `report_generator_burp.py` (type Python): a Report Generator tab appears, and its status line
      names that folder", line 2 "load a copy of the file alone from another folder: the message
      appears and Start stays disabled", and a new **line 11: after every other line, Extender's
      Errors pane holds nothing from this extension** (a swallowed Jython exception would sit there).
      Then the four bring-over and Start fresh lines already listed under this step.
  - *Invariant:* the extension passes no data folder and no port; no `waitFor`, subprocess or folder
    scan runs on the Swing thread; the address is never rewritten (never `localhost`); the folder, the
    command and the address are always printed.

- [x] **Step 7 — Release: ship the file, no build**
  - *Files:* `scripts/package_release.py`; `tests/test_launcher.py`; `README.md`; `docs/DATA_MAP.md` §1
    (the zip's contents gain `report_generator_burp.py`) and the verification line.
  - *What:*
    - **The file.** `burp/report_generator_burp.py` in the repository, copied by `build_release` to the
      **root of the release folder, beside `run.py`**, under the same name. The app folder is the
      file's parent, so it must sit next to `run.py`. `package_release.py` no longer compiles anything,
      downloads nothing, pins no hash and needs no JDK or Montoya jar; the release's only extension
      code is that readable `.py`, which anyone can open before loading it. The `burp/` folder itself is
      not shipped.
    - **The README** (ships in the zip): what changes from the agreed list is the first bullet.
      "Extensions, Add, type Python, choose `report_generator_burp.py` in this folder. Burp's Python
      environment must already point at a Jython standalone JAR." Keep the file in the folder Burp
      loaded it from; if you move the folder, add it again. Everything else in the agreed Step 7 list
      stands: Start, Stop and Force stop with the two accepted risks, the local address from 8765 up
      and unsaved browser work tied to its port, Bring reports over and its manual form, deleting
      `.venv` after an interrupted setup.
  - *Test:* `test_release_zip_carries_the_burp_file_at_the_root`: build a release into a temporary
    `DIST`; the zip lists `<name>/report_generator_burp.py` and `<name>/run.py` (the positive case);
    the extension file is byte-identical to `burp/report_generator_burp.py`; and no member sits under
    `data/` or `generated/` or ends in `.jar`. Then by hand: load the file from an unzipped copy and
    repeat Step 6's checklist lines 1 and 3.
  - *Invariant:* the zip still carries no drafts, evidence or finished documents, and now no compiled
    or downloaded code either.

- [ ] **Step 8 — Check on Windows what reading code cannot settle**
  - *Files:* none; record each result in this plan, under this step.
  - *What:* round 2's Step 8 items a–i, with d and e now about the lock: Stop then Start gets the same
    port back, and a console `run.py` in the same folder is refused by the lock. Plus:
    - j. Bring over with the old app stopped: the rename succeeds, the copied `.venv` passes its import
      check, and the first Start downloads nothing.
    - k. Bring over with the old app running: the rename is refused and nothing moves.
    - l. A generation from the Burp-started server: Word's pass runs, and the document lands in
      `generated/`. The document side is otherwise unexamined, because no scribe round ran.
    - Item g now reads: from a checkout with Java and a Jython jar named by `VULNREPORT_JYTHON_JAR`,
      `.venv\Scripts\python -m unittest tests.test_launcher` passes with the Jython tests run, not
      skipped.
    - m. What Burp really does: the Burp, Jython and Java versions on that machine;
      `getExtensionFilename()` returns the `.py` with `run.py` beside it; Force stop's output has no
      "could not list child processes" line (`ProcessHandle` works); the tab is readable in light and
      dark; whether the saved Python field survives closing and reopening a Burp project.
    - n. A release unzipped into a folder whose name has an accented letter: load, Start, Stop.
    - o. Lines 1, 3 and 6 of Step 6's checklist on the oldest Burp and Jython the testers run.
  - *Invariant:* scratch reports only; nothing touches a tester's real drafts.

- [ ] **Step 9 — Close out**
  - *Files:* this plan (status `shipped`, date, commit, what deviated); `.github/copilot-instructions.md`
    (one line: `burp/report_generator_burp.py` is the Burp launcher, one Jython 2.7 file on the legacy
    Extender API, checked by `tests/test_launcher.py`, whose Jython self-checks run when `java` and
    `VULNREPORT_JYTHON_JAR` are available, and by Step 6's checklist); `docs/ARCHITECTURE.md` (a short paragraph on starting from Burp, and the corrected
    library-fallback lines).
  - *Test:* `.venv/bin/python scripts/relevant_tests.py --affected --run`. For `run.py` it picks every Python module and no browser tests; `burp/` is listed
    under "No rule for these", and the answer by hand is `tests.test_launcher`.
  - *Invariant:* the plan and the map describe what was built.

**Accepted risks, stated once:**
- A kill during an import or duplicate can leave missing screenshots (answer 5).
- When another program holds 8765, the port shifts, and unsaved browser work waits on the old port
  (answer 3).
- An old release (no lock file) still running on macOS or Linux during Bring over is guarded only by
  the tester's confirmation (round 3, finding 4).
- Two first-run setups racing into one `.venv` are now prevented by the lock (Step 1).
- Burp's legacy Extender API is "no longer actively maintained" by PortSwigger. Only the one Jython
  file would need porting if a future Burp drops it (answer 6).
- Jython 2.7.4 is officially supported on Java 8 and 11; the Java inside testers' Burp is recorded in
  Step 8m. Force stop needs Java 9+ (`ProcessHandle`), otherwise it kills the root only and says so.
- With no compiler, a typo in a branch no test reaches shows only at run time; the syntax test, the
  headless panel test and Step 6's empty-Errors-pane line are the nets.

**Deliberately not done** (reasons in round 2's "What I would not do"): a per-user data folder; an HTTP
shutdown route; starting `.venv`'s interpreter directly from the extension; killing by process name or killing
Word; serving the app inside Burp's browser or through its proxy; a fixed port (answer 3).
