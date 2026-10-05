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
  <input id="owner-field" data-field="owner">
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
SAVED = r"^Saved \d\d:\d\d$"
SCOPE_HOLD = "Confirm the scope target change"
# What the test page's nameField calls its one named field.
OWNER_FIELD = {"name": "owner"}


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


def page_url(page_name: str) -> str:
    return f"{ORIGIN}/reports/{REPORT_ID}/{page_name}"


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
    def test_a_page_check_stops_the_next_round_of_a_save_already_out(self) -> None:
        self.start(report_json())
        save_button = self.page.locator("#save-button")
        self.edit("Sent")
        self.page.evaluate(
            """hold => {
              saveCode.save();
              saveCode.report.engagement.app_owner = 'Typed while it was out';
              saveCode.scheduleSave();
              window.heldBy = hold;
            }""",
            SCOPE_HOLD,
        )

        expect(save_button).to_have_text(SCOPE_HOLD)
        self.assertEqual(len(self.saves), 1)
        self.assertEqual(self.saves[0]["engagement"]["app_owner"], "Sent")

    def test_load_latest_stays_in_conflict_when_undo_history_cannot_be_removed(self) -> None:
                self.run_into_conflict()
                history_key = f"vulnreport-history:{REPORT_ID}"
                self.page.evaluate(
                        """prefix => {
                            const original = Storage.prototype.removeItem;
                            Storage.prototype.removeItem = function(key, ...rest) {
                                if (key.startsWith(prefix)) throw new DOMException('blocked', 'SecurityError');
                                return original.call(this, key, ...rest);
                            };
                        }""",
                        "vulnreport-history:",
                )
                panel = self.page.locator("#app-diagnostics")

                panel.get_by_role("button", name="Load latest").click()

                self.assertEqual(self.page.evaluate("typeof saveCode"), "object", "the page reloaded")
                expect(panel.get_by_role("heading")).to_have_text("Browser recovery unavailable")
                self.assertEqual(self.page.locator("#save-button").get_attribute("data-save-state"), "conflict")
                self.assertEqual(len(self.recovery_copies()), 1)
                self.assertIn(history_key, self.stored_keys()["session"])

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

    def open_page(self, init_script: str | None = None) -> None:
        # A context per page, so no test sees another's Web Storage.
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        if init_script:
            self.page.add_init_script(init_script)
        # Every save request, answered or not; each one takes the next answer, and a success once they run out.
        self.saves: list[dict] = []
        self.answers: list = []
        self.page.route(f"{ORIGIN}/**", self.serve)
        # Before the save code loads, so every timer it sets is on the test's clock.
        self.page.clock.install(time=START)
        self.page.clock.pause_at(START)
        self.page.goto(page_url("findings"))

    def serve(self, route) -> None:
        request = route.request
        url_path = request.url.removeprefix(ORIGIN).split("?")[0]
        if url_path.startswith("/static/"):
            route.fulfill(content_type="text/javascript", body=(STATIC / url_path.removeprefix("/static/")).read_text(encoding="utf-8"))
        elif request.method == "GET":
            # Every report page is the same blank page; a test reads which one from the address.
            route.fulfill(content_type="text/html", body=PAGE)
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

    @staticmethod
    def refuse(route) -> None:
        route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Refused"}))

    def history(self) -> dict:
        return self.page.evaluate("key => JSON.parse(sessionStorage.getItem(key) || '{}')", f"vulnreport-history:{REPORT_ID}")

    def step_made_on(self, page_name: str, owner: str, in_field: bool = False) -> dict:
        """An edit made and saved on `page_name`; returns the report the server then holds."""
        self.page.goto(page_url(page_name))
        self.start(report_json(), page_name)
        if in_field:
            self.edit_in_field(owner)
        else:
            self.edit(owner)
        self.page.locator("#save-button").click()
        expect(self.page.locator("#save-button")).to_have_attribute("data-save-state", "saved")
        return self.page.evaluate("saveCode.report")

    def edit(self, owner: str) -> None:
        self.page.evaluate("owner => { saveCode.report.engagement.app_owner = owner; saveCode.scheduleSave(); }", owner)

    def edit_in_field(self, owner: str) -> None:
        """The same edit, typed into the page's one named field, which then loses focus."""
        self.page.evaluate(
            """owner => {
              const field = document.querySelector('#owner-field');
              field.focus();
              saveCode.report.engagement.app_owner = owner;
              saveCode.scheduleSave();
              field.blur();
            }""",
            owner,
        )

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

    def open_tab(self):
        """A second tab in the same browser, sharing localStorage with self.page but not sessionStorage."""
        tab = self.page.context.new_page()
        tab.route(f"{ORIGIN}/**", self.serve)
        tab.goto(f"{ORIGIN}/")
        return tab

    def plant_copy(self, owner: str, based_on: str, page_name: str | None = None, field: dict | None = None) -> str:
        """A recovery copy left by a tab that closed before its edit was saved; returns its key.
        Without `page_name` it is a copy written before copies recorded their page."""
        report = report_json()
        report["engagement"]["app_owner"] = owner
        key = f"vulnreport-pending:{REPORT_ID}:closed-tab:copy"
        envelope = {
            "schemaVersion": 1, "reportId": REPORT_ID, "tabId": "closed-tab", "baseSavedAt": based_on,
            "capturedAt": based_on, "editRevision": 1, "report": report,
        }
        if page_name:
            envelope["page"] = page_name
        if field:
            envelope["field"] = field
        self.page.evaluate("([key, envelope]) => localStorage.setItem(key, JSON.stringify(envelope))", [key, envelope])
        return key

    def start(self, report: dict, page_name: str = "findings") -> None:
        self.page.evaluate(
            """([report, idle, page]) => {
              window.VULNREPORT_AUTOSAVE_IDLE_MS = idle;
              window.saveCode = window.vrSave.start({
                root: document.querySelector("main"), serverReport: report, page, saveCheck: () => window.heldBy, onSaved: () => {},
                nameField: element => element?.dataset?.field ? {name: element.dataset.field} : null,
              });
            }""",
            [report, IDLE_MS, page_name],
        )

    def changed_field(self):
        return self.page.evaluate("saveCode.changedField")

    def test_a_step_and_a_recovery_copy_record_the_field_they_were_made_in(self) -> None:
        self.start(report_json())

        self.edit_in_field("Typed in the field")
        self.page.clock.run_for(150)

        [step] = self.history()["undoHistory"]
        self.assertEqual(step["field"], OWNER_FIELD)
        [copy] = self.recovery_copies()
        self.assertEqual(copy["field"], OWNER_FIELD)

    def test_a_step_made_with_no_field_focused_records_its_page_alone(self) -> None:
        self.start(report_json())

        self.edit("Changed with nothing focused")

        [step] = self.history()["undoHistory"]
        self.assertEqual(step["page"], "findings")
        self.assertNotIn("field", step)

    def test_undo_and_redo_hand_the_steps_field_to_the_page_they_open(self) -> None:
        saved = self.step_made_on("setup", "Typed on Setup", in_field=True)
        self.page.goto(page_url("findings"))
        self.start(saved, "findings")
        self.assertIsNone(self.changed_field())

        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#undo-button").click()
        self.start(report_json(**self.saves[-1]), "setup")
        self.assertEqual(self.changed_field(), OWNER_FIELD)
        # Redo on the step's own page reloads it, and the field comes back again.
        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#redo-button").click()
        self.start(report_json(**self.saves[-1]), "setup")

        self.assertEqual(self.changed_field(), OWNER_FIELD)

    def test_a_page_the_tester_is_redirected_to_gets_no_field(self) -> None:
        saved = self.step_made_on("setup", "Typed on Setup", in_field=True)
        self.page.goto(page_url("findings"))
        self.start(saved, "findings")
        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#undo-button").click()

        # As if a page gate had sent the tester on to Findings.
        self.start(report_json(**self.saves[-1]), "findings")
        self.assertIsNone(self.changed_field())
        self.page.goto(page_url("setup"))
        self.start(report_json(**self.saves[-1]), "setup")

        self.assertIsNone(self.changed_field())

    def test_a_restored_copy_keeps_its_field_when_written_again(self) -> None:
        self.plant_copy("Recovered owner", report_json()["saved_at"], "findings", OWNER_FIELD)
        self.start(report_json(), "findings")
        with self.page.expect_navigation(url=page_url("findings")):
            self.page.locator("#app-diagnostics").get_by_role("button", name="Restore", exact=True).click()
        self.answers.append(self.refuse)
        self.start(report_json(), "findings")

        # The restored copy's save is refused, so the page writes a copy of its own.
        self.page.clock.run_for(IDLE_MS)
        self.expect_attempts(1)

        [rewritten] = [copy for copy in self.recovery_copies() if copy["tabId"] != "closed-tab"]
        self.assertEqual(rewritten["field"], OWNER_FIELD)

    def test_restore_hands_the_copys_field_to_the_page_it_opens(self) -> None:
        self.plant_copy("Recovered owner", report_json()["saved_at"], "setup", OWNER_FIELD)
        self.start(report_json(), "findings")

        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#app-diagnostics").get_by_role("button", name="Restore on Setup", exact=True).click()
        self.start(report_json(), "setup")

        self.assertEqual(self.changed_field(), OWNER_FIELD)

    def test_an_undo_step_and_a_recovery_copy_record_the_page_they_were_made_on(self) -> None:
        self.page.goto(page_url("setup"))
        self.start(report_json(), "setup")

        self.edit("Typed on Setup")
        self.page.clock.run_for(150)

        [step] = self.history()["undoHistory"]
        self.assertEqual(step["page"], "setup")
        [copy] = self.recovery_copies()
        self.assertEqual(copy["page"], "setup")

    def test_undo_opens_the_page_of_its_step_and_redo_there_brings_the_change_back(self) -> None:
        saved = self.step_made_on("setup", "Typed on Setup")
        self.page.goto(page_url("findings"))
        self.start(saved, "findings")

        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#undo-button").click()
        self.assertEqual(self.saves[-1]["engagement"]["app_owner"], report_json()["engagement"]["app_owner"])
        self.start(report_json(**self.saves[-1]), "setup")
        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#redo-button").click()

        self.assertEqual(self.saves[-1]["engagement"]["app_owner"], "Typed on Setup")

    def test_an_undo_reloads_the_page_when_its_step_was_made_there_or_records_no_page(self) -> None:
        older_step = {"changes": [{"path": ["engagement", "app_owner"], "beforePresent": True, "before": "Before", "afterPresent": True, "after": ""}]}
        cases = [("a step made on this page", None), ("a step written before steps recorded a page", older_step)]
        for name, planted in cases:
            with self.subTest(name):
                self.open_page()
                if planted:
                    self.page.evaluate(
                        "([key, step]) => sessionStorage.setItem(key, JSON.stringify({undoHistory: [step], redoHistory: []}))",
                        [f"vulnreport-history:{REPORT_ID}", planted],
                    )
                    self.start(report_json(), "findings")
                else:
                    self.step_made_on("findings", "Typed on Findings")
                sent = len(self.saves)

                with self.page.expect_navigation(url=page_url("findings")):
                    self.page.locator("#undo-button").click()

                self.assertEqual(len(self.saves), sent + 1)
                self.assertEqual(self.saves[-1]["engagement"]["app_owner"], "Before" if planted else report_json()["engagement"]["app_owner"])

    def test_a_refused_undo_still_opens_the_steps_page_with_its_recovery_copy(self) -> None:
        saved = self.step_made_on("setup", "Typed on Setup", in_field=True)
        self.page.goto(page_url("findings"))
        self.start(saved, "findings")
        self.answers.append(self.refuse)

        with self.page.expect_navigation(url=page_url("setup")):
            self.page.locator("#undo-button").click()

        [copy] = self.recovery_copies()
        self.assertEqual(copy["page"], "setup")
        self.assertEqual(copy["field"], OWNER_FIELD)
        self.start(saved, "setup")
        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), report_json()["engagement"]["app_owner"])
        self.assertEqual(self.page.locator("#save-button").get_attribute("data-save-state"), "recovered")

    def test_restore_opens_the_page_where_the_copy_was_made_and_names_it(self) -> None:
        cases = [
            ("setup", "Restore on Setup", "setup"),
            ("edit", "Restore on Content", "edit"),
            ("findings", "Restore", "findings"),
            (None, "Restore", "findings"),
        ]
        for copy_page, words, opens in cases:
            with self.subTest(copy_page=copy_page):
                self.open_page()
                self.plant_copy("Recovered owner", report_json()["saved_at"], copy_page)
                self.start(report_json(), "findings")
                panel = self.page.locator("#app-diagnostics")
                expect(panel.get_by_role("heading")).to_have_text("Unsaved changes found")

                with self.page.expect_navigation(url=page_url(opens)):
                    panel.get_by_role("button", name=words, exact=True).click()
                self.start(report_json(), opens)

                self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Recovered owner")

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

    def test_save_my_version_can_receive_and_resolve_a_second_conflict(self) -> None:
        self.run_into_conflict()
        second_latest = START.replace(minute=2).isoformat()
        second_conflict = {**self.conflict}
        second_body = json.loads(second_conflict["body"])
        second_body["error"]["latest_saved_at"] = second_latest
        second_conflict["body"] = json.dumps(second_body)
        self.answers.append(lambda route: route.fulfill(**second_conflict))
        panel = self.page.locator("#app-diagnostics")

        panel.get_by_role("button", name="Save my version").click()

        expect(self.page.locator("#save-button")).to_have_attribute("data-save-state", "conflict")
        expect(panel.get_by_role("heading")).to_have_text("Save conflict")
        self.assertEqual(len(self.saves), 2)
        self.assertEqual(self.saves[1]["saved_at"], self.latest_saved_at)
        self.assertEqual(len(self.recovery_copies()), 1)

        panel.get_by_role("button", name="Save my version").click()

        expect(self.page.locator("#save-button")).to_have_attribute("data-save-state", "saved")
        self.assertEqual(len(self.saves), 3)
        self.assertEqual(self.saves[2]["saved_at"], second_latest)
        self.assertEqual(self.recovery_copies(), [])

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

    def test_load_latest_stays_in_conflict_when_the_recovery_copy_cannot_be_removed(self) -> None:
        self.run_into_conflict()
        self.page.evaluate(
            """() => {
              const original = Storage.prototype.removeItem;
              Storage.prototype.removeItem = function(key, ...rest) {
                if (key.startsWith('vulnreport-pending:')) throw new DOMException('blocked', 'SecurityError');
                return original.call(this, key, ...rest);
              };
            }"""
        )
        panel = self.page.locator("#app-diagnostics")

        panel.get_by_role("button", name="Load latest").click()

        self.assertEqual(self.page.evaluate("typeof saveCode"), "object", "the page reloaded")
        expect(panel.get_by_role("heading")).to_have_text("Browser recovery unavailable")
        self.assertEqual(self.page.locator("#save-button").get_attribute("data-save-state"), "conflict")
        self.assertEqual(len(self.recovery_copies()), 1)

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

    def test_an_edit_writes_a_recovery_copy_that_its_save_removes(self) -> None:
        self.start(report_json())
        self.edit("Not saved yet")
        self.page.clock.run_for(149)
        self.assertEqual(self.recovery_copies(), [])
        self.page.clock.run_for(1)

        [copy] = self.recovery_copies()
        self.assertEqual(copy["report"]["engagement"]["app_owner"], "Not saved yet")
        self.assertEqual(copy["baseSavedAt"], report_json()["saved_at"])

        self.page.clock.run_for(IDLE_MS - 150)
        self.expect_attempts(1, settled=SAVED)
        self.assertEqual(self.recovery_copies(), [])

    def test_restore_makes_the_copy_left_behind_the_report_and_saves_it_after_the_idle_time(self) -> None:
        self.plant_copy("Recovered owner", report_json()["saved_at"])
        self.start(report_json())
        panel = self.page.locator("#app-diagnostics")
        expect(panel.get_by_role("heading")).to_have_text("Unsaved changes found")
        self.assertNotEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Recovered owner")

        with self.page.expect_navigation():
            panel.get_by_role("button", name="Restore", exact=True).click()
        self.start(report_json())

        save_button = self.page.locator("#save-button")
        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Recovered owner")
        self.assertEqual(save_button.text_content(), "Recovered changes")
        self.assertEqual(save_button.get_attribute("data-save-state"), "recovered")
        self.wait_without_a_save(IDLE_MS - 1)
        self.page.clock.run_for(1)
        self.expect_attempts(1, settled=SAVED)
        self.assertEqual(self.saves[0]["engagement"]["app_owner"], "Recovered owner")
        self.assertEqual(self.recovery_copies(), [])

    def test_restore_waits_for_a_fresh_edit_to_save_before_arming_the_old_copy(self) -> None:
        self.plant_copy("Old recovered owner", report_json()["saved_at"])
        self.start(report_json())
        self.edit("Fresh owner")
        dialogs = []

        def cancel_leave(dialog) -> None:
            dialogs.append(dialog.type)
            dialog.dismiss()

        self.page.once("dialog", cancel_leave)
        self.page.locator("#app-diagnostics").get_by_role("button", name="Restore", exact=True).click()

        self.assertEqual(dialogs, [])
        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Fresh owner")
        save_button = self.page.locator("#save-button")
        expect(save_button).to_have_text("Save current changes before restoring")
        self.assertEqual(save_button.get_attribute("data-save-state"), "unsaved")
        save_button.click()
        expect(save_button).to_have_attribute("data-save-state", "saved")
        saved_report = self.page.evaluate("saveCode.report")

        self.page.reload()
        self.start(saved_report)

        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Fresh owner")

    def test_discard_removes_the_copy_left_behind(self) -> None:
        offers = [
            ("a copy of the saved revision", report_json()["saved_at"], "Unsaved changes from an earlier session are available."),
            ("a copy of an older revision", START.replace(hour=8).isoformat(), "A local draft was created from an older saved version of this report."),
        ]
        for name, based_on, message in offers:
            with self.subTest(name):
                self.open_page()
                self.plant_copy("Discarded owner", based_on)
                self.start(report_json())
                panel = self.page.locator("#app-diagnostics")
                expect(panel.get_by_role("heading")).to_have_text("Unsaved changes found")
                self.assertEqual(panel.locator(".diagnostic-message").text_content(), message)

                panel.get_by_role("button", name="Discard", exact=True).click()

                expect(panel).to_have_count(0)
                self.assertEqual(self.recovery_copies(), [])
                self.assertEqual(self.page.locator("#save-button").get_attribute("data-save-state"), "saved")
                self.assertNotEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Discarded owner")
                self.wait_without_a_save(IDLE_MS * 10)

    def test_discarding_an_old_copy_does_not_claim_a_new_edit_is_saved(self) -> None:
        self.plant_copy("Discarded owner", report_json()["saved_at"])
        self.start(report_json())
        panel = self.page.locator("#app-diagnostics")
        expect(panel.get_by_role("heading")).to_have_text("Unsaved changes found")

        self.edit("Fresh edit")
        panel.get_by_role("button", name="Discard", exact=True).click()

        expect(panel).to_have_count(0)
        self.assertEqual(self.recovery_copies(), [])
        self.assertEqual(self.page.locator("#save-button").get_attribute("data-save-state"), "unsaved")
        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Fresh edit")

    def test_equal_time_recovery_copies_prefer_the_newer_server_revision(self) -> None:
        current = report_json()
        copies = []
        for suffix, owner, based_on in (
            ("older", "Older-base copy", START.replace(hour=8).isoformat()),
            ("current", "Current-base copy", current["saved_at"]),
        ):
            recovered = report_json()
            recovered["engagement"]["app_owner"] = owner
            copies.append({
                "key": f"vulnreport-pending:{REPORT_ID}:closed-tab:{suffix}",
                "envelope": {
                    "schemaVersion": 1,
                    "reportId": REPORT_ID,
                    "tabId": f"closed-tab-{suffix}",
                    "baseSavedAt": based_on,
                    "capturedAt": START.isoformat(),
                    "editRevision": 1,
                    "report": recovered,
                },
            })
        self.page.evaluate(
            "copies => copies.forEach(copy => localStorage.setItem(copy.key, JSON.stringify(copy.envelope)))",
            copies,
        )
        self.start(current)

        panel = self.page.locator("#app-diagnostics")
        with self.page.expect_navigation():
            panel.get_by_role("button", name="Restore", exact=True).click()
        self.start(current)

        self.assertEqual(self.page.evaluate("saveCode.report.engagement.app_owner"), "Current-base copy")

    def test_a_save_leaves_another_tabs_copy_alone(self) -> None:
        first = self.page
        second = self.open_tab()
        for tab, owner in ((first, "First tab"), (second, "Second tab")):
            self.page = tab
            self.start(report_json())
            self.edit(owner)
        # One clock serves the whole browser, so both tabs write their copies now.
        first.clock.run_for(150)
        tab_ids = {copy["report"]["engagement"]["app_owner"]: copy["tabId"] for copy in self.recovery_copies()}
        self.assertEqual(sorted(tab_ids), ["First tab", "Second tab"])
        self.assertNotEqual(tab_ids["First tab"], tab_ids["Second tab"])
        # The first tab's save also removes its copy under the key used before each page load had its own.
        older_key = f"vulnreport-pending:{REPORT_ID}:{tab_ids['First tab']}"
        first.evaluate(
            "key => localStorage.setItem(key, JSON.stringify({tabId: key.split(':').at(-1), report: {engagement: {app_owner: 'Older key'}}}))",
            older_key,
        )

        self.page = first
        first.locator("#save-button").click()
        self.expect_attempts(1, settled=SAVED)

        [copy] = self.recovery_copies()
        self.assertEqual(copy["tabId"], tab_ids["Second tab"])
        self.assertEqual(copy["report"]["engagement"]["app_owner"], "Second tab")

    def test_web_storage_that_throws_is_reported_and_saves_still_reach_the_server(self) -> None:
        for storage in ("localStorage", "sessionStorage"):
            with self.subTest(storage):
                self.open_page(
                    f"Object.defineProperty(window, '{storage}', {{configurable: true, get() {{ throw new DOMException('blocked', 'SecurityError'); }}}})"
                )
                self.answers.append(lambda route: route.abort())
                self.start(report_json())
                heading = self.page.locator("#app-diagnostics").get_by_role("heading")
                expect(heading).to_have_text("Browser recovery unavailable")
                self.assertIn("Server saves still work", self.page.locator("#app-diagnostics").text_content())

                self.edit("Saved without storage")
                self.page.clock.run_for(IDLE_MS)
                self.expect_attempts(1)
                self.page.clock.run_for(IDLE_MS)
                self.expect_attempts(2, settled=SAVED)

                self.assertEqual(self.saves[1]["engagement"]["app_owner"], "Saved without storage")
                # The failure notice replaced the warning; the save that cleared it brings the warning back.
                expect(heading).to_have_text("Browser recovery unavailable")

    def test_restore_or_discard_that_storage_refuses_keeps_the_copy_and_says_so(self) -> None:
        refusals = [
            ("Restore", "setItem", "vulnreport-recovery:"),
            ("Discard", "removeItem", "vulnreport-pending:"),
        ]
        for action, method, refused_prefix in refusals:
            with self.subTest(action):
                self.open_page()
                key = self.plant_copy("Kept owner", report_json()["saved_at"])
                self.start(report_json())
                self.page.evaluate(
                    """([method, prefix]) => {
                      const original = Storage.prototype[method];
                      Storage.prototype[method] = function(key, ...rest) {
                        if (key.startsWith(prefix)) throw new DOMException('blocked', 'SecurityError');
                        return original.call(this, key, ...rest);
                      };
                    }""",
                    [method, refused_prefix],
                )
                panel = self.page.locator("#app-diagnostics")

                panel.get_by_role("button", name=action, exact=True).click()

                expect(panel.get_by_role("heading")).to_have_text("Browser recovery unavailable")
                self.assertEqual(self.page.evaluate("typeof saveCode"), "object", "the page reloaded")
                self.assertIsNotNone(self.page.evaluate("key => localStorage.getItem(key)", key))

    def test_a_save_check_that_returns_words_holds_the_save(self) -> None:
        words = "Correct invalid Setup fields"
        self.start(report_json())
        save_button = self.page.locator("#save-button")
        self.page.evaluate("words => { window.heldBy = words; }", words)

        self.edit("Held by the check")
        self.wait_without_a_save(IDLE_MS * 10)
        self.assertEqual(save_button.text_content(), words)
        self.assertEqual(save_button.get_attribute("data-save-state"), "unsaved")
        save_button.click()
        self.assertEqual(self.page.evaluate("saveRequests"), 0)
        self.assertEqual(save_button.text_content(), words)

        self.page.evaluate("() => { window.heldBy = undefined; }")
        save_button.click()
        self.expect_attempts(1, settled=SAVED)
        self.assertEqual(self.saves[0]["engagement"]["app_owner"], "Held by the check")

    def test_hold_saves_holds_every_save_until_released(self) -> None:
        self.start(report_json())
        save_button = self.page.locator("#save-button")
        self.page.evaluate("() => saveCode.holdSaves(true)")

        self.edit("Held for the scope dialog")
        self.wait_without_a_save(IDLE_MS * 10)
        self.assertEqual(save_button.text_content(), SCOPE_HOLD)
        save_button.click()
        # An upload asks for a save, with its words, before it goes.
        self.assertIs(self.page.evaluate("() => saveCode.save('Uploading...')"), False)
        self.assertEqual(self.page.evaluate("saveRequests"), 0)
        self.assertEqual(save_button.text_content(), SCOPE_HOLD)

        self.page.evaluate("() => saveCode.holdSaves(false)")
        save_button.click()
        self.expect_attempts(1, settled=SAVED)
        self.assertEqual(self.saves[0]["engagement"]["app_owner"], "Held for the scope dialog")

    def test_hold_saves_stops_the_next_round_of_a_save_already_out(self) -> None:
        self.start(report_json())
        save_button = self.page.locator("#save-button")
        self.edit("Sent")
        # One step in the page, so the save is still out when the second edit and the hold arrive.
        self.page.evaluate(
            """() => {
              saveCode.save();
              saveCode.report.engagement.app_owner = 'Typed while it was out';
              saveCode.scheduleSave();
              saveCode.holdSaves(true);
            }"""
        )

        # The loop sets these words only once the first answer is back.
        expect(save_button).to_have_text(SCOPE_HOLD)
        self.assertEqual(len(self.saves), 1)
        self.assertEqual(self.saves[0]["engagement"]["app_owner"], "Sent")
        self.wait_without_a_save(IDLE_MS * 10)

        self.page.evaluate("() => saveCode.holdSaves(false)")
        save_button.click()
        self.expect_attempts(2, settled=SAVED)
        self.assertEqual(self.saves[1]["engagement"]["app_owner"], "Typed while it was out")

if __name__ == "__main__":
    unittest.main()
