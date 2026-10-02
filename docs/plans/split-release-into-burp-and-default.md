# Split the release into a Burp build and a default build

> **Status:** in progress

## Request
"I want to have 2 package release scripts so that I can release a burp extension or the default
local web app. Changes on where init.py and other affected files are located can be changed."

## Answers

Reached through a grilling session (`/grill-with-docs`) over 2026-10-01/02, one round at a time.

1. **Scope of divergence — just the launcher's presence and location.** Nothing else differs
   functionally between the two builds.
2. **Launcher location — `run.py` at the release root for the default build, `app/init.py` for the
   Burp build.** `report_generator_burp.py` hardcodes `<its own folder>/app/init.py`
   (`launcher_file()`), so the Burp build's layout is unchanged; the default build reverts to the
   pre-`launcher-file-layout.md` root location, under the new name `run.py`.
3. **Code sharing between the two launcher files — fully independent, not a shared implementation
   behind two entry points.** Checked directly: a shared `app/init.py` entered via a thin `run.py`
   wrapper would still ship Burp-naming fragments into the default build (the `BURP_FLAG` constant,
   `started_by_burp()`, a comment naming `report_generator_burp.py`, and the whole
   `# --- commands for the Burp extension ---` section), and no refactor removes that without
   introducing a conditional import that is itself a hint the other build exists. `run.py` therefore
   carries its own copy of the shared bootstrap/relaunch/port/data-dir/locking/serve logic, with no
   Burp awareness at all, and no `--data-status`/`--bring-over` (the manual "Moving to a new release"
   steps in `README.md` already cover a console-only tester; nothing is lost). **`app/init.py` itself
   needs zero changes.**
4. **Packaging scripts — fully independent, not a shared `build_release()` helper.** Each of
   `scripts/default_release.py` and `scripts/burp_release.py` owns its own `INCLUDE_FILES`/
   `INCLUDE_DIRS`/`EXCLUDE_*`. `scripts/package_release.py` is deleted.
5. **READMEs — tailored per build, both tracked.** `README.md` stays the default build's tester
   README (trimmed: no Burp section, `run.py` instead of `app/init.py`, and the "Moving to a new
   release" steps cut down to the manual path only, since the automated Bring-reports-over dialog is
   Burp-tab UI that only exists in the Burp build). `README-burp.md` is today's full README
   unchanged, shipped renamed to `README.md` inside the Burp zip.
6. **This decision's record — a plan doc, not an ADR.** It meets `domain-modeling`'s ADR bar (hard to
   reverse, surprising without context, a real trade-off), but this repo has no `docs/adr/` and
   already tracks this exact kind of decision as a plan (`docs/plans/launcher-file-layout.md`); this
   file continues that convention.

**Known, deliberate reversal.** `docs/plans/launcher-file-layout.md` added
`test_burp_file_names_the_launcher_once_and_by_its_current_path`, which asserts no `run.py` exists at
the repository root ("a second launcher at the root would undo the move"). That assertion is retired
here on purpose: the two-build split requires exactly the `run.py` it was guarding against, just never
in the same zip as `app/init.py`.

## Agreed plan

| Piece | Default build | Burp build |
|---|---|---|
| Launcher | `run.py`, repo root, own copy of the shared logic, no Burp code | `app/init.py`, unchanged |
| Burp file | absent | `report_generator_burp.py`, unchanged |
| README | `README.md`, trimmed | `README-burp.md` → shipped as `README.md` |
| Packaging script | `scripts/default_release.py` | `scripts/burp_release.py` |

- [x] `run.py`: independent copy of `app/init.py`'s shared logic (bootstrap, relaunch, free_port,
      data_dir, pin_data_dir, locking, guard_start, serve), `ROOT = Path(__file__).resolve().parent`,
      no `BURP_FLAG`/`started_by_burp`/`child_streams`/`_stop_at_end_of_input`/`data_status`/
      `bring_over`/`count_reports`/`lock_is_held` (the last two are only used by the two Burp-only
      commands being dropped).
- [x] `scripts/default_release.py` and `scripts/burp_release.py`, each with its own manifest; delete
      `scripts/package_release.py`.
- [x] `README-burp.md` (today's `README.md`, unchanged); trim `README.md` for the default build.
- [x] `tests/test_launcher.py`: retire the "no `run.py`" assertion (see above), add a test that
      `run.py` carries no Burp fragment (`BURP_FLAG`, `started_by_burp`, `--data-status`,
      `--bring-over`, `report_generator_burp`), rewrite `ReleaseTests` for both scripts.
- [x] `scripts/relevant_tests.py`: rows for `run.py` and `README-burp.md`.
- [x] `.github/copilot-instructions.md`, `CLAUDE.md`, `docs/DATA_MAP.md`: describe two scripts and
      two launchers instead of one.

## What deviated

- **The first draft of `run.py` itself violated Q8**, caught by its own new test before the code
  review ever ran: the header comment explaining `ROOT` named `app/init.py` and the word "Burp",
  and separately named the plan file (whose filename contains "burp"). `test_run_py_has_no_fragment_of_the_burp_build`
  failed on the first run, which is the point of writing it first. Fixed by dropping the comparison
  to the other file entirely rather than trying to phrase around it.
- **The code-review pass (`code-reviewer` subagent) caught more of the same class of issue** that the
  test, as first written, missed: the check was case-sensitive (`"Burp"`, not `"burp"`) and didn't
  probe for `app/init.py` by name. Strengthened to a case-insensitive check plus an `"init.py"` probe.
- **A planned `scripts/relevant_tests.py` row for `README-burp.md` turned out to be dead code.** Every
  `.md` file except `docs/DATA_MAP.md` already selects zero tests through an earlier, more general
  rule (`path.endswith(".md")`), so the dedicated row could never be reached. Removed again.
- **`docs/ROUTES.md` also named the deleted `scripts/package_release.py`** and needed the same update
  as the three files in the original checklist; missed in the first pass, caught by code review.
- **`docs/DATA_MAP.md`'s "Moving into a new release" paragraph** called a release with `run.py` at its
  root purely historical ("before the launcher moved"). Reworded, since that is now also a live
  current layout for a default build.
- Nothing from the agreed design itself changed: `app/init.py` ended up with zero edits, exactly as
  planned, and the two packaging scripts and both READMEs match the table above.

## Next steps

1. `/implement`: The code shipped in c48b716, but the status line still says in progress. Finish any open step in its Agreed plan, then set the status to done.
