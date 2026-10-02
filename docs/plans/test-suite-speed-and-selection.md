# Test suite: speed, honesty, and running only the tests a change needs

> **Status:** done · 2026-09-29 · `5bb2c65`
>
> **What deviated.** Merging `overrides.css` was the previous change; this one found that tests wrote
> into the real `data/` (every test error was appended to the user's error log), which became step 1.
> Browser tests now default to a 500 ms autosave idle instead of 5 s, because most of the remaining
> run time was tests waiting for autosave; tests that need a long idle still set it themselves.
> None of the three deletion candidates was strictly covered by a stronger test (1911 checks the
> not-ready side of an imported report, 3920 pins a verdict the contract test only compares, and
> `test_report_management_lifecycle` checks folder naming and renaming nothing else does), so no test
> was deleted; the conclusion trio was merged instead and 1911's docstring and branch guard were fixed.
> Pairs that share a setup but assert different outcomes got shared helpers rather than `subTest`
> tables (`plant_recovery_draft`/`restore_recovery_draft`, `_two_thick_client_components`), and two
> `test_app` pairs and the "Northstar" engagement builders were left alone, because merging them would
> hide which state each test depends on. The evidence-record builders were not shared either: the
> copies differ in size, name and hash. `tests/test_docx.py:1125` was flagged as assertion-free by a
> reviewer but is not (rendering raises on an unresolved placeholder). The browser file was not split
> by page: the selector reads each test's pages from its URLs and buttons, checked against a recorded
> run of every test (no misses, 7 over-selected page slots).

## Request

> check the test scripts, and how test scripts are made. find inconsistencies, redundancies, also,
> inefficiencies. also, when testing a new function, only necessary test should be done. suggest ways
> on how this will be done. also, suggest ways on how both github ai and you(claude) will also do these.

## Findings

1. The browser harness started a server, Playwright and Chromium for every test.
2. Two Word-dependent tests failed on every Mac run although they test the route and the page; one
   burned a 60 s timeout, both hard-coded the year, both wrote to the real `generated/`.
3. Tests wrote to real project data: the error log, `prefs.json`, the configured library.
4. About fifteen tests could pass without testing what they claim.
5. The "two tabs" browser tests use two browser profiles, not two tabs (left for a separate change).
6. The selector picked whole modules only, and missed `test_app` for several paths.
7. `test_docx_import` rendered the identical base report about 36 times.
8. Helpers and fixtures were copied between modules; about ten near-duplicate test pairs per file.
9. Inconsistent waits, relative resource paths, hand-written segment lists, stale docstrings.

## Agreed plan

- [x] **Step 0 — Commit the finished cleanup on its own** (`e6a0f06`, local).
- [x] **Step 1 — Hermetic tests.** `VULNREPORT_DATA_DIR` in `app/main.py`, `tests/__init__.py`,
  `use_temp_workspace` in `tests/support.py` (also redirects `generated/`), `ERROR_LOG_LABEL` so an
  outside data folder cannot crash error responses. Verified: `data/` and `generated/` unchanged.
- [x] **Step 2 — Word-dependent tests run everywhere.** Word patched out; the table-of-contents check
  that needs real Word is its own test and skips off Windows; year pinned.
- [x] **Step 3 — Shared browser harness.** One server, Playwright and Chromium per class, a fresh
  context per test, class cleanups in order.
- [x] **Step 4 — Deterministic waits.** 26 of 27 fixed sleeps replaced by signals; the 3 s timeouts
  replaced by a race between the navigation and the refusal marker; the last sleep documented.
- [x] **Step 5 — Three-level selector** (`scripts/relevant_tests.py`, `tests/test_relevant_tests.py`).
- [x] **Step 6 — Weak tests fixed**, each proven to fail when its rule is broken where practical.
- [x] **Step 7 — Base render cached** in `test_docx_import` (12.4 s → 9.1 s).
- [x] **Step 8 — Duplicates consolidated** (see the deviation note).
- [x] **Step 9 — One set of rules**: rewritten "Running tests in this repo",
  `.github/instructions/tests.instructions.md`, `CLAUDE.md` imports it, invader and tactician point at it.
- [x] **Step 10 — Guardrails**: `.claude/hooks/full_suite_guard.py` (local) and `.vscode/settings.json`.

## Results

| | Before | After |
|---|---|---|
| Browser tests, one process | 163 tests, 381 s | 229 s after step 3, before the autosave default |
| Browser tests, parallel chunks | — | 156 tests, 19–26 s per chunk, about 27 s wall with the Python suites |
| A changed browser test | whole module, 163 tests | that test only |
| A change inside `continuousEditor()` | 163 browser tests | 88 |
| Real `data/` written by a run | yes | no |
