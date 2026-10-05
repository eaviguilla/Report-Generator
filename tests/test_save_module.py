"""The save code in save.js, run in a blank page with no app server and no report page (ADR 0004)."""
from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.models import Report

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - the dev requirements install it
    sync_playwright = None

STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"
# A made-up address gives the page real Web Storage; https makes it a secure context, which crypto.randomUUID needs.
ORIGIN = "https://save-module.test"
PAGE = """<!doctype html>
<html><body>
<main>
  <button id="save-button" type="button"></button>
  <button id="undo-button" type="button"></button>
  <button id="redo-button" type="button"></button>
</main>
<script src="/static/diagnostics.js"></script>
<script src="/static/save.js"></script>
</body></html>"""
START = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
IDLE_MS = 5000


def report_json(**fields) -> dict:
    """A report as the server sends it, built by the server's own model."""
    data = {"report_id": "r_save_module", "app_id": "unnamed", "saved_at": START.isoformat(), **fields}
    return Report.model_validate(data).model_dump(mode="json", by_alias=True)


def item(uid: str, **fields) -> dict:
    return {"uid": uid, **fields}


# (name, live, sent, canonical, expected live afterwards, expected return value)
RECONCILE_CASES = [
    ("a value the server changed is adopted", {"a": "x"}, {"a": "x"}, {"a": "X"}, {"a": "X"}, True),
    ("a value the tester changed while the save was out is kept", {"a": "typed"}, {"a": "x"}, {"a": "X"}, {"a": "typed"}, False),
    ("a value the server dropped goes", {"a": "x", "b": 1}, {"a": "x", "b": 1}, {"a": "x"}, {"a": "x"}, True),
    (
        "a nested value the server changed is adopted beside the tester's edit",
        {"engagement": {"app_name": "typed", "tester": "Q"}},
        {"engagement": {"app_name": "x", "tester": "Q"}},
        {"engagement": {"app_name": "x", "tester": "QA"}},
        {"engagement": {"app_name": "typed", "tester": "QA"}},
        True,
    ),
    (
        "an item the server added appears",
        {"vulnerabilities": [item("v1")]},
        {"vulnerabilities": [item("v1")]},
        {"vulnerabilities": [item("v1"), item("v2", title="New")]},
        {"vulnerabilities": [item("v1"), item("v2", title="New")]},
        True,
    ),
    (
        "an item the server removed goes",
        {"vulnerabilities": [item("v1"), item("v2")]},
        {"vulnerabilities": [item("v1"), item("v2")]},
        {"vulnerabilities": [item("v1")]},
        {"vulnerabilities": [item("v1")]},
        True,
    ),
    (
        "an item the server removed stays when the tester changed it meanwhile",
        {"vulnerabilities": [item("v1"), item("v2", title="Typed")]},
        {"vulnerabilities": [item("v1"), item("v2", title="Old")]},
        {"vulnerabilities": [item("v1")]},
        {"vulnerabilities": [item("v1"), item("v2", title="Typed")]},
        False,
    ),
    (
        "items with ids merge by id, whatever their order",
        {"vulnerabilities": [item("v2", title="Typed"), item("v1", title="a")]},
        {"vulnerabilities": [item("v1", title="a"), item("v2", title="b")]},
        {"vulnerabilities": [item("v1", title="A"), item("v2", title="b")]},
        {"vulnerabilities": [item("v2", title="Typed"), item("v1", title="A")]},
        True,
    ),
    (
        "a list without ids is replaced when the tester left it alone",
        {"tested_channels": ["web"]},
        {"tested_channels": ["web"]},
        {"tested_channels": ["web", "api"]},
        {"tested_channels": ["web", "api"]},
        True,
    ),
    (
        "a list without ids is kept when the tester changed it",
        {"tested_channels": ["web", "mobile"]},
        {"tested_channels": ["web"]},
        {"tested_channels": ["web", "api"]},
        {"tested_channels": ["web", "mobile"]},
        False,
    ),
    (
        "scope text, which the server never sends back, is kept",
        {"scope_text": {"production": {"web": "https://a.test"}}},
        {"scope_text": {"production": {"web": "https://a.test"}}},
        {},
        {"scope_text": {"production": {"web": "https://a.test"}}},
        False,
    ),
    ("saved_at is skipped", {"saved_at": "old"}, {"saved_at": "old"}, {"saved_at": "new"}, {"saved_at": "old"}, False),
    ("app_id is skipped", {"app_id": "unnamed"}, {"app_id": "unnamed"}, {"app_id": "northstar"}, {"app_id": "unnamed"}, False),
    (
        "the folder-name hint is skipped",
        {"_folder_name_hint": {"app_folder": ""}},
        {"_folder_name_hint": {"app_folder": ""}},
        {"_folder_name_hint": {"app_folder": "Northstar"}},
        {"_folder_name_hint": {"app_folder": ""}},
        False,
    ),
]


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class SaveModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self) -> None:
        # A context per test, so no test sees another's Web Storage.
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.saves: list[dict] = []
        self.page.route(f"{ORIGIN}/**", self.serve)
        # Before the save code loads, so every timer it sets is on the test's clock.
        self.page.clock.install(time=START)
        self.page.clock.pause_at(START)
        self.page.goto(f"{ORIGIN}/")

    def serve(self, route) -> None:
        request = route.request
        url_path = request.url.removeprefix(ORIGIN).split("?")[0]
        if url_path == "/":
            route.fulfill(content_type="text/html", body=PAGE)
        elif url_path.startswith("/static/"):
            route.fulfill(content_type="text/javascript", body=(STATIC / url_path.removeprefix("/static/")).read_text(encoding="utf-8"))
        elif request.method == "PUT" and url_path.startswith("/reports/"):
            sent = json.loads(request.post_data)
            self.saves.append(sent)
            saved = report_json(**{**sent, "saved_at": (START.replace(second=5)).isoformat()})
            route.fulfill(content_type="application/json", body=json.dumps({"saved_at": saved["saved_at"], "report": saved}))
        else:
            route.fulfill(status=404, body="")

    def start(self, report: dict) -> None:
        self.page.evaluate(
            """([report, idle]) => {
              window.VULNREPORT_AUTOSAVE_IDLE_MS = idle;
              window.saveCode = window.vrSave.start({root: document.querySelector("main"), serverReport: report, onSaved: () => {}});
            }""",
            [report, IDLE_MS],
        )

    def test_reconcile_canonical_object(self) -> None:
        self.assertTrue(RECONCILE_CASES, "an empty case table checks nothing")
        for name, live, sent, canonical, expected, changed in RECONCILE_CASES:
            with self.subTest(name):
                actual = self.page.evaluate(
                    """([live, sent, canonical]) => {
                      const changed = window.vrSave.reconcileCanonicalObject(live, sent, canonical);
                      return {changed, live};
                    }""",
                    [live, sent, canonical],
                )
                self.assertEqual(actual, {"changed": changed, "live": expected})

    def test_an_edit_saves_once_after_the_idle_time(self) -> None:
        self.start(report_json())
        save_button = self.page.locator("#save-button")
        expect(save_button).to_have_text(re.compile(r"^Saved"))

        self.page.evaluate("() => { saveCode.report.engagement.app_name = 'Northstar'; saveCode.scheduleSave(); }")
        self.page.clock.run_for(IDLE_MS - 1)
        # save() sets Saving before its request, so this reads in step with the clock.
        self.assertEqual(save_button.text_content(), "Unsaved changes")
        self.page.clock.run_for(1)

        expect(save_button).to_have_text(re.compile(r"^Saved \d\d:\d\d$"))
        self.assertEqual(len(self.saves), 1)
        self.assertEqual(self.saves[0]["engagement"]["app_name"], "Northstar")


if __name__ == "__main__":
    unittest.main()
