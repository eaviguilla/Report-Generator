# Move the launcher into app/ and the Burp file to the root

> **Status:** shipped · 2026-09-30 · `f53eef5` (248 Python tests pass, 4 skipped: three need Java, one
> needs Word).
>
> **What deviated.**
> - Two more launcher tests than planned besides Step 3's pin: `test_data_status_runs_from_any_folder…` and the
>   real-script-path server test run from a temporary working folder, and a test that both layouts, and both markers
>   together, are accepted by `--bring-over`.
> - `test_burp_file_names_the_launcher_once…` also asserts that no `run.py` exists at the root, so a leftover shim
>   would fail the suite.
> - The Step 4 server test passes `RELAUNCH_FLAG` and a temporary `VULNREPORT_DATA_DIR`, so it never reads or locks the
>   real `data/`. `--data-status` in the default folder is not run for that reason; Step 3 pins the default by
>   comparing `run.data_dir()` with `app.main.DATA`.
> - Break checks all failed a test as planned: `ROOT` one level short (data-folder pin, script-path start), the
>   `sys.path` line removed (script-path start only), and `--bring-over` accepting only one layout (a test each way).
> - `--affected` lists the old paths (`run.py`, `burp/…`) under "No rule for these" until the move is committed,
>   because a deleted file matches no rule. It goes away by itself after the commit.
> - The Jython file has still not run under Jython or in Burp.

## Request

> i want to rename run.py to init.py then move it to the app folder. also the report_generator_burp.py to be in the root folder for easy access for testers to import it to burp. make all the calls in sync with the new names and directories of each file. also the package release should be in sync as well with the changes.

## Coordinator's framing

Size: **medium**: a rename and two moves across about ten files. No report field changes and nothing reaches the `.docx`, so there is no scribe. Round 1 only, unless the tactician's risk table has a `RISK` row.

Where things are today (commit `33e8b7e`):

- `run.py` at the repository root is the launcher: bootstrap `.venv` → relaunch itself with the venv python → serve `app.main:app`. It also holds the Burp half: the `server.lock` per data folder, `--data-status`, `--bring-over`, stop at end of input. It computes `ROOT = Path(__file__).resolve().parent` and from it `.venv`, `requirements.txt`, `data/`, `DATA-MOVED.txt`, `generated/`.
- `burp/report_generator_burp.py` (Jython 2.7) takes the app folder as the parent of its own file, checks `File(app_folder, "run.py")` to enable Start, and runs `<python> <app>/run.py`, `run.py --data-status` and `run.py --bring-over <old>`. The release build copies it to the release root beside `run.py`.
- Files that name `run.py` or `burp/`: `.github/copilot-instructions.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MAP.md`, `scripts/package_release.py`, `scripts/relevant_tests.py`, `tests/test_launcher.py`, the Burp file, and `run.py` itself. Nothing under `.claude/` or `.vscode/` does. `docs/plans/burp-extension-launcher.md` names it throughout as history.

Target: `app/init.py` replaces `run.py`, and `report_generator_burp.py` sits at the repository root (so the release no longer needs to relocate it).

## Round 1 - Loremaster: how it works today

Everything below was read from source at commit `33e8b7e` (working tree clean apart from this file). The two
behaviours in section 2 were also run once in a scratch copy (`app/init.py` = a copy of `run.py`), then deleted.

### 1. Everything that depends on `run.py`'s name or location

**Inside `run.py` (all derive from one line):**

| What | Where | Depends on |
|---|---|---|
| `ROOT = Path(__file__).resolve().parent` | `run.py:17` | file sits at the repository/release root |
| `VENV_DIR = ROOT / ".venv"`, `STAMP`, `REQUIREMENTS = ROOT / "requirements.txt"` | `run.py:18-20` | `ROOT` |
| `data_dir()` default `ROOT / "data"` | `run.py:131` | `ROOT`; must equal `main.DATA`'s default (`app/main.py:34,37`, where `main.ROOT = Path(__file__).resolve().parent.parent`, already correct) |
| `guard_start()` reads `ROOT / MOVED_NOTE` | `run.py:205` | `ROOT` |
| `bring_over`: `_is_inside(old, ROOT)`, `new_data = ROOT / "data"`, `ROOT / "generated"`, `ROOT / f"data.before-move-…"`, `ROOT / f"generated.before-move-…"`, `VENV_DIR` copy target | `run.py:300,306,320,332,340,353-356` | `ROOT` |
| `bring_over` recognises a previous release by `(old / "run.py").is_file()`, plus two message strings naming `run.py` | `run.py:302-303`, `296` | **the old release's layout, not this one's** (see section 3) |
| relaunch: `[venv_python, str(Path(__file__).resolve())]`, `cwd=ROOT` | `run.py:106` | `__file__` (fine after the move: it re-runs itself) and `ROOT` |
| uvicorn import string `"app.main:app"` | `run.py:247` | `sys.path` containing the repository root (see section 2: **breaks**) |
| comment naming `burp/report_generator_burp.py` | `run.py:23` | wording only |

There is no `generated` computation in `run.py` other than in `bring_over`; the server's own `GENERATED` is `app/main.py:39`.
Nothing else in `app/*.py` names `run.py` (grepped).

**Burp file `burp/report_generator_burp.py`** takes `app_folder = parent of its own file` (`:600`, `getExtensionFilename()`
then `getParentFile()`); once it sits at the repository root that is still the repository/release root, so `app_folder`
stays correct and the same. What names `run.py`:
`:115` (`ServerProcess.command`), `:222` (`--data-status`), `:384` (`self.installed = File(app_folder, u"run.py").isFile()`,
which enables Start), `:504` (`--bring-over`), plus messages/docstrings at `:4,:35,:36,:146,:220,:427,:658`. `:119`
sets the child's cwd to `app_folder` (root), which stays right. The self-check modes take `<app folder> <python>`
(`:763`, driven by `tests/test_launcher.py:604` with `str(REPO)`), unaffected by the move except through `:222`.
All four command sites build the path as `File(app_folder, u"run.py")`; a nested path needs `File(File(app_folder, u"app"), u"init.py")`
(Jython 2.7 `java.io.File` has no varargs join).

**`scripts/package_release.py`**: `INCLUDE_FILES = ["run.py", "requirements.txt", "README.md"]` (`:22`);
`RELEASE_ROOT_FILES = {"burp/report_generator_burp.py": "report_generator_burp.py"}` (`:26`), copied at `:59-60`;
`INCLUDE_DIRS = ["app", "resources"]` (`:27`) already copies the whole `app/` directory, so `app/init.py` ships with no
rule change and is not in `EXCLUDE_RELATIVE` (`:30-35`). After the move: drop `run.py` from `INCLUDE_FILES`, add
`report_generator_burp.py` there, delete `RELEASE_ROOT_FILES` and its loop (and the comment at `:23-25`).

**`scripts/relevant_tests.py`** (first matching prefix wins, `:312`): `("run.py", frozenset())` at `:61`;
`("burp/", frozenset())` at `:63`. **Contradiction with the framing's tone: this is a live trap.** `app/init.py` would
match `("app/", ALL_PAGES)` at `:57` and trigger every browser test for a launcher edit, exactly as the request notes for
`app/*.py`. It needs its own row *above* `:57` (like `("app/library_editor.py", frozenset())` at `:53`). The root
`report_generator_burp.py` would match no row at all and land in "No rule for these" (`:314`); it needs
`("report_generator_burp.py", frozenset())`. Both changes still run every Python module (`:304`, "any real change runs them all"),
which is what covers `tests.test_launcher`. `tests/test_relevant_tests.py` does not pin these rows (grepped `run.py`/`burp`: no hits).

**`tests/test_launcher.py`** (640 lines), every point that must change:
- `:24` `import run` and ~60 uses of `run.<name>` (attributes, `patch.object(run, "ROOT"/"VENV_DIR"/"STAMP"/"_server_lock"/"LOCK_WAIT")`). It becomes `from app import init as run` (or similar); importing `app.init` runs only the trivial `app/__init__.py` (a one-line docstring) and never `app.main`.
- `:28-33` `HOLDER`: `sys.path.insert(0, sys.argv[2]); import run`. `sys.argv[2]` is `REPO`, so `from app import init as run` works unchanged in shape.
- `:35` `SERVE_WRAPPER`: `import run; raise SystemExit(run.main())` run with `python -c` from `cwd=REPO` (`:74`); `''` is on `sys.path`, so `import app.init` resolves and `uvicorn.Config("app.main:app")` resolves too. **This means the serve tests would pass even if `python app/init.py` is broken** (section 2). Nothing in the suite runs the launcher as a script path.
- `:185` `code = "import run; ..."` (guard test, `cwd=REPO`).
- `:225-238`, `:279-283`, `:363-368`: bring-over fixtures create `release / "run.py"` and a `"no run.py"` refusal row; these encode the *old* layout as the recognition rule.
- `:446` docstring, `:501` `BURP_FILE = REPO / "burp" / "report_generator_burp.py"`, `:565-580` (`test_burp_file_shares_only_two_names_with_run_py`, and `test_burp_file_only_runs_run_py_commands_that_exist` which **regex-pins the call shape** `u"run\.py"\)\.getPath\(\), u"(--[a-z-]+)"` and reads `REPO / "run.py"` at `:576`; both the regex and the path must change together, and if the Burp file switches to the nested `File(File(...))` form the regex will silently match nothing and the assertion `passed == {"--data-status","--bring-over"}` will fail, which is the good outcome, but it must be updated on purpose).
- `:583-598` `ReleaseTests`: asserts `Report-Generator-test/run.py` in names and that the shipped burp file is the repo's bytes (`BURP_FILE.read_bytes()`); its "must not ship" top-level set includes `burp` (harmless after the move, since the directory disappears; can stay or go).
- `:545` uses `run.REQUIREMENTS`; `:604` passes `str(BURP_FILE)` to the jar.

**Docs naming `run.py`** (all must change; `grep -rln`): `.github/copilot-instructions.md:8,20,21,147` (the `:147` row is `run.py`, `burp/`); `README.md:4,7,23,57` and Burp text at `:23-59`; `docs/ARCHITECTURE.md:186,187,216,218,222,225,228,232`; `docs/DATA_MAP.md:5,25,40,42,46,87,100,527,528` (map contract applies: refresh the "Last verified" line; §40/§42/§46 describe the lock, `--bring-over` and the release contents). `docs/plans/burp-extension-launcher.md` names both throughout as history and carries a **manual checklist that copilot-instructions.md:20-24 points to**; its status is `in progress` (Step 8, running the extension under Jython, was never done: commit message of `33e8b7e`, plan line 8). So the file being moved has still never run under a real Jython/Burp.
Not present: `.claude/`, `.vscode/`, `.gitignore`, `requirements*.txt`, `resources/`, `app/*.py`.

### 2. Running as `python app/init.py`

- **`import app.main` does not resolve. This is a blocker, not a detail.** With a script path, `sys.path[0]` is the script's directory (`app/`), not the working directory. Verified in a scratch tree: `python app/probe.py` doing `uvicorn.Config("app.main:app").load()` raises `ModuleNotFoundError("No module named 'app'")`; the same load after `sys.path.insert(0, <root>)` succeeds. `cwd=ROOT` in `relaunch()` (`run.py:106`) does not help, since cwd is only put on the path for `-c`/`-m`/stdin. uvicorn's `Config` does not add an `app_dir` (only `uvicorn.run()` and the CLI do: `uvicorn/main.py:543-549`, version 0.52.4), and `run.py` builds `uvicorn.Config` directly (`:247`). So `serve()` (or the top of the module) must put the root on `sys.path` before uvicorn imports the string, or the string must change. This affects both the first (system Python) start and the relaunched child, and it would fail only at serve time, after the venv has been built.
- **No stdlib or installed-package shadowing.** With `sys.path[0] = app/`, top-level names available are: `docx_captions, docx_components, docx_import, docx_report, library, library_editor, main, models, report_service, storage, tester_identity, web, workspace, init` (`__init__` aside). Checked against `sys.stdlib_module_names` (none is stdlib) and against every top-level module in the project `.venv`'s site-packages via `pkgutil.iter_modules` (none present; `docx_*` do not collide with python-docx's `docx`). Also `app/*.py` import each other as `from app.models import …` (absolute; grepped), so nothing would import them as top-level and load a module twice. The venv's subprocess calls (`-m venv`, `-m pip`, `-c import …` at `run.py:91,93,284`) start their own interpreters and never see `app/` on their path.
- **`app/__init__.py` is one line** (`"""VulnReport application package."""`); importing `app` or `app.init` pulls in nothing.
- **`--data-status` and `--bring-over` stay stdlib-only** as long as `app/init.py` keeps its module-level imports as they are (`run.py:3-15`; `uvicorn` is imported inside `serve()` at `:230`) and does not add `import app.<anything heavy>` at module level. They run at `main()` `:370-373` before any venv code. Verified in the scratch tree: `python app/init.py --data-status` under system-side stdlib printed JSON and exited 0.
- **Same scratch run shows the naive-`ROOT` failure directly:** with `ROOT = Path(__file__).resolve().parent` copied as is, `--data-status` reported `"venv": false` because it looked at `app/.venv`.

### 3. Data safety across releases

If `ROOT` is left as `Path(__file__).resolve().parent`, `ROOT` becomes `<release>/app`, and every derived path moves with it:

| Derived path | Where it lands | Consequence |
|---|---|---|
| `data_dir()` default (`run.py:131`) | `app/data` | The lock (`server.lock`), `count_reports`, `--data-status` all look at a folder the server does not use: `app.main` serves `<release>/data` (`app/main.py:37`, twin pinned by `test_launcher.py:170-180`). **The one-server-per-folder guard would protect an empty, wrong folder and two servers could run on the real data.** |
| `bring_over` (`run.py:306,323`) | renames the old `data/` into `app/data` | **The reports move out of the folder the app reads. They look lost** (not deleted: nothing under `data/` is deleted by this code, but the app would open empty). The `DATA-MOVED.txt` note is then left in the old release, saying data moved. This is the worst failure and needs a test. |
| `.venv` / `requirements.txt` (`:18-19`) | `app/.venv`, `app/requirements.txt` | `bootstrap()` `read_bytes()` raises `FileNotFoundError` on first run (`:85`). |
| `DATA-MOVED.txt` (`:205`) | `app/DATA-MOVED.txt` | A folder whose data moved would not refuse to start. |
| `generated/` (`:332,340`) | `app/generated` | Finished documents not moved with their data. |

Correct value: `ROOT = Path(__file__).resolve().parent.parent` (the same expression `app/main.py:34` already uses). Everything else
in section 1's table then keeps its current meaning. The tests that patch `run.ROOT` (`:280-300`, `:225-238`) patch the attribute, so they are unaffected in mechanism.

**What recognises a previous release.** Only `(old / "run.py").is_file()` (`run.py:302`), then `DATA-MOVED.txt` in the old root (`:304`), reports under `old/data` (`:307`), and the old lock (`:311`). Every release already in the field has `run.py` at its root and **no `app/init.py`**. So the recognition rule must accept the old layout (`old/run.py`) and the new (`old/app/init.py`); accepting only the new rule would refuse to move data out of every existing release, which is the exact upgrade the feature exists for. The pre-move `.venv` copy (`:353`), `data/`, `generated/` and `DATA-MOVED.txt` are all root-relative in both layouts, so nothing else in `bring_over` is layout-specific. `_is_inside(old, ROOT)` (`:300`) is fine once `ROOT` is the release root. The test fixtures at `test_launcher.py:283,363` only need a marker file; a fixture for each layout is what would prove both are accepted. Not established in the source: whether any release in the field predates the lock (only `33e8b7e` introduced it, `git log -- run.py`), so old releases may hold no `server.lock` at all.

**`server.lock` needs:** the file at `<data>/server.lock` (`run.py:29,169`), first-byte record lock (`_try_lock`, `:144-158`), and the same `LOCK_NAME`/byte/lock kind on both old and new code so they conflict. None of that moves; only `data_dir()`'s default (above) must stay `<release>/data`. **`DATA-MOVED.txt` refusal needs:** `ROOT / MOVED_NOTE` read at the release root (`:205`), the same place `bring_over` writes it in the old release (`:347`), and where the old code looks for it.

**Stale `run.py` after an overlay unzip.** Nothing in the code deletes a file, and unzipping a new release over an old folder leaves the old `run.py` next to the new `app/init.py`. That stale file still works: its `ROOT` is the folder, `sys.path[0]` is the folder, so `import app.main` succeeds and it serves the *new* `app/`. Does the lock still stop a second server? Yes if the stale `run.py` is the version with the lock (`33e8b7e` or later): both take the same first-byte lock on `<folder>/data/server.lock`, so a stale start against a running new server is refused, and vice versa. A stale `run.py` from a release before `33e8b7e` has no lock and no `--data-status`, so it would happily start a second server on the same data with no lock refusal (the new server would already hold the lock but the old code never asks). The real reports are protected only by the per-report file locks in `app/workspace.py`, which is the pre-existing safety net (DATA_MAP §4). The release zip and README are where this needs a sentence ("unzip into a new folder; do not overlay"); README currently says a new release starts empty and to bring data over (`README.md:57-59`), i.e. it already implies a fresh folder.

### 4. `.gitignore` and the release

- `.gitignore` names no path for `run.py` or `burp/`. Its root-anchored entries are `/dist/`, `/*.docx`, `/vuln_library.json`; the others (`data/…`, `DATA-MOVED.txt`, `data.before-move-*/`, `generated.before-move-*/`) are unanchored or under `data/`, so they still match after the move. A root `report_generator_burp.py` is not ignored. `app/init.py` is not ignored (`__pycache__/`, `*.pyc` only). No `.gitignore` change is needed.
- Release: `INCLUDE_DIRS` already ships all of `app/` minus `EXCLUDE_RELATIVE`, so `app/init.py` ships by itself; only the two `package_release.py` edits in section 1 are needed. The zip loses `run.py` at the root, which is the point where the README start command changes for testers.
- Shipped Burp file is byte-for-byte the repo's (test `:590-592`); the move to root makes the repo file and the shipped file the same path, so that test still reads meaningfully.

### 5. Rules that exist on both sides (Python launcher ↔ Jython file)

Pinned today by `tests/test_launcher.py:565-580`: `ADDRESS_LINE` and `BURP_FLAG` values (`run.py:25-26` ↔ `burp:35-36`), the set `{--data-status, --bring-over}` the extension passes, and that the extension mentions no `VULNREPORT_*` name except `BURP_FLAG`. What else must stay in step, by name:
- **The launcher's path** — `app/init.py` — in four Jython call sites (`:115,:222,:384,:504`); pinned only through the regex at `test_launcher.py:577`, which will need editing.
- **The `--data-status` JSON keys** `data, reports, locked, venv` (`run.py:262-267`) ↔ what the Burp file reads from `data_status()` (`burp:219-222`, consumed at `:493-497,:656`). Not pinned by a test that parses both; only the Jython self-checks exercise it (skipped without Java + jar).
- **`--bring-over` recognition** in `run.py:302` ↔ the Burp dialog's folder validation, if any (`burp:340-350,497-504` ask for the old folder; not established whether the Burp side pre-checks for `run.py` in the old folder: the text search finds no `run.py` check on the old folder there, only on the app folder).
- **The app folder = release root** assumption: `burp:600` (parent of the extension file) ↔ `run.py`'s `ROOT` after the move (`parent.parent` of `app/init.py`). This is the pair that stays equal only if the Burp file is at the root and the launcher's `ROOT` is fixed as above; today both are "the folder of the file".
- **Stop by end of input / `BURP_FLAG` behaviour** (`run.py:216-226,248-249`, `burp:146`) and **cwd = app folder** (`burp:119` ↔ `run.py:106`): unchanged by the move.
- The message text "the one that contains run.py" (`burp:427`) and the `README.md:23-59` Burp instructions.
- DATA_MAP §12 (the twin table checked by `test_app.py:2427-2457`) does not list any launcher pair, so the data-layer twin test does not cover them; the launcher pairs live only in `test_launcher.py`.

### Framing check and open questions

- Framing correct: file list, `ROOT`-derived paths, release copies burp file beside `run.py`, nothing under `.claude/` or `.vscode/`. `app/` needs no change beyond the new file.
- Framing understates: (a) `import app.main` fails when run as `python app/init.py` and no test would notice (section 2); (b) `relevant_tests.py` needs rows before `app/` (section 1); (c) `bring_over` recognition must accept both layouts (section 3); (d) the naive `ROOT` moves data into `app/data`, silently (section 3).
- Open, not decidable from the source: is the field's oldest release older than `33e8b7e` (no lock, so a stale `run.py` gets no refusal)? Should the new launcher ever delete or warn about a stale `run.py` beside `app/init.py`? Should the README start command be `python app/init.py` on every platform (`py -3 app\init.py` on Windows), given the current text at `README.md:4,7`?

## Round 1 - Tactician: proposal and open questions

### Understanding

Move the launcher from `run.py` to `app/init.py` and the Burp extension from `burp/` to the repository root, and
keep every call site in step. No report data, schema or `.docx` is touched, so the data-layer failure modes in the
agent checklist are all `clear`; the real hazard is a different one: **the launcher decides where the reports live**
(`ROOT / "data"`, the lock, `--bring-over`), and one wrong `ROOT` line moves the app's data view into `app/data`
without any error. Every step below is ordered so that the path that can lose sight of data is fixed and pinned first.

I checked the loremaster's claims where the plan leans on them. One correction: the loremaster says the
`data_dir()` rule is pinned by `tests/test_launcher.py:170-180`. That test sets `VULNREPORT_DATA_DIR` for both sides,
so it pins the *environment-variable* path only. The **default** (`ROOT / "data"`) on the launcher side is not pinned by
anything, and the `ROOT` bug would sail through. Step 3 adds that pin. This changes no conclusion, only how much the
existing suite protects.

Also verified: `run.py` never runs `-m`; it relaunches with `[venv_python, <script path>]` (`run.py:106`), so the
`sys.path[0]` = `app/` problem applies to the *child* too, not just a first start. `python -m app.init` would not have it
(cwd is on the path), which is why `-c` and `-m` hide it and only a script path shows it.

### Blast radius

| File | Change |
|---|---|
| `run.py` -> `app/init.py` (`git mv`) | `ROOT = ...parent.parent`; root on `sys.path` inside `serve()`; `--bring-over` accepts old and new layout; message strings |
| `burp/report_generator_burp.py` -> `report_generator_burp.py` (`git mv`) | one helper for the launcher path (4 call sites); Start check; texts |
| `scripts/package_release.py` | drop `run.py` from `INCLUDE_FILES`, add the Burp file there, delete `RELEASE_ROOT_FILES` and its loop and comment |
| `scripts/relevant_tests.py` | rows: `app/init.py` above the `app/` row, root Burp file; drop `run.py` and `burp/` rows |
| `tests/test_launcher.py`, `tests/test_relevant_tests.py` | import, fixtures for both layouts, script-path test, default-data pin, regex pin |
| `README.md`, `.github/copilot-instructions.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MAP.md`, `docs/plans/burp-extension-launcher.md` | names, start command, verification line |

### Open questions

Three decisions are waiting for the user. Each is written so it can be answered alone.

1. **Warn about a leftover `run.py` in the release folder?** Background: nothing in the code deletes files, so a tester
   who unzips the new release over an old folder ends with the old `run.py` sitting beside `app/init.py`. That stale file
   still starts the app (it serves the new `app/`), and if it is from commit `33e8b7e` or later it takes the same
   `server.lock`, so it cannot run a second server. If it is from an earlier release it has no lock, so it could start a
   second server on the same data; per-report file locks are then the only protection. Options: (a) say nothing in code,
   add one README sentence ("unzip into a new folder; do not unzip over an old one"); (b) also make `app/init.py` print one
   line at start when `<root>/run.py` exists ("delete run.py; start with app/init.py"), never deleting it; (c) delete it
   automatically. (c) is rejected (the project rule is never to delete without a prompt, and this would delete a file the
   user might have edited). (b) costs about four lines and one test. Recommendation: (a), because the README already
   implies a fresh folder (it tells testers to use `--bring-over` for a new release) and the pre-lock case needs a release
   old enough to predate `33e8b7e`. Choose (b) if any such old release is in testers' hands. Which is it?
2. **Should every start command become `py -3 app/init.py`?** Background: the README says `py -3 run.py` (with
   `python run.py` as the fallback) and `.github/copilot-instructions.md` and `docs/ARCHITECTURE.md` say the same. After the
   move the file is inside `app/`, so the command changes. `py -3 app/init.py` works in PowerShell and cmd (forward
   slashes are accepted by `py` and by Windows Python); `python3 app/init.py` on macOS. The alternative, `python -m
   app.init`, also works and would not need the `sys.path` line, but it only works from the release root and testers
   double-click or type paths, so a script path is the more forgiving form. Recommendation: `py -3 app/init.py` /
   `python3 app/init.py` everywhere, and `.venv/bin/python app/init.py` for "after the first run". Confirm?
3. **Keep the name `init.py`?** You asked for it, and I found no technical reason to change it: nothing in Python,
   uvicorn, `unittest`, the release script or `.gitignore` treats `init.py` specially (only `__init__.py`), `import
   app.init` pulls in no heavy module, and no top-level name in `app/` collides with the standard library or the
   installed packages (loremaster verified). The only cost is human: `init.py` beside `__init__.py` looks like a typo at a
   glance, and `init` reads as "package init". I am not recommending a rename; this is listed only so the choice is
   visible. Recommendation: keep `init.py`. Confirm?

### Data risks

Failure-mode checklist from the agent brief (report data). All `clear` because no field, shape or save path changes.

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write, lost update, backup exhaustion | clear | no mutation path added; `Workspace` untouched |
| Orphan reference, silent stranding, derived-state fight | clear | nothing under `app/models.py`, `report_service.py`, `app.js` |
| Schema break | clear | `draft.json` shape and `load_path` untouched |
| Request/response asymmetry, rule drift, navigation trap | clear | no route, field or gate |

Launcher risks (the real ones for this change).

| Risk | Verdict | Reasoning and the step that closes it |
|---|---|---|
| Data lands in `app/data` (or lock, venv, `DATA-MOVED.txt`, `generated/` under `app/`) | clear once Step 2 and Step 3 land; **RISK if only the move is done** | `ROOT` must be `parent.parent`. Step 3 pins the default `data_dir()` to `app.main.DATA`, and a `--bring-over` test asserts the data ends in `<release>/data`. |
| Old releases no longer recognised by `--bring-over` | clear with Step 6 | rule becomes "`old/run.py` or `old/app/init.py`"; a fixture per layout plus a "neither" refusal row |
| Stale `run.py` after unzipping over an old release | **RISK (accepted, mitigation pending question 1)** | not a data-shape risk. A `run.py` from `33e8b7e` or later shares the lock; one from before it has no lock, so a second server on the same data is possible, protected only by per-report file locks (pre-existing). Mitigation is documentation (or question 1(b)), not code that deletes. |
| Testers' existing Burp extension entry | clear for testers, changes for developers | the release already put the Burp file at the release root (`RELEASE_ROOT_FILES`), so a tester's entry path does not move and the new file overwrites the old one in place. Developers who loaded `burp/report_generator_burp.py` from a checkout must re-add it from the root; say so in the Burp plan note. |
| `init.py` beside `app/__init__.py` | clear | nothing special-cases `init.py`; importing `app.init` runs only the one-line `app/__init__.py`; uvicorn's string is `app.main:app`, untouched |
| `python app/init.py` vs `python -m app.init` | clear once Step 2 lands | script path puts `app/` first, not the root, so `app.main` fails to import at serve time (after the venv is built). `-m` and `-c` hide this. Step 2 inserts the root; Step 4 adds a test that runs the real script path. Both invocation forms then work. |
| Windows path handling in the Jython `File` calls | clear if one helper builds the path | `File(File(app_folder, u"app"), u"init.py")` is the correct two-level join in Jython 2.7 (no varargs); `getPath()` then yields backslashes on Windows, which `ProcessBuilder` accepts. Putting it in one helper removes four hand-built copies. The Jython self-check runs it only when Java and the jar exist, so the Python 2.7 syntax test and the regex pin (Step 7) carry the load elsewhere. **Not run under real Jython/Burp before or after** (Step 8 of the launcher plan is still open). |
| `from __future__ import annotations` and stdlib-only before `.venv` exists | clear | keep line 1 and the module-level imports as they are; the new `sys.path.insert` uses only `sys` and `ROOT`; `uvicorn` stays imported inside `serve()`. Step 4's script-path test runs `--data-status` with the system interpreter to prove it. |

### Plan

Order: fix the data-critical path and its pins first; then the callers; then docs. The app is never left where a save
or a start can fail, because the move and the `ROOT` fix are one step.

- [x] **Step 1 — Move both files with `git mv`, changing nothing else.**
  Files: `git mv run.py app/init.py`; `git mv burp/report_generator_burp.py report_generator_burp.py`; remove the empty
  `burp/` directory. Commit boundary: do not commit here (the tree is deliberately broken until Step 3), but keep `git mv`
  separate from the edits so history follows the rename (git's similarity match needs the content mostly unchanged; edit
  after moving).
  Test: none yet (`tests.test_launcher` fails at import; that is the expected signal).
  Invariant: file history survives (`git log --follow app/init.py`).

- [x] **Step 2 — Fix `ROOT` and the import path in `app/init.py`.**
  Files: `app/init.py`. `ROOT = Path(__file__).resolve().parent.parent` (the expression `app/main.py:34` uses). In
  `serve()`, before `uvicorn.Config`, add `sys.path.insert(0, str(ROOT))` with a one-line comment saying why (script path
  puts `app/` first; uvicorn's `Config` adds no app dir). Put it in `serve()`, not at module top, so importing `app.init`
  (tests, `--data-status`) has no `sys.path` side effect. Update the comment at the top and the `--bring-over` usage message
  (`app/init.py --bring-over <folder>`). `relaunch()` needs no change (`__file__` is still itself; `cwd=ROOT` is now
  correct).
  Test: Step 3 and Step 4.
  Invariant: `data/`, `.venv`, `requirements.txt`, `DATA-MOVED.txt`, `generated/` all resolve against the release root.

- [x] **Step 3 — Pin the launcher's default data folder to the server's, in `tests/test_launcher.py`.**
  Files: `tests/test_launcher.py`: change `import run` to `from app import init as run`, and the `HOLDER`, `SERVE_WRAPPER`
  and `:185` `-c` snippets to `from app import init as run` (all run from `cwd=REPO`, or `sys.path[0]=REPO`, so they resolve).
  Add `test_default_data_folder_is_the_servers_default_data_folder`: with `DATA_ENV` removed
  (`patch.dict(os.environ)` + `pop`), `run.data_dir()` equals what a subprocess `python -c "import app.main as m;
  print(m.DATA)"` prints (also `os.environ.pop` in that child's env), and both equal `REPO / "data"`. Also assert
  `run.ROOT == REPO` and `run.VENV_DIR == REPO / ".venv"`. Break check: change Step 2's `.parent.parent` back to
  `.parent` and confirm the test fails.
  Invariant: the launcher, the lock and `--data-status` look at the folder the server serves.

- [x] **Step 4 — Add a test that runs the launcher as a real script path, in `tests/test_launcher.py`.**
  Files: `tests/test_launcher.py`, new class beside the serve tests. Two cases, both `[sys.executable,
  str(REPO / "app" / "init.py"), ...]` with `cwd` = a temporary directory that is *not* the repository (so cwd cannot be
  what makes the import work):
  (a) `--data-status` under the current interpreter prints JSON with `"data"` ending in `data` under `REPO`, `venv` a
  boolean, exit 0 (stdlib-only proof);
  (b) set `RELAUNCH_FLAG` so it goes straight to `serve()`, plus `DATA_ENV` at a temp folder and `BURP_FLAG`, wait for the
  `ADDRESS_LINE`, then close stdin and expect exit 0 (reuse `start_child`, `Lines.wait_for` and `finish`; copy the shape of
  the existing serve test, do not invent a new harness). This is the case `-c` cannot catch.
  Break check: delete the `sys.path.insert` line and watch (b) fail with `No module named 'app'`.
  Invariant: `python app/init.py` works from any cwd, first start and relaunched child.

- [x] **Step 5 — Make `--bring-over` accept old and new layouts.**
  Files: `app/init.py` (`bring_over`); the one recognition line becomes
  `(old / "run.py").is_file() or (old / "app" / "init.py").is_file()`, and the refusal text becomes "is not a Report
  Generator folder (it has neither run.py nor app/init.py)". Nothing else in `bring_over` is layout-specific.
  Test: `tests/test_launcher.py`: parametrise the existing bring-over fixtures (`:225-238`, `:279-283`, `:363-368`) with
  `subTest` over the two markers; keep the "no marker" refusal row, updating its message with `assertRaisesRegex`-style
  message check (the existing tests check the refusal text; keep them checking it). One extra case with **both** markers
  present (an overlay-unzipped folder) succeeds. Add one assertion in the success case that the data ends in
  `ROOT / "data"` and `generated` in `ROOT / "generated"` (the `app/data` failure, from the bring-over side).
  Invariant: never refuse to move data out of an existing release; never move it anywhere but `<release>/data`.

- [x] **Step 6 — Update the Burp file for the new launcher path.**
  Files: `report_generator_burp.py` (root). Add one helper near `ServerProcess`, for example
  `def launcher_file(app_folder): return File(File(app_folder, u"app"), u"init.py")`, and use it at the four sites
  (`:115` command, `:222` `--data-status`, `:384` `self.installed`, `:504` `--bring-over`), so the path is written once.
  Update the messages and docstrings that name `run.py` (`:4,:35,:36,:146,:220,:427,:658`); the `:427` text becomes
  "the one that contains app/init.py and this file" (the folder rule is unchanged: `app_folder` is the parent of the
  extension file, which is now the release root in both the repository and the release). Keep Jython 2.7 syntax (no
  f-strings, `u""` literals) and keep the file's only shared names with the launcher (`ADDRESS_LINE`, `BURP_FLAG`).
  Test: Step 7.
  Invariant: Start is enabled only when `app/init.py` exists; the command is `<python> <root>/app/init.py`, cwd = root.

- [x] **Step 7 — Update the launcher tests that read the Burp file.**
  Files: `tests/test_launcher.py`: `BURP_FILE = REPO / "report_generator_burp.py"`; in
  `test_burp_file_only_runs_run_py_commands_that_exist` change the regex from `u"run\.py"\)\.getPath\(\), u"(--...)"`
  to match the new helper call (`launcher_file\([^)]*\)\.getPath\(\), u"(--...)"`) and read `REPO / "app" / "init.py"`
  for the flags it must define; add a floor (`assertGreaterEqual(len(matches), 2)`) so a regex that silently matches nothing
  fails instead of passing an empty set. Update the name of `test_burp_file_shares_only_two_names_with_run_py`, and the
  "must not ship" set in `ReleaseTests` (`burp` can stay; harmless). The Python 2.7 syntax test reads `BURP_FILE` and needs
  only the path change. Assert once that `launcher_file` is called with `u"app"` and `u"init.py"` in the helper, and that the
  string `run.py` no longer occurs in the file.
  Invariant: the four commands the extension can send exist in the launcher and only those; the path pin matches reality.

- [x] **Step 8 — Release script.**
  Files: `scripts/package_release.py`: `INCLUDE_FILES = ["requirements.txt", "README.md", "report_generator_burp.py"]`
  (drop `run.py`; `app/` already ships `init.py`); delete `RELEASE_ROOT_FILES`, its comment (`:23-25`) and the loop at
  `:59-60`; update the module docstring/comment if it names run.py. No relocation remains, so the repository file and the
  shipped file are the same path.
  Test: `tests/test_launcher.py` `ReleaseTests`: replace `Report-Generator-test/run.py` with `.../app/init.py` in the
  expected names; assert `run.py` is **not** in the zip; keep the byte-for-byte Burp check (now `REPO /
  "report_generator_burp.py"`) and add the same for `app/init.py`. Also assert the zip has no `burp/` directory.
  Invariant: a release contains exactly one launcher and one Burp file, in the places testers are told.

- [x] **Step 9 — Test-selection rules.**
  Files: `scripts/relevant_tests.py`: add `("app/init.py", frozenset())` **above** `("app/", ALL_PAGES)` (next to
  `app/library_editor.py`), and `("report_generator_burp.py", frozenset())`; delete `("run.py", ...)` and `("burp/", ...)`.
  The first matching prefix wins, so a row below `app/` would never fire.
  Test: `tests/test_relevant_tests.py`: one case that `app/init.py` selects no browser pages and that
  `report_generator_burp.py` gets a rule (is not reported under "No rule for these"), using whatever helper neighbouring
  tests use to classify a path; and a floor case that `app/main.py` still selects every page (proves the new row did not
  swallow `app/`).
  Invariant: editing the launcher does not trigger every browser test; nothing lands in "No rule for these".

- [x] **Step 10 — Docs, in one change.**
  Files and edits (all `run.py` -> `app/init.py`, `burp/report_generator_burp.py` -> `report_generator_burp.py`):
  `README.md` (start command at `:4,:7`, Burp text `:23-59`, and one sentence "unzip a new release into a new folder; do not
  unzip over an old one" unless question 1 says otherwise); `.github/copilot-instructions.md` (Start line `:8` including the
  `.venv/bin/python app/init.py` form, Burp launcher line `:20-21`, and the affected-tests table row `:147`, which becomes
  `app/init.py`, `report_generator_burp.py`: none); `docs/ARCHITECTURE.md` (`:186-232`); `docs/DATA_MAP.md` (verification
  line, and every `run.py` mention `:5,25,40,42,46,87,100,527,528`, refreshing "Last verified" per
  `.github/instructions/data-layer.instructions.md`; §40/§42/§46 also gain the fact that `ROOT` is `parent.parent`);
  `docs/plans/burp-extension-launcher.md` (a note at the top under its status line: "paths moved: `run.py` is now
  `app/init.py`, the Burp file is at the root; the text below is history; see `launcher-file-layout.md`", and re-point the
  manual checklist that `.github/copilot-instructions.md` links to at the new paths, keeping the plan's status `in
  progress` since its Jython step is still open).
  Test: `grep -rn "run\.py" .` over tracked files returns only history (plan files) and this plan; `grep -rn "burp/"` likewise.
  Then the one `--affected` run (`.venv/bin/python scripts/relevant_tests.py --affected --run`), announced with its scope line.
  Invariant: every doc's start command works when pasted; DATA_MAP reflects the launcher's `ROOT` rule.

- [x] **Step 11 — Update this plan.** Tick the steps, status `shipped` with date and commit, and one paragraph on what deviated
  (`.github/copilot-instructions.md`, "Implementing a plan").

### What I would not do

- **Leave `ROOT = Path(__file__).resolve().parent` and "fix the paths one by one"** (`ROOT.parent / "data"` and so on).
  Five derived paths hang off one name; patching each leaves `ROOT` meaning "the app folder" while the Burp file's
  `app_folder` means "the release root", which is the mismatch that shipped bug would live in.
- **Keep a `run.py` shim at the root** that forwards to `app/init.py`, to make old habits and stale folders keep working.
  It would undo the request, and it would make bring-over recognition ambiguous. The stale-file case is handled with
  documentation (question 1), not by shipping a second launcher.
- **Add the root to `sys.path` at module import time**, or switch to `uvicorn.run(..., app_dir=...)`. The first gives every
  importer (tests, `--data-status`) a side effect; the second changes how the server is built for a problem one line in
  `serve()` solves.
- **Recognise only the new layout in `--bring-over`.** That refuses to move data out of every release already in the field,
  which is the exact upgrade the feature exists for.
- **Trust `-c`/`-m` tests** for "the launcher still starts". Only a script path from a different cwd proves it (Step 4).

## Round 2 - skipped

The tactician's one `RISK` row (a leftover `run.py` from a release older than `33e8b7e`, which takes no lock) is a
decision for the user, not a factual dispute, so it goes to question 1 instead. The only disagreement with the
loremaster was which test pins the launcher's default data folder. The tactician checked it at
`tests/test_launcher.py:170-180`: that test sets `VULNREPORT_DATA_DIR` on both sides, so nothing pins the default.
Step 3 adds that pin, so no second loremaster pass is needed. The name question (keep `init.py`) was not put to the
user again: they chose it, and the tactician found no technical reason against it.

## Answers

1. **Leftover `run.py` after unzipping over an old release:** "they will not unzip past release folders that has
   the old run.py as this will not be instructed to them". No README sentence, no warning, no deletion. The
   tactician's `RISK` row is accepted as out of scope: releases always go into a fresh folder.
2. **Console start command:** script path. `py -3 app/init.py` on Windows, `python3 app/init.py` on macOS,
   `.venv/bin/python app/init.py` after the first run. `app/init.py` therefore puts the release root on `sys.path`
   itself (inside `serve()`).
3. **Name:** `init.py`, as requested (not asked again; see *Round 2 - skipped*).

## Agreed plan

Readable on its own. Goal: the launcher `run.py` becomes `app/init.py`, and the Burp extension moves from
`burp/report_generator_burp.py` to `report_generator_burp.py` at the repository root, so a release has it at its top
level with no relocation step. Every caller, test, doc and the release build follow. Nothing about a report, a route
or the Word document changes.

The two traps this plan exists to avoid:
- **Reports appear lost.** The launcher derives the data folder, `.venv`, `requirements.txt`, `DATA-MOVED.txt`,
  `generated/` and the server lock from its own location. Moved into `app/`, a naive `ROOT` points all of them at
  `app/…`, and `--bring-over` would move old reports into `app/data`, which the server never reads.
- **The app does not start.** Run as `python app/init.py`, Python searches `app/` for modules, not the release root,
  so uvicorn cannot import `app.main`. Tests started with `python -c` do not show this.

| Decision | Choice |
|---|---|
| Launcher path and name | `app/init.py` (moved with `git mv`) |
| Burp file | `report_generator_burp.py` at the repository root (moved with `git mv`) |
| `ROOT` | `Path(__file__).resolve().parent.parent`, the expression `app/main.py` already uses |
| Import path | `sys.path.insert(0, str(ROOT))` inside `serve()` only, so importing the module has no side effect |
| Console start | `py -3 app/init.py` / `python3 app/init.py` / `.venv/bin/python app/init.py` |
| Old releases | `--bring-over` accepts a folder with `run.py` **or** `app/init.py` |
| Leftover `run.py` from unzipping over an old release | not handled: releases always go into a fresh folder (answer 1) |
| Compatibility shim `run.py` at the root | not added (it would undo the request) |

- [ ] **Step 1 — Move both files with `git mv`, nothing else.** `git mv run.py app/init.py`;
  `git mv burp/report_generator_burp.py report_generator_burp.py`; remove the empty `burp/`. Edit only after moving, so
  `git log --follow` keeps the history. Test: none yet (the launcher tests fail at import; expected).
- [ ] **Step 2 — Fix `ROOT` and the import path in `app/init.py`.** `ROOT = …parent.parent`; in `serve()`, before
  `uvicorn.Config`, insert `ROOT` into `sys.path` with a comment saying why. Update the top comment and the
  `--bring-over` usage text. `relaunch()` needs no change. Invariant: every derived path resolves against the release root.
- [ ] **Step 3 — Pin the default data folder.** `tests/test_launcher.py`: import as `from app import init as run`
  (also in the `HOLDER`, `SERVE_WRAPPER` and guard `-c` snippets). New
  `test_default_data_folder_is_the_servers_default_data_folder`: with `VULNREPORT_DATA_DIR` unset on both sides,
  `run.data_dir()` equals `app.main.DATA` printed by a subprocess, and both equal `REPO / "data"`; also
  `run.ROOT == REPO`, `run.VENV_DIR == REPO / ".venv"`. Break check: revert to `.parent`, watch it fail.
- [ ] **Step 4 — Run the launcher as a real script path.** New tests start
  `[sys.executable, REPO/"app"/"init.py", …]` from a temporary working directory outside the repository:
  (a) `--data-status` prints JSON whose `data` is `REPO/"data"` (standard library only, before any `.venv`);
  (b) with the relaunch flag, a temp data folder and the Burp flag, the address line arrives, then closing input exits 0.
  Reuse `start_child`, `Lines` and `finish`. Break check: remove the `sys.path` line, watch (b) fail with
  `No module named 'app'`.
- [ ] **Step 5 — `--bring-over` accepts both layouts.** Recognition becomes
  `(old/"run.py").is_file() or (old/"app"/"init.py").is_file()`; refusal text names both. Tests: the bring-over fixtures
  run as `subTest`s over both markers; a folder with both markers works; the "neither" refusal row stays with its message;
  the success case asserts data lands in `<release>/data` and `generated` in `<release>/generated`.
  Invariant: never refuse to move data out of an existing release; never move it anywhere but `<release>/data`.
- [ ] **Step 6 — The Burp file follows.** One helper, `launcher_file(app_folder)` returning
  `File(File(app_folder, u"app"), u"init.py")`, used by the command, `--data-status`, `--bring-over` and the Start check.
  Messages and docstrings name `app/init.py`. The app folder stays the parent of the extension file, now the root in both
  the repository and a release. Jython 2.7 syntax; shared names stay `ADDRESS_LINE` and `BURP_FLAG` only.
- [ ] **Step 7 — The tests that read the Burp file.** `BURP_FILE = REPO/"report_generator_burp.py"`; the flag pin
  matches `launcher_file(...).getPath(), u"--…"`, reads the flags from `app/init.py`, and has a floor so an empty match
  fails; assert `run.py` no longer appears in the Burp file; rename the shared-names test.
- [ ] **Step 8 — Release script.** `scripts/package_release.py`: `INCLUDE_FILES` drops `run.py` and adds
  `report_generator_burp.py`; delete `RELEASE_ROOT_FILES`, its comment and its loop. `ReleaseTests`: expects
  `app/init.py` and the root Burp file byte for byte, and asserts no `run.py` and no `burp/` in the zip.
- [ ] **Step 9 — Test-selection rules.** `scripts/relevant_tests.py`: `("app/init.py", frozenset())` above
  `("app/", ALL_PAGES)`, `("report_generator_burp.py", frozenset())`; delete the `run.py` and `burp/` rows. Test in
  `tests/test_relevant_tests.py`: `app/init.py` selects no browser pages, the Burp file has a rule, and `app/main.py`
  still selects every page.
- [ ] **Step 10 — Docs.** `README.md` (start commands, Burp section), `.github/copilot-instructions.md` (Start line,
  Burp launcher line, affected-tests row), `docs/ARCHITECTURE.md`, `docs/DATA_MAP.md` (every `run.py` mention, the
  `ROOT` rule, verification line), and a note under the status line of `docs/plans/burp-extension-launcher.md` that the
  paths moved (its status stays `in progress`: its Jython step is still open). Check: `git grep "run\.py"` and
  `git grep "burp/"` find only plan history. Then one announced `relevant_tests.py --affected --run`.
- [ ] **Step 11 — Close this plan.** Tick the steps, status `shipped` with date and commit, and what deviated.

**Accepted risk.** A tester who unzips a release over an old folder keeps the old `run.py`; one from before `33e8b7e`
takes no lock and could run a second server on the same reports. Out of scope by answer 1: releases go into a fresh
folder.

**Not verified by this change either.** The Burp file has still never run under Jython or in Burp (Step 8 of
`burp-extension-launcher.md`). Moving it does not change that.
