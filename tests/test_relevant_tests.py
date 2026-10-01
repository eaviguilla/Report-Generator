"""The test selector decides what runs, so a mistake here silently skips tests. One check per rule."""
from __future__ import annotations

import unittest

from scripts.relevant_tests import ALL_PAGES, DECLARATION, FILE_PAGES, REPORT_PAGES, ROOT, RULE_SYNC_TEST, app_js_pages, browser_tags, changed_tests, parse_diff, parse_module, select, test_modules

SAMPLE_TESTS = '''import unittest

CONSTANT = 1


class Sample(unittest.TestCase):
    def setUp(self):
        self.value = 1

    def helper(self):
        return 2

    def test_uses_helper(self):
        self.assertEqual(self.helper(), 2)

    def test_standalone(self):
        self.assertTrue(True)
'''

SAMPLE_APP_JS = '''(() => {
  const shared = () => 1;
  // a comment on its own changes nothing
  function setup() {
    shared();
  }
  function continuousEditor() {
    shared();
  }
  root.id === "setup" ? setup() : continuousEditor();
})();
'''

SAMPLE_BROWSER = '''import unittest


class Browser(unittest.TestCase):
    def _open(self, report_id):
        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")

    def test_content(self):
        self._open("r")

    def test_home_then_setup(self):
        self.page.goto(f"{self.base_url}/")
        self.page.get_by_role("button", name="Open Setup").click()

    def test_bounced_to_findings(self):
        self._open("r")
        self.page.wait_for_url("**/findings?incomplete=findings")

    def test_unknown(self):
        pass
'''


def line_of(source: str, text: str, occurrence: int = 0) -> int:
    return [number for number, line in enumerate(source.splitlines(), 1) if line == text][occurrence]


class SelectorTests(unittest.TestCase):
    def test_diff_hunks_mark_added_lines_and_both_sides_of_a_deletion(self) -> None:
        diff = "\n".join([
            "diff --git a/app/x.py b/app/x.py",
            "--- a/app/x.py",
            "+++ b/app/x.py",
            "@@ -10,0 +11,2 @@",
            "@@ -20,3 +21,0 @@",
            "diff --git a/gone.py b/gone.py",
            "--- a/gone.py",
            "+++ /dev/null",
            "@@ -1,2 +0,0 @@",
        ])
        self.assertEqual(parse_diff(diff), {"app/x.py": {11, 12, 21, 22}})

    def test_a_changed_line_selects_its_test_a_helper_its_callers_and_setup_its_class(self) -> None:
        module = parse_module(SAMPLE_TESTS, "tests.test_sample")
        helper = changed_tests(module, {line_of(SAMPLE_TESTS, "        return 2")})
        standalone = changed_tests(module, {line_of(SAMPLE_TESTS, "        self.assertTrue(True)")})
        setup = changed_tests(module, {line_of(SAMPLE_TESTS, "        self.value = 1")})
        self.assertEqual(helper[0], {"tests.test_sample.Sample.test_uses_helper"})
        self.assertEqual(standalone[0], {"tests.test_sample.Sample.test_standalone"})
        self.assertEqual(setup[0], {"tests.test_sample.Sample.test_uses_helper", "tests.test_sample.Sample.test_standalone"})
        # An added import changes no behaviour; a module-level statement could change any test.
        self.assertEqual(changed_tests(module, {line_of(SAMPLE_TESTS, "import unittest")}), (set(), set(), False))
        self.assertTrue(changed_tests(module, {line_of(SAMPLE_TESTS, "CONSTANT = 1")})[2])
        self.assertTrue(changed_tests(module, None)[2], "a new or untracked test file runs whole")

    def test_app_js_lines_map_to_the_pages_whose_code_they_touch(self) -> None:
        in_setup = line_of(SAMPLE_APP_JS, "    shared();", 0)
        in_editor = line_of(SAMPLE_APP_JS, "    shared();", 1)
        self.assertEqual(app_js_pages(SAMPLE_APP_JS, {in_setup}), {"setup", "findings"})
        self.assertEqual(app_js_pages(SAMPLE_APP_JS, {in_editor}), {"content"})
        self.assertEqual(app_js_pages(SAMPLE_APP_JS, {line_of(SAMPLE_APP_JS, "  const shared = () => 1;")}), set(REPORT_PAGES))
        self.assertEqual(app_js_pages(SAMPLE_APP_JS, {line_of(SAMPLE_APP_JS, "  // a comment on its own changes nothing")}), set())

    def test_browser_tests_are_tagged_with_every_page_they_reach(self) -> None:
        tags = browser_tags(parse_module(SAMPLE_BROWSER, "tests.test_sample"))
        prefix = "tests.test_sample.Browser."
        self.assertEqual(tags[prefix + "test_content"], {"content"})
        self.assertEqual(tags[prefix + "test_home_then_setup"], {"home", "setup"})
        self.assertEqual(tags[prefix + "test_bounced_to_findings"], {"content", "findings"})
        self.assertEqual(tags[prefix + "test_unknown"], set(ALL_PAGES), "an unclassifiable test must run for every page")

    def test_the_launcher_and_the_burp_file_select_no_browser_pages_but_the_server_still_selects_all(self) -> None:
        def pages_for(path: str):
            return next((found for prefix, found in FILE_PAGES if path.startswith(prefix)), None)

        self.assertEqual(pages_for("app/init.py"), frozenset(), "the launcher sits in app/, whose row would select every page")
        self.assertEqual(pages_for("report_generator_burp.py"), frozenset(), "no rule would list it under 'No rule for these'")
        for path in ("app/main.py", "app/workspace.py", "app/storage.py"):
            self.assertEqual(pages_for(path), ALL_PAGES, f"{path} is server code every page talks to")

    def test_the_real_app_js_still_has_its_two_page_entry_points(self) -> None:
        """If these are renamed, every app.js change quietly selects all report-page tests."""
        source = (ROOT / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        names = {match[1] or match[2] for line in source.splitlines() if (match := DECLARATION.match(line))}
        self.assertLessEqual({"setup", "continuousEditor"}, names)

    def test_a_change_to_the_instructions_or_their_claude_copies_selects_the_drift_test(self) -> None:
        """.github/ and .claude/ otherwise select nothing, so this pair could drift unnoticed."""
        modules = test_modules()
        for path in (".github/instructions/tests.instructions.md", ".claude/rules/tests.md"):
            self.assertEqual(select("affected", {path: None}, modules).python, {RULE_SYNC_TEST}, path)
        for path in (".github/copilot-instructions.md", ".claude/settings.json", "CLAUDE.md"):
            self.assertEqual(select("affected", {path: None}, modules).python, set(), f"{path} has no copy to compare")


if __name__ == "__main__":
    unittest.main()
