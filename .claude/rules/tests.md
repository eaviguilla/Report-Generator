---
paths:
  - "tests/**"
  - "scripts/relevant_tests.py"
---
<!-- Generated from .github/instructions/tests.instructions.md. Edit that file, not this one. -->

# Writing tests

- **Test a rule at the lowest layer that owns it.** A pure function: call it (`test_app.py`,
  `test_docx*.py`). A route: `TestClient`. A browser test only for what needs a page: wiring, focus,
  save races, and the Python↔JavaScript twin contracts.
- **A twin rule gets a case in the existing contract tests** (for example
  `test_browser_readiness_verdict_matches_server_generation_issues`), and a browser test takes its
  expected message from the Python function, never from a copied string.
- **No fixed sleeps.** Wait for the signal: `expect(locator).to_have_text(...)`, the save state, a
  response, a navigation. To check that something did *not* happen, first wait for the event that
  would have caused it (`_next_report_change`). A pause needs a comment saying why no signal exists.
- **Every check must be able to fail.** A loop needs a floor on how much it checked; a message checked
  as absent needs a positive case showing the rule really emits it; use `assertRaisesRegex` with the
  message, not a bare `assertRaises`. When fixing a bug, break the code once and watch the test fail.
- **One behaviour per test.** Variants are `subTest` rows, not copied tests; the name says what is asserted.
- **Never touch real data.** `tests/__init__.py` points the app at a temporary data folder, and
  `use_temp_workspace` in `tests/support.py` also redirects `generated/`. That only happens when tests
  run as `tests.MODULE` or through `scripts/relevant_tests.py`: `discover -s tests` skips the package and
  writes into the real `data/`. Patch Word with `patch.object(main, "update_docx_bytes_with_word", ...)`;
  only a check of Word's own output skips off Windows.
- **Shared helpers** go in `tests/support.py`, and only when more than one module needs them. Browser
  fixtures are methods on the harness in `test_browser.py`: `ready_report`, `plant_recovery_draft`,
  `restore_recovery_draft`, `other_profile_page`.
- **Reading `test_browser.py`:** read the harness at the top and one neighbouring test, not the whole
  file.
- **Running them:** announce the scope in one line before each run, and run the full suite (`--full`)
  only when the user asks. The rest is in "Running tests in this repo" in
  `.github/copilot-instructions.md`.
