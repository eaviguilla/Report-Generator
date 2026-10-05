"""The save code in save.js, run in a blank page with no app server and no report page (ADR 0004)."""
from __future__ import annotations

import asyncio
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import main
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
<script>
  // Counted as each save is sent, so a test reads it in step with the clock, before any answer arrives.
  window.saveRequests = 0;
  const send = window.fetch;
  window.fetch = (input, init) => {
    if (init?.method === "PUT") window.saveRequests += 1;
    return send(input, init);
  };
</script>
<script src="/static/diagnostics.js"></script>
<script src="/static/save.js"></script>
</body></html>"""
START = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
IDLE_MS = 5000
REPORT_ID = "r_save_module"
FAILED = "Save failed - Retry"


def report_json(**fields) -> dict:
    """A report as the server sends it, built by the server's own model."""
    data = {"report_id": REPORT_ID, "app_id": "unnamed", "saved_at": START.isoformat(), **fields}
    return Report.model_validate(data).model_dump(mode="json", by_alias=True)


def conflict_reply() -> dict:
    """The server's answer to a stale save, built by its own code, after another tab saved a minute later."""
    latest = Report.model_validate(report_json(saved_at=START.replace(minute=1).isoformat()))
    with patch.object(main.workspace, "load", return_value=latest):
        detail = main.stale_report_detail(REPORT_ID)
    request = Request({
        "type": "http", "method": "PUT", "path": f"/reports/{REPORT_ID}", "headers": [], "query_string": b"",
        "scheme": "https", "server": ("save-module.test", 443), "endpoint": main.save_report,
    })
    response = asyncio.run(main.http_exception_handler(request, HTTPException(409, detail)))
    return {
        "status": response.status_code,
        "content_type": "application/json",
        "headers": {"X-VulnReport-Error": response.headers["x-vulnreport-error"]},
        "body": response.body.decode(),
    }


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
        # Built before Playwright starts, which runs an event loop of its own.
        cls.conflict = conflict_reply()
        cls.latest_saved_at = json.loads(cls.conflict["body"])["error"]["latest_saved_at"]
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self) -> None:
        self.open_page()

    def open_page(self) -> None:
        # A context per page, so no test sees another's Web Storage.
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        # Every save request, answered or not; each one takes the next answer, and a success once they run out.
        self.saves: list[dict] = []
        self.answers: list = []
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
            if self.answers:
                self.answers.pop(0)(route)
                return
            saved = report_json(**{**sent, "saved_at": (START.replace(second=5)).isoformat()})
            route.fulfill(content_type="application/json", body=json.dumps({"saved_at": saved["saved_at"], "report": saved}))
        else:
            route.fulfill(status=404, body="")

    def answer_conflict(self, route) -> None:
        route.fulfill(**self.conflict)

    def edit(self, owner: str) -> None:
        self.page.evaluate("owner => { saveCode.report.engagement.app_owner = owner; saveCode.scheduleSave(); }", owner)

    def stored_keys(self) -> dict:
        return self.page.evaluate("() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})")

    def recovery_copies(self) -> list[dict]:
        return self.page.evaluate(
            """prefix => Object.keys(localStorage).filter(key => key.startsWith(prefix)).map(key => JSON.parse(localStorage.getItem(key)))""",
            f"vulnreport-pending:{REPORT_ID}:",
        )

    def run_into_conflict(self) -> None:
        """An edit, saved at once by a click, that the server refuses as stale."""
        self.answers.append(self.answer_conflict)
        self.start(report_json())
        self.edit("Stale tab")
        # Clicked before the edit's own recovery copy is due, so any copy left is the conflict's.
        self.page.locator("#save-button").click()
        expect(self.page.locator("#save-button")).to_have_attribute("data-save-state", "conflict")
        self.assertEqual(len(self.saves), 1)

    def expect_attempts(self, count: int, settled: str = FAILED) -> None:
        """Attempt number `count` has just been sent; wait for its answer to settle the Save button."""
        self.assertEqual(self.page.evaluate("saveRequests"), count, f"attempt {count} was not sent")
        # The attempt set Saving as it was sent, so reaching this text means its answer arrived.
        expect(self.page.locator("#save-button")).to_have_text(re.compile(settled))
        self.assertEqual(len(self.saves), count)

    def wait_without_a_save(self, milliseconds: int) -> None:
        sent = self.page.evaluate("saveRequests")
        self.page.clock.run_for(milliseconds)
        self.assertEqual(self.page.evaluate("saveRequests"), sent, "a save was sent early")

    def fail_every_retry(self, fail) -> None:
        """An edit whose save and three retries all fail, each retry checked to the millisecond."""
        self.answers.extend([fail] * 4)
        self.start(report_json())
        self.edit("Retried")
        self.page.clock.run_for(IDLE_MS)
        self.expect_attempts(1)
        for attempt, delays in ((2, 1), (3, 2), (4, 4)):
            self.wait_without_a_save(IDLE_MS * delays - 1)
            self.page.clock.run_for(1)
            self.expect_attempts(attempt)
        self.wait_without_a_save(IDLE_MS * 100)
        self.assertEqual(len(self.saves), 4)

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

    def test_a_save_conflict_shows_resolve_conflict_and_keeps_a_recovery_copy(self) -> None:
        self.run_into_conflict()

        save_button = self.page.locator("#save-button")
        self.assertEqual(save_button.text_content(), "Resolve conflict")
        self.assertEqual(save_button.get_attribute("data-action"), "resolve")
        panel = self.page.locator("#app-diagnostics")
        expect(panel.get_by_role("heading")).to_have_text("Save conflict")
        self.assertEqual(panel.locator(".diagnostic-message").text_content(), main.STALE_REPORT_DETAIL)
        self.assertIn("save_report / 409 / stale_report", panel.locator(".diagnostic-code").text_content())
        copies = self.recovery_copies()
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["report"]["engagement"]["app_owner"], "Stale tab")

    def test_nothing_is_sent_while_a_save_conflict_stands(self) -> None:
        self.run_into_conflict()
        save_button = self.page.locator("#save-button")

        self.edit("Typed after the conflict")
        self.page.clock.run_for(IDLE_MS * 10)
        # An upload and a library insert each ask for a save, with these words, before they go.
        for asked_by, words in (("an upload", "Uploading..."), ("a library insert", "Adding...")):
            with self.subTest(asked_by):
                self.assertIs(self.page.evaluate("words => saveCode.save(words)", words), False)
        save_button.click()
        expect(self.page.locator("#app-diagnostics")).to_be_focused()

        self.assertEqual(len(self.saves), 1)
        self.assertEqual(save_button.get_attribute("data-save-state"), "conflict")
        self.assertEqual(save_button.text_content(), "Resolve conflict")

    def test_save_my_version_sends_the_report_again_with_the_latest_revision(self) -> None:
        self.run_into_conflict()
        save_button = self.page.locator("#save-button")

        self.page.locator("#app-diagnostics").get_by_role("button", name="Save my version").click()

        expect(save_button).to_have_attribute("data-save-state", "saved")
        self.assertEqual(len(self.saves), 2)
        self.assertEqual(self.saves[1]["saved_at"], self.latest_saved_at)
        self.assertEqual(self.saves[1]["engagement"]["app_owner"], "Stale tab")
        self.assertEqual(self.page.locator("#app-diagnostics").count(), 0)
        self.assertEqual(self.recovery_copies(), [])
        # The conflict is over: the next edit saves as usual.
        self.edit("Saved after the conflict")
        save_button.click()
        expect(save_button).to_have_attribute("data-save-state", "saved")
        self.assertEqual(len(self.saves), 3)
        self.assertEqual(self.saves[2]["engagement"]["app_owner"], "Saved after the conflict")

    def test_load_latest_removes_the_recovery_copy_and_the_undo_history_and_reloads(self) -> None:
        self.run_into_conflict()
        history_key = f"vulnreport-history:{REPORT_ID}"
        self.assertEqual(len(self.recovery_copies()), 1)
        self.assertIn(history_key, self.stored_keys()["session"])

        with self.page.expect_navigation():
            self.page.locator("#app-diagnostics").get_by_role("button", name="Load latest").click()

        self.assertEqual(self.recovery_copies(), [])
        self.assertNotIn(history_key, self.stored_keys()["session"])
        self.assertEqual(len(self.saves), 1)

    def test_a_failed_save_retries_three_times_after_one_two_and_four_idle_delays(self) -> None:
        failures = [
            ("a dropped save", lambda route: route.abort()),
            ("a 5xx", lambda route: route.fulfill(status=503, body="")),
        ]
        for name, fail in failures:
            with self.subTest(name):
                self.open_page()
                self.fail_every_retry(fail)
                self.assertTrue(all(sent["engagement"]["app_owner"] == "Retried" for sent in self.saves))

    def test_a_retry_that_succeeds_saves_the_edit_and_clears_the_failure(self) -> None:
        self.answers.append(lambda route: route.abort())
        self.start(report_json())
        self.edit("Saved on retry")
        self.page.clock.run_for(IDLE_MS)
        self.expect_attempts(1)
        expect(self.page.locator("#app-diagnostics").get_by_role("heading")).to_have_text("Operation failed")

        self.page.clock.run_for(IDLE_MS)
        self.expect_attempts(2, settled=r"^Saved \d\d:\d\d$")
        self.assertEqual(self.saves[1]["engagement"]["app_owner"], "Saved on retry")
        self.assertEqual(self.page.locator("#app-diagnostics").count(), 0)

    def test_a_refused_save_is_not_retried(self) -> None:
        self.answers.append(lambda route: route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Refused"})))
        self.start(report_json())
        self.edit("Refused")
        self.page.clock.run_for(IDLE_MS)
        self.expect_attempts(1)

        self.wait_without_a_save(IDLE_MS * 100)
        self.assertEqual(len(self.saves), 1)

    def test_an_edit_or_a_save_click_starts_the_retry_count_again(self) -> None:
        triggers = [
            ("an edit", lambda: (self.edit("Edited again"), self.page.clock.run_for(IDLE_MS))),
            ("a Save click", lambda: self.page.locator("#save-button").click()),
        ]
        for name, trigger in triggers:
            with self.subTest(name):
                self.open_page()
                self.fail_every_retry(lambda route: route.abort())
                self.answers.append(lambda route: route.abort())

                trigger()
                self.expect_attempts(5)
                self.wait_without_a_save(IDLE_MS - 1)
                self.page.clock.run_for(1)
                self.expect_attempts(6, settled=r"^Saved \d\d:\d\d$")


if __name__ == "__main__":
    unittest.main()
