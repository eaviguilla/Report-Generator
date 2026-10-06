from __future__ import annotations

import base64
import json
import re
import socket
import hashlib
import threading
import time
import unittest
from copy import deepcopy
from datetime import date, datetime as RealDateTime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import uvicorn
import app.workspace as workspace_module
from docx import Document
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from app import acceptance, main
from app.docx_import import NO_FINDINGS_TITLE
from app.docx_report import generation_issues, main_template_path, render_report_docx
from app.report_service import finding_input_issues, format_rule_message, setup_input_issues, setup_issues, setup_refusal_message, scope_text_refusals, status_conclusion_runs
from app.storage import atomic_write_json, read_json
from tests.support import png_bytes, use_temp_workspace
from app.models import STATUS_LABELS, CodeFragment, Content, Engagement, EvidenceItem, ImageFragment, LibraryRef, ListFragment, ListItem, NoteFragment, ParagraphFragment, Run, Scope, ScopeTarget, TestAccount, TestWindow, Vulnerability


# Tests wait for "Saved" constantly, and the app autosaves after 5 s idle, so most of that wait was the
# idle timer. This shortens it for every test, but yields to a value a test sets itself, whichever of
# the two init scripts runs first (Playwright does not define their order), and to the legacy alias.
AUTOSAVE_TEST_DEFAULT = """(() => {
    let explicit = window.VULNREPORT_AUTOSAVE_IDLE_MS;
    Object.defineProperty(window, "VULNREPORT_AUTOSAVE_IDLE_MS", {
        configurable: true,
        get: () => explicit ?? (window.VULNREPORT_AUTOSAVE_INTERVAL_MS === undefined ? 500 : undefined),
        set: value => { explicit = value; },
    });
})()"""
# The mark Content's Go to button leaves, which Undo, Redo and Restore also leave on the changed field.
MARKED = re.compile(r"\bis-review-target\b")


def setup_issue(field_name: str, value: str, environment: str = "production") -> str:
    """The server's message for one invalid Setup value, which the browser must show word for word."""
    windows = {environment: TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)) for environment in ("production", "non_production")}
    engagement = Engagement(tested_environments=["production", "non_production"], test_windows=windows, test_accounts=[TestAccount(user_role="N/A", username="N/A")])
    target = windows[environment] if field_name == "test_time" else engagement.test_accounts[0] if field_name in ("user_role", "username") else engagement
    setattr(target, field_name, value)
    [issue] = setup_input_issues(engagement)
    return issue


class BrowserWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # One server, Playwright and Chromium per class; starting them per test was most of the run.
        # Class cleanups run last-in-first-out: browser, Playwright, then the server.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.addClassCleanup(sock.close)
        cls.base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(main.app, log_level="error"))
        server_thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [sock]}, daemon=True)
        server_thread.start()
        cls.addClassCleanup(server_thread.join, 5)
        cls.addClassCleanup(setattr, cls.server, "should_exit", True)
        deadline = time.monotonic() + 10
        while not cls.server.started:
            if not server_thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Browser test server did not start")
            time.sleep(0.01)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self) -> None:
        # Registered first, so it is undone last: the context closes before the workspace goes back.
        self.root = use_temp_workspace(self, "Browser QA")
        # A fresh context per test: same origin every time, so localStorage would otherwise leak.
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.add_init_script(AUTOSAVE_TEST_DEFAULT)
        self.page = self.context.new_page()

    def other_profile_page(self):
        """A page in its own browser context, i.e. a second browser profile rather than a second tab."""
        page = self.browser.new_page()
        self.addCleanup(lambda: page.is_closed() or page.close())
        return page

    def _next_report_change(self, action) -> None:
        """Run an edit and wait for the reportchange event it causes (app.js fires one 100 ms after an
        edit, and redraws its offers on it), so a test can then check what did not happen without a sleep."""
        self.page.evaluate("() => { window.reportChanges = 0; document.addEventListener('reportchange', () => { window.reportChanges += 1; }); }")
        action()
        self.page.wait_for_function("window.reportChanges > 0", timeout=5_000)

    def plant_recovery_draft(self, report: dict, page_path: str, tab_id: str) -> None:
        """Leave `report` in localStorage as another tab's unsaved draft, then reload the page so it
        finds the draft and offers to restore it."""
        report_id = report["report_id"]
        envelope = {
            "schemaVersion": 1, "reportId": report_id, "tabId": tab_id, "baseSavedAt": report["saved_at"],
            "capturedAt": report["saved_at"], "editRevision": 1, "report": report,
        }
        self.page.goto(f"{self.base_url}/reports/{report_id}/{page_path}")
        self.page.evaluate("([key, draft]) => localStorage.setItem(key, JSON.stringify(draft))", [f"vulnreport-pending:{report_id}:{tab_id}", envelope])
        self.page.reload()

    def restore_recovery_draft(self) -> None:
        """Take the recovery offer. Restoring reloads the page, so wait for that navigation itself:
        wait_for_load_state() alone returns at once while the old page still counts as loaded."""
        with self.page.expect_navigation():
            self.page.get_by_role("button", name="Restore", exact=True).click()

    @staticmethod
    def _count_or_zero(locator) -> int:
        """A locator count that reads 0 while the page is mid-navigation instead of raising."""
        try:
            return locator.count()
        except PlaywrightError:
            return 0

    def choose_required_engagement_details(self) -> None:
        """Network access and the report date start blank and are required before Findings."""
        self.page.get_by_label("Network Access").select_option("Internal")
        self.page.get_by_label("Report Date").fill("2026-01-03")

    def ready_report(self, include_finding: bool = False) -> str:
        report = main.workspace.create_report()
        report.app_id = "CI-BROWSER"
        report.engagement.app_name = "Browser QA"
        report.engagement.ci_number = "CI-BROWSER"
        report.engagement.segment = "JH"
        report.engagement.report_type = "annual_pentest"
        report.engagement.network = "Internal"
        report.engagement.report_date = date(2026, 1, 3)
        report.engagement.tested_environments = ["production"]
        report.engagement.test_windows = {"production": TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))}
        report.scope_targets = [ScopeTarget(target_id="tgt_browser", environment="production", channel="web", value="https://prod.example.test")]
        if include_finding:
            finding = Vulnerability(
                uid="v_browser",
                title="Browser finding",
                likelihood="low",
                impact="low",
                severity="low",
                status="open_new",
                scope={"mode": "custom", "target_ids": ["tgt_browser"]},
            )
            main.provision(finding)
            report.vulnerabilities = [finding]
            main.sync_evidence_image_slots(finding, report)
        main.workspace.save(report)
        return report.report_id

    def importable_docx(self) -> bytes:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report_folder = main.workspace.find_path(report_id).parent
        image = BytesIO()
        Image.new("RGB", (40, 20), "white").save(image, format="PNG")
        image_bytes = image.getvalue()
        (report_folder / "evidence").mkdir(exist_ok=True)
        (report_folder / "evidence" / "ev_import.png").write_bytes(image_bytes)
        report.evidence = {
            "ev_import": EvidenceItem(
                file="evidence/ev_import.png",
                original_name="import.png",
                width_px=40,
                height_px=20,
                sha256=hashlib.sha256(image_bytes).hexdigest(),
                uploaded_at=RealDateTime.now().astimezone(),
            ),
        }
        proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
        slot = next(fragment for fragment in proof.fragments if fragment.type == "image")
        slot.evidence_id = "ev_import"
        slot.caption = "Imported response"
        main.workspace.save(report)
        return render_report_docx(
            report,
            main_template_path(report, Path(__file__).resolve().parent.parent / "resources"),
            report_folder,
            allow_incomplete=True,
        )

    def test_setup_inputs_report_character_and_date_errors_before_save(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")

        # The browser must show exactly the server's wording, so each expected message is taken from
        # setup_input_issues rather than typed out a second time.
        field_cases = [
            ("Application Name", "app_name", "Bad/App", "Portal-2: (Web)"),
            ("CI Number", "ci_number", "CI_123", "CI-123"),
            ("BSN Number", "bsn_number", "BSN.123", "BSN-123"),
            ("Application Owner", "app_owner", "Owner 2", "Anne-Marie Owner"),
            ("Tester", "tester", "QA_Tester", "QA Tester"),
            ("Production time", "test_time", "08:00_17:00", "08:00-17:00"),
            ("User role 1", "user_role", "Admin_2", "Admin-2 / QA"),
            ("Username 1", "username", "bad/user", "DOMAIN\\qa user@example"),
            ("Limitations", "limitations", "No testing @ production", "No API - version 2. (Read only) & 'approved' / \"reviewed\"; see scope: prod only."),
        ]
        for label, field_name, invalid_value, valid_value in field_cases:
            with self.subTest(label=label):
                field = page.get_by_label(label, exact=True)
                field.fill(invalid_value)
                self.assertEqual(field.evaluate("input => input.validationMessage"), setup_issue(field_name, invalid_value))
                field.fill(valid_value)
                self.assertEqual(field.evaluate("input => input.validationMessage"), "")

            application_name = page.get_by_label("Application Name")
            application_name.fill("Bad/_App/")
            self.assertEqual(application_name.evaluate("input => input.validationMessage"), setup_issue("app_name", "Bad/_App/"))

        production_start = page.get_by_label("Production start date", exact=True)
        production_end = page.get_by_label("Production end date", exact=True)
        production_start.fill("2026-01-01")
        self.assertEqual(production_end.get_attribute("min"), "2026-01-01")
        production_end.fill("2026-01-01")
        self.assertEqual(production_start.get_attribute("max"), "2026-01-01")
        self.assertEqual(production_start.evaluate("input => input.validationMessage"), "")
        self.assertEqual(production_end.evaluate("input => input.validationMessage"), "")
        production_start.fill("2026-01-02")
        self.assertEqual(production_start.evaluate("input => input.validationMessage"), "Production start date is after its end date. Change one of them.")
        self.assertEqual(production_end.evaluate("input => input.validationMessage"), "Production start date is after its end date. Change one of them.")
        self.assertTrue(production_start.evaluate("input => input.validity.rangeOverflow"))
        production_start.fill("2026-01-01")
        self.assertEqual(production_start.evaluate("input => input.validationMessage"), "")
        self.assertEqual(production_end.evaluate("input => input.validationMessage"), "")

        page.get_by_label("Application Name").fill("Bad/App")
        page.get_by_role("button", name="Next: Findings").click()
        self.assertIn("/setup", page.url)
        self.assertRegex(page.locator("#setup-validation-note").inner_text(), r"^\d+ things to fix before Findings\.")

    def test_authoring_workflow_autosave_fragments_and_manager_grouping(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Segment").select_option("JH")
        page.get_by_label("Application Name").fill("Browser QA")
        page.get_by_label("Report Type").select_option("annual_pentest")
        page.get_by_label("CI Number").fill("CI-BROWSER")
        page.get_by_label("BSN Number").fill("BSN-BROWSER")
        page.get_by_label("Application Owner").fill("QA")
        self.choose_required_engagement_details()
        page.locator('input[aria-label="Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Production end date"]').fill("2026-01-02")
        page.locator('input[aria-label="Non-Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Non-Production end date"]').fill("2026-01-02")
        self.assertEqual(page.get_by_role("textbox", name="Production time", exact=True).input_value(), "Anytime")
        page.get_by_role("textbox", name="Non-Production time", exact=True).fill("7:00 EST")
        self.assertEqual(page.get_by_label("User role 1").input_value(), "N/A")
        self.assertEqual(page.get_by_label("Username 1").input_value(), "N/A")
        page.get_by_role("button", name="Add account").click()
        page.get_by_label("User role 2").fill("Administrator")
        page.get_by_label("Username 2").fill("qa-admin")
        page.get_by_label("Limitations").fill("No production write access")
        page.get_by_role("textbox", name="Web", exact=True).nth(0).fill("https://prod.example.test")
        page.get_by_role("textbox", name="Web", exact=True).nth(1).fill("https://test.example.test")
        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for()
        page.reload()
        self.assertEqual(page.get_by_label("Application Name").input_value(), "Browser QA")
        self.assertEqual(page.get_by_label("Segment").input_value(), "JH")
        self.assertEqual(page.get_by_label("Report Type").input_value(), "annual_pentest")
        self.assertEqual(page.get_by_role("textbox", name="Non-Production time", exact=True).input_value(), "7:00 EST")
        self.assertEqual(page.get_by_label("User role 2").input_value(), "Administrator")
        self.assertEqual(page.get_by_label("Username 2").input_value(), "qa-admin")
        self.assertEqual(page.get_by_label("Limitations").input_value(), "No production write access")

        page.get_by_role("button", name="Next: Findings").click()
        page.wait_for_url("**/reports/*/findings")
        page.get_by_role("button", name="Add finding").click()
        page.get_by_role("combobox", name="Finding Name").fill("Browser finding")
        page.get_by_role("combobox", name="Likelihood").select_option(label="Low")
        page.get_by_role("combobox", name="Impact").select_option(label="Low")
        page.get_by_role("combobox", name="Severity").select_option(label="Low")
        page.get_by_role("checkbox", name="Select https://prod.example.test").check()
        page.get_by_text("Next: Content", exact=False).click()
        description_toggle = page.get_by_role("button", name="Description 1 fragment")
        if description_toggle.get_attribute("aria-expanded") == "false":
            description_toggle.click()
        fragments = page.locator("#finding-editor .fragment")
        initial_fragment_count = fragments.count()
        page.get_by_role("combobox", name="Add fragment to Description").select_option(label="note")
        self.assertEqual(fragments.count(), initial_fragment_count + 1)

        page.goto(f"{self.base_url}/")
        # Groups are keyed on the application name now, not its CI number.
        page.get_by_role("searchbox", name="Apps").fill("Browser QA")
        group = page.locator(".app-group:not([hidden])")
        group.first.wait_for()
        self.assertEqual(group.count(), 1)
        self.assertTrue(group.evaluate("element => element.open"))
        self.assertEqual(group.locator(".app-group-name").first.text_content(), "Browser QA")

    def test_automatic_save_uses_configured_idle_delay(self) -> None:
        page = self.page
        page.add_init_script("window.VULNREPORT_AUTOSAVE_INTERVAL_MS = 500")
        page.goto(f"{self.base_url}/new")
        self.assertFalse(page.evaluate("() => { const event = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented; }"))
        page.get_by_label("Application Name").fill("Interval QA")
        save_button = page.locator("#save-button")
        self.assertEqual(save_button.get_attribute("data-save-state"), "unsaved")
        self.assertEqual(save_button.text_content(), "Unsaved changes")
        self.assertTrue(page.evaluate("() => { const event = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented; }"))
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        self.assertRegex(save_button.text_content() or "", r"^Saved \d{2}:\d{2}$")
        self.assertTrue((save_button.get_attribute("title") or "").startswith("Last saved "))
        self.assertFalse(page.evaluate("() => { const event = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(event); return event.defaultPrevented; }"))
        page.reload()
        self.assertEqual(page.get_by_label("Application Name").input_value(), "Interval QA")

    def test_undo_does_not_reload_or_lose_changes_when_recovery_write_fails(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        owner = page.get_by_label("Application Owner")
        owner.fill("Keep this edit")
        page.get_by_role("heading", name="Application").click()
        page.wait_for_function(
            "prefix => Object.keys(localStorage).some(key => key.startsWith(prefix))",
            arg=f"vulnreport-pending:{report_id}:",
        )
        page.evaluate(
            """() => {
                const original = Storage.prototype.setItem;
                Storage.prototype.setItem = function(key, value) {
                    if (key.startsWith('vulnreport-recovery:')) throw new DOMException('blocked', 'SecurityError');
                    return original.call(this, key, value);
                };
            }"""
        )
        self.assertEqual(
            page.evaluate(
                """() => {
                    try { sessionStorage.setItem('vulnreport-recovery:probe', 'x'); return 'allowed'; }
                    catch (error) { return error.name; }
                }"""
            ),
            "SecurityError",
        )

        page.get_by_role("button", name="Undo last change").click()

        page.get_by_role("heading", name="Browser recovery unavailable").wait_for()
        self.assertTrue(page.url.endswith(f"/reports/{report_id}/setup"))
        self.assertEqual(owner.input_value(), "Keep this edit")
        self.assertTrue(page.get_by_role("button", name="Undo last change").is_enabled())

    def test_server_normalization_reaches_the_live_browser_draft(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_role("button", name="Add finding").click()
        page.get_by_role("combobox", name="Finding Name").fill("Normalization QA")
        page.get_by_role("combobox", name="Likelihood").select_option(label="Low")
        page.get_by_role("combobox", name="Impact").select_option(label="Low")
        page.get_by_role("combobox", name="Severity").select_option(label="Low")
        page.get_by_role("checkbox", name="Select https://prod.example.test").check()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        page.get_by_role("combobox", name="Severity").select_option(label="Medium")
        prefix = f"vulnreport-pending:{report_id}:"
        page.wait_for_function(
            "prefix => Object.keys(localStorage).some(key => key.startsWith(prefix))",
            arg=prefix,
        )
        envelope = page.evaluate(
            "prefix => JSON.parse(localStorage.getItem(Object.keys(localStorage).find(key => key.startsWith(prefix))))",
            prefix,
        )
        contents = envelope["report"]["vulnerabilities"][0]["contents"]
        self.assertEqual(envelope["report"]["vulnerabilities"][0]["severity"], "medium")
        self.assertEqual([content["type"] for content in contents], ["description", "recommended_remediation", "proof_of_concept"])
        proof = next(content for content in contents if content["type"] == "proof_of_concept")
        images = [fragment for fragment in proof["fragments"] if fragment["type"] == "image"]
        self.assertEqual([image["environment"] for image in images], ["production"])

    def test_edit_during_delayed_save_is_not_overwritten(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.evaluate(
            """() => {
                const originalFetch = window.fetch.bind(window);
                let delayed = true;
                window.fetch = (input, init = {}) => {
                    if (delayed && init.method === "PUT") {
                        delayed = false;
                        return new Promise(resolve => {
                            window.releaseDelayedSave = () => resolve(originalFetch(input, init));
                        });
                    }
                    return originalFetch(input, init);
                };
            }"""
        )

        owner = page.get_by_label("Application Owner")
        owner.fill("First edit")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saving"]').wait_for()
        owner.fill("Latest edit")
        page.evaluate("window.releaseDelayedSave()")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        self.assertEqual(owner.input_value(), "Latest edit")
        self.assertEqual(main.workspace.load(report_id).engagement.app_owner, "Latest edit")

    def test_next_button_is_keyboard_accessible(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        next_button = page.get_by_role("button", name="Next: Findings")
        next_button.focus()
        next_button.press("Enter")
        page.wait_for_url(f"**/reports/{report_id}/findings")

    def test_network_access_starts_unchosen_blocks_next_and_persists_external(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.network = None
        main.workspace.save(report)
        expected_message = next(message for message in setup_issues(report) if "network access" in message.lower())
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        network = page.get_by_label("Network Access")

        self.assertEqual(network.locator("option").all_text_contents(), ["Select network access", "Internal", "External"])
        self.assertEqual(network.input_value(), "")
        page.get_by_role("button", name="Next: Findings").click()
        described_by = network.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(page.locator(f"#{described_by}").inner_text(), expected_message)
        self.assertTrue(network.evaluate("select => select.classList.contains('validation-error')"))

        network.select_option("External")
        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        page.reload()

        self.assertEqual(page.get_by_label("Network Access").input_value(), "External")

    def test_missing_test_environment_is_described_by_its_checkbox(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = []
        main.workspace.save(report)
        expected_message = next(message for message in setup_issues(report) if "environment" in message.lower())
        page = self.page

        page.goto(f"{self.base_url}/reports/{report_id}/setup?incomplete=setup")

        production = page.get_by_label("Production", exact=True)
        described_by = production.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(page.locator(f"#{described_by}").inner_text(), expected_message)
        self.assertEqual(production.get_attribute("aria-invalid"), "true")
        message = page.locator(f"#{described_by}")
        page.get_by_label("Non-Production", exact=True).check()
        expect(message).to_be_hidden()
        self.assertIsNone(production.get_attribute("aria-describedby"))
        self.assertIsNone(production.get_attribute("aria-invalid"))

    def test_mutually_exclusive_app_types_share_their_issue_message(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["mobile", "thick_client"]
        report.scope_targets = []
        main.workspace.save(report)
        expected_message = next(message for message in setup_issues(report) if "not both" in message.lower())
        page = self.page

        page.goto(f"{self.base_url}/reports/{report_id}/setup?incomplete=setup")

        mobile = page.get_by_label("Test Mobile", exact=True)
        thick_client = page.get_by_label("Test Thick Client", exact=True)
        described_by = mobile.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(thick_client.get_attribute("aria-describedby"), described_by)
        self.assertEqual(page.locator(f"#{described_by}").inner_text(), expected_message)
        self.assertEqual(mobile.get_attribute("aria-invalid"), "true")
        self.assertEqual(thick_client.get_attribute("aria-invalid"), "true")
        message = page.locator(f"#{described_by}")
        mobile.uncheck()
        expect(message).to_be_hidden()
        self.assertIsNone(mobile.get_attribute("aria-describedby"))
        self.assertIsNone(thick_client.get_attribute("aria-describedby"))

    def test_removing_a_tested_environment_clears_its_dates_in_one_undo_step(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 5), end_date=date(2026, 1, 6), test_time="08:00-17:00")
        report.scope_targets.append(ScopeTarget(target_id="tgt_test", environment="non_production", channel="web", value="https://test.example.test"))
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")

        page.get_by_label("Non-Production", exact=True).uncheck()
        page.get_by_role("button", name="Make the change anyway").click()
        page.locator('#save-button:not([data-save-state="saved"])').wait_for(timeout=5_000)
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        window = main.workspace.load(report_id).engagement.test_windows["non_production"]
        self.assertEqual((window.start_date, window.end_date, window.test_time), (None, None, "08:00-17:00"))

        with page.expect_navigation():
            page.locator("#undo-button").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        restored = main.workspace.load(report_id).engagement
        self.assertIn("non_production", restored.tested_environments)
        self.assertEqual((restored.test_windows["non_production"].start_date, restored.test_windows["non_production"].end_date), (date(2026, 1, 5), date(2026, 1, 6)))

    def test_an_over_length_setup_field_shows_the_server_message_and_holds_the_save(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["web", "mobile"]
        report.scope_targets = []
        main.workspace.save(report)
        report_data = report.model_dump(mode="json", by_alias=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        limits = json.loads(page.locator("#vocabulary").text_content())["scope_limits"]
        web_line = "x" * (limits["line"] + 1)
        draft = {**report_data, "scope_text": {"production": {"web": web_line}}}
        [refusal] = scope_text_refusals(draft)
        expected_message = format_rule_message(refusal, draft)
        web = page.get_by_role("textbox", name="Web", exact=True).first
        self.assertIsNone(web.get_attribute("maxlength"))
        web.fill(web_line)
        web.evaluate("element => element.blur()")
        described_by = web.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        expect(page.locator(f"#{described_by}")).to_have_text(expected_message)
        self.assertEqual(web.input_value(), web_line)
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#save-button")).to_have_attribute("data-save-state", "unsaved")
        self.assertEqual(main.workspace.load(report_id).saved_at, report.saved_at)

    def test_setup_character_limit_stops_typing_and_announces_the_limit(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        vocabulary = json.loads(page.locator("#vocabulary").text_content())
        maximum = vocabulary["character_rules"]["tester"]["max_length"]
        tester = page.get_by_label("Tester", exact=True)
        self.assertEqual(tester.get_attribute("maxlength"), str(maximum))

        tester.fill("T" * maximum)
        tester.press("x")

        self.assertEqual(tester.input_value(), "T" * maximum)
        described_by = tester.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        note = page.locator(f"#{described_by}")
        expect(note).to_have_text(f"Tester holds up to {maximum} characters.")
        self.assertEqual(note.get_attribute("role"), "status")
        self.assertEqual(note.get_attribute("aria-live"), "polite")
        self.assertIn("setup-character-limit-note", note.get_attribute("class"))
        self.assertEqual(note.evaluate("element => getComputedStyle(element).color"), page.evaluate("() => { const probe = document.createElement('span'); probe.style.color = 'var(--muted)'; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; }"))
        self.assertIsNone(tester.get_attribute("aria-invalid"))

        tester.press("Backspace")
        expect(note).to_be_hidden()
        self.assertIsNone(tester.get_attribute("aria-describedby"))
        tester.press("x")
        tester.press("x")
        expect(note).to_be_visible()
        tester.evaluate("element => element.blur()")
        expect(note).to_be_hidden()

    def test_generated_setup_fields_use_vocabulary_character_limits(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        vocabulary = json.loads(page.locator("#vocabulary").text_content())

        page.get_by_label("Test Mobile").check()
        page.get_by_label("Non-Production", exact=True).check()
        page.get_by_label("Non-Production name", exact=True).select_option("OTHERS")

        fields = [
            (page.get_by_label("User role 1", exact=True), vocabulary["character_rules"]["user_role"]["max_length"]),
            (page.get_by_label("Username 1", exact=True), vocabulary["character_rules"]["username"]["max_length"]),
            (page.get_by_label("Production time", exact=True), vocabulary["character_rules"]["test_time"]["max_length"]),
            (page.get_by_label("Mobile Description", exact=True).first, vocabulary["scope_limits"]["description"]),
        ]
        for field, maximum in fields:
            with self.subTest(label=field.get_attribute("aria-label")):
                self.assertEqual(field.get_attribute("maxlength"), str(maximum))

        component = page.get_by_label("Mobile Component", exact=True).first
        self.assertIsNone(component.get_attribute("maxlength"))

        custom_name = page.get_by_label("Non-Production name, typed", exact=True)
        self.assertEqual(custom_name.get_attribute("maxlength"), "40")
        custom_name.fill("N" * 40)
        custom_name.press("x")
        note_id = custom_name.get_attribute("aria-describedby")
        self.assertTrue(note_id)
        expect(page.locator(f"#{note_id}")).to_have_text("Non-Production name, typed holds up to 40 characters.")

    def test_setup_character_limit_cuts_a_paste_and_announces_the_cut(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        vocabulary = json.loads(page.locator("#vocabulary").text_content())
        maximum = vocabulary["character_rules"]["tester"]["max_length"]
        tester = page.get_by_label("Tester", exact=True)
        tester.fill("T" * (maximum - 2))

        tester.evaluate("""(element, pasted) => {
            const clipboard = new DataTransfer();
            clipboard.setData("text/plain", pasted);
            element.focus();
            element.setSelectionRange(element.value.length, element.value.length);
            element.dispatchEvent(new ClipboardEvent("paste", {bubbles:true, cancelable:true, clipboardData:clipboard}));
            document.execCommand("insertText", false, pasted);
        }""", "XYZ")

        self.assertEqual(tester.input_value(), "T" * (maximum - 2) + "XY")
        described_by = tester.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        note = page.locator(f"#{described_by}")
        expect(note).to_have_text(f"Tester holds up to {maximum} characters, so the paste was cut to fit.")
        self.assertIsNone(tester.get_attribute("aria-invalid"))

    def test_over_limit_draft_stays_invalid_while_shortening_without_limit_note(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        vocabulary = json.loads(page.locator("#vocabulary").text_content())
        maximum = vocabulary["character_rules"]["app_name"]["max_length"]
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        over_limit = "A" * (maximum + 2)
        report.engagement.app_name = over_limit
        main.workspace.save(report)
        self.assertEqual(main.workspace.load(report_id).engagement.app_name, over_limit)
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        embedded_name = page.locator("main[data-report]").evaluate("element => JSON.parse(element.dataset.report).engagement.app_name")
        self.assertEqual(embedded_name, over_limit)

        name = page.get_by_label("Application Name", exact=True)
        expect(name).to_have_value(over_limit)
        described_by = name.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message = page.locator(f"#{described_by}")
        expect(message).to_have_text(setup_issue("app_name", over_limit))
        self.assertEqual(name.get_attribute("aria-invalid"), "true")
        self.assertNotIn("setup-character-limit-note", message.get_attribute("class"))

        name.fill("A" * maximum)
        expect(name).to_have_value("A" * maximum)
        expect(message).to_be_hidden()
        self.assertIsNone(name.get_attribute("aria-invalid"))
        self.assertNotIn("setup-character-limit-note", message.get_attribute("class"))

    def test_held_autosave_shows_every_refusal_on_setup(self) -> None:
        report_id = self.ready_report()
        limitations_value = "x" * 5000
        report = main.workspace.load(report_id)
        report.engagement.limitations = limitations_value
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        name = page.get_by_label("Application Name", exact=True)
        limitations = page.get_by_label("Limitations", exact=True)
        name.fill("Bad/App")
        name.evaluate("element => element.blur()")

        page.wait_for_function("() => ['engagement.app_name', 'engagement.limitations'].every(path => document.querySelector(`[data-path=\"${path}\"]`)?.hasAttribute('aria-describedby'))")
        page.wait_for_function("document.querySelector('#save-button').textContent === 'Correct invalid Setup fields'")

        self.assertEqual(page.locator(f"#{name.get_attribute('aria-describedby')}").inner_text(), setup_issue("app_name", "Bad/App"))
        self.assertEqual(page.locator(f"#{limitations.get_attribute('aria-describedby')}").inner_text(), setup_issue("limitations", limitations_value))
        self.assertEqual(main.workspace.load(report_id).engagement.app_name, "Browser QA")
        self.assertEqual(main.workspace.load(report_id).engagement.limitations, limitations_value)
        self.assertEqual(page.evaluate("document.activeElement.dataset.path"), "engagement.app_name")

    def test_setup_refusal_is_described_below_its_field_and_clears_when_fixed(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        name = page.get_by_label("Application Name", exact=True)
        name.fill("Bad/App")
        self.assertIsNone(name.get_attribute("aria-describedby"))
        name.press("Tab")

        self.assertEqual(name.get_attribute("aria-invalid"), "true")
        described_by = name.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message = page.locator(f"#{described_by}")
        self.assertEqual(message.inner_text(), setup_issue("app_name", "Bad/App"))
        self.assertIsNone(message.evaluate("element => element.closest('label')"))
        self.assertEqual(page.get_by_role("textbox", name="Application Name", exact=True).count(), 1)

        name.fill("Bad/Portal")
        expect(message).to_have_text(setup_issue("app_name", "Bad/Portal"))
        name.fill("Portal")
        self.assertEqual(name.get_attribute("aria-invalid"), None)
        self.assertEqual(name.get_attribute("aria-describedby"), None)

    def test_date_pair_message_is_shared_below_the_row_and_clears_when_fixed(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        time_value = "x" * 1000
        for environment in ("production", "non_production"):
            report.engagement.test_windows.setdefault(environment, TestWindow()).test_time = time_value
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        start = page.get_by_label("Production start date", exact=True)
        end = page.get_by_label("Production end date", exact=True)
        report = main.workspace.load(report_id)
        report.engagement.test_windows["production"].start_date = date(2026, 1, 3)
        order_message = next(message for message in setup_input_issues(report.engagement) if "start date is after" in message)

        start.fill("2026-01-03")
        start.evaluate("input => input.blur()")

        start_described_by = start.get_attribute("aria-describedby")
        self.assertTrue(start_described_by)
        self.assertEqual(end.get_attribute("aria-describedby"), start_described_by)
        message = page.locator(f"#{start_described_by}")
        expect(message).to_have_text(order_message)
        self.assertEqual(start.get_attribute("aria-invalid"), "true")
        self.assertEqual(end.get_attribute("aria-invalid"), "true")
        self.assertIsNone(message.evaluate("element => element.closest('label')"))
        self.assertTrue(message.evaluate("element => element.previousElementSibling?.classList.contains('date-pair')"))

        end.fill("2026-01-04")
        expect(message).to_be_hidden()
        self.assertIsNone(start.get_attribute("aria-describedby"))
        self.assertIsNone(end.get_attribute("aria-describedby"))
        self.assertIsNone(start.get_attribute("aria-invalid"))
        self.assertIsNone(end.get_attribute("aria-invalid"))

        for environment, label in (("production", "Production"), ("non_production", "Non-Production")):
            time_input = page.get_by_label(f"{label} time", exact=True)
            time_described_by = time_input.get_attribute("aria-describedby")
            self.assertTrue(time_described_by)
            time_line = page.locator(f"#{time_described_by}")
            expect(time_line).to_have_text(setup_issue("test_time", time_value, environment))
            self.assertIsNone(time_line.evaluate("element => element.closest('label')"))
            self.assertTrue(time_line.evaluate("element => element.parentElement.classList.contains('setup-field-wrap')"))

            character_value = "Bad@Time"
            time_input.fill(character_value)
            expect(time_line).to_have_text(setup_issue("test_time", character_value, environment))
            time_input.fill("Anytime")
            expect(time_line).to_be_hidden()
            self.assertIsNone(time_input.get_attribute("aria-describedby"))
            self.assertIsNone(time_input.get_attribute("aria-invalid"))

        report.engagement.test_windows["production"].start_date = None
        missing_date_message = next(message for message in setup_issues(report) if "Production start date" in message)
        start.fill("")
        self.assertIsNone(start.get_attribute("aria-describedby"))
        page.get_by_role("button", name="Next: Findings").click()

        start_described_by = start.get_attribute("aria-describedby")
        self.assertTrue(start_described_by)
        self.assertEqual(end.get_attribute("aria-describedby"), start_described_by)
        expect(page.locator(f"#{start_described_by}")).to_have_text(missing_date_message)
        self.assertEqual(start.get_attribute("aria-invalid"), "true")
        self.assertEqual(end.get_attribute("aria-invalid"), "true")

        start.fill("2026-01-03")
        expect(page.locator(f"#{start_described_by}")).to_be_hidden()
        self.assertIsNone(start.get_attribute("aria-describedby"))
        self.assertIsNone(end.get_attribute("aria-describedby"))
        self.assertIsNone(start.get_attribute("aria-invalid"))
        self.assertIsNone(end.get_attribute("aria-invalid"))

    def test_test_account_messages_span_the_row_and_clear_when_fixed(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.locator("#add-test-account").click()
        role = page.get_by_label("User role 2", exact=True)
        username = page.get_by_label("Username 2", exact=True)
        role.fill("Service")
        report = main.workspace.load(report_id)
        report.engagement.test_accounts.append(TestAccount(user_role="Service", username=""))
        incomplete_message = next(message for message in setup_issues(report) if "test account 2" in message.lower())

        page.get_by_role("button", name="Next: Findings").click()

        described_by = role.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(username.get_attribute("aria-describedby"), described_by)
        message = page.locator(f"#{described_by}")
        expect(message).to_have_text(incomplete_message)
        self.assertEqual(message.evaluate("element => element.closest('td').colSpan"), 3)
        self.assertIsNone(message.evaluate("element => element.closest('label')"))
        self.assertEqual(role.get_attribute("aria-invalid"), "true")
        self.assertEqual(username.get_attribute("aria-invalid"), "true")
        self.assertEqual(role.get_attribute("aria-label"), "User role 2")
        self.assertEqual(username.get_attribute("aria-label"), "Username 2")

        username.fill("service")
        expect(message).to_be_hidden()
        self.assertIsNone(role.get_attribute("aria-describedby"))
        self.assertIsNone(username.get_attribute("aria-describedby"))
        self.assertIsNone(role.get_attribute("aria-invalid"))
        self.assertIsNone(username.get_attribute("aria-invalid"))

        report.engagement.test_accounts[1].username = "service "
        trailing_space_message = next(message for message in setup_input_issues(report.engagement) if "Username 2" in message)
        username.fill("service ")
        self.assertIsNone(username.get_attribute("aria-describedby"))
        username.evaluate("input => input.blur()")
        expect(message).to_have_text(trailing_space_message)
        self.assertEqual(role.get_attribute("aria-describedby"), described_by)
        self.assertEqual(username.get_attribute("aria-describedby"), described_by)
        self.assertEqual(role.get_attribute("aria-invalid"), "true")
        self.assertEqual(username.get_attribute("aria-invalid"), "true")

        report.engagement.test_accounts[1].username = "bad/name"
        invalid_character_message = next(message for message in setup_input_issues(report.engagement) if "Username 2" in message)
        username.fill("bad/name")
        expect(message).to_have_text(invalid_character_message)
        username.fill("service")
        expect(message).to_be_hidden()
        self.assertIsNone(role.get_attribute("aria-describedby"))
        self.assertIsNone(username.get_attribute("aria-describedby"))

        page.locator("#add-test-account").click()
        role_three = page.get_by_label("User role 3", exact=True)
        username_three = page.get_by_label("Username 3", exact=True)
        role_three.fill("N/A")
        username_three.fill("N/A")
        report.engagement.test_accounts.append(TestAccount(user_role="N/A", username="N/A"))
        repeated_message = next(message for message in setup_issues(report) if "test account 3" in message.lower())

        page.get_by_role("button", name="Next: Findings").click()

        repeated_described_by = role_three.get_attribute("aria-describedby")
        self.assertTrue(repeated_described_by)
        self.assertEqual(username_three.get_attribute("aria-describedby"), repeated_described_by)
        repeated_line = page.locator(f"#{repeated_described_by}")
        expect(repeated_line).to_have_text(repeated_message)
        self.assertEqual(repeated_line.evaluate("element => element.closest('td').colSpan"), 3)
        self.assertEqual(role_three.get_attribute("aria-invalid"), "true")
        self.assertEqual(username_three.get_attribute("aria-invalid"), "true")
        username_three.fill("unique")
        expect(repeated_line).to_be_hidden()
        self.assertIsNone(role_three.get_attribute("aria-describedby"))
        self.assertIsNone(username_three.get_attribute("aria-describedby"))

    def test_stored_invalid_setup_value_shows_its_refusal_immediately(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.app_name = "Bad/App"
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        name = page.get_by_label("Application Name", exact=True)

        self.assertEqual(name.input_value(), "Bad/App")
        self.assertEqual(name.get_attribute("aria-invalid"), "true")
        described_by = name.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(page.locator(f"#{described_by}").inner_text(), setup_issue("app_name", "Bad/App"))

    def test_setup_missing_segment_is_described_after_next(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        report_id = page.url.split("/reports/")[1].split("/")[0]
        expected_messages = setup_issues(main.workspace.load(report_id))
        segment = page.get_by_label("Segment")
        accessible_name = segment.aria_snapshot().splitlines()[0].split(" [", 1)[0].rstrip(":")

        page.get_by_role("button", name="Next: Findings").click()

        self.assertIn("/setup", page.url)
        self.assertEqual(segment.aria_snapshot().splitlines()[0].split(" [", 1)[0].rstrip(":"), accessible_name)
        described_by = segment.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message = page.locator(f"#{described_by}").inner_text()
        self.assertIn(message, expected_messages)
        self.assertIn("segment", message.lower())
        self.assertEqual(segment.get_attribute("aria-invalid"), "true")
        self.assertEqual(page.evaluate("document.activeElement.dataset.path"), "engagement.segment")
        notice = page.locator("#setup-validation-note")
        count = len(expected_messages)
        self.assertGreater(count, 1)
        self.assertEqual(notice.inner_text(), f"{count} things to fix before Findings. Each one is marked above, and the cursor is on the first.")

        segment.select_option("JH")

        self.assertIsNone(segment.get_attribute("aria-describedby"))
        self.assertIsNone(segment.get_attribute("aria-invalid"))
        self.assertNotIn(message, notice.inner_text())
        self.assertEqual(notice.inner_text(), f"{count - 1} things to fix before Findings. Each one is marked above, and the cursor is on the first.")

    def test_setup_page_gate_shows_one_count_and_the_missing_field_message(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tester = "Browser QA"
        report.engagement.segment = None
        main.workspace.save(report)
        expected_messages = setup_issues(report)
        self.assertEqual(len(expected_messages), 1)
        page = self.page

        page.goto(f"{self.base_url}/reports/{report_id}/setup?incomplete=setup")

        segment = page.get_by_label("Segment")
        described_by = segment.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(page.locator(f"#{described_by}").inner_text(), expected_messages[0])
        self.assertEqual(segment.get_attribute("aria-invalid"), "true")
        self.assertEqual(page.locator("#setup-validation-note").inner_text(), "1 thing to fix before Findings. It is marked above, and the cursor is on it.")

    def test_setup_next_shows_refusals_and_missing_details_together(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        report_id = page.url.split("/reports/")[1].split("/")[0]
        expected_count = len(setup_issues(main.workspace.load(report_id)))
        name = page.get_by_label("Application Name", exact=True)
        segment = page.get_by_label("Segment")
        name.fill("Bad/App")

        page.get_by_role("button", name="Next: Findings").click()

        name_message = page.locator(f"#{name.get_attribute('aria-describedby')}")
        segment_message = page.locator(f"#{segment.get_attribute('aria-describedby')}")
        self.assertEqual(name_message.inner_text(), setup_issue("app_name", "Bad/App"))
        self.assertIn(segment_message.inner_text(), setup_issues(main.workspace.load(report_id)))
        self.assertEqual(page.locator("#setup-validation-note").inner_text(), f"{expected_count} things to fix before Findings. Each one is marked above, and the cursor is on the first.")
        self.assertEqual(page.evaluate("document.activeElement.dataset.path"), "engagement.segment")

    def test_typed_non_production_name_shows_and_clears_its_refusal(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        environment = page.get_by_label("Non-Production", exact=True)
        if not environment.is_checked():
            environment.check()
        page.get_by_label("Non-Production name", exact=True).select_option("OTHERS")
        name = page.get_by_label("Non-Production name, typed", exact=True)
        name.fill("QA\\Team")
        name.press("Tab")

        described_by = name.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message = page.locator(f"#{described_by}")
        self.assertEqual(message.inner_text(), setup_issue("non_production_label", "QA\\Team"))
        self.assertIsNone(message.evaluate("element => element.closest('label')"))

        name.fill("QA Team")

        self.assertIsNone(name.get_attribute("aria-invalid"))
        self.assertIsNone(name.get_attribute("aria-describedby"))

    def test_web_scope_box_lists_refused_lines_and_scope_issues(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        box = page.get_by_role("textbox", name="Web", exact=True).first
        accessible_boxes = page.get_by_role("textbox", name="Web", exact=True)
        accessible_box_count = accessible_boxes.count()
        scope_text = f"{'x' * 3000}\u0007\nhttps://invalid.example.test\u0008"
        draft = main.workspace.load(report_id).model_dump(mode="json")
        draft["scope_text"] = {"production": {"web": scope_text}}
        refusals = scope_text_refusals(draft)
        expected_lines = [
            f"Line {line} " + " ".join(
                format_rule_message(result, draft).removeprefix(f"Line {line} ")
                for result in refusals if result.get("line") == line - 1
            )
            for line in (1, 2)
        ]

        box.focus()
        box.evaluate("(element, value) => { element.value = value; element.dispatchEvent(new Event('input', {bubbles:true})); }", scope_text)
        self.assertIsNone(box.get_attribute("aria-describedby"))
        box.evaluate("element => element.blur()")

        described_by = box.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message_list = page.locator(f"#{described_by}")
        expect(message_list).to_be_visible()
        self.assertEqual(message_list.evaluate("element => element.tagName"), "UL")
        self.assertEqual(message_list.locator(":scope > li").all_text_contents(), expected_lines)
        self.assertTrue(all(text.startswith(f"Line {line}") for line, text in enumerate(expected_lines, 1)))
        self.assertEqual(box.get_attribute("aria-invalid"), "true")
        self.assertIsNone(message_list.evaluate("element => element.closest('label')"))
        self.assertEqual(accessible_boxes.count(), accessible_box_count)

        page.get_by_role("button", name="Next: Findings").click()
        self.assertTrue(box.evaluate("element => document.activeElement === element"))
        expect(page.locator("#setup-validation-note")).to_have_text(
            "2 things to fix before Findings. Each one is marked above, and the cursor is on the first."
        )

        box.fill("https://first.example.test\nhttps://second.example.test")
        expect(message_list).to_be_hidden()
        self.assertIsNone(box.get_attribute("aria-describedby"))
        self.assertIsNone(box.get_attribute("aria-invalid"))

        box.fill("")
        page.get_by_role("button", name="Next: Findings").click()
        issue = format_rule_message({"code": "missing_scope_target", "environment": "production"})
        expect(message_list).to_be_visible()
        expect(message_list).to_have_text(issue)
        expect(page.locator("#setup-validation-note")).to_have_text(
            "1 thing to fix before Findings. It is marked above, and the cursor is on it."
        )
        self.assertEqual(box.get_attribute("aria-invalid"), "true")
        box.fill("https://fixed.example.test")
        expect(message_list).to_be_hidden()
        self.assertIsNone(box.get_attribute("aria-describedby"))
        self.assertIsNone(box.get_attribute("aria-invalid"))

        stored_id = self.ready_report()
        stored = main.workspace.load(stored_id)
        stored.scope_targets[0].value = "https://stored.example.test\u0007"
        main.workspace.save(stored)
        page.goto(f"{self.base_url}/reports/{stored_id}/setup")
        stored_box = page.get_by_role("textbox", name="Web", exact=True).first
        stored_described_by = stored_box.get_attribute("aria-describedby")
        self.assertTrue(stored_described_by)
        stored_message = page.locator(f"#{stored_described_by}")
        stored_draft = main.workspace.load(stored_id).model_dump(mode="json")
        stored_text = "https://stored.example.test\u0007"
        stored_draft["scope_text"] = {"production": {"web": stored_text}}
        [stored_refusal] = scope_text_refusals(stored_draft)
        expect(stored_message).to_have_text(format_rule_message(stored_refusal, stored_draft))

        gate_id = self.ready_report()
        gated = main.workspace.load(gate_id)
        gated.scope_targets = []
        main.workspace.save(gated)
        page.goto(f"{self.base_url}/reports/{gate_id}/setup?incomplete=setup")
        gate_box = page.get_by_role("textbox", name="Web", exact=True).first
        gate_described_by = gate_box.get_attribute("aria-describedby")
        self.assertTrue(gate_described_by)
        gate_message = page.locator(f"#{gate_described_by}")
        expect(gate_message).to_have_text(issue)
        self.assertEqual(gate_box.get_attribute("aria-invalid"), "true")
        expect(page.locator("#setup-validation-note")).to_have_text(
            "1 thing to fix before Findings. It is marked above, and the cursor is on it."
        )

    def test_web_lines_and_component_names_keep_their_scope_length_refusals(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        vocabulary = json.loads(page.locator("#vocabulary").text_content())
        limits = vocabulary["scope_limits"]
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["web", "mobile"]
        report.scope_targets = []
        main.workspace.save(report)
        report_data = report.model_dump(mode="json", by_alias=True)
        page.goto(f"{self.base_url}/reports/{report_id}/setup")

        web_line = "x" * (limits["line"] + 1)
        web_data = {**report_data, "scope_text": {"production": {"web": web_line}}}
        [web_refusal] = scope_text_refusals(web_data)
        web_message = format_rule_message(web_refusal, web_data)
        web_box = page.get_by_role("textbox", name="Web", exact=True).first
        self.assertIsNone(web_box.get_attribute("maxlength"))
        web_box.fill(web_line)
        web_box.evaluate("element => element.blur()")
        web_message_id = web_box.get_attribute("aria-describedby")
        self.assertTrue(web_message_id)
        expect(page.locator(f"#{web_message_id}")).to_have_text(web_message)

        component_name = "C" * (limits["component"] + 1)
        component_data = {
            **report_data,
            "scope_text": {"production": {"mobile": {"component": component_name, "description": ""}}},
        }
        [component_refusal] = [result for result in scope_text_refusals(component_data) if result.get("box") == "component"]
        component_message = format_rule_message(component_refusal, component_data).removeprefix("In the Production Mobile scope, ")
        component_box = page.get_by_role("textbox", name="Mobile Component", exact=True).first
        self.assertIsNone(component_box.get_attribute("maxlength"))
        component_box.fill(component_name)
        component_box.evaluate("element => element.blur()")
        component_message_id = component_box.get_attribute("aria-describedby")
        self.assertTrue(component_message_id)
        expect(page.locator(f"#{component_message_id}")).to_have_text(component_message)

    def test_setup_next_does_not_open_the_native_validity_bubble(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Application Name", exact=True).fill("Bad/App")
        page.evaluate("() => { window.reportValidityCalls = 0; HTMLElement.prototype.reportValidity = function() { window.reportValidityCalls += 1; return false; }; }")

        page.get_by_role("button", name="Next: Findings").click()

        self.assertEqual(page.evaluate("window.reportValidityCalls"), 0)

    def test_segment_and_report_type_are_required(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        report_id = page.url.split("/reports/")[1].split("/")[0]
        expected_messages = setup_issues(main.workspace.load(report_id))
        self.assertEqual(page.get_by_label("Segment").locator("option").all_text_contents(), ["Select segment", "JH", "GWAM", "Asia", "GDT", "GFT"])
        self.assertEqual(page.get_by_label("Report Type").locator("option").all_text_contents(), ["Select report type", "Annual Pentest", "Retest", "Deployment Pentest", "New Test"])
        page.get_by_label("Application Name").fill("Required Fields")
        page.get_by_label("CI Number").fill("CI-REQUIRED")
        page.locator('input[aria-label$="start date"]').evaluate_all("inputs => inputs.forEach(input => { input.value = '2026-01-01'; input.dispatchEvent(new Event('input', {bubbles:true})); })")
        page.locator('input[aria-label$="end date"]').evaluate_all("inputs => inputs.forEach(input => { input.value = '2026-01-02'; input.dispatchEvent(new Event('input', {bubbles:true})); })")
        page.get_by_role("textbox", name="Web", exact=True).nth(0).fill("https://prod.example.test")
        page.get_by_role("textbox", name="Web", exact=True).nth(1).fill("https://test.example.test")
        page.get_by_role("button", name="Next: Findings").click()
        self.assertIn("/setup", page.url)
        for label, field in (("Segment", "segment"), ("Report Type", "report type")):
            control = page.get_by_label(label)
            described_by = control.get_attribute("aria-describedby")
            self.assertTrue(described_by)
            message = page.locator(f"#{described_by}").inner_text()
            self.assertIn(message, expected_messages)
            self.assertIn(field, message.lower())

        page.get_by_label("Segment").select_option("GWAM")
        page.get_by_label("Report Type").select_option("new_test")
        self.choose_required_engagement_details()
        page.get_by_role("button", name="Next: Findings").click()
        page.wait_for_url("**/findings")

    def test_pages_take_their_lists_from_the_served_vocabulary(self) -> None:
        """No page keeps its own copy of a closed list, so a value or label that only the server adds
        reaches the template's options and the script's selects alike."""
        vocabulary = deepcopy(main.templates.env.globals["vocabulary"])
        vocabulary["segments"].append("QA")
        vocabulary["statuses"] = [[status, f"{label} (served)"] for status, label in vocabulary["statuses"]]
        report_id = self.ready_report(include_finding=True)
        page = self.page
        with patch.dict(main.templates.env.globals, {"vocabulary": vocabulary}):
            page.goto(f"{self.base_url}/reports/{report_id}/setup")
            self.assertEqual(page.get_by_label("Segment").locator("option").all_text_contents()[-1], "QA")
            page.goto(f"{self.base_url}/reports/{report_id}/findings")
            self.assertEqual(
                page.get_by_label("Status", exact=True).locator("option").all_text_contents(),
                [label for _, label in vocabulary["statuses"]],
            )

    def test_mobile_scope_allows_any_printable_name_and_refuses_what_word_cannot_store(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Test Mobile").check()
        page.get_by_label("Test Web").uncheck()
        production = page.locator("#scope-grid .scope-panel.production")
        # A "#" row is a note to the tester, and is held to no rule at all.
        note = production.get_by_role("textbox", name="Mobile Component", exact=True).first
        note.evaluate("input => { input.value = '# ignored \\u0007 []'; input.dispatchEvent(new Event('input', {bubbles:true})); }")
        production.get_by_role("button", name="Add component").click()
        mobile = production.get_by_role("textbox", name="Mobile Component", exact=True).nth(1)

        mobile.fill("Client's \"Mobile\" App! iOS/Android_v2.1 @ QA+&")
        self.assertEqual(mobile.evaluate("input => input.validationMessage"), "")
        self.assertEqual(note.evaluate("input => input.validationMessage"), "")

        mobile.evaluate("input => { input.value = 'Mobile\\u0007App'; input.dispatchEvent(new Event('input', {bubbles:true})); }")
        self.assertEqual(
            mobile.evaluate("input => input.validationMessage"),
            'Line 2 has a hidden character after "Mobile". Delete it.',
        )
        self.assertEqual(mobile.get_attribute("aria-invalid"), "true")

    def test_an_ignored_component_row_does_not_validate_its_description(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["mobile"]
        report.scope_targets = []
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        component = page.get_by_role("textbox", name="Mobile Component", exact=True).first
        description = page.get_by_role("textbox", name="Mobile Description", exact=True).first
        component.fill("# ignored row!")
        description.fill("ignored description!")

        self.assertEqual(component.evaluate("input => input.validationMessage"), "")
        self.assertEqual(description.evaluate("input => input.validationMessage"), "")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).scope_targets, [])

    def test_a_cached_draft_written_before_the_two_box_scope_still_accepts_typing(self) -> None:
        """A tab open across the deploy restores scope_text holding a bare string. This script is not
        in strict mode, so writing .component onto that string would no-op and swallow every
        keystroke -- no error, and the stale value saved instead."""
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["tested_channels"] = ["mobile"]
        report["scope_text"] = {"production": {"mobile": "Stale wallet app"}, "non_production": {"mobile": ""}}
        page = self.page
        self.plant_recovery_draft(report, "setup", "orphan")
        page.get_by_role("button", name="Restore", exact=True).click()

        mobile = page.get_by_role("textbox", name="Mobile Component", exact=True).first
        self.assertEqual(mobile.input_value(), "Stale wallet app", "the cached string must survive into the new shape")
        mobile.fill("Wallet app")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        stored = main.workspace.load(report_id)
        self.assertEqual(
            [(target.channel, target.value) for target in stored.scope_targets],
            [("mobile", "Wallet app")],
            "the keystroke was written onto a string primitive and silently discarded",
        )

    def test_a_recovered_non_string_component_pair_is_normalized_before_save(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["tested_channels"] = ["mobile"]
        report["engagement"]["tested_environments"] = ["production", "non_production"]
        report["engagement"]["test_windows"]["non_production"] = {"start_date": "2026-01-03", "end_date": "2026-01-04", "test_time": "Anytime"}
        report["scope_text"] = {
            "production": {"mobile": {"component": "Wallet app", "description": "Production build"}},
            "non_production": {"mobile": {"component": None, "description": ["stale cached value"]}},
        }
        requests = []
        page = self.page
        page.on("request", lambda request: requests.append(json.loads(request.post_data)) if request.method == "PUT" and request.post_data else None)
        self.plant_recovery_draft(report, "setup", "nullable")
        page.get_by_role("button", name="Restore", exact=True).click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        self.assertEqual(requests[-1]["scope_text"]["non_production"]["mobile"], {"component": "", "description": ""})

    def test_a_recovered_non_object_scope_environment_accepts_valid_component_rows(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["tested_channels"] = ["mobile"]
        report["scope_targets"] = []
        report["scope_text"] = {"production": [], "non_production": "stale"}

        page = self.page
        self.plant_recovery_draft(report, "setup", "environment-shape")
        page.get_by_role("button", name="Restore", exact=True).click()
        production = page.locator("#scope-grid .scope-panel.production")
        production.get_by_role("textbox", name="Mobile Component", exact=True).fill("Wallet app")
        production.get_by_role("textbox", name="Mobile Description", exact=True).fill("Production build")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        saved = main.workspace.load(report_id)
        self.assertEqual([(target.value, target.description) for target in saved.scope_targets], [("Wallet app", "Production build")])

    def test_a_recovered_non_object_test_window_accepts_valid_dates(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["tested_channels"] = ["mobile"]
        report["engagement"]["test_windows"]["production"] = []
        report["scope_targets"] = []
        report["scope_text"] = {"production": {"mobile": {"component": "Wallet app", "description": "Production build"}}}

        page = self.page
        self.plant_recovery_draft(report, "setup", "window-shape")
        page.get_by_role("button", name="Restore", exact=True).click()
        page.get_by_label("Production start date", exact=True).fill("2026-02-01")
        page.get_by_label("Production end date", exact=True).fill("2026-02-02")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.test_windows["production"].start_date, date(2026, 2, 1))
        self.assertEqual(saved.engagement.test_windows["production"].end_date, date(2026, 2, 2))

    def test_a_recovered_non_array_account_list_does_not_break_setup(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["test_accounts"] = {}

        page = self.page
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        self.plant_recovery_draft(report, "setup", "account-shape")
        self.restore_recovery_draft()

        self.assertEqual(errors, [])
        self.assertEqual(page.get_by_label("User role 1").input_value(), "N/A")
        page.get_by_label("Application Owner").fill("Recovered account list")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).engagement.app_owner, "Recovered account list")

    def test_recovered_scalar_coverage_values_render_component_scope(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["tested_environments"] = "production"
        report["engagement"]["tested_channels"] = "mobile"
        report["scope_targets"] = []
        report["scope_text"] = {"production": {"mobile": {"component": "Wallet app", "description": "Production build"}}}

        page = self.page
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        self.plant_recovery_draft(report, "setup", "coverage-shape")
        self.restore_recovery_draft()

        self.assertEqual(errors, [])
        self.assertTrue(page.get_by_label("Test Mobile").is_checked())
        self.assertEqual(page.get_by_role("textbox", name="Mobile Component", exact=True).input_value(), "Wallet app")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.tested_environments, ["production"])
        self.assertEqual(saved.engagement.tested_channels, ["mobile"])

    def test_recovered_non_array_scope_targets_fall_back_to_the_server_targets(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["app_owner"] = "Recovered owner"
        report["scope_targets"] = {}

        page = self.page
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        self.plant_recovery_draft(report, "setup", "target-shape")
        self.restore_recovery_draft()

        self.assertEqual(errors, [])
        self.assertEqual(page.get_by_role("textbox", name="Web", exact=True).input_value(), "https://prod.example.test")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.app_owner, "Recovered owner")
        self.assertEqual([target.value for target in saved.scope_targets], ["https://prod.example.test"])

    def test_recovered_non_array_findings_fall_back_to_the_server_findings(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["app_owner"] = "Recovered owner"
        report["vulnerabilities"] = {}

        page = self.page
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        self.plant_recovery_draft(report, "findings", "finding-shape")
        self.restore_recovery_draft()

        self.assertEqual(errors, [])
        self.assertEqual(page.locator("#findings > tr:not(.finding-location-row)").count(), 1)
        self.assertEqual(page.get_by_role("button", name="Edit finding name").text_content(), "Browser finding")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.app_owner, "Recovered owner")
        self.assertEqual([finding.title for finding in saved.vulnerabilities], ["Browser finding"])

    def test_recovery_restore_preserves_an_empty_supporting_tile(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        main.workspace.save(report)

        recovered = main.workspace.load(report_id)
        proof = next(content for content in recovered.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting = ImageFragment(
            frag_id="f_recovered_supporting",
            type="image",
            environment="non_production",
        )
        proof.fragments.append(supporting)
        recovered_payload = recovered.model_dump(mode="json", by_alias=True)

        page = self.page
        self.plant_recovery_draft(recovered_payload, "edit", "supporting-tile")
        self.restore_recovery_draft()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        saved_proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        saved_supporting = next(fragment for fragment in saved_proof.fragments if fragment.frag_id == supporting.frag_id)
        self.assertEqual((saved_supporting.environment, saved_supporting.evidence_id, saved_supporting.caption), (
            "non_production", None, "",
        ))
        page.reload()
        page.wait_for_selector(f'.evidence-tile[data-fragment-id="{supporting.frag_id}"]')
        tile = page.locator(f'.evidence-tile[data-fragment-id="{supporting.frag_id}"]')
        self.assertEqual(tile.locator(".evidence-environment").input_value(), "non_production")
        self.assertEqual(page.locator(".review-row").filter(has_text="Non-Production supporting evidence").count(), 0)

    def test_a_second_component_row_lands_as_its_own_target(self) -> None:
        """The two boxes are paired by line index, so a row is that pairing made visible. A second row
        has to reach the draft as its own target, and removing a row has to take that target with it."""
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Test Thick Client").check()
        page.get_by_label("Test Web").uncheck()
        page.get_by_label("Non-Production", exact=True).uncheck()
        page.get_by_label("Segment").select_option("JH")
        page.get_by_label("Application Name").fill("Row Scope")
        page.get_by_label("Report Type").select_option("annual_pentest")
        page.get_by_label("Tester").fill("QA Tester")
        self.choose_required_engagement_details()
        page.locator('input[aria-label="Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Production end date"]').fill("2026-01-02")

        production = page.locator("#scope-grid .scope-panel.production")
        production.get_by_role("textbox", name="Thick Client Component", exact=True).first.fill("Acme.exe")
        production.get_by_role("textbox", name="Thick Client Description", exact=True).first.fill("Main desktop client")
        production.get_by_role("button", name="Add component").click()
        production.get_by_role("textbox", name="Thick Client Component", exact=True).nth(1).fill("AcmeUpdater.exe")
        production.get_by_role("textbox", name="Thick Client Description", exact=True).nth(1).fill("Background updater")
        page.locator("#next").click()
        page.wait_for_url("**/findings")

        report_id = page.url.split("/reports/")[1].split("/")[0]
        self.assertEqual(
            [(target.value, target.description) for target in main.workspace.load(report_id).scope_targets],
            [("Acme.exe", "Main desktop client"), ("AcmeUpdater.exe", "Background updater")],
        )

        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.locator("#scope-grid .scope-panel.production tbody tr").first.wait_for()
        page.get_by_role("button", name="Remove Thick Client component 1").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=8_000)
        self.assertEqual(
            [(target.value, target.description) for target in main.workspace.load(report_id).scope_targets],
            [("AcmeUpdater.exe", "Background updater")],
            "removing a row renumbered the descriptions instead of dropping the pair",
        )

    def test_duplicate_component_names_are_rejected_before_save(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["mobile"]
        report.scope_targets = []
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        production = page.locator("#scope-grid .scope-panel.production")
        production.get_by_role("textbox", name="Mobile Component", exact=True).first.fill("Wallet app")
        production.get_by_role("textbox", name="Mobile Description", exact=True).first.fill("Android")
        production.get_by_role("button", name="Add component").click()
        duplicate = production.get_by_role("textbox", name="Mobile Component", exact=True).nth(1)
        duplicate.fill("  Wallet app  ")
        production.get_by_role("textbox", name="Mobile Description", exact=True).nth(1).fill("iOS")

        self.assertEqual(
            duplicate.evaluate("input => input.validationMessage"),
            "Component 2 is the same as component 1. Remove one of them.",
        )
        page.locator("#save-button").click()
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "unsaved")
        self.assertEqual(page.locator("#app-diagnostics").count(), 0)

    def test_duplicate_component_message_marks_only_the_later_row(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["mobile"]
        report.scope_targets = []
        main.workspace.save(report)
        report_data = report.model_dump(mode="json", by_alias=True)
        report_data["scope_text"] = {
            "production": {"mobile": {"component": "Wallet app\nWallet app", "description": "Android\niOS"}}
        }
        [duplicate_result] = [result for result in scope_text_refusals(report_data) if result["code"] == "duplicate_component"]
        expected_message = setup_refusal_message(duplicate_result, report_data).removeprefix("In the Production Mobile scope, ")

        page = self.page
        page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 10000")
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        production = page.locator("#scope-grid .scope-panel.production")
        first = production.get_by_role("textbox", name="Mobile Component", exact=True).first
        first.fill("Wallet app")
        production.get_by_role("textbox", name="Mobile Description", exact=True).first.fill("Android")
        production.get_by_role("button", name="Add component").click()
        duplicate = production.get_by_role("textbox", name="Mobile Component", exact=True).nth(1)
        description = production.get_by_role("textbox", name="Mobile Description", exact=True).nth(1)
        self.assertTrue(duplicate.evaluate("input => input.validity.valid"))
        self.assertIsNone(duplicate.get_attribute("aria-describedby"))
        duplicate.press_sequentially("  Wallet app  ")

        self.assertTrue(first.evaluate("input => input.validity.valid"))
        self.assertFalse(duplicate.evaluate("input => input.validity.valid"))
        described_by = duplicate.get_attribute("aria-describedby")
        self.assertIsNone(described_by)
        duplicate.evaluate("input => input.blur()")
        description.fill("iOS")

        described_by = duplicate.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(description.get_attribute("aria-describedby"), described_by)
        message = page.locator(f"#{described_by}")
        expect(message).to_have_text(expected_message)
        self.assertEqual(message.evaluate("element => element.closest('td').colSpan"), 3)
        self.assertEqual(
            message.evaluate("element => element.closest('tr').previousElementSibling.querySelector('[data-scope-field=component]').value"),
            "  Wallet app  ",
        )
        self.assertEqual(first.get_attribute("aria-invalid"), None)
        self.assertEqual(duplicate.get_attribute("aria-invalid"), "true")
        self.assertEqual(description.get_attribute("aria-invalid"), "true")

        duplicate.fill("Wallet app copy")
        expect(message).to_be_hidden()
        self.assertTrue(first.evaluate("input => input.validity.valid"))
        self.assertTrue(duplicate.evaluate("input => input.validity.valid"))
        self.assertIsNone(duplicate.get_attribute("aria-describedby"))
        self.assertIsNone(description.get_attribute("aria-describedby"))
        self.assertIsNone(duplicate.get_attribute("aria-invalid"))
        self.assertIsNone(description.get_attribute("aria-invalid"))

        report.scope_targets = [
            ScopeTarget(target_id="tgt_mobile_one", environment="production", channel="mobile", value="Wallet app", description="Android", order=0),
            ScopeTarget(target_id="tgt_mobile_two", environment="production", channel="mobile", value="Wallet app copy", description="", order=1),
        ]
        missing_description_message = next(message for message in setup_issues(report) if "component 2" in message.lower())
        description.fill("")
        page.get_by_role("button", name="Next: Findings").click()
        expect(message).to_have_text(missing_description_message)
        self.assertEqual(duplicate.get_attribute("aria-describedby"), described_by)
        self.assertEqual(description.get_attribute("aria-describedby"), described_by)
        self.assertEqual(duplicate.get_attribute("aria-invalid"), "true")
        self.assertEqual(description.get_attribute("aria-invalid"), "true")
        description.fill("iOS")
        expect(message).to_be_hidden()
        self.assertIsNone(duplicate.get_attribute("aria-describedby"))
        self.assertIsNone(description.get_attribute("aria-describedby"))

    def _two_thick_client_components(self) -> str:
        """A thick-client report with two components, both referenced by its one finding."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["thick_client"]
        report.scope_targets = [
            ScopeTarget(target_id="tgt_main", environment="production", channel="thick_client", value="Acme.exe", description="Main client", order=0),
            ScopeTarget(target_id="tgt_updater", environment="production", channel="thick_client", value="Updater.exe", description="Updater", order=1),
        ]
        report.vulnerabilities[0].scope.target_ids = ["tgt_main", "tgt_updater"]
        main.workspace.save(report)
        return report_id

    def _assert_both_components_kept(self, report_id: str) -> None:
        saved = main.workspace.load(report_id)
        self.assertEqual(
            [(target.target_id, target.value) for target in saved.scope_targets],
            [("tgt_main", "Acme.exe"), ("tgt_updater", "Updater.exe")],
        )
        self.assertEqual(saved.vulnerabilities[0].scope.target_ids, ["tgt_main", "tgt_updater"])

    def test_cancelling_component_removal_cannot_save_the_proposed_deletion(self) -> None:
        report_id = self._two_thick_client_components()

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Application Owner").fill("Pending owner edit")
        page.get_by_role("button", name="Remove Thick Client component 2").click()
        page.locator(".vr-dialog").wait_for()
        page.evaluate("document.querySelector('#save-button').click()")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        page.get_by_role("button", name="Keep the current targets").click()

        self._assert_both_components_kept(report_id)

    def test_cancelling_component_rename_preserves_target_identity_and_references(self) -> None:
        report_id = self._two_thick_client_components()

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        component = page.get_by_role("textbox", name="Thick Client Component", exact=True).nth(1)
        component.fill("Updater2.exe")
        component.press("Tab")
        page.locator(".vr-dialog").wait_for()
        page.evaluate("document.querySelector('#save-button').click()")
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "unsaved")
        self._assert_both_components_kept(report_id)
        page.get_by_role("button", name="Keep the current targets").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        self._assert_both_components_kept(report_id)

    def test_a_component_needs_a_description_before_setup_will_let_you_leave(self) -> None:
        """A description-only entry would pass an unnarrowed textarea count and 422 server-side.
        The notice must also read the same as setup_issues, or the two describe one report differently."""
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Test Thick Client").check()
        page.get_by_label("Test Web").uncheck()
        # Production only, so the one empty box on the page is the one under test.
        page.get_by_label("Non-Production", exact=True).uncheck()
        page.get_by_label("Segment").select_option("JH")
        page.get_by_label("Application Name").fill("Binary Scope")
        page.get_by_label("Report Type").select_option("annual_pentest")
        page.get_by_label("Tester").fill("QA Tester")
        self.choose_required_engagement_details()
        page.locator('input[aria-label="Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Production end date"]').fill("2026-01-02")

        component = page.get_by_role("textbox", name="Thick Client Component", exact=True).first
        description = page.get_by_role("textbox", name="Thick Client Description", exact=True).first

        # Description only: the component box is what names a target, so this is still empty scope.
        description.fill("Main desktop client")
        page.locator("#next").click()
        notice = page.locator("#setup-validation-note")
        self.assertEqual(notice.text_content(), "1 thing to fix before Findings. It is marked above, and the cursor is on it.")
        self.assertTrue(component.evaluate("input => input.classList.contains('validation-error')"))

        # Component only: now a target exists, and the missing description is named by component.
        component.fill("Acme.exe")
        description.fill("")
        page.locator("#next").click()
        self.assertEqual(notice.text_content(), "1 thing to fix before Findings. It is marked above, and the cursor is on it.")
        described_by = component.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        self.assertEqual(description.get_attribute("aria-describedby"), described_by)
        expect(page.locator(f"#{described_by}")).to_be_visible()
        self.assertTrue(description.evaluate("input => input.classList.contains('validation-error')"))
        self.assertEqual(component.evaluate("input => document.activeElement === input"), True)

        description.evaluate("input => { input.value = 'Crashes on start\\u0007'; input.dispatchEvent(new Event('input', {bubbles:true})); }")
        self.assertEqual(
            description.evaluate("input => input.validationMessage"),
            'Line 1 has a hidden character after "...hes on start". Delete it.',
        )

        description.fill("Main desktop client")
        page.locator("#next").click()
        page.wait_for_url("**/findings")

        # The pair survives the round trip, which is the whole point of storing it on the target.
        page.goto(f"{self.base_url}{page.url.split(self.base_url)[1].replace('/findings', '/setup')}")
        self.assertEqual(page.get_by_role("textbox", name="Thick Client Component", exact=True).first.input_value(), "Acme.exe")
        self.assertEqual(page.get_by_role("textbox", name="Thick Client Description", exact=True).first.input_value(), "Main desktop client")

    def test_thick_client_and_mobile_swap_silently_but_ask_when_scope_would_be_lost(self) -> None:
        """The request is a silent swap. Silent is right when the outgoing panel is empty, and wrong
        when it holds typed work -- which is deleted with no undo."""
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Test Mobile").check()
        page.get_by_label("Test Web").uncheck()

        # Nothing typed yet, so the swap is instant and unprompted.
        page.get_by_label("Test Thick Client").check()
        self.assertFalse(page.get_by_label("Test Mobile").is_checked())
        self.assertTrue(page.get_by_label("Test Thick Client").is_checked())

        page.get_by_role("textbox", name="Thick Client Component", exact=True).first.fill("Acme.exe")
        page.get_by_role("textbox", name="Thick Client Description", exact=True).first.fill("Main desktop client")
        # The impact count reads saved targets, so unsaved typing is invisible to the confirmation.
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        page.get_by_label("Test Mobile").check()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for()
        self.assertIn("Replace Thick Client with Mobile?", dialog.text_content())
        dialog.get_by_role("button", name="Keep Thick Client").click()

        # Cancelling restores both boxes, so the list is never momentarily empty.
        self.assertFalse(page.get_by_label("Test Mobile").is_checked())
        self.assertTrue(page.get_by_label("Test Thick Client").is_checked())
        self.assertEqual(page.get_by_role("textbox", name="Thick Client Component", exact=True).first.input_value(), "Acme.exe")

        # Confirming completes the swap and takes the outgoing app type's scope with it.
        page.get_by_label("Test Mobile").check()
        page.locator(".vr-dialog").wait_for()
        page.get_by_role("button", name="Switch to Mobile anyway").click()
        self.assertTrue(page.get_by_label("Test Mobile").is_checked())
        self.assertFalse(page.get_by_label("Test Thick Client").is_checked())
        self.assertEqual(page.get_by_role("textbox", name="Mobile Component", exact=True).first.input_value(), "")

    def test_component_swap_keeps_lost_location_evidence_as_supporting(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["web", "thick_client"]
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.extend([
            ScopeTarget(target_id="tgt_thick", environment="production", channel="thick_client", value="Acme.exe", description="Desktop client"),
            ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"),
        ])
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_thick", "tgt_uat"]
        acceptance.provision(report)

        image_data = png_bytes(2, 2)
        evidence_id = "ev_component_swap"
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="component-swap.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production")
        production_image.evidence_id = evidence_id
        production_image.caption = "Desktop response retained after Mobile swap"
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Test Mobile").check()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn("Replace Thick Client with Mobile?", dialog.inner_text())
        self.assertIn("One screenshot stays in the report as a supporting image", dialog.inner_text())
        dialog.get_by_role("button", name="Switch to Mobile anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.tested_channels, ["web", "mobile"])
        self.assertFalse(any(target.channel == "thick_client" for target in saved.scope_targets))
        self.assertEqual(saved.vulnerabilities[0].scope.target_ids, ["tgt_uat"])
        saved_proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting = next(fragment for fragment in saved_proof.fragments if fragment.type == "image" and fragment.evidence_id == evidence_id)
        self.assertEqual(supporting.environment, "production")
        self.assertTrue(evidence_path.exists())
        rendered = Document(BytesIO(render_report_docx(
            saved,
            main_template_path(saved, Path(__file__).resolve().parent.parent / "resources"),
            main.workspace.find_path(report_id).parent,
            allow_incomplete=True,
        )))
        self.assertIn("Desktop response retained after Mobile swap", "\n".join(paragraph.text for paragraph in rendered.paragraphs))

    def test_component_swap_warns_before_discarding_an_unsaved_row(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["thick_client"]
        report.scope_targets = []
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_role("textbox", name="Thick Client Component", exact=True).first.fill("Unsaved.exe")
        page.get_by_role("textbox", name="Thick Client Description", exact=True).first.fill("Unsaved client")
        page.get_by_label("Test Mobile").check()

        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=2_000)
        self.assertIn("1 scope target", dialog.inner_text())
        dialog.get_by_role("button", name="Keep Thick Client").click()
        self.assertTrue(page.get_by_label("Test Thick Client").is_checked())
        self.assertFalse(page.get_by_label("Test Mobile").is_checked())
        self.assertEqual(page.get_by_role("textbox", name="Thick Client Component", exact=True).first.input_value(), "Unsaved.exe")
        self.assertEqual(page.get_by_role("textbox", name="Thick Client Description", exact=True).first.input_value(), "Unsaved client")

    def test_environment_removal_warns_before_discarding_saved_and_unsaved_components(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["mobile"]
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets = [
            ScopeTarget(target_id="tgt_prod", environment="production", channel="mobile", value="Prod app", description="Production build"),
            ScopeTarget(target_id="tgt_uat", environment="non_production", channel="mobile", value="UAT app", description="Test build"),
        ]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        non_production = page.locator("#scope-grid .scope-panel.non_production")
        non_production.get_by_role("button", name="Add component").click()
        non_production.get_by_role("textbox", name="Mobile Component", exact=True).nth(1).fill("UAT helper")
        non_production.get_by_role("textbox", name="Mobile Description", exact=True).nth(1).fill("Unsaved helper build")
        page.get_by_label("Non-Production", exact=True).uncheck()

        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=2_000)
        self.assertIn("2 scope targets", dialog.inner_text())
        dialog.get_by_role("button", name="Keep the current coverage").click()
        self.assertTrue(page.get_by_label("Non-Production", exact=True).is_checked())
        self.assertEqual(
            non_production.get_by_role("textbox", name="Mobile Component", exact=True).evaluate_all("inputs => inputs.map(input => input.value)"),
            ["UAT app", "UAT helper"],
        )

    def test_environment_removal_does_not_relabel_uploaded_evidence(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(
            start_date=date(2026, 1, 3), end_date=date(2026, 1, 4)
        )
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        finding = report.vulnerabilities[0]
        finding.scope = Scope(mode="custom", target_ids=["tgt_browser", "tgt_uat"])
        main.sync_evidence_image_slots(finding, report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(
            fragment for fragment in proof.fragments
            if fragment.type == "image" and fragment.environment == "production"
        )
        production_frag_id = production_image.frag_id
        image = BytesIO()
        Image.new("RGB", (3, 3), "red").save(image, format="PNG")
        image_bytes = image.getvalue()
        production_image.evidence_id = "ev_production"
        production_image.caption = "Production-only response"
        report.evidence["ev_production"] = EvidenceItem(
            file="evidence/ev_production.png",
            original_name="production.png",
            width_px=3,
            height_px=3,
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            uploaded_at=report.saved_at,
        )
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / "ev_production.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_bytes)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Production", exact=True).click()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn("screenshot", dialog.inner_text().lower())
        self.assertIn("until that environment is tested again", dialog.inner_text())
        dialog.get_by_role("button", name="Make the change anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        saved_image = next(
            fragment for content in saved.vulnerabilities[0].contents for fragment in content.fragments
            if getattr(fragment, "evidence_id", None) == "ev_production"
        )
        self.assertEqual(saved_image.environment, "production", "Production evidence was relabelled as Non-Production")
        self.assertIn("ev_production", saved.evidence)
        self.assertTrue(evidence_path.exists())

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        environment = page.locator(f'[data-fragment-id="{production_frag_id}"] .evidence-environment')
        self.assertEqual(environment.input_value(), "production")
        self.assertIn("Production (not tested)", environment.locator("option:checked").inner_text())

    def test_environment_removal_does_not_describe_an_empty_slot_as_a_screenshot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(
            start_date=date(2026, 1, 3), end_date=date(2026, 1, 4)
        )
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        finding = report.vulnerabilities[0]
        finding.scope = Scope(mode="custom", target_ids=["tgt_browser", "tgt_uat"])
        main.sync_evidence_image_slots(finding, report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(
            fragment for fragment in proof.fragments
            if fragment.type == "image" and fragment.environment == "production"
        )
        self.assertFalse(production_image.evidence_id or production_image.caption)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_role("checkbox", name="Production", exact=True).uncheck()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertNotIn("screenshot", dialog.inner_text().lower())
        dialog.get_by_role("button", name="Make the change anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        saved_proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertNotIn(production_image.frag_id, [fragment.frag_id for fragment in saved_proof.fragments])

    def test_environment_warning_counts_required_and_supporting_images_that_stop_printing(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        required_finding = report.vulnerabilities[0]
        required_finding.title = "Required UAT evidence"
        required_finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        supporting_finding = Vulnerability(
            uid="v_supporting_uat",
            title="Supporting UAT evidence",
            likelihood="low",
            impact="low",
            severity="low",
            status="open_new",
            scope={"mode": "custom", "target_ids": ["tgt_browser"]},
        )
        main.provision(supporting_finding)
        report.vulnerabilities.append(supporting_finding)
        acceptance.provision(report)
        supporting_proof = next(content for content in supporting_finding.contents if content.type == "proof_of_concept")
        supporting_proof.fragments.append(ImageFragment(
            frag_id="f_supporting_uat", type="image", environment="non_production",
            evidence_id="ev_supporting_uat", caption="Supporting UAT response",
        ))
        required_proof = next(content for content in required_finding.contents if content.type == "proof_of_concept")
        required_image = next(fragment for fragment in required_proof.fragments if fragment.type == "image" and fragment.environment == "non_production")
        required_image.evidence_id = "ev_required_uat"
        required_image.caption = "Required UAT response"

        image_data = png_bytes(2, 2)
        evidence_root = main.workspace.find_path(report_id).parent / "evidence"
        evidence_root.mkdir(exist_ok=True)
        for evidence_id in ("ev_required_uat", "ev_supporting_uat"):
            (evidence_root / f"{evidence_id}.png").write_bytes(image_data)
            report.evidence[evidence_id] = EvidenceItem(
                file=f"evidence/{evidence_id}.png",
                original_name=f"{evidence_id}.png",
                width_px=2,
                height_px=2,
                sha256=hashlib.sha256(image_data).hexdigest(),
                uploaded_at=report.saved_at,
            )
        main.workspace.save(report)

        def rendered_text() -> str:
            stored = main.workspace.load(report_id)
            document = Document(BytesIO(render_report_docx(
                stored,
                main_template_path(stored, Path(__file__).resolve().parent.parent / "resources"),
                main.workspace.find_path(report_id).parent,
                allow_incomplete=True,
            )))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)

        self.assertIn("Required UAT response", rendered_text())
        self.assertIn("Supporting UAT response", rendered_text())

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Non-Production", exact=True).uncheck()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn(
            "2 screenshots keep their environment and files, but stop appearing in the report",
            dialog.inner_text(),
        )
        dialog.get_by_role("button", name="Make the change anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertNotIn("Required UAT response", rendered_text())
        self.assertNotIn("Supporting UAT response", rendered_text())

        page.get_by_label("Non-Production", exact=True).check()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertIn("Required UAT response", rendered_text())
        self.assertIn("Supporting UAT response", rendered_text())

    def test_scope_target_rename_keeps_its_screenshot_as_supporting(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        acceptance.provision(report)

        image_data = png_bytes(2, 2)
        evidence_id = "ev_renamed_scope"
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="renamed-scope.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production")
        production_image.evidence_id = evidence_id
        production_image.caption = "Response from the renamed Production target"
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        production_scope = page.get_by_role("textbox", name="Web", exact=True).nth(0)
        production_scope.fill("https://renamed.example.test")
        production_scope.press("Tab")
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn("One screenshot stays in the report as a supporting image", dialog.inner_text())
        dialog.get_by_role("button", name="Change them anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(
            [(target.environment, target.value) for target in saved.scope_targets],
            [("production", "https://renamed.example.test"), ("non_production", "https://uat.example.test")],
        )
        self.assertEqual(saved.vulnerabilities[0].scope.target_ids, ["tgt_uat"])
        saved_proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting = next(fragment for fragment in saved_proof.fragments if fragment.type == "image" and fragment.evidence_id == evidence_id)
        self.assertEqual(supporting.environment, "production")
        self.assertTrue(evidence_path.exists())
        rendered = Document(BytesIO(render_report_docx(
            saved,
            main_template_path(saved, Path(__file__).resolve().parent.parent / "resources"),
            main.workspace.find_path(report_id).parent,
            allow_incomplete=True,
        )))
        self.assertIn("Response from the renamed Production target", "\n".join(paragraph.text for paragraph in rendered.paragraphs))

    def test_unchecking_an_app_type_confirms_then_clears_it_from_every_finding(self) -> None:
        """Dropping an app type deletes its scope targets and every affected location and additional
        endpoint recorded under it, so the tester is told exactly what goes before it happens."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["web", "api"]
        report.scope_targets.append(ScopeTarget(target_id="tgt_api", environment="production", channel="api", value="https://prod-api.example.test"))
        report.vulnerabilities[0].scope = Scope(
            mode="custom",
            target_ids=["tgt_browser", "tgt_api"],
            custom_locations={"production": {"api": ["POST /v1/pay"]}},
        )
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Test API").click()
        page.locator(".vr-dialog").wait_for(timeout=5_000)
        prompt = page.locator(".vr-dialog").inner_text()
        self.assertIn("additional affected endpoint", prompt)
        self.assertIn("Browser finding", prompt)
        self.assertNotIn("cannot be undone", prompt.lower())

        page.locator('[data-dialog-action="cancel"]').click()
        self.assertTrue(page.get_by_label("Test API").is_checked(), "cancelling keeps the app type")

        page.get_by_label("Test API").click()
        page.locator('[data-dialog-action="confirm"]').click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.tested_channels, ["web"])
        self.assertEqual([target.channel for target in saved.scope_targets], ["web"])
        self.assertEqual(saved.vulnerabilities[0].scope.target_ids, ["tgt_browser"], "the api location is gone from the finding")
        self.assertEqual(saved.vulnerabilities[0].scope.custom_locations, {}, "the typed api endpoint is gone too")

        page.get_by_role("button", name="Undo last change").click()
        page.wait_for_function(
            "() => document.querySelector('[aria-label=\"Test API\"]')?.checked === true",
            timeout=10_000,
        )
        restored = main.workspace.load(report_id)
        self.assertEqual(restored.engagement.tested_channels, ["web", "api"])
        self.assertEqual([target.channel for target in restored.scope_targets], ["web", "api"])
        self.assertEqual(restored.vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_api"])
        self.assertEqual(
            restored.vulnerabilities[0].scope.custom_locations,
            {"production": {"api": ["POST /v1/pay"]}},
        )

    def test_app_type_removal_keeps_custom_location_evidence_as_a_supporting_image(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_channels = ["web", "api"]
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(
            start_date=date(2026, 1, 3), end_date=date(2026, 1, 4)
        )
        report.scope_targets = [ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        )]
        finding = report.vulnerabilities[0]
        finding.scope = Scope(
            mode="custom",
            target_ids=["tgt_uat"],
            custom_locations={"production": {"api": ["POST /v1/pay"]}},
        )
        main.sync_evidence_image_slots(finding, report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(
            fragment for fragment in proof.fragments
            if fragment.type == "image" and fragment.environment == "production"
        )
        production_image.caption = "Production API response"
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Test API").click()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn("screenshot", dialog.inner_text().lower())
        self.assertIn("stays in the report as a supporting image", dialog.inner_text())
        dialog.get_by_role("button", name="Remove API anyway").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        saved_image = next(
            fragment for content in saved.vulnerabilities[0].contents for fragment in content.fragments
            if fragment.frag_id == production_image.frag_id
        )
        self.assertEqual(saved_image.environment, "production")
        self.assertEqual(saved.vulnerabilities[0].scope.custom_locations, {})

    def test_cancelling_a_finding_location_removal_cannot_save_the_proposed_scope(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production").caption = "Production evidence caption"
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_role("button", name="Edit finding name").click()
        page.locator(".finding-title-cell input").fill("Pending title edit")
        page.get_by_label("Select https://prod.example.test").uncheck()
        page.locator(".vr-dialog").wait_for()
        page.evaluate("document.querySelector('#save-button').click()")

        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "unsaved")
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_uat"])
        page.get_by_role("button", name="Keep the affected location").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_uat"])

    def test_a_finding_that_loses_an_environment_can_keep_its_screenshots_as_supporting_images(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        acceptance.provision(report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production").caption = "Production evidence caption"
        proof.fragments.append(ImageFragment(frag_id="f_empty_production", type="image", environment="production", evidence_id=None, caption=""))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_label("Select https://prod.example.test").uncheck()
        dialog = page.locator(".vr-dialog")
        dialog.wait_for()
        self.assertIn("supporting images", dialog.inner_text())
        dialog.get_by_role("button", name="Keep as supporting images").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(saved.scope.target_ids, ["tgt_uat"])
        # The captioned screenshot stays as a supporting image; the empty Production tile goes.
        self.assertEqual(
            [fragment.caption for content in saved.contents for fragment in content.fragments if fragment.type == "image" and fragment.environment == "production"],
            ["Production evidence caption"],
        )

    def test_undo_after_removing_location_screenshots_restores_the_png(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        acceptance.provision(report)

        image_data = png_bytes(2, 2)
        evidence_id = "ev_scope_undo"
        report_folder = main.workspace.find_path(report_id).parent
        evidence_path = report_folder / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="scope-undo.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production")
        production_image.evidence_id = evidence_id
        production_image.caption = "Production response"
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_label("Select https://prod.example.test").uncheck()
        page.locator(".vr-dialog").get_by_role("button", name="Remove them").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertFalse(evidence_path.exists(), "removing the screenshot did not prune its file")

        with page.expect_navigation():
            page.locator("#undo-button").click()

        restored = main.workspace.load(report_id)
        self.assertEqual(restored.vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_uat"])
        restored_proof = next(content for content in restored.vulnerabilities[0].contents if content.type == "proof_of_concept")
        restored_image = next(fragment for fragment in restored_proof.fragments if fragment.type == "image" and fragment.evidence_id == evidence_id)
        self.assertEqual(restored_image.environment, "production")
        self.assertIn(evidence_id, restored.evidence)
        self.assertTrue(evidence_path.exists(), "undo restored a reference to a PNG the preceding save deleted")

        with page.expect_navigation():
            page.locator("#redo-button").click()
        removed_again = main.workspace.load(report_id)
        self.assertEqual(removed_again.vulnerabilities[0].scope.target_ids, ["tgt_uat"])
        self.assertFalse(any(
            getattr(fragment, "evidence_id", None) == evidence_id
            for content in removed_again.vulnerabilities[0].contents
            for fragment in content.fragments
        ), "redo did not remove the screenshot tile")

        with page.expect_navigation():
            page.locator("#undo-button").click()
        restored_again = main.workspace.load(report_id)
        self.assertEqual(restored_again.vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_uat"])
        self.assertIn(evidence_id, restored_again.evidence)
        self.assertTrue(evidence_path.exists(), "a second undo could not restore the archived PNG")

    def test_undo_redo_after_keeping_a_supporting_image_preserves_its_png(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
        finding = report.vulnerabilities[0]
        finding.scope.target_ids = ["tgt_browser", "tgt_uat"]
        acceptance.provision(report)

        image_data = png_bytes(2, 2)
        evidence_id = "ev_scope_keep"
        report_folder = main.workspace.find_path(report_id).parent
        evidence_path = report_folder / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="scope-keep.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        production_image = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production")
        production_image.evidence_id = evidence_id
        production_image.caption = "Production response"
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_label("Select https://prod.example.test").uncheck()
        page.locator(".vr-dialog").get_by_role("button", name="Keep as supporting images").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        supporting = main.workspace.load(report_id)
        self.assertEqual(supporting.vulnerabilities[0].scope.target_ids, ["tgt_uat"])
        self.assertIn(evidence_id, supporting.evidence)
        self.assertTrue(evidence_path.exists())

        with page.expect_navigation():
            page.locator("#undo-button").click()
        required_again = main.workspace.load(report_id)
        self.assertEqual(required_again.vulnerabilities[0].scope.target_ids, ["tgt_browser", "tgt_uat"])
        self.assertIn(evidence_id, required_again.evidence)
        self.assertTrue(evidence_path.exists())

        with page.expect_navigation():
            page.locator("#redo-button").click()
        supporting_again = main.workspace.load(report_id)
        self.assertEqual(supporting_again.vulnerabilities[0].scope.target_ids, ["tgt_uat"])
        supporting_proof = next(content for content in supporting_again.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting_image = next(fragment for fragment in supporting_proof.fragments if fragment.type == "image" and fragment.evidence_id == evidence_id)
        self.assertEqual(supporting_image.environment, "production")
        self.assertIn(evidence_id, supporting_again.evidence)
        self.assertTrue(evidence_path.exists())

    def test_custom_location_removal_cannot_autosave_before_its_evidence_decision(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
        finding = report.vulnerabilities[0]
        finding.scope = Scope(mode="custom", target_ids=["tgt_uat"], custom_locations={"production": {"web": ["POST /prod"]}})
        acceptance.provision(report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production").caption = "Production evidence caption"
        main.workspace.save(report)

        page = self.page
        page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 100")
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        endpoint = page.get_by_label("Production affected endpoints", exact=True)
        endpoint.fill("")
        page.wait_for_function("""() => {
            const button = document.querySelector('#save-button');
            return button.textContent === 'Confirm the scope target change' || button.dataset.saveState === 'saved';
        }""")

        self.assertEqual(page.locator("#save-button").inner_text(), "Confirm the scope target change")
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].scope.custom_locations["production"]["web"], ["POST /prod"])
        endpoint.blur()
        page.locator(".vr-dialog").wait_for()
        page.get_by_role("button", name="Keep the affected location").click()
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].scope.custom_locations["production"]["web"], ["POST /prod"])

        endpoint = page.get_by_label("Production affected endpoints", exact=True)
        endpoint.fill("")
        endpoint.blur()
        page.locator(".vr-dialog").wait_for()
        page.get_by_role("button", name="Remove them").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        saved = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(saved.scope.custom_locations, {})
        self.assertFalse(any(
            fragment.type == "image" and fragment.environment == "production"
            for content in saved.contents
            for fragment in content.fragments
        ))

    def test_library_insert_preserves_pending_finding(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_role("button", name="Add finding").click()
        page.get_by_role("combobox", name="Finding Name").fill("Unsaved manual finding")
        search = page.get_by_role("combobox", name="Search vulnerability library")
        search.fill(main.library.entries[0]["title"])
        page.locator("#library-results [role=option]").first.click()
        page.locator("#findings > tr:not(.finding-location-row)").nth(1).wait_for()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        page.reload()
        self.assertEqual(page.locator("#findings > tr:not(.finding-location-row)").count(), 2)
        self.assertTrue(page.get_by_text("Unsaved manual finding", exact=True).is_visible())

    def test_evidence_upload_preserves_pending_content(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.assertEqual(page.locator(".evidence-environment").count(), 0)
        self.assertEqual(page.locator(".evidence-environment-value").first.text_content(), "Production")
        description = page.locator(".content-block").filter(has_text="Description").locator(".rich").first
        description.fill("Unsaved description")
        image_data = png_bytes(2, 2)
        page.locator('input[type="file"]').first.set_input_files({"name": "proof.png", "mimeType": "image/png", "buffer": image_data})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        page.reload()
        self.assertEqual(page.locator(".content-block").filter(has_text="Description").locator(".rich").first.text_content(), "Unsaved description")
        self.assertEqual(page.locator(".image-preview").count(), 1)

    def paste_png(self, selector: str | None = None) -> None:
        """Dispatch a genuine paste event carrying a PNG, on one card or on the page itself."""
        image_data = png_bytes(2, 2)
        self.page.evaluate(
            """([selector, encoded]) => {
                const transfer = new DataTransfer();
                transfer.items.add(new File([Uint8Array.from(atob(encoded), character => character.charCodeAt(0))], "pasted.png", {type: "image/png"}));
                const target = selector ? document.querySelector(selector) : document.body;
                target.dispatchEvent(new ClipboardEvent("paste", {clipboardData: transfer, bubbles: true, cancelable: true}));
            }""",
            [selector, base64.b64encode(image_data).decode()],
        )

    def paste_png_as_item_only(self, selector: str | None = None) -> None:
        """A clipboard whose image is reachable only through `items`.

        OneNote and Word put HTML on the clipboard beside the picture, and the browser then leaves
        `files` empty. A real DataTransfer always fills both, so the shape has to be faked.
        """
        image_data = png_bytes(2, 2)
        self.page.evaluate(
            """([selector, encoded]) => {
                const file = new File([Uint8Array.from(atob(encoded), character => character.charCodeAt(0))], "pasted.png", {type: "image/png"});
                const event = new Event("paste", {bubbles: true, cancelable: true});
                Object.defineProperty(event, "clipboardData", {value: {
                    files: [],
                    items: [
                        {kind: "string", type: "text/html", getAsFile: () => null},
                        {kind: "file", type: "image/png", getAsFile: () => file},
                    ],
                }});
                const target = selector ? document.querySelector(selector) : document.body;
                target.dispatchEvent(event);
            }""",
            [selector, base64.b64encode(image_data).decode()],
        )

    def arm_evidence(self, fragment_id: str) -> None:
        """Arm an evidence image the way a click does, without opening the file picker a label would."""
        self.page.evaluate(
            """id => document.querySelector(`.evidence-tile[data-fragment-id="${id}"]`)
                .dispatchEvent(new PointerEvent("pointerdown", {bubbles: true}))""",
            fragment_id,
        )

    def evidence_ids(self, filled: bool | None = None) -> list[str]:
        return self.page.evaluate(
            """filled => [...document.querySelectorAll(".evidence-tile")]
                .filter(tile => filled === null || tile.classList.contains("has-evidence") === filled)
                .map(tile => tile.dataset.fragmentId)""",
            filled,
        )

    def test_pasting_a_screenshot_attaches_it_as_evidence(self) -> None:
        """Both clipboard shapes must attach. OneNote and Word put HTML on the clipboard beside the
        picture, which leaves `clipboardData.files` empty; reading only that list dropped the paste
        with no message."""
        for clipboard, paste in (("file list", self.paste_png), ("item only", self.paste_png_as_item_only)):
            with self.subTest(clipboard=clipboard):
                report_id = self.ready_report(include_finding=True)
                page = self.page
                page.goto(f"{self.base_url}/reports/{report_id}/edit")
                page.locator(".evidence-tile").first.wait_for(timeout=5_000)
                # An unarmed image must not offer a paste that would not reach it.
                self.assertNotIn("paste", page.locator(".evidence-thumb").first.inner_text().lower())
                self.arm_evidence(self.evidence_ids()[0])
                self.assertIn("paste", page.locator(".evidence-thumb").first.inner_text().lower(), "the armed image must say how to paste")
                paste(".evidence-tile")
                page.locator(".image-preview").first.wait_for(timeout=5_000)
                page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

                page.reload()
                self.assertEqual(page.locator(".image-preview").count(), 1)
                self.assertEqual(page.locator(".evidence-thumb span").count(), 0, "the prompt stayed on a filled image")

    def test_pasting_an_image_from_a_focused_editor_uses_the_armed_evidence_slot(self) -> None:
        """Text focus must not steal an image paste from the evidence image the tester armed, and
        the editor receiving the event must retain its text rather than acquiring clipboard noise."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        description = page.locator(".content-block").filter(has_text="Description").locator(".rich").first
        description.fill("Keep this description")
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        evidence_id = self.evidence_ids()[0]
        self.arm_evidence(evidence_id)

        self.paste_png(".content-block .rich")
        page.locator(f'.evidence-tile[data-fragment-id="{evidence_id}"] .image-preview').wait_for(timeout=8_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)
        self.assertEqual(description.inner_text(), "Keep this description")

        page.reload()
        stored = main.workspace.load(report_id)
        stored_description = next(content for content in stored.vulnerabilities[0].contents if content.type == "description")
        proof = next(content for content in stored.vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertEqual(stored_description.fragments[0].runs[0].text, "Keep this description")
        self.assertTrue(
            any(isinstance(fragment, ImageFragment) and fragment.frag_id == evidence_id and fragment.evidence_id for fragment in proof.fragments),
            "the armed image must hold the pasted evidence after reload",
        )

    def test_two_rapid_pastes_into_one_armed_slot_leave_no_orphaned_evidence(self) -> None:
        """The target advances only when an upload finishes. Two pastes before then queue against
        the same fragment, so the earlier image must be replaced cleanly rather than left as an
        unreferenced record and file in the report."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        self.arm_evidence(self.evidence_ids()[0])
        page.evaluate(
            """() => {
                const originalFetch = window.fetch.bind(window);
                window.heldPasteUploads = [];
                window.fetch = (input, init = {}) => {
                    if (String(input).endsWith("/evidence") && init.method === "POST") {
                        return new Promise(resolve => window.heldPasteUploads.push(() => originalFetch(input, init).then(resolve)));
                    }
                    return originalFetch(input, init);
                };
            }"""
        )
        self.paste_png()
        self.paste_png()
        page.wait_for_function("window.heldPasteUploads.length === 1")
        page.evaluate("window.heldPasteUploads.shift()()")
        page.wait_for_function("window.heldPasteUploads.length === 1")
        page.evaluate("window.heldPasteUploads.shift()()")
        page.get_by_role("button", name="Saved").wait_for(timeout=10_000)

        page.reload()
        stored = main.workspace.load(report_id)
        references = {
            fragment.evidence_id
            for finding in stored.vulnerabilities
            for content in finding.contents
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment) and fragment.evidence_id
        }
        self.assertEqual(set(stored.evidence), references, "replaced rapid paste left unreferenced evidence behind")

    def test_deleting_a_paste_target_during_upload_leaves_no_orphaned_evidence(self) -> None:
        """The server registers evidence before the client assigns its ID to the target fragment.
        If the tester deletes that extra tile during the upload, the completed mutation must clean
        up the now-unreferenced record rather than leave exportable evidence with no owner."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        page.get_by_role("button", name="Add another screenshot").first.click()
        page.wait_for_function("() => document.querySelectorAll('.evidence-tile').length === 2")
        self.arm_evidence(self.evidence_ids(filled=False)[-1])
        page.evaluate(
            """() => {
                const originalFetch = window.fetch.bind(window);
                window.heldPasteUploads = [];
                window.fetch = (input, init = {}) => {
                    if (String(input).endsWith("/evidence") && init.method === "POST") {
                        return new Promise(resolve => window.heldPasteUploads.push(() => originalFetch(input, init).then(resolve)));
                    }
                    return originalFetch(input, init);
                };
            }"""
        )
        self.paste_png()
        page.wait_for_function("window.heldPasteUploads.length === 1")
        page.get_by_role("button", name="Delete screenshot 2").click()
        page.wait_for_function("() => document.querySelectorAll('.evidence-tile').length === 1")
        page.evaluate("window.heldPasteUploads.shift()()")
        page.get_by_role("button", name="Saved").wait_for(timeout=10_000)

        page.reload()
        stored = main.workspace.load(report_id)
        references = {
            fragment.evidence_id
            for finding in stored.vulnerabilities
            for content in finding.contents
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment) and fragment.evidence_id
        }
        self.assertEqual(set(stored.evidence), references, "deleted upload target left unreferenced evidence behind")

    def test_replacing_one_shared_evidence_image_keeps_the_other_reference(self) -> None:
        """Replacement cleanup may remove an old record only after checking every fragment. Two
        screenshots can intentionally reuse one evidence file, so replacing one must not lose the
        other image's source file or turn its reference into a 404."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        first_input = page.locator('.evidence-tile input[type="file"]').first
        image = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image, format="PNG")
        first_input.set_input_files({"name": "shared.png", "mimeType": "image/png", "buffer": image.getvalue()})
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)

        report = main.workspace.load(report_id)
        proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
        first = next(fragment for fragment in proof.fragments if isinstance(fragment, ImageFragment))
        original_id = first.evidence_id
        proof.fragments.append(ImageFragment(frag_id="f_shared_evidence", type="image", environment="production", evidence_id=original_id))
        main.workspace.save(report)

        page.reload()
        page.locator(".evidence-tile").nth(1).wait_for(timeout=5_000)
        replacement = BytesIO()
        Image.new("RGB", (3, 3), "red").save(replacement, format="PNG")
        page.locator('.evidence-tile input[type="file"]').first.set_input_files({
            "name": "replacement.png", "mimeType": "image/png", "buffer": replacement.getvalue(),
        })
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)

        stored = main.workspace.load(report_id)
        images = [
            fragment
            for content in stored.vulnerabilities[0].contents
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment)
        ]
        self.assertIn(original_id, stored.evidence, "replacement cleanup deleted evidence still used by another image")
        self.assertEqual(images[1].evidence_id, original_id)
        self.assertEqual(len({fragment.evidence_id for fragment in images if fragment.evidence_id}), 2)

    def test_pasting_with_nothing_armed_imports_nothing(self) -> None:
        """The old fallback filled the first empty image anywhere in the pane, which is how a
        screenshot landed on a finding the tester was not looking at. Now it goes nowhere and says so."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)

        self.paste_png()
        page.wait_for_selector("#paste-notice.is-visible", timeout=5_000)
        self.assertIn("evidence image", page.locator("#paste-notice").inner_text())
        # Deliberately a pause: this checks an upload did NOT happen, and one would only start after
        # an asynchronous file read, so there is no event to wait for instead.
        page.wait_for_timeout(800)
        self.assertEqual(page.locator(".image-preview").count(), 0)
        # The draft is the assertion, not the screen: an image that reached the report without a
        # fragment to hold it would leave the pane looking exactly this empty.
        self.assertEqual(main.workspace.load(report_id).evidence, {})

    def test_a_pasted_screenshot_lands_in_the_armed_image_and_advances(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        # A second empty image is the whole point: with one, landing in the armed image and landing
        # in the first empty image are the same event and prove nothing.
        page.get_by_role("button", name="Add another screenshot").first.click()
        page.wait_for_function("() => document.querySelectorAll('.evidence-tile:not(.has-evidence)').length >= 2", timeout=5_000)
        empty = self.evidence_ids(filled=False)

        # The last one, so landing in the first would look like success under the old rule.
        self.arm_evidence(empty[-1])
        self.paste_png()
        page.locator(f'.evidence-tile[data-fragment-id="{empty[-1]}"] .image-preview').wait_for(timeout=8_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)

        self.assertEqual(page.locator(f'.evidence-tile[data-fragment-id="{empty[0]}"] .image-preview').count(), 0,
                         "the image reached the first empty slot rather than the armed one")
        armed_now = page.locator(".evidence-tile.is-paste-target").count()
        self.assertLessEqual(armed_now, 1, "only one image is ever armed")

        # On the draft as well as on the screen, so a render that merely looks right cannot pass.
        stored = main.workspace.load(report_id)
        attached = {
            fragment.frag_id: getattr(fragment, "evidence_id", None)
            for finding in stored.vulnerabilities for content in finding.contents
            for fragment in content.fragments if fragment.frag_id in {empty[0], empty[-1]}
        }
        self.assertIsNotNone(attached.get(empty[-1]), "the armed image holds no evidence")
        self.assertIsNone(attached.get(empty[0]), "the unarmed image was filled")

    def test_undo_then_redo_of_a_replaced_screenshot_keeps_the_file(self) -> None:
        """Undo used to drop the evidence record, the next save pruned its file, and redo restored a
        reference to a file nothing could bring back."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        target = self.evidence_ids(filled=False)[0]

        self.arm_evidence(target)
        self.paste_png()
        page.locator(f'.evidence-tile[data-fragment-id="{target}"] .image-preview').wait_for(timeout=8_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)
        first = self._stored_fragment(report_id, target)["evidence_id"]

        self.arm_evidence(target)
        with page.expect_response(lambda response: response.url.endswith("/evidence") and response.request.method == "POST"):
            self.paste_png()
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)
        second = self._stored_fragment(report_id, target)["evidence_id"]
        self.assertNotEqual(first, second, "the second paste did not replace the screenshot")

        # Undo and redo each save first and then reload the page (restoreHistory in app.js).
        with page.expect_navigation():
            page.locator("#undo-button").click()
        self.assertEqual(self._stored_fragment(report_id, target)["evidence_id"], first, "undo did not bring the first screenshot back")
        with page.expect_navigation():
            page.locator("#redo-button").click()
        self.assertEqual(self._stored_fragment(report_id, target)["evidence_id"], second, "redo did not bring the replacement back")

        stored = main.workspace.load(report_id)
        folder = main.workspace.find_path(report_id).parent
        referenced = [
            fragment.evidence_id
            for finding in stored.vulnerabilities for content in finding.contents
            for fragment in content.fragments if getattr(fragment, "evidence_id", None)
        ]
        for evidence_id in referenced:
            self.assertIn(evidence_id, stored.evidence, "a fragment points at a record that is gone")
            self.assertTrue((folder / stored.evidence[evidence_id].file).exists(), "the image file was pruned out from under a redo")

    def test_leaving_a_page_mid_upload_keeps_the_screenshot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=8_000)
        # Holds the upload open until the test releases it, so Previous is clicked while the POST is
        # still in flight however fast or slow the machine is.
        page.evaluate(
            """() => {
                const original = window.fetch.bind(window);
                window.releaseUpload = null;
                window.fetch = (url, options = {}) => String(url).endsWith("/evidence") && options.method === "POST"
                    ? new Promise(resolve => { window.releaseUpload = () => original(url, options).then(resolve); })
                    : original(url, options);
            }"""
        )
        image_data = png_bytes(2, 2)
        page.locator('input[type="file"]').first.set_input_files({"name": "proof.png", "mimeType": "image/png", "buffer": image_data})
        page.wait_for_function("window.releaseUpload !== null")
        page.get_by_role("button", name="Previous: Findings").click()
        page.evaluate("window.releaseUpload()")
        page.wait_for_url(f"{self.base_url}/reports/{report_id}/findings", timeout=10_000)

        saved = main.workspace.load(report_id)
        referenced = [
            fragment.evidence_id
            for finding in saved.vulnerabilities
            for content in finding.contents
            for fragment in content.fragments
            if getattr(fragment, "evidence_id", None)
        ]
        self.assertEqual(len(saved.evidence), 1, "navigating away dropped the upload")
        self.assertEqual(referenced, list(saved.evidence), "the uploaded image is referenced by no fragment")

    def test_back_waits_for_two_queued_evidence_uploads(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
        proof.fragments.append(ImageFragment(frag_id="f_second_upload", type="image", environment="production"))
        main.workspace.save(report)

        image = BytesIO()
        Image.new("RGB", (3, 3), "red").save(image, format="PNG")
        payload = image.getvalue()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.evaluate(
            """() => {
                const originalFetch = window.fetch.bind(window);
                window.heldEvidenceUploads = [];
                window.fetch = (input, init = {}) => {
                    if (String(input).endsWith("/evidence") && init.method === "POST") {
                        return new Promise(resolve => window.heldEvidenceUploads.push(() => originalFetch(input, init).then(resolve)));
                    }
                    return originalFetch(input, init);
                };
            }"""
        )
        uploads = page.locator('.evidence-tile:not(.has-evidence) input[type="file"]')
        uploads.nth(0).set_input_files({"name": "first.png", "mimeType": "image/png", "buffer": payload})
        uploads.nth(1).set_input_files({"name": "second.png", "mimeType": "image/png", "buffer": payload})
        page.wait_for_function("window.heldEvidenceUploads.length >= 1")
        page.get_by_role("button", name="Previous: Findings").click()

        self.assertEqual(page.evaluate("window.heldEvidenceUploads.length"), 1, "two revisioned mutations ran concurrently")
        page.evaluate("window.heldEvidenceUploads[0]()")
        page.wait_for_function("window.heldEvidenceUploads.length === 2")
        page.evaluate("window.heldEvidenceUploads[1]()")
        page.wait_for_url("**/findings", timeout=10_000)

        saved = main.workspace.load(report_id)
        proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertEqual(len(saved.evidence), 2)
        self.assertEqual(sum(bool(fragment.evidence_id) for fragment in proof.fragments if fragment.type == "image"), 2)

    def test_back_waits_for_an_upload_queued_after_the_click(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
        proof.fragments.append(ImageFragment(frag_id="f_late_upload", type="image", environment="production"))
        main.workspace.save(report)

        image = BytesIO()
        Image.new("RGB", (3, 3), "green").save(image, format="PNG")
        payload = image.getvalue()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.evaluate(
            """() => {
                const originalFetch = window.fetch.bind(window);
                window.heldEvidenceUploads = [];
                window.fetch = (input, init = {}) => {
                    if (String(input).endsWith("/evidence") && init.method === "POST") {
                        return new Promise(resolve => {
                            window.heldEvidenceUploads.push(() => originalFetch(input, init).then(resolve));
                            sessionStorage.setItem("held-evidence-count", String(window.heldEvidenceUploads.length));
                        });
                    }
                    return originalFetch(input, init);
                };
            }"""
        )
        uploads = page.locator('.evidence-tile:not(.has-evidence) input[type="file"]')
        uploads.nth(0).set_input_files({"name": "first.png", "mimeType": "image/png", "buffer": payload})
        page.wait_for_function('sessionStorage.getItem("held-evidence-count") === "1"')
        page.get_by_role("button", name="Previous: Findings").click()
        uploads.nth(1).set_input_files({"name": "late.png", "mimeType": "image/png", "buffer": payload})
        page.evaluate("window.heldEvidenceUploads[0]()")
        page.wait_for_function('sessionStorage.getItem("held-evidence-count") === "2"')

        self.assertTrue(page.url.endswith("/edit"), "Back left while the late upload was still queued")
        page.evaluate("window.heldEvidenceUploads[1]()")
        page.wait_for_url("**/findings", timeout=10_000)
        saved = main.workspace.load(report_id)
        proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertEqual(len(saved.evidence), 2)
        self.assertEqual(sum(bool(fragment.evidence_id) for fragment in proof.fragments if fragment.type == "image"), 2)

    def test_each_affected_environment_requires_an_image_and_allows_more(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        report.vulnerabilities[0].scope.target_ids.append("tgt_browser_uat")
        main.sync_evidence_image_slots(report.vulnerabilities[0], report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        image_cards = proof.locator(".evidence-tile")
        self.assertEqual(image_cards.count(), 2)
        self.assertEqual(proof.locator(".evidence-environment").evaluate_all("selects => selects.map(select => select.value)"), ["production", "non_production"])
        self.assertEqual(proof.locator(".evidence-environment option").evaluate_all("options => [...new Set(options.map(option => option.value))]"), ["production", "non_production"])
        self.assertTrue(page.get_by_text("Production evidence image required", exact=True).is_visible())
        self.assertTrue(page.get_by_text("Non-Production evidence image required", exact=True).is_visible())

        image_data = png_bytes(2, 2)
        image_cards.nth(0).locator(".evidence-caption").fill("Production transaction response")
        image_cards.nth(0).locator('input[type="file"]').set_input_files({"name": "prod.png", "mimeType": "image/png", "buffer": image_data})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(page.get_by_text("Production evidence image required", exact=True).count(), 0)
        self.assertTrue(page.get_by_text("Non-Production evidence image required", exact=True).is_visible())

        image_cards = proof.locator(".evidence-tile")
        image_cards.nth(1).locator(".evidence-caption").fill("Non-Production transaction response")
        image_cards.nth(1).locator('input[type="file"]').set_input_files({"name": "uat.png", "mimeType": "image/png", "buffer": image_data})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(page.get_by_text("Non-Production evidence image required", exact=True).count(), 0)

        proof.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("image")
        image_cards = proof.locator(".evidence-tile")
        self.assertEqual(image_cards.count(), 3)
        self.assertEqual(proof.locator(".evidence-environment").last.input_value(), "production")

    def test_switching_the_only_required_image_to_supporting_adds_a_required_slot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        required_tile = proof.locator(".evidence-tile").first
        required_tile.locator(".evidence-caption").fill("Production response moved to supporting")
        required_tile.locator('input[type="file"]').set_input_files(
            {"name": "required-to-supporting.png", "mimeType": "image/png", "buffer": png_bytes(2, 2)}
        )
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        proof.locator(".evidence-tile.has-evidence .evidence-environment").select_option("non_production")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertEqual(proof.locator(".evidence-tile").count(), 2, "the page did not add a replacement Production tile")
        self.assertEqual(
            proof.locator(".evidence-environment").evaluate_all("selects => selects.map(select => select.value)"),
            ["non_production", "production"],
        )
        self.assertTrue(page.get_by_text("Production evidence image required", exact=True).is_visible())

        proof.locator(".evidence-tile.has-evidence .evidence-environment").select_option("production")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertEqual(proof.locator(".evidence-tile").count(), 2)
        delete_buttons = proof.locator('button[aria-label^="Delete screenshot"]')
        self.assertFalse(delete_buttons.nth(1).is_disabled(), "the now-extra empty tile cannot be deleted")
        delete_buttons.nth(1).click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        self.assertEqual(proof.locator(".evidence-tile").count(), 1)
        self.assertTrue(proof.get_by_role("button", name="Delete screenshot 1").is_disabled())

    def test_a_finding_that_affects_one_environment_can_hold_a_supporting_screenshot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        main.sync_evidence_image_slots(report.vulnerabilities[0], report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        self.assertEqual(
            proof.locator(".evidence-environment").first.locator("option").all_inner_texts(),
            ["Production", "Non-Production (supporting)"],
        )
        proof.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("image")
        proof.locator(".evidence-environment").last.select_option("non_production")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        saved_proof = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertEqual([fragment.environment for fragment in saved_proof.fragments if fragment.type == "image"], ["production", "non_production"])

        # Reloading runs the page's own slot cleanup, which used to drop an untouched slot like this.
        page.reload()
        page.wait_for_selector("#issue-count")
        supporting = page.locator(".content-block").filter(has_text="Proof of Concept").last.locator(".evidence-tile").last
        self.assertEqual(supporting.locator(".evidence-environment").input_value(), "non_production")
        rows = page.locator(".review-row").filter(has_text="Non-Production supporting evidence")
        self.assertEqual(rows.count(), 0, "an untouched supporting slot was demanded")
        supporting.locator(".evidence-caption").fill("Same response in the test environment")
        rows.first.wait_for(state="attached")
        self.assertIn("requires image", rows.first.inner_text())

    def test_supporting_tile_survives_conflict_resolution_before_upload(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        main.workspace.save(report)

        stale_page = self.page
        stale_page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 60000")
        current_page = self.context.new_page()
        stale_page.goto(f"{self.base_url}/reports/{report_id}/edit")
        current_page.goto(f"{self.base_url}/reports/{report_id}/edit")

        stale_proof = stale_page.locator(".content-block").filter(has_text="Proof of Concept").last
        stale_proof.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("image")
        supporting_tile = stale_proof.locator(".evidence-tile").last
        supporting_tile.locator(".evidence-environment").select_option("non_production")
        supporting_tile.locator(".evidence-caption").fill("Supporting response after conflict")

        current_page.locator(".content-block").filter(has_text="Description").locator(".rich").first.fill("Current tab edit")
        current_page.get_by_role("button", name="Save").click()
        current_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        stale_page.get_by_role("button", name="Save").click()
        conflict = stale_page.locator("#app-diagnostics")
        conflict.get_by_role("heading", name="Save conflict").wait_for(timeout=5_000)
        conflict.get_by_role("button", name="Save my version").click()
        stale_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        supporting_tile = stale_page.locator(".content-block").filter(has_text="Proof of Concept").last.locator(".evidence-tile").last
        self.assertEqual(supporting_tile.locator(".evidence-environment").input_value(), "non_production")
        self.assertEqual(supporting_tile.locator(".evidence-caption").input_value(), "Supporting response after conflict")
        supporting_tile.locator('input[type="file"]').set_input_files(
            {"name": "supporting.png", "mimeType": "image/png", "buffer": png_bytes(3, 3)}
        )
        stale_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(saved.vulnerabilities[0].scope.target_ids, ["tgt_browser"])
        proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.caption == "Supporting response after conflict")
        self.assertEqual(supporting.environment, "non_production")
        self.assertIsNotNone(supporting.evidence_id)
        evidence = saved.evidence[supporting.evidence_id]
        self.assertTrue((main.workspace.find_path(report_id).parent / evidence.file).is_file())
        current_page.close()

    def test_supporting_upload_waits_for_its_in_flight_autosave(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.evaluate(
            """reportId => {
                const originalFetch = window.fetch.bind(window);
                let held = false;
                window.releaseSupportingSave = null;
                window.fetch = (input, init = {}) => {
                    if (!held && String(input).endsWith(`/reports/${reportId}`) && init.method === "PUT") {
                        held = true;
                        return new Promise(resolve => {
                            window.releaseSupportingSave = () => originalFetch(input, init).then(resolve);
                        });
                    }
                    return originalFetch(input, init);
                };
            }""",
            report_id,
        )
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        proof.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("image")
        supporting_tile = proof.locator(".evidence-tile").last
        supporting_tile.locator(".evidence-environment").select_option("non_production")
        supporting_fragment_id = supporting_tile.get_attribute("data-fragment-id")
        page.wait_for_function("window.releaseSupportingSave !== null", timeout=5_000)

        supporting_tile.locator('input[type="file"]').set_input_files(
            {"name": "supporting-in-flight.png", "mimeType": "image/png", "buffer": png_bytes(3, 3)}
        )
        with page.expect_response(lambda response: response.url.endswith("/evidence") and response.request.method == "POST"):
            page.evaluate("window.releaseSupportingSave()")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        proof = next(content for content in saved.vulnerabilities[0].contents if content.type == "proof_of_concept")
        supporting = next(fragment for fragment in proof.fragments if fragment.frag_id == supporting_fragment_id)
        self.assertEqual(supporting.environment, "non_production")
        self.assertIsNotNone(supporting.evidence_id)
        production = next(fragment for fragment in proof.fragments if fragment.type == "image" and fragment.environment == "production")
        self.assertIsNone(production.evidence_id, "the upload attached to the required tile instead")
        evidence = saved.evidence[supporting.evidence_id]
        self.assertTrue((main.workspace.find_path(report_id).parent / evidence.file).is_file())

    def test_two_tabs_racing_the_first_save_after_editable_import_conflict_correctly(self) -> None:
        """An imported report's saved_at comes from the import route, not an ordinary save. Two
        tabs opened on it before either edits must still detect a stale second save exactly like
        two tabs on a hand-built report do."""
        document = self.importable_docx()
        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as editable draft").click()
        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        result.get_by_role("button", name="Open Setup").click()
        self.page.wait_for_url("**/reports/*/setup")
        report_id = self.page.url.split("/reports/")[1].split("/")[0]

        first_page = self.page
        stale_page = self.other_profile_page()
        stale_page.goto(f"{self.base_url}/reports/{report_id}/setup")

        first_page.get_by_label("Application Owner").fill("First tab after import")
        first_page.get_by_role("button", name="Save").click()
        first_page.get_by_role("button", name="Saved").wait_for()
        stale_page.get_by_label("Application Owner").fill("Stale tab after import")
        stale_page.get_by_role("button", name="Save").click()
        conflict = stale_page.locator("#app-diagnostics")
        conflict.get_by_role("heading", name="Save conflict").wait_for()
        self.assertIn("409", conflict.text_content())
        conflict.get_by_role("button", name="Save my version").click()
        stale_page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).engagement.app_owner, "Stale tab after import")
        stale_page.close()

    def test_editable_import_content_page_matches_server_readiness_verdict(self) -> None:
        """An imported draft that still has gaps: the Content page must agree with the server that it
        is not ready. test_editable_import_of_an_asia_cvss_finding_reaches_ready_state covers the
        ready side of the same agreement."""
        document = self.importable_docx()
        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as editable draft").click()
        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        result.get_by_role("button", name="Open Setup").click()
        self.page.wait_for_url("**/reports/*/setup")
        imported_id = self.page.url.split("/reports/")[1].split("/")[0]

        server_issues = generation_issues(main.workspace.load(imported_id))
        self.assertTrue(server_issues, "the fixture must still have gaps, or this only repeats the ready-side test")
        self.page.goto(f"{self.base_url}/reports/{imported_id}/edit")
        self.page.wait_for_selector("#issue-count")
        browser_state = self.page.locator("#issue-count").get_attribute("data-state")
        self.assertEqual(
            browser_state,
            "ready" if not server_issues else "issues",
            f"browser says {browser_state!r} but the server reports {server_issues}",
        )
        self.assertEqual(self.page.get_by_role("button", name="Generate Report").is_enabled(), not server_issues)

    def test_editable_import_and_first_save_keep_open_resolved_on_non_prod(self) -> None:
        """The status prints retest sections but is not one of the historical two-status cases.
        Its parser round trip is unit-tested; this covers the browser's first canonical save after
        the manager imports the editable document."""
        source_id = self.ready_report(include_finding=True)
        source = main.workspace.load(source_id)
        finding = source.vulnerabilities[0]
        finding.status = "open_resolved_on_non_prod"
        acceptance.provision(source)
        main.workspace.save(source)
        document = render_report_docx(
            source,
            main_template_path(source, Path(__file__).resolve().parent.parent / "resources"),
            main.workspace.find_path(source_id).parent,
            allow_incomplete=True,
        )

        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "lower-region.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        result = self.page.get_by_role("dialog")
        result.get_by_role("button", name="Import as editable draft").click()
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        result.get_by_role("button", name="Open Setup").click()
        self.page.wait_for_url("**/reports/*/setup")
        imported_id = self.page.url.split("/reports/")[1].split("/")[0]

        self.page.get_by_label("Application Owner").fill("Imported owner")
        self.page.get_by_role("button", name="Save").click()
        self.page.get_by_role("button", name="Saved").wait_for(timeout=10_000)
        stored = main.workspace.load(imported_id).vulnerabilities[0]
        self.assertEqual(stored.status, "open_resolved_on_non_prod")
        self.assertEqual(
            [content.type for content in stored.contents],
            ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
        )

    def test_upload_attempt_during_conflict_keeps_the_resolution_state(self) -> None:
        report_id = self.ready_report(include_finding=True)
        stale_page = self.page
        current_page = self.other_profile_page()
        stale_page.goto(f"{self.base_url}/reports/{report_id}/edit")
        current_page.goto(f"{self.base_url}/reports/{report_id}/edit")

        current_page.locator(".content-block").filter(has_text="Description").locator(".rich").first.fill("Current tab edit")
        current_page.get_by_role("button", name="Save").click()
        current_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        stale_page.locator(".content-block").filter(has_text="Description").locator(".rich").first.fill("Stale tab edit")
        stale_page.get_by_role("button", name="Save").click()
        stale_page.get_by_role("heading", name="Save conflict").wait_for(timeout=5_000)

        image = BytesIO()
        Image.new("RGB", (3, 3), "yellow").save(image, format="PNG")
        upload = stale_page.locator('.evidence-tile input[type="file"]').first
        upload.set_input_files(
            {"name": "conflict.png", "mimeType": "image/png", "buffer": image.getvalue()}
        )
        save_button = stale_page.locator("#save-button")
        self.assertEqual(save_button.get_attribute("data-save-state"), "conflict")
        self.assertEqual(save_button.inner_text(), "Resolve conflict")
        self.assertEqual(upload.evaluate("input => input.files.length"), 0, "the same screenshot cannot be selected again")
        self.assertEqual(len(main.workspace.load(report_id).evidence), 0)

        stale_page.get_by_role("button", name="Save my version").click()
        stale_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].contents[0].fragments[0].runs[0].text, "Stale tab edit")
        current_page.close()

    def test_native_back_refreshes_a_revision_saved_later_in_the_same_tab(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_role("button", name="Next: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)
        page.get_by_role("button", name="Edit finding name").click()
        page.get_by_role("combobox", name="Finding Name").fill("History saved title")
        page.get_by_role("button", name="Save").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        page.go_back(wait_until="domcontentloaded")
        page.wait_for_url("**/setup", timeout=10_000)
        page.wait_for_function(
            "JSON.parse(document.querySelector('main[data-report]').dataset.report).vulnerabilities[0].title === 'History saved title'",
            timeout=5_000,
        )
        page.get_by_label("Application Owner").fill("Saved after native Back")
        page.get_by_role("button", name="Save").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(saved.engagement.app_owner, "Saved after native Back")
        self.assertEqual(saved.vulnerabilities[0].title, "History saved title")

    def test_native_back_refreshes_a_revision_newer_only_by_microseconds(self) -> None:
        class FrozenDateTime(RealDateTime):
            @classmethod
            def now(cls, tz=None):
                value = RealDateTime(2026, 1, 1, 12, 0, 0, 100000)
                return value if tz is None else value.astimezone(tz)

        with patch.object(workspace_module, "datetime", FrozenDateTime):
            report_id = self.ready_report(include_finding=True)
            page = self.page
            page.goto(f"{self.base_url}/reports/{report_id}/setup")
            before = main.workspace.load(report_id).saved_at
            page.get_by_role("button", name="Next: Findings").click()
            page.wait_for_url("**/findings", timeout=10_000)
            page.get_by_role("button", name="Edit finding name").click()
            page.get_by_role("combobox", name="Finding Name").fill("Microsecond-newer title")
            page.get_by_role("button", name="Save").click()
            page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
            after = main.workspace.load(report_id).saved_at
            self.assertGreater(after, before)
            self.assertEqual(after.replace(microsecond=0), before.replace(microsecond=0))
            self.assertEqual(after.microsecond // 1000, before.microsecond // 1000)

            page.go_back(wait_until="domcontentloaded")
            page.wait_for_url("**/setup", timeout=10_000)
            page.wait_for_function(
                "JSON.parse(document.querySelector('main[data-report]').dataset.report).vulnerabilities[0].title === 'Microsecond-newer title'",
                timeout=5_000,
            )

    def test_later_page_save_does_not_erase_an_unresolved_recovery_draft(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_role("button", name="Next: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)
        page.go_back(wait_until="domcontentloaded")
        page.wait_for_url("**/setup", timeout=10_000)

        page.get_by_label("Application Owner").fill("Unsaved setup owner")
        prefix = f"vulnreport-pending:{report_id}:"
        page.wait_for_function(
            "prefix => Object.keys(localStorage).some(key => key.startsWith(prefix))",
            arg=prefix,
        )
        page.once("dialog", lambda dialog: dialog.accept())
        page.go_forward(wait_until="domcontentloaded")
        page.wait_for_url("**/findings", timeout=10_000)
        page.get_by_role("heading", name="Unsaved changes found").wait_for(timeout=5_000)

        page.get_by_role("button", name="Edit finding name").click()
        page.get_by_role("combobox", name="Finding Name").fill("Saved after leaving Setup")
        page.get_by_role("button", name="Save").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        recovered_owners = page.evaluate(
            """prefix => Object.keys(localStorage)
              .filter(key => key.startsWith(prefix))
              .map(key => JSON.parse(localStorage.getItem(key)).report.engagement.app_owner)""",
            prefix,
        )
        self.assertIn("Unsaved setup owner", recovered_owners)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].title, "Saved after leaving Setup")

    def test_stale_local_draft_does_not_replace_newer_backend_report(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        local_report = report.model_dump(mode="json", by_alias=True)
        local_report["engagement"]["app_owner"] = "Older local owner"
        local_key = f"vulnreport-pending:{report_id}:orphan"
        envelope = {
            "schemaVersion": 1,
            "reportId": report_id,
            "tabId": "orphan",
            "baseSavedAt": report.saved_at.isoformat(),
            "capturedAt": report.saved_at.isoformat(),
            "editRevision": 1,
            "report": local_report,
        }

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.evaluate("([key, draft]) => localStorage.setItem(key, JSON.stringify(draft))", [local_key, envelope])
        report.engagement.app_owner = "Newer backend owner"
        main.workspace.save(report)
        page.reload()

        recovery = page.locator("#app-diagnostics")
        recovery.get_by_role("heading", name="Unsaved changes found").wait_for()
        self.assertIn("older saved version", recovery.text_content())
        self.assertEqual(page.get_by_label("Application Owner").input_value(), "Newer backend owner")
        recovery.get_by_role("button", name="Discard", exact=True).click()
        self.assertIsNone(page.evaluate("key => localStorage.getItem(key)", local_key))

    def test_text_undo_redo_and_interrupted_save_recovery(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        owner = page.get_by_label("Application Owner")
        owner.fill("Undo this value")
        page.get_by_role("heading", name="Application").click()
        # Undo sends the change to the server before reloading, so wait for the reloaded value.
        owner_value = '() => document.querySelector(\'[data-path="engagement.app_owner"]\')?.value'
        page.get_by_role("button", name="Undo last change").click()
        page.wait_for_function(f"{owner_value} === ''", timeout=10_000)
        self.assertEqual(page.get_by_label("Application Owner").input_value(), "")
        self.assertEqual(page.url, f"{self.base_url}/reports/{report_id}/setup")
        expect(page.get_by_label("Application Owner")).to_have_class(MARKED)
        expect(page.get_by_label("Application Owner")).not_to_be_focused()
        page.get_by_role("button", name="Redo last change").click()
        page.wait_for_function(f"{owner_value} === 'Undo this value'", timeout=10_000)
        self.assertEqual(page.get_by_label("Application Owner").input_value(), "Undo this value")

        def interrupt_put(route) -> None:
            if route.request.method == "PUT":
                route.abort()
            else:
                route.continue_()

        page.route(f"**/reports/{report_id}", interrupt_put)
        page.get_by_label("Application Owner").fill("Recovered value")
        page.get_by_role("button", name="Save").click()
        page.wait_for_function(
            "prefix => Object.keys(localStorage).some(key => key.startsWith(prefix))",
            arg=f"vulnreport-pending:{report_id}:",
        )
        diagnostic = page.locator("#app-diagnostics")
        diagnostic.get_by_role("heading", name="Operation failed").wait_for()
        self.assertIn("save_report", diagnostic.text_content())
        self.assertIn("Client", diagnostic.text_content())
        self.assertIn("save_report", diagnostic.locator(".diagnostic-code").text_content())
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "failed")
        self.assertEqual(page.locator("#save-button").text_content(), "Save failed - Retry")
        page.reload()
        recovery = page.locator("#app-diagnostics")
        recovery.get_by_role("heading", name="Unsaved changes found").wait_for()
        # Redo persisted before reloading, so the server holds the redone value; only the
        # aborted "Recovered value" edit is still unsaved.
        self.assertEqual(page.get_by_label("Application Owner").input_value(), "Undo this value")
        recovery.get_by_role("button", name="Restore", exact=True).click()
        page.wait_for_load_state()
        self.assertEqual(page.get_by_label("Application Owner").input_value(), "Recovered value")
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "recovered")
        page.unroute(f"**/reports/{report_id}", interrupt_put)

    def test_undo_or_redo_on_findings_of_a_refused_setup_value_opens_setup_and_holds_the_save(self) -> None:
        name_value = '() => document.querySelector(\'[data-path="engagement.app_name"]\')?.value'
        for history_button in ("Undo last change", "Redo last change"):
            with self.subTest(history_button):
                report_id = self.ready_report()
                # A tab of its own, so the last subtest's held edit cannot stop this one loading.
                page = self.context.new_page()
                page.goto(f"{self.base_url}/reports/{report_id}/setup")
                application_name = page.get_by_label("Application Name")
                application_name.fill("Bad/App")
                application_name.blur()
                if history_button == "Undo last change":
                    # A second step fixes the name, so undoing it brings the refused value back.
                    application_name.fill("Fixed App")
                    application_name.blur()
                else:
                    # Undone on Setup, so a Redo brings the refused value back.
                    page.get_by_role("button", name="Undo last change").click()
                    page.wait_for_function(f"{name_value} === 'Browser QA'", timeout=10_000)
                page.get_by_role("button", name="Next: Findings").click()
                page.wait_for_url("**/findings", timeout=10_000)
                saved_name = main.workspace.load(report_id).engagement.app_name

                page.get_by_role("button", name=history_button).click()

                page.wait_for_url(f"**/reports/{report_id}/setup", timeout=10_000)
                application_name = page.get_by_label("Application Name")
                expect(application_name).to_have_value("Bad/App")
                expect(application_name).to_have_class(MARKED)
                self.assertEqual(application_name.evaluate("input => input.validationMessage"), setup_issue("app_name", "Bad/App"))
                expect(page.locator("#save-button")).to_have_text("Correct invalid Setup fields")
                self.assertEqual(main.workspace.load(report_id).engagement.app_name, saved_name)

    def test_undo_on_findings_of_a_refused_additional_information_value_opens_content(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        # Severity Review Tickets shows for every status but Open (New).
        finding.status = "open_previously_discovered"
        main.provision(finding)
        # A refused value already stored, as an import can leave one, so one fix on Content is the step to undo.
        finding.severity_review_tickets = "TKT 1"
        main.workspace.save(report)
        [message] = finding_input_issues(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        tickets = page.get_by_label("Severity Review Tickets")
        tickets.fill("12345")
        tickets.blur()
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].severity_review_tickets, "12345")

        page.get_by_role("button", name="Undo last change").click()

        page.wait_for_url(f"**/reports/{report_id}/edit", timeout=10_000)
        expect(page.locator("#editor-notifications")).to_contain_text(message)
        tickets = page.get_by_label("Severity Review Tickets")
        expect(tickets).to_have_value("TKT 1")
        self.assertEqual(tickets.evaluate("input => input.validationMessage"), message)
        expect(page.locator(f'[data-fragment-id="{finding.uid}:severity_review_tickets"]')).to_have_class(MARKED)
        expect(tickets).to_be_in_viewport()
        expect(tickets).not_to_be_focused()
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].severity_review_tickets, "12345")

    def test_restore_on_findings_of_a_copy_written_on_setup_opens_setup_with_it(self) -> None:
        report_id = self.ready_report()
        page = self.page

        def drop_put(route) -> None:
            if route.request.method == "PUT":
                route.abort()
            else:
                route.continue_()

        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.route(f"**/reports/{report_id}", drop_put)
        page.get_by_label("Application Owner").fill("Unsaved setup owner")
        page.wait_for_function(
            "prefix => Object.keys(localStorage).some(key => key.startsWith(prefix))",
            arg=f"vulnreport-pending:{report_id}:",
        )
        page.once("dialog", lambda dialog: dialog.accept())
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.unroute(f"**/reports/{report_id}", drop_put)

        with page.expect_navigation(url=f"{self.base_url}/reports/{report_id}/setup"):
            page.get_by_role("button", name="Restore on Setup", exact=True).click()

        self.assertEqual(page.get_by_label("Application Owner").input_value(), "Unsaved setup owner")
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "recovered")
        owner = page.get_by_label("Application Owner")
        expect(owner).to_have_class(MARKED)
        expect(owner).to_be_in_viewport()
        expect(owner).not_to_be_focused()
        page.get_by_role("heading", name="Limitations").click()
        expect(owner).not_to_have_class(MARKED)

    def test_undo_of_a_coverage_change_marks_its_box(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        api = page.get_by_label("Test API", exact=True)
        api.check()
        expect(api).to_be_focused()

        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()

        expect(api).not_to_be_checked()
        expect(api).to_have_class(MARKED)

    def test_undo_of_an_added_test_account_lands_on_its_section(self) -> None:
        report_id = self.ready_report()
        page = self.page
        # Short enough that Test Accounts starts below the fold.
        page.set_viewport_size({"width": 1280, "height": 400})
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        accounts = page.locator("#setup > section", has=page.locator("#test-accounts"))
        rows = page.locator("#test-accounts input[aria-label^='User role']")
        added = rows.count() + 1
        page.get_by_role("button", name="Add account").click()
        expect(page.get_by_label(f"User role {added}")).to_be_focused()
        page.evaluate("() => window.scrollTo(0, 0)")
        expect(accounts).not_to_be_in_viewport()

        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()

        expect(rows).to_have_count(added - 1)
        expect(accounts).to_be_in_viewport()

    def test_undo_of_a_setup_button_marks_the_field_it_changed(self) -> None:
        def two_components(report) -> None:
            report.engagement.tested_channels = ["thick_client"]
            report.scope_targets = [
                ScopeTarget(target_id="tgt_main", environment="production", channel="thick_client", value="Acme.exe", description="Main client", order=0),
                ScopeTarget(target_id="tgt_updater", environment="production", channel="thick_client", value="Updater.exe", description="Updater", order=1),
            ]

        def limitation_offer(report) -> None:
            report.engagement.report_type = "retest"
            report.engagement.non_production_label = "UAT"

        # Each button takes the cursor away from the field it changes before the step is recorded.
        cases = [
            ("Remove account", None, lambda page: page.get_by_role("button", name="Remove test account 1"), lambda page: page.get_by_label("User role 1")),
            ("Remove component", two_components, lambda page: page.get_by_role("button", name="Remove Thick Client component 1"), lambda page: page.get_by_role("textbox", name="Thick Client Component", exact=True).first),
            ("Use it", limitation_offer, lambda page: page.locator("#limitations-offer").get_by_role("button", name="Use it"), lambda page: page.get_by_label("Limitations")),
        ]
        for name, prepare, button, field in cases:
            with self.subTest(name):
                report_id = self.ready_report()
                if prepare:
                    report = main.workspace.load(report_id)
                    prepare(report)
                    main.workspace.save(report)
                page = self.context.new_page()
                page.goto(f"{self.base_url}/reports/{report_id}/setup")
                button(page).click()

                with page.expect_navigation():
                    page.get_by_role("button", name="Undo last change").click()

                expect(field(page)).to_have_class(MARKED)

    def _add_zebra_finding(self, report_id: str) -> Vulnerability:
        """A second complete finding, after the seeded one on Findings and on Content."""
        report = main.workspace.load(report_id)
        later = Vulnerability(
            uid="v_later", title="Zebra finding", likelihood="low", impact="low", severity="low",
            status="open_new", scope={"mode": "custom", "target_ids": ["tgt_browser"]},
        )
        main.provision(later)
        report.vulnerabilities.append(later)
        main.sync_evidence_image_slots(later, report)
        main.workspace.save(report)
        return later

    def test_undo_on_content_shows_the_steps_finding_and_marks_its_fragment(self) -> None:
        report_id = self.ready_report(include_finding=True)
        later = self._add_zebra_finding(report_id)
        description = next(content for content in later.contents if content.type == "description").fragments[0]
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        # Content opens on the first finding by severity and title, which is not this one.
        expect(page.locator(".finding-nav.active")).to_contain_text("Browser finding")
        page.locator(".finding-nav", has_text="Zebra finding").click()
        card = page.locator(f'[data-fragment-id="{description.frag_id}"]')
        text = card.get_by_role("textbox")
        text.fill("Undo this description")

        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()

        expect(page.locator(".finding-nav.active")).to_contain_text("Zebra finding")
        expect(text).to_have_text("")
        expect(card).to_have_class(MARKED)
        expect(card).to_be_in_viewport()
        expect(text).not_to_be_focused()
        page.locator(".finding-header").click()
        expect(card).not_to_have_class(MARKED)

    def test_redo_of_a_deleted_fragment_lands_on_its_section(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        # Short enough that Proof of Concept starts below the fold.
        page.set_viewport_size({"width": 1280, "height": 400})
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        proof = page.locator('.content-block[data-content-type="proof_of_concept"]')
        proof.get_by_label("Add fragment to Proof of Concept").select_option("note")
        note = proof.locator("[data-fragment-id]", has=page.locator(".tag", has_text=re.compile(r"^note$")))
        note_id = note.get_attribute("data-fragment-id")
        note.get_by_role("button", name="Delete fragment").click()
        expect(note).to_have_count(0)

        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()

        restored = page.locator(f'[data-fragment-id="{note_id}"]')
        expect(restored).to_have_class(MARKED)
        page.evaluate("() => { window.scrollTo(0, 0); document.querySelector('#finding-editor').scrollTop = 0; }")
        expect(proof).not_to_be_in_viewport()

        with page.expect_navigation():
            page.get_by_role("button", name="Redo last change").click()

        expect(restored).to_have_count(0)
        expect(proof).to_be_in_viewport()

    def test_undo_on_content_of_a_findings_step_unfolds_and_marks_its_field(self) -> None:
        report_id = self.ready_report(include_finding=True)
        self._add_zebra_finding(report_id)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        rows = page.locator("#findings > tr:not(.finding-location-row)")
        locations = page.locator("#findings > tr.finding-location-row")
        # Only the first finding's locations start unfolded.
        expect(locations.nth(1)).to_be_hidden()
        rows.nth(1).locator(".finding-fold-toggle").click()
        value = locations.nth(1).get_by_label("Location value for https://prod.example.test")
        value.fill("https://prod.example.test/zebra")
        page.get_by_role("button", name="Next: Content").click()
        page.wait_for_url("**/edit", timeout=10_000)

        page.get_by_role("button", name="Undo last change").click()

        page.wait_for_url(f"**/reports/{report_id}/findings", timeout=10_000)
        expect(value).to_have_value("https://prod.example.test")
        expect(value).to_have_class(MARKED)
        expect(value).to_be_in_viewport()
        expect(value).not_to_be_focused()
        page.locator(".section-title h1").click()
        expect(value).not_to_have_class(MARKED)

    def test_undo_on_findings_reloads_and_marks_the_field(self) -> None:
        cases = [
            # A select the row keeps, and a location box whose change rebuilds the table before its step is recorded.
            ("Likelihood", lambda row: row.get_by_label("Likelihood"), lambda field: field.select_option("high"), lambda field: expect(field).to_have_value("low")),
            ("location", lambda row: row.locator("xpath=following-sibling::tr[1]").get_by_label("Select https://prod.example.test"), lambda field: field.uncheck(), lambda field: expect(field).to_be_checked()),
            # A Vuln ID shows as a button once typed, so the button carries the mark.
            ("Vuln ID", lambda row: row.get_by_role("button", name="Edit vulnerability ID"), lambda field: (field.click(), field.page.keyboard.type("123")), lambda field: expect(field).to_have_text("\u2014")),
            ("Select all", lambda row: row.locator("xpath=following-sibling::tr[1]").get_by_role("button", name="Select all"), lambda field: field.click(), lambda field: expect(field).to_have_text("Select all")),
        ]
        for name, find, change, undone in cases:
            with self.subTest(name):
                report_id = self.ready_report(include_finding=True)
                report = main.workspace.load(report_id)
                # A second production target, so the locations offer Select all.
                report.scope_targets.append(ScopeTarget(target_id="tgt_second", environment="production", channel="web", value="https://prod2.example.test"))
                main.workspace.save(report)
                page = self.context.new_page()
                page.goto(f"{self.base_url}/reports/{report_id}/findings")
                field = find(page.locator("#findings > tr:not(.finding-location-row)").first)
                # A tester's click focuses the box; select_option alone does not.
                field.focus()
                change(field)

                with page.expect_navigation():
                    page.get_by_role("button", name="Undo last change").click()

                undone(field)
                expect(field).to_have_class(MARKED)
                expect(field).not_to_be_focused()

    def test_undo_of_an_added_finding_lands_on_the_list(self) -> None:
        report_id = self.ready_report(include_finding=True)
        self._add_zebra_finding(report_id)
        page = self.page
        # Short enough that the page scrolls past the list's heading.
        page.set_viewport_size({"width": 1280, "height": 400})
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        rows = page.locator("#findings > tr:not(.finding-location-row)")
        heading = page.locator(".section-title h1")
        page.get_by_role("button", name="Add finding").click()
        expect(rows).to_have_count(3)
        expect(rows.nth(2).locator(".finding-title-cell input")).to_be_focused()
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        expect(heading).not_to_be_in_viewport()

        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()

        expect(rows).to_have_count(2)
        expect(heading).to_be_in_viewport()

    def test_redo_of_a_library_insert_marks_the_select_all_it_focused(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        # A second production target, so the new finding's locations start with Select all.
        report.scope_targets.append(ScopeTarget(target_id="tgt_second", environment="production", channel="web", value="https://prod2.example.test"))
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        rows = page.locator("#findings > tr:not(.finding-location-row)")
        page.get_by_role("combobox", name="Search vulnerability library").fill(main.library.entries[0]["title"])
        page.locator("#library-results [role=option]").first.click()
        expect(rows).to_have_count(2)
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        with page.expect_navigation():
            page.get_by_role("button", name="Undo last change").click()
        expect(rows).to_have_count(1)

        with page.expect_navigation():
            page.get_by_role("button", name="Redo last change").click()

        expect(page.locator("#findings > tr.finding-location-row").nth(1).get_by_role("button", name="Select all")).to_have_class(MARKED)

    def test_keyboard_library_selection_and_fragment_movement(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        search = page.get_by_role("combobox", name="Search vulnerability library")
        search.fill(main.library.entries[0]["title"])
        search.press("ArrowDown")
        self.assertTrue(search.get_attribute("aria-activedescendant"))
        search.press("Enter")
        page.locator("#findings > tr:not(.finding-location-row)").wait_for()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(page.locator("#findings > tr:not(.finding-location-row)").count(), 1)

        report = main.workspace.load(report_id)
        report.vulnerabilities[0].scope = Scope(mode="custom", target_ids=["tgt_browser"])
        report.vulnerabilities[0].likelihood = report.vulnerabilities[0].likelihood or "low"
        report.vulnerabilities[0].impact = report.vulnerabilities[0].impact or "low"
        main.workspace.save(report)
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        description = page.locator(".content-block").filter(has_text="Description")
        cards = description.locator(".fragment")
        initial_count = cards.count()
        description.get_by_role("combobox", name="Add fragment to Description").select_option("note")
        self.assertEqual(cards.count(), initial_count + 1)
        cards.last.get_by_role("button", name="Move fragment up").click()
        self.assertEqual(cards.nth(initial_count - 1).locator(".tag").text_content(), "note")

    def test_library_search_highlights_the_first_result_and_enter_adds_it(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        search = page.get_by_role("combobox", name="Search vulnerability library")
        search.fill("xss")
        options = page.locator("#library-results [role=option]")
        expect(options.nth(1)).to_be_attached()
        expect(options.first).to_have_attribute("aria-selected", "true")
        expect(page.locator('#library-results [aria-selected="true"]')).to_have_count(1)
        first_title = options.first.locator("b").inner_text()

        search.press("Enter")
        page.locator("#findings > tr:not(.finding-location-row)").wait_for()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual([finding.title for finding in main.workspace.load(report_id).vulnerabilities], [first_title])

    def test_a_finding_name_box_highlights_the_first_library_result_and_enter_applies_it(self) -> None:
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_role("button", name="Add finding").click()
        title = page.locator(".finding-title-cell input").first
        title.fill("xss")
        options = page.locator('.row-library-results [role="option"]')
        expect(options.nth(1)).to_be_attached()
        expect(options.first).to_have_attribute("aria-selected", "true")
        expect(page.locator('.row-library-results [aria-selected="true"]')).to_have_count(1)
        first_title = options.first.locator("b").inner_text()

        title.press("Enter")
        expect(page.locator(".finding-title-cell input").first).to_have_value(first_title)

    def test_editor_library_selection_commits_the_full_option_title(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, _ = self._complete_finding(report_id)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".edit-title").click()
        editor = page.locator(".editor-title-search input")
        editor.fill("Session Token Remains")
        option = page.locator('.editor-title-search [role="option"]').first
        expected_title = option.locator("b").inner_text()
        option.click()
        page.wait_for_selector(".finding-title .edit-title")
        self.assertEqual(page.locator(".finding-title .edit-title").inner_text(), expected_title)
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].title, expected_title)

    def test_typing_a_vuln_id_updates_in_place_without_rebuilding_the_table(self) -> None:
        """Blurring the ID cell used to rebuild the whole table, taking the fold state with it."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        expanded = page.locator("#findings > tr.finding-expanded")
        expanded.wait_for()
        # Driven directly because the fold toggle's actionability check does not settle headless.
        page.evaluate("() => document.querySelector('.finding-fold-toggle').click()")
        self.assertEqual(expanded.count(), 0)

        row = page.evaluate_handle("() => document.querySelector('#findings > tr')")
        display = page.locator("#findings .finding-id-display")
        display.click()
        vuln_id = page.locator("#findings input[inputmode='numeric']")
        vuln_id.fill("1234")
        vuln_id.blur()
        self.assertTrue(row.evaluate("node => node.isConnected"), "the table was rebuilt while the ID was being edited")
        self.assertEqual(expanded.count(), 0, "the collapsed finding re-opened when the ID was typed")
        self.assertEqual(display.text_content(), "1234")

    def test_an_empty_vuln_id_cell_offers_a_dash_and_swaps_for_the_field(self) -> None:
        """Run narrow: below 960px the field is no longer lifted out of flow, so [hidden] has to really hide."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.set_viewport_size({"width": 800, "height": 900})
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        display = page.locator("#findings .finding-id-display")
        field = page.locator("#findings input[inputmode='numeric']")
        display.wait_for()
        self.assertEqual(display.text_content(), "\u2014")
        self.assertFalse(field.is_visible(), "the field sits under the button when both are shown")
        display.click()
        self.assertFalse(display.is_visible(), "the button stayed on top of the field being edited")
        self.assertTrue(field.is_visible())
        self.assertTrue(field.evaluate("node => node === document.activeElement"))

    def test_a_long_affected_location_wraps_instead_of_running_past_its_column(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        long_value = "https://prod.example.test/" + "a" * 120
        report.scope_targets[0].value = long_value
        report.scope_targets.append(ScopeTarget(target_id="tgt_long", environment="production", channel="web", value=f"{long_value}/other"))
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        selected = page.locator("#findings textarea.location-value")
        selected.wait_for()
        self.assertLessEqual(selected.evaluate("node => node.scrollWidth - node.clientWidth"), 1, "the selected location ran past its column")
        self.assertGreater(selected.evaluate("node => node.clientHeight"), 28, "the selected location did not grow to fit")
        unselected = page.locator("#findings .location-preview")
        self.assertLessEqual(unselected.evaluate("node => node.scrollWidth - node.clientWidth"), 1, "the unselected location ran past its column")

    def test_previous_saves_before_library_replacement_and_next_navigation(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image_data = png_bytes(2, 2)
        evidence_id = "ev_previous_navigation"
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data).hexdigest(), uploaded_at=report.saved_at)
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data)
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        description = page.locator(".content-block").filter(has_text="Description")
        description.locator(".rich").first.fill("Pending content edit")

        def interrupt_put(route) -> None:
            if route.request.method == "PUT":
                route.abort()
            else:
                route.continue_()

        page.route(f"**/reports/{report_id}", interrupt_put)
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_selector('#save-button[data-save-state="failed"]', timeout=5_000)
        self.assertTrue(page.url.endswith(f"/reports/{report_id}/edit"))
        page.unroute(f"**/reports/{report_id}", interrupt_put)

        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url(f"**/reports/{report_id}/findings")
        persisted = main.workspace.load(report_id)
        description = next(content for content in persisted.vulnerabilities[0].contents if content.type == "description")
        self.assertEqual(description.fragments[0].runs[0].text, "Pending content edit")

        page.get_by_role("button", name="Edit finding name").click()
        title = page.locator(".finding-title-cell input")
        replacement = "Missing/Misconfigured Security Header: Content-Security-Policy (CSP)"
        title.fill(replacement)
        page.locator('.row-library-results [role="option"]').filter(has_text=replacement).click()
        page.get_by_role("button", name="Next: Content", exact=False).click()
        page.wait_for_url(f"**/reports/{report_id}/edit")
        self.assertEqual(page.get_by_role("heading", name=replacement).text_content(), replacement)

    def test_a_note_in_the_additional_locations_box_does_not_open_the_content_page(self) -> None:
        """A finding complete in every other way must still be held at Findings until it has a real
        affected location, and a typed endpoint is a real one."""
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.get_by_role("button", name="Add finding").click()
        row = page.locator("#findings tr").first
        row.locator(".finding-title-cell input").fill("Located by typing")
        for select, value in zip(row.locator("select").all(), ["low", "low", "low"]):
            select.select_option(value)

        endpoints = page.locator("[data-custom-location]").first
        endpoints.fill("# ask the app owner which host")
        page.locator("#next").click()
        page.wait_for_selector('#findings[data-validation-attempted="true"]', timeout=5_000)
        self.assertTrue(page.url.endswith("/findings"), "a note is not an affected location")

        endpoints.fill("# ask the app owner which host\nhttps://typed.example.test/admin")
        page.locator("#next").click()
        page.wait_for_url("**/edit", timeout=10_000)
        stored = read_json(main.workspace.find_path(report_id))["vulnerabilities"][0]
        self.assertEqual(
            stored["scope"]["custom_locations"]["production"]["web"],
            ["# ask the app owner which host", "https://typed.example.test/admin"],
            "the note is kept alongside the location it stands next to",
        )

    def test_findings_gate_blocks_next_but_back_is_never_refused(self) -> None:
        """Completeness is a forward requirement. Editing the application details is not something a
        tester should have to finish a finding to reach."""
        findings_report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{findings_report_id}/findings")
        page.get_by_role("button", name="Add finding").click()

        previous = page.get_by_role("button", name="Previous: Setup")
        self.assertIsNone(previous.get_attribute("href"))
        previous.click(button="middle")
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))
        # Both Back controls share one handler, so the stepper only has to still be wired.
        self.assertEqual(page.locator("nav.stepper .back-link").count(), 1)

        # The forward gate is what refuses, and what reveals the incomplete fields.
        page.get_by_role("button", name="Next: Content", exact=False).click()
        page.locator("#finding-validation-note").wait_for(state="visible", timeout=5_000)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))

        previous.click()
        page.wait_for_url(f"**/reports/{findings_report_id}/setup")
        # Corroborating only: the blank finding reached disk. The flush guarantee itself is pinned by
        # test_previous_saves_before_library_replacement_and_next_navigation.
        self.assertEqual(len(read_json(main.workspace.find_path(findings_report_id))["vulnerabilities"]), 1)

        content_report_id = self.ready_report(include_finding=True)
        page.goto(f"{self.base_url}/reports/{content_report_id}/edit")
        self.assertEqual(page.locator("#issue-count").get_attribute("data-state"), "issues")
        # Going back from Content is never gated: the tester is on their way to fix the gaps.
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url(f"**/reports/{content_report_id}/findings")

    def test_a_report_with_no_findings_can_still_reach_setup(self) -> None:
        """The literal complaint: a brand-new report has nothing to fix and no field to highlight, so
        refusing to let it back to Setup left the tester with no way forward or back."""
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#next")
        self.assertEqual(page.locator("#findings tr").count(), 0)

        page.get_by_role("button", name="Previous: Setup").click()
        page.wait_for_url(f"**/reports/{report_id}/setup")

    def test_content_with_no_findings_says_what_will_print_and_offers_no_add_button(self) -> None:
        """Findings are added on the Findings page only. Content kept an add button for this state
        while the server never let a report reach it."""
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#finding-summary b")
        page.get_by_role("button", name="Next: Content").click()
        page.wait_for_url(f"**/reports/{report_id}/edit")

        pane = page.locator("#finding-editor")
        expect(pane.get_by_role("heading", name="No findings")).to_be_visible()
        expect(pane).to_contain_text(NO_FINDINGS_TITLE)
        self.assertEqual(pane.get_by_role("button").count(), 0)
        expect(page.locator("#editor-notifications")).to_have_text("No findings to complete. The report is ready to generate.")

    def test_generating_a_report_with_no_findings_asks_first(self) -> None:
        """A report with no findings tells the reader nothing was found, so it is generated only once
        the tester says so, and the request carries that answer for the server to check."""
        word = patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents)
        word.start()
        self.addCleanup(word.stop)
        report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        generate = page.get_by_role("button", name="Generate Report")
        expect(generate).to_be_enabled()
        generate_requests = []
        page.on("request", lambda request: "/generate" in request.url and generate_requests.append(request.url))

        generate.click()
        dialog = page.locator(".vr-dialog")
        expect(dialog.get_by_role("heading")).to_have_text("This report has no findings")
        expect(dialog.locator("p")).to_have_text("Generate a report with no findings?")
        expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
        # A second Enter lands on Cancel, so it cannot generate the report.
        page.keyboard.press("Enter")
        expect(dialog).to_have_count(0)

        generate.click()
        with page.expect_response(lambda response: "/generate" in response.url) as generated:
            dialog.get_by_role("button", name="Generate with no findings").click()
        self.assertEqual(generated.value.status, 200)
        # Exactly one request, so Cancel sent nothing.
        self.assertEqual(generate_requests, [f"{self.base_url}/reports/{report_id}/generate?confirm_no_findings=true"])
        page.get_by_role("dialog", name="Your Word report is ready").wait_for()
        rendered = Document(generated.value.json()["path"])
        summary = next(table for table in rendered.tables if table.cell(0, 0).text == "Findings")
        self.assertEqual(summary.rows[1].cells[0].text, NO_FINDINGS_TITLE)

    def test_a_bounce_from_content_names_the_missing_fields(self) -> None:
        """The bounce used to show one fixed sentence that never updated. It now reveals the same
        per-finding count the Next button does, so the tester can see what is actually missing."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.vulnerabilities[0].severity = None
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_url(f"**/reports/{report_id}/findings?incomplete=findings")
        note = page.locator("#finding-validation-note")
        note.wait_for()
        self.assertIn("severity", note.inner_text().lower())
        self.assertNotIn("Complete every finding before continuing to Content", note.inner_text())

    def test_matching_a_library_title_applies_metadata_without_a_confirm(self) -> None:
        """Title, likelihood, impact, severity, and library_ref apply immediately and silently on a
        title match; there is no whole-finding confirm dialog, and content is left untouched."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        title = "Session Token Remains Valid after Session Expiry Message"
        page.get_by_role("button", name="Edit finding name").click()
        page.locator(".finding-title-cell input").fill(title)
        page.locator('.row-library-results [role="option"]').filter(has_text=title).click()
        self.assertEqual(page.locator("[data-dialog-action]").count(), 0, "no confirm dialog appears")
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        finding = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(finding.title, title)
        self.assertEqual(finding.library_ref.library_id, "VDB-047")
        description = next(content for content in finding.contents if content.type == "description")
        self.assertEqual([fragment.type for fragment in description.fragments], ["paragraph"], "content is untouched by the title match")

    def test_library_remediation_offers_add_no_empty_starter_paragraph(self) -> None:
        """Whichever offer the tester takes, the section ends up holding only the library's own
        fragments: no stray empty paragraph appended, and no blank starter left above them."""
        title = "Session Token Remains Valid after Session Expiry Message"
        for button in ("Fill from library", "Add below"):
            with self.subTest(button=button):
                report_id = self.ready_report(include_finding=True)
                page = self.page
                # A title match only applies metadata now; content offers live on the Content page.
                page.goto(f"{self.base_url}/reports/{report_id}/findings")
                page.get_by_role("button", name="Edit finding name").click()
                page.get_by_role("combobox", name="Finding Name").fill(title)
                page.locator('.row-library-results [role="option"]').filter(has_text=title).click()
                page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

                # VDB-047 carries no default ratings, so restore them before Content so /edit doesn't
                # redirect on an incomplete finding; the offer under test is unrelated to this rating.
                report = main.workspace.load(report_id)
                finding = report.vulnerabilities[0]
                finding.likelihood = finding.impact = finding.severity = "low"
                main.workspace.save(report)

                page.goto(f"{self.base_url}/reports/{report_id}/edit")
                page.locator(".content-block").filter(has_text="Recommended Remediation").get_by_role("button", name=button).click()
                # The autosave is debounced, so wait for it to leave and re-enter "saved" before asserting.
                page.wait_for_selector('#save-button:not([data-save-state="saved"])', timeout=5_000)
                page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

                remediation = next(
                    content for content in main.workspace.load(report_id).vulnerabilities[0].contents
                    if content.type == "recommended_remediation"
                )
                self.assertEqual([fragment.type for fragment in remediation.fragments], ["bulleted_list", "note"])

    def test_adding_library_content_below_retains_unfinished_fragments(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        entry = main.library.get("VDB-047")
        finding.library_ref = LibraryRef(library_id=entry["library_id"], source_id=entry["source_id"], inserted_at=report.saved_at)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        remediation.fragments[0].runs = [Run(text="Keep this tester remediation")]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        remediation_block = page.locator(".content-block").filter(has_text="Recommended Remediation")
        remediation_block.get_by_role("combobox", name="Add fragment to Recommended Remediation").select_option("table")
        remediation_block = page.locator(".content-block").filter(has_text="Recommended Remediation")
        remediation_block.get_by_role("button", name="Add below").click()
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)

        remediation = next(
            content
            for content in main.workspace.load(report_id).vulnerabilities[0].contents
            if content.type == "recommended_remediation"
        )
        self.assertEqual(
            [fragment.type for fragment in remediation.fragments],
            ["paragraph", "table", "bulleted_list", "note"],
        )

    def test_replacing_library_content_drops_only_its_orphaned_evidence(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        entry = main.library.get("VDB-047")
        finding.library_ref = LibraryRef(library_id=entry["library_id"], source_id=entry["source_id"], inserted_at=report.saved_at)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        remediation.fragments[0].runs = [Run(text="Tester remediation")]
        remediation.fragments.append(ImageFragment(frag_id="f_replace_image", type="image", evidence_id="ev_replace", caption="Remove with section"))
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof_image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        proof_image.evidence_id = "ev_keep"
        proof_image.caption = "Keep outside section"

        image = BytesIO()
        Image.new("RGB", (3, 3), "blue").save(image, format="PNG")
        payload = image.getvalue()
        for evidence_id in ("ev_replace", "ev_keep"):
            report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name=f"{evidence_id}.png", width_px=3, height_px=3, sha256=hashlib.sha256(payload).hexdigest(), uploaded_at=report.saved_at)
        evidence_root = main.workspace.find_path(report_id).parent / "evidence"
        evidence_root.mkdir(exist_ok=True)
        for evidence_id in report.evidence:
            (evidence_root / f"{evidence_id}.png").write_bytes(payload)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        remediation_block = page.locator(".content-block").filter(has_text="Recommended Remediation")
        remediation_block.get_by_role("button", name="Use library version").click()
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)

        saved = main.workspace.load(report_id)
        self.assertEqual(set(saved.evidence), {"ev_keep"})
        self.assertFalse((evidence_root / "ev_replace.png").exists())
        self.assertTrue((evidence_root / "ev_keep.png").exists())

    def test_readiness_flags_placeholder_and_whitespace_content(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        description = next(content for content in report.vulnerabilities[0].contents if content.type == "description")
        description.fragments[0].runs = [Run(text="(insert version here)")]
        remediation = next(content for content in report.vulnerabilities[0].contents if content.type == "recommended_remediation")
        remediation.fragments[0].runs = [Run(text="   ")]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.assertTrue(page.get_by_text("replace placeholder text", exact=False).is_visible())
        self.assertTrue(page.get_by_text("text is required", exact=False).first.is_visible())

    def test_in_conclusion_opens_empty_and_offers_the_standard_sentence(self) -> None:
        """The section is created but never written for you: an empty paragraph plus an offer, so the
        tester owes a real conclusion rather than inheriting one the app made up."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.vulnerabilities[0].status = "open_previously_discovered"
        main.provision(report.vulnerabilities[0])
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        conclusion = page.locator(".content-block").filter(has_text="In Conclusion")
        self.assertEqual(conclusion.locator(".fragment").count(), 1)
        self.assertEqual(conclusion.locator(".rich").first.text_content(), "")
        self.assertEqual(conclusion.locator("[data-conclusion-restore]").count(), 1, "an empty conclusion was not offered the standard sentence")

        conclusion.get_by_role("button", name="Put it back").click()
        expect(conclusion.locator(".rich").first).to_have_text('The finding "Browser finding" is still Open.')
        self.assertEqual(conclusion.locator(".fragment").count(), 1, "accepting the offer added a fragment")

        conclusion.locator(".rich").first.fill("Testing confirmed that compensating controls reduce the exposure. The issue remains open pending remediation.")
        conclusion.get_by_role("combobox", name="Add fragment to In Conclusion").select_option("note")
        conclusion.locator(".fragment").last.locator(".rich").fill("Monitor the control until permanent remediation is complete.")

        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        page.reload()
        conclusion = page.locator(".content-block").filter(has_text="In Conclusion")
        self.assertEqual(conclusion.locator(".rich").first.text_content(), "Testing confirmed that compensating controls reduce the exposure. The issue remains open pending remediation.")
        self.assertEqual(conclusion.locator(".rich").nth(1).text_content(), "Monitor the control until permanent remediation is complete.")

    def test_all_fragment_types_render_and_persist(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")

        for fragment_type in ("numbered_list", "bulleted_list", "table", "note", "code_block", "image"):
            page.get_by_role("combobox", name="Add fragment to Description").select_option(fragment_type)
        page.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("instance_title")
        self.assertEqual(page.locator(".table-fragment").count(), 1)
        self.assertGreaterEqual(page.locator(".fragment .rich").count(), 3)
        self.assertGreaterEqual(page.locator(".list-textarea").count(), 2)
        self.assertGreaterEqual(page.locator(".fragment textarea.instance-title-input").count(), 1)
        self.assertGreaterEqual(page.locator(".evidence-tile").count(), 2)

        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        persisted = main.workspace.load(report_id)
        fragment_types = {fragment.type for content in persisted.vulnerabilities[0].contents for fragment in content.fragments}
        self.assertTrue({"paragraph", "numbered_list", "bulleted_list", "table", "note", "code_block", "image", "instance_title"} <= fragment_types)

    def test_text_formatting_toolbar_is_beside_fragment_title(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        fragment = page.locator(".fragment").filter(has=page.locator(".toolbar")).first
        header = fragment.locator(".fragment-head")

        self.assertEqual(
            header.evaluate("head => [...head.children].map(child => child.className || child.tagName)"),
            ["fragment-drag-handle", "tag", "toolbar", "fragment-convert", "fragment-move-up", "fragment-move-down", "danger fragment-delete"],
        )
        self.assertEqual(header.locator(".toolbar").get_by_role("button").count(), 3)
        self.assertEqual(
            header.locator(".toolbar").get_by_role("button").evaluate_all("buttons => buttons.map(button => button.title)"),
            ["Bold", "Italic", "Underline"],
        )

    def _setup_page(self, report_id: str):
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}")
        page.wait_for_selector(".limitations-field")
        return page

    def _saved_engagement(self, report_id: str):
        return main.workspace.load(report_id).engagement

    def test_the_non_production_name_offers_presets_and_a_typed_option(self) -> None:
        """The typed branch has no closed set behind it, so the browser message is the only thing
        standing between a typo and a 422. It must read exactly as the server's does."""
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        main.workspace.save(report)

        page = self._setup_page(report_id)
        picker = page.locator(".coverage-name")
        self.assertEqual(picker.locator("option").all_text_contents(), ["NON-PROD", "MOD", "UAT", "STAGE", "OTHERS"])
        self.assertEqual(picker.input_value(), "NON-PROD")
        self.assertEqual(page.locator(".coverage-name-custom").count(), 0)

        picker.select_option("OTHERS")
        typed = page.locator(".coverage-name-custom")
        typed.wait_for()
        typed.fill("MY@LAB")
        self.assertEqual(
            typed.evaluate("input => input.validationMessage"),
            setup_issue("non_production_label", "MY@LAB"),
        )
        self.assertIsNone(typed.get_attribute("aria-describedby"))
        typed.evaluate("input => input.blur()")
        described_by = typed.get_attribute("aria-describedby")
        self.assertTrue(described_by)
        message = page.locator(f"#{described_by}")
        expect(message).to_have_text(setup_issue("non_production_label", "MY@LAB"))
        self.assertIsNone(message.evaluate("element => element.closest('label')"))
        self.assertTrue(message.evaluate("element => element.parentElement.classList.contains('setup-field-wrap')"))
        typed.fill("MY@LAB2")
        expect(message).to_have_text(setup_issue("non_production_label", "MY@LAB2"))
        typed.fill("MY LAB/2")
        expect(message).to_be_hidden()
        self.assertIsNone(typed.get_attribute("aria-describedby"))
        self.assertEqual(typed.evaluate("input => input.validationMessage"), "")
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(self._saved_engagement(report_id).non_production_label, "MY LAB/2")

        page.locator(".coverage-name").select_option("STAGE")
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(self._saved_engagement(report_id).non_production_label, "STAGE")

    def test_opening_setup_never_rewrites_a_label_that_is_not_a_preset(self) -> None:
        """A retired or imported label must not be silently replaced by whatever the dropdown
        happens to show first. The assertion is on the stored value, not the control."""
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.non_production_label = "TEST/MO"
        main.workspace.save(report)

        page = self._setup_page(report_id)
        self.assertEqual(page.locator(".coverage-name").input_value(), "OTHERS")
        self.assertEqual(page.locator(".coverage-name-custom").input_value(), "TEST/MO")
        # A rewrite on open would mark the page unsaved at once, and autosave it moments later.
        self.assertNotEqual(page.locator("#save-button").get_attribute("data-save-state"), "unsaved", "opening Setup changed the report")
        self.assertEqual(self._saved_engagement(report_id).non_production_label, "TEST/MO")

    def _retest_setup(self, report_id: str, environments: list[str], label: str = "NON-PROD"):
        report = main.workspace.load(report_id)
        report.engagement.report_type = "retest"
        report.engagement.tested_environments = environments
        report.engagement.non_production_label = label
        report.engagement.limitations = "N/A"
        main.workspace.save(report)
        return self._setup_page(report_id)

    def test_a_single_environment_retest_offers_a_limitation_naming_the_chosen_label(self) -> None:
        report_id = self.ready_report()
        page = self._retest_setup(report_id, ["production"], "UAT")
        offer = page.locator("#limitations-offer")
        offer.wait_for()
        self.assertIn("Retest only in PROD; no UAT testing.", offer.inner_text())

        offer.get_by_role("button", name="Use it").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        # The model, not just the textarea: assigning .value fires no event, so the [data-path]
        # handler would never see it and the sentence would never reach the draft.
        self.assertEqual(self._saved_engagement(report_id).limitations, "Retest only in PROD; no UAT testing.")
        self.assertEqual(page.get_by_label("Limitations").input_value(), "Retest only in PROD; no UAT testing.")
        self.assertEqual(page.get_by_label("Limitations").evaluate("input => input.validationMessage"), "")
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

    def test_the_limitation_offer_names_prod_second_when_only_non_production_was_tested(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.scope_targets = [ScopeTarget(target_id="tgt_np", environment="non_production", channel="web", value="https://uat.example.test")]
        main.workspace.save(report)
        page = self._retest_setup(report_id, ["non_production"], "STAGE")
        offer = page.locator("#limitations-offer")
        offer.wait_for()
        self.assertIn("Retest only in STAGE; no PROD testing.", offer.inner_text())

    def test_the_limitation_offer_stays_away_once_limitations_say_something(self) -> None:
        """Only offered while the field still holds the app's own default, so it cannot nag over
        wording the tester has already chosen."""
        report_id = self.ready_report()
        page = self._retest_setup(report_id, ["production"])
        page.locator("#limitations-offer").wait_for()

        report = main.workspace.load(report_id)
        report.engagement.limitations = "Tester wrote this."
        main.workspace.save(report)
        # The banner is drawn while the page loads, and goto waits for load, so its state is final here.
        page = self._setup_page(report_id)
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

    def test_a_dismissed_limitation_offer_does_not_come_back_while_the_page_is_open(self) -> None:
        page = self._retest_setup(self.ready_report(), ["production"])
        page.locator("#limitations-offer").wait_for()
        page.locator("#limitations-offer").get_by_role("button", name="Dismiss").click()
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

        page.get_by_label("Limitations").click()
        page.get_by_label("Limitations").blur()
        self._next_report_change(lambda: page.get_by_label("Application Owner").fill("Somebody else"))
        self.assertEqual(page.locator("#limitations-offer").count(), 0, "a dismissed offer returned on the next report change")

    def test_the_offer_follows_the_label_when_it_changes(self) -> None:
        """The sentence is derived at paint time, not captured when the page loaded: a tester who
        renames the environment after seeing the offer must be offered the new wording."""
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        main.workspace.save(report)
        page = self._retest_setup(report_id, ["production"], "UAT")
        page.locator("#limitations-offer").wait_for()
        self.assertIn("no UAT testing.", page.locator("#limitations-offer").inner_text())

        report = main.workspace.load(report_id)
        report.engagement.non_production_label = "STAGE"
        main.workspace.save(report)
        page = self._setup_page(report_id)
        page.locator("#limitations-offer").wait_for()
        self.assertIn("no STAGE testing.", page.locator("#limitations-offer").inner_text())

    def _non_production_retest(self, label: str = "UAT"):
        """Non-production only: the name control is disabled unless that environment is covered, so
        this is the one single-environment retest where a rename is reachable at all."""
        report_id = self.ready_report()
        report = main.workspace.load(report_id)
        report.scope_targets = [ScopeTarget(target_id="tgt_np", environment="non_production", channel="web", value="https://uat.example.test")]
        main.workspace.save(report)
        return report_id, self._retest_setup(report_id, ["non_production"], label)

    def test_renaming_the_environment_offers_to_update_the_limitation_without_a_reload(self) -> None:
        """The whole point is that it reacts to the rename in place. A test that reloads would pass
        against a version that only ever recomputed on boot."""
        report_id, page = self._non_production_retest("UAT")
        offer = page.locator("#limitations-offer")
        offer.wait_for()
        offer.get_by_role("button", name="Use it").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(page.get_by_label("Limitations").input_value(), "Retest only in UAT; no PROD testing.")

        # Same page, no reload: the rename alone must bring the offer back.
        page.locator(".coverage-name").select_option("STAGE")
        offer = page.locator("#limitations-offer")
        offer.wait_for(timeout=5_000)
        self.assertIn('It would now read "Retest only in STAGE; no PROD testing."', offer.inner_text())

        offer.get_by_role("button", name="Update it").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(self._saved_engagement(report_id).limitations, "Retest only in STAGE; no PROD testing.")
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

    def test_a_typed_environment_name_updates_the_offer_while_it_is_being_typed(self) -> None:
        """The redraw guard must be narrow enough to let this through: only the Limitations textarea
        blocks a repaint, because only it sits under the banner."""
        _report_id, page = self._non_production_retest("UAT")
        page.locator("#limitations-offer").wait_for()

        page.locator(".coverage-name").select_option("OTHERS")
        typed = page.locator(".coverage-name-custom")
        typed.wait_for()
        typed.fill("PREPROD")
        # Waits on the banner's own state rather than its presence: the stale banner is still on
        # screen, so a presence check would return the old wording immediately.
        page.wait_for_selector('#limitations-offer[data-offer-state*="PREPROD"]', timeout=5_000)
        self.assertIn("Retest only in PREPROD; no PROD testing.", page.locator("#limitations-offer").inner_text())
        self.assertEqual(typed.evaluate("input => document.activeElement === input"), True, "the repaint stole focus from the name being typed")

    def test_the_update_offer_leaves_wording_the_tester_composed_alone(self) -> None:
        """Recognising only the sentence this app generates is what stops a rename rewriting prose
        the tester wrote themselves. The offer is live here -- it simply must not fire."""
        report_id, page = self._non_production_retest("UAT")
        page.locator("#limitations-offer").wait_for()
        prose = "Retested UAT only, production was out of scope this cycle."
        self._next_report_change(lambda: (page.get_by_label("Limitations").fill(prose), page.get_by_label("Limitations").blur()))
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

        self._next_report_change(lambda: page.locator(".coverage-name").select_option("STAGE"))
        self.assertEqual(page.locator("#limitations-offer").count(), 0, "a rename offered to rewrite the tester's own wording")
        self.assertEqual(page.get_by_label("Limitations").input_value(), prose)

    def _convert_report(self):
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        description = next(content for content in finding.contents if content.type == "description")
        description.fragments = [
            ParagraphFragment(frag_id="f_plain", type="paragraph", runs=[Run(text="A plain paragraph.")]),
            ParagraphFragment(frag_id="f_bold", type="paragraph", runs=[Run(text="Mind the "), Run(text="gap", bold=True)]),
            CodeFragment(frag_id="f_capped", type="code_block", caption="Request", text="GET /accounts/123"),
            CodeFragment(frag_id="f_bare", type="code_block", caption=None, text="GET /health"),
        ]
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        return report_id, page

    def _stored_fragment(self, report_id: str, frag_id: str) -> dict:
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        return next(
            fragment for finding in report["vulnerabilities"]
            for content in finding["contents"] for fragment in content["fragments"]
            if fragment["frag_id"] == frag_id
        )

    def test_converting_a_paragraph_to_a_code_block_swaps_the_editor_and_the_payload(self) -> None:
        """The editor body is chosen by which payload key is present, not by type. Without a re-render
        the old rich field stays on screen and writes `runs` straight back onto a code block, and
        everything typed into it is deleted when the save response reconciles."""
        report_id, page = self._convert_report()
        card = page.locator('[data-fragment-id="f_plain"]')
        self.assertEqual(card.locator(".rich").count(), 1)

        card.locator(".fragment-convert").select_option("code_block")
        page.wait_for_selector('[data-fragment-id="f_plain"] .code-block', timeout=5_000)
        card = page.locator('[data-fragment-id="f_plain"]')
        self.assertEqual(card.locator(".rich").count(), 0, "the rich editor survived the conversion")

        card.locator(".code-block").fill("A plain paragraph. Typed after.")
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        stored = self._stored_fragment(report_id, "f_plain")
        self.assertEqual(stored["type"], "code_block")
        self.assertEqual(stored["text"], "A plain paragraph. Typed after.")
        self.assertNotIn("runs", stored, "the source key outlived the conversion")

    def test_the_convert_control_appears_only_where_a_type_change_is_possible(self) -> None:
        report_id, page = self._convert_report()
        for frag_id in ("f_plain", "f_capped"):
            self.assertEqual(page.locator(f'[data-fragment-id="{frag_id}"] .fragment-convert').count(), 1, frag_id)

        proof = page.locator('.content-block[data-content-type="proof_of_concept"]')
        self.assertEqual(proof.locator(".fragment:has(.list-text-editor) .fragment-convert").count(), 0,
                         "a numbered list was offered a type change")
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertEqual(conclusion.locator(".fragment-convert").count(), 0,
                         "In Conclusion was offered a type change, which provision would undo")

        # The Add menu offers no paragraph in a proof of concept, but converting to one there is
        # deliberate: reusing that list would let a note convert out to a code block and never back.
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(c for c in finding.contents if c.type == "proof_of_concept").fragments.append(
            NoteFragment(frag_id="f_poc_note", type="note", runs=[Run(text="A note.")])
        )
        main.workspace.save(report)
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        options = page.locator('[data-fragment-id="f_poc_note"] .fragment-convert option')
        self.assertEqual(options.all_text_contents(), ["change to…", "paragraph", "code block"])

    def test_converting_a_captioned_code_block_warns_before_deleting_the_caption(self) -> None:
        """The caption has no editor field anywhere, so it arrived from an imported document and
        prints unseen. This dialog is the only place the tester ever reads it."""
        report_id, page = self._convert_report()
        page.locator('[data-fragment-id="f_capped"] .fragment-convert').select_option("paragraph")
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn('"Request"', dialog.inner_text(), "the dialog did not quote the caption it is about to delete")

        page.click('[data-dialog-action="cancel"]')
        page.wait_for_selector(".vr-dialog", state="detached")
        # Declining writes nothing, so the Save button stays disabled and disk still holds the fixture.
        self.assertEqual(page.locator('[data-fragment-id="f_capped"] .code-block').count(), 1)
        stored = self._stored_fragment(report_id, "f_capped")
        self.assertEqual((stored["type"], stored["caption"]), ("code_block", "Request"), "declining still changed the fragment")

        page.locator('[data-fragment-id="f_capped"] .fragment-convert').select_option("paragraph")
        page.wait_for_selector(".vr-dialog", timeout=5_000)
        page.click('[data-dialog-action="confirm"]')
        page.wait_for_selector('[data-fragment-id="f_capped"] .rich', timeout=5_000)
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        stored = self._stored_fragment(report_id, "f_capped")
        self.assertEqual(stored["type"], "paragraph")
        self.assertEqual([run["text"] for run in stored["runs"]], ["GET /accounts/123"])
        self.assertNotIn("caption", stored)
        self.assertNotIn("text", stored)

    def test_a_lossless_conversion_asks_nothing(self) -> None:
        """A dialog on a conversion that loses nothing is what trains a tester to click through the
        one that matters."""
        report_id, page = self._convert_report()
        page.locator('[data-fragment-id="f_bare"] .fragment-convert').select_option("note")
        page.wait_for_selector('[data-fragment-id="f_bare"] .rich', timeout=5_000)
        self.assertEqual(page.locator(".vr-dialog").count(), 0, "a caption-free code block asked before converting")

        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        stored = self._stored_fragment(report_id, "f_bare")
        self.assertEqual(stored["type"], "note")
        self.assertEqual(stored["runs"], [{"text": "GET /health", "bold": False, "italic": False, "underline": False}])
        self.assertNotIn("text", stored)
        self.assertNotIn("caption", stored)

    def test_dropping_run_formatting_into_a_code_block_is_confirmed_first(self) -> None:
        _report_id, page = self._convert_report()
        page.locator('[data-fragment-id="f_bold"] .fragment-convert').select_option("code_block")
        dialog = page.locator(".vr-dialog")
        dialog.wait_for(timeout=5_000)
        self.assertIn("formatting", dialog.inner_text())
        page.click('[data-dialog-action="confirm"]')
        page.wait_for_selector('[data-fragment-id="f_bold"] .code-block', timeout=5_000)
        self.assertEqual(page.locator('[data-fragment-id="f_bold"] .code-block').input_value(), "Mind the gap")

    def test_paragraph_and_note_convert_without_touching_their_runs(self) -> None:
        """The pair that shares a payload shape, so nothing should be rebuilt on the way across.
        Written after a first implementation reconstructed runs from a `text` key a paragraph does not
        have, silently emptying it."""
        report_id, page = self._convert_report()
        page.locator('[data-fragment-id="f_bold"] .fragment-convert').select_option("note")
        page.wait_for_selector('[data-fragment-id="f_bold"] .rich', timeout=5_000)
        self.assertEqual(page.locator(".vr-dialog").count(), 0, "a lossless conversion asked first")
        self.assertEqual(page.locator('[data-fragment-id="f_bold"] .rich').inner_text(), "Mind the gap")

        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        stored = self._stored_fragment(report_id, "f_bold")
        self.assertEqual(stored["type"], "note")
        self.assertEqual(
            [(run["text"], run["bold"]) for run in stored["runs"]],
            [("Mind the ", False), ("gap", True)],
            "the runs were rebuilt instead of carried, losing text or formatting",
        )

    def test_a_proof_of_concept_note_can_become_a_paragraph_and_come_back(self) -> None:
        """The Add menu has no paragraph here, so this is the one route to one -- and the reason the
        conversion list is its own rather than borrowed from Add: a one-way door out of `note` would
        strand anything converted by mistake."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        next(c for c in finding.contents if c.type == "proof_of_concept").fragments.append(
            NoteFragment(frag_id="f_note", type="note", runs=[Run(text="Observed on every request.")])
        )
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")

        for target in ("paragraph", "note"):
            page.locator('[data-fragment-id="f_note"] .fragment-convert').select_option(target)
            page.wait_for_selector(f'[data-fragment-id="f_note"] .tag:text-is("{target}")', timeout=5_000)
            page.locator("#save-button").click()
            page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
            stored = self._stored_fragment(report_id, "f_note")
            self.assertEqual(stored["type"], target)
            self.assertEqual([run["text"] for run in stored["runs"]], ["Observed on every request."])

    def _two_list_proof(self, report_id: str, *, continue_second: bool):
        """A proof of concept shaped steps -> image -> steps, which is the only shape the continue
        option is reachable in: merge_step_lists would have collapsed two adjacent lists."""
        report, finding = self._complete_finding(report_id)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        first = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list")
        first.items = [ListItem(runs=[Run(text="First step")]), ListItem(runs=[Run(text="Second step")])]
        proof.fragments.append(ListFragment(
            frag_id="f_second_list", type="numbered_list", continue_numbering=continue_second,
            items=[ListItem(runs=[Run(text="Third step")])],
        ))
        main.workspace.save(report)
        return report, finding

    def test_a_continued_list_numbers_on_from_the_one_above_it(self) -> None:
        report_id = self.ready_report(include_finding=True)
        self._two_list_proof(report_id, continue_second=True)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        proof = page.locator('.content-block[data-content-type="proof_of_concept"]')
        second = proof.locator('[data-fragment-id="f_second_list"] .list-textarea')
        self.assertEqual(second.locator("xpath=..").locator(".list-marker").all_text_contents(), ["3."])

        first = proof.locator(".list-textarea").first
        first.click()
        page.keyboard.press("End")
        page.keyboard.type("\nInserted step")
        expect(second.locator("xpath=..").locator(".list-marker"), "editing the list above did not repaint the one continuing it").to_have_text(["4."])
        self.assertEqual(
            second.locator("xpath=..").locator(".list-marker").all_text_contents(), ["4."],
            "editing the list above did not repaint the one continuing it",
        )
        self.assertTrue(
            first.evaluate("field => field === document.activeElement"),
            "the repaint stole focus from the list being typed in",
        )

    def test_a_list_that_restarts_numbers_from_one(self) -> None:
        report_id = self.ready_report(include_finding=True)
        self._two_list_proof(report_id, continue_second=False)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        second = page.locator('[data-fragment-id="f_second_list"] .list-textarea')
        self.assertEqual(second.locator("xpath=..").locator(".list-marker").all_text_contents(), ["1."])

    def test_the_continue_control_appears_only_where_it_can_act(self) -> None:
        """Hidden on a section's first numbered list, which every proof of concept is guaranteed to
        have -- a permanently disabled control on the most common card in the app explains nothing."""
        report_id = self.ready_report(include_finding=True)
        self._two_list_proof(report_id, continue_second=False)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        proof = page.locator('.content-block[data-content-type="proof_of_concept"]')
        self.assertEqual(proof.locator(".fragment").first.locator(".list-continue").count(), 0)
        second = proof.locator('[data-fragment-id="f_second_list"]')
        self.assertEqual(second.locator(".list-continue").count(), 1)

        second.locator(".list-continue input").check()
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        saved = main.workspace.load(report_id).vulnerabilities[0]
        stored = next(content for content in saved.contents if content.type == "proof_of_concept")
        self.assertTrue(next(fragment for fragment in stored.fragments if fragment.frag_id == "f_second_list").continue_numbering)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        second = page.locator('[data-fragment-id="f_second_list"]')
        self.assertEqual(second.locator(".list-textarea").locator("xpath=..").locator(".list-marker").all_text_contents(), ["3."])
        self.assertTrue(second.locator(".list-continue input").is_checked())

    def test_a_set_continue_flag_stays_visible_after_the_list_above_it_goes(self) -> None:
        """Deleting the list above leaves the flag set but inert. Hiding the control then would make
        a set flag invisible and able to re-activate later without the tester ever seeing it."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._two_list_proof(report_id, continue_second=True)
        description = next(content for content in finding.contents if content.type == "description")
        description.fragments.append(ListFragment(
            frag_id="f_orphan", type="numbered_list", continue_numbering=True,
            items=[ListItem(runs=[Run(text="Orphaned step")])],
        ))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        orphan = page.locator('[data-fragment-id="f_orphan"]')
        self.assertEqual(orphan.locator(".list-continue").count(), 1, "a set flag was hidden")
        self.assertTrue(orphan.locator(".list-continue input").is_checked())
        self.assertEqual(
            orphan.locator(".list-textarea").locator("xpath=..").locator(".list-marker").all_text_contents(), ["1."],
            "a flag with nothing above it must fall back to 1 rather than invent an offset",
        )

    def test_ticking_continue_numbering_does_not_disturb_a_dismissed_library_offer(self) -> None:
        """The library offer asks whether the section still matches the entry's content. Numbering
        presentation is not content, so the tick must leave the dismissal fingerprint alone. The
        presence assertion is what stops this rotting into a green test that proves nothing."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._library_finding(report_id)
        description = next(content for content in finding.contents if content.type == "description")
        description.fragments.append(ListFragment(
            frag_id="f_first", type="numbered_list", items=[ListItem(runs=[Run(text="A step")])],
        ))
        description.fragments.append(ListFragment(
            frag_id="f_numbered", type="numbered_list", items=[ListItem(runs=[Run(text="Another step")])],
        ))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        self.assertEqual(block.locator("[data-content-offer]").count(), 1, "the fixture no longer produces an offer to dismiss")

        block.get_by_role("button", name="Keep mine").click()
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(block.locator("[data-content-offer]").count(), 0)

        block.locator('[data-fragment-id="f_numbered"] .list-continue input').check()
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        self.assertEqual(
            block.locator("[data-content-offer]").count(), 0,
            "ticking a numbering option resurrected a dismissed library offer",
        )

    def _complete_finding(self, report_id: str):
        """Fill the seeded finding in so both sides consider the report ready to generate."""
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image_data = png_bytes(2, 2)
        evidence_id = "ev_contract"
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data).hexdigest(), uploaded_at=report.saved_at)
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data)
        return report, finding

    def _fill_retest_history(self, report, finding):
        """Complete everything a previously-discovered status adds, and accept the standard closing
        sentence, so a caller's verdict turns on the conclusion rule rather than on retest history.
        The app offers that sentence now instead of writing it, so the fixture has to say so."""
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Original reproduction step")]
        history = next(fragment for fragment in previous.fragments if fragment.type == "image")
        history.environment = "production"
        history.evidence_id = "ev_contract"
        history.caption = "Original production response"
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = status_conclusion_runs(finding.title, "Resolved" if finding.status == "resolved" else "Open")
        return conclusion

    def test_a_finding_is_offered_only_the_app_types_it_has_not_installed(self) -> None:
        """Variants are per app type now, so a finding spanning web and API with only the web steps
        installed is offered API alone, and narrowing it back to web leaves nothing to offer."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.tested_channels = ["web", "api"]
        report.scope_targets.append(ScopeTarget(target_id="tgt_api", environment="production", channel="api", value="https://prod-api.example.test"))
        finding.scope = Scope(mode="custom", target_ids=["tgt_browser", "tgt_api"])
        finding.library_ref = LibraryRef(library_id="VDB-036", source_id="VDB-036", inserted_at=report.saved_at)
        finding.poc_variants = ["web"]
        finding.poc_variant_declined = []
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        offer = page.locator(".poc-offer")
        self.assertEqual(offer.count(), 1, "the api steps are still missing")
        self.assertEqual(offer.get_attribute("data-poc-offer"), "api")

        report = main.workspace.load(report_id)
        report.vulnerabilities[0].scope = Scope(mode="custom", target_ids=["tgt_browser"])
        acceptance.provision(report)
        main.workspace.save(report)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        self.assertEqual(page.locator(".poc-offer").count(), 0, "web is already installed, so nothing is left to offer")

    def test_a_review_jump_leaves_one_red_mark_and_lets_go_when_you_look_away(self) -> None:
        """Ringing every gap at once drowns the single one the panel just sent the tester to."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        tile = page.locator(".evidence-tile:not(.has-evidence)").first
        tile.wait_for()
        self.assertNotIn("is-incomplete", tile.get_attribute("class") or "", "an empty evidence slot was ringed on its own")
        self.assertGreater(page.locator(".is-incomplete").count(), 0, "nothing was marked before the jump")

        page.get_by_role("button", name="Go to Proof of Concept").first.click()
        page.wait_for_selector(".is-review-target")
        self.assertEqual(page.locator(".is-incomplete").count(), 0, "other red marks were left competing with the jump")

        page.evaluate("() => document.querySelector('#editor').click()")
        page.wait_for_selector(".is-review-target", state="detached")
        self.assertGreater(page.locator(".is-incomplete").count(), 0, "the marks never came back after looking away")

    def test_go_to_marks_only_the_selected_empty_evidence_slot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof.fragments.extend([
            ImageFragment(frag_id="f_empty_a", type="image", environment="production"),
            ImageFragment(frag_id="f_empty_b", type="image", environment="production"),
        ])
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        empty_tiles = page.locator(".evidence-tile:not(.has-evidence)")
        self.assertEqual(empty_tiles.count(), 2)
        target_id = empty_tiles.first.get_attribute("data-fragment-id")
        page.locator(f'[data-review-fragment="{target_id}"]').first.click()
        page.wait_for_selector(f'.evidence-tile[data-fragment-id="{target_id}"].is-incomplete')
        highlighted = page.locator(".evidence-tile.is-incomplete")
        self.assertEqual(highlighted.count(), 1)
        self.assertEqual(highlighted.get_attribute("data-fragment-id"), target_id)

    def test_supporting_evidence_readiness_arrow_targets_the_tile_and_gates_generate(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        supporting = ImageFragment(
            frag_id="f_readiness_supporting",
            type="image",
            environment="non_production",
            caption="Supporting caption awaiting its image",
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof.fragments.append(supporting)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        row = page.locator(".review-row").filter(has_text="Non-Production supporting evidence").filter(has_text="requires image")
        self.assertEqual(row.count(), 1)
        generate = page.get_by_role("button", name="Generate Report")
        self.assertTrue(generate.is_disabled())

        row.get_by_role("button", name="Go to Proof of Concept").click()
        tile = page.locator(f'.evidence-tile[data-fragment-id="{supporting.frag_id}"]')
        page.wait_for_selector(f'.evidence-tile[data-fragment-id="{supporting.frag_id}"].is-review-target')
        self.assertTrue(tile.evaluate("node => node === document.activeElement"))
        tile.locator('input[type="file"]').set_input_files({
            "name": "readiness-supporting.png",
            "mimeType": "image/png",
            "buffer": png_bytes(2, 2),
        })
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        page.wait_for_selector('#issue-count[data-state="ready"]', timeout=5_000)
        self.assertEqual(row.count(), 0)
        self.assertFalse(generate.is_disabled())

    def test_unchecking_a_location_in_the_page_withdraws_that_app_types_offer(self) -> None:
        """The same narrowing done through the Findings page, which is how a tester actually does it."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.tested_channels = ["web", "api"]
        report.scope_targets.append(ScopeTarget(target_id="tgt_api", environment="production", channel="api", value="https://prod-api.example.test"))
        finding.scope = Scope(mode="custom", target_ids=["tgt_browser", "tgt_api"])
        finding.library_ref = LibraryRef(library_id="VDB-036", source_id="VDB-036", inserted_at=report.saved_at)
        finding.poc_variants = ["web"]
        finding.poc_variant_declined = []
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        # Driven directly because the fold toggle's actionability check does not settle headless.
        page.evaluate("""() => {
          const box = document.querySelector('input[data-location][value="tgt_api"]');
          box.checked = false;
          box.dispatchEvent(new Event("change", {bubbles: true}));
        }""")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)
        saved = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(saved.scope.target_ids, ["tgt_browser"], "the api location was not dropped")
        self.assertEqual(saved.poc_variants, ["web"], "the installed app types are untouched by a scope edit")

        page.evaluate("document.querySelector('#next').click()")
        page.wait_for_url("**/edit", timeout=10_000)
        page.wait_for_selector("#issue-count")
        self.assertEqual(page.locator(".poc-offer").count(), 0, "the finding no longer touches api, so its steps are not offered")

    def test_the_later_statuses_are_offered_and_save_with_the_retest_sections(self) -> None:
        """The dropdown is the last thing to learn a status, because until the server, the document,
        the importer, the recogniser and the builder all know it, offering it hands the tester a
        value that loses work. Saving here is the first moment a draft on disk can hold one."""
        for value, label in (("open_resolved_on_non_prod", "Open (Resolved on Non-Prod)"), ("closed", "Closed")):
            with self.subTest(status=value):
                report_id = self.ready_report(include_finding=True)
                page = self.page
                page.goto(f"{self.base_url}/reports/{report_id}/findings")
                page.wait_for_selector("#findings tr")
                status = page.locator("#findings tr").first.locator("select").last
                self.assertIn(label, status.evaluate("select => [...select.options].map(option => option.textContent)"))

                saved_put = lambda response: response.request.method == "PUT" and response.url.endswith(f"/reports/{report_id}")
                with page.expect_response(saved_put):
                    status.select_option(value)
                page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

                stored = main.workspace.load(report_id).vulnerabilities[0]
                self.assertEqual(stored.status, value, "the client offered a status the server refused")
                self.assertEqual(
                    [content.type for content in stored.contents],
                    ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
                )

    def test_status_round_trip_preserves_a_supporting_image(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        finding = report.vulnerabilities[0]
        acceptance.provision(report)

        image_data = png_bytes(2, 2)
        evidence_id = "ev_status_supporting"
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="status-supporting.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        supporting = ImageFragment(
            frag_id="f_status_supporting", type="image", environment="non_production",
            evidence_id=evidence_id, caption="Supporting response through status changes",
        )
        proof.fragments.append(supporting)
        main.workspace.save(report)

        def assert_supporting_survives(expected_status: str) -> None:
            saved = main.workspace.load(report_id)
            saved_finding = saved.vulnerabilities[0]
            self.assertEqual(saved_finding.status, expected_status)
            saved_proof = next(content for content in saved_finding.contents if content.type == "proof_of_concept")
            saved_image = next(fragment for fragment in saved_proof.fragments if fragment.type == "image" and fragment.frag_id == supporting.frag_id)
            self.assertEqual((saved_image.environment, saved_image.evidence_id, saved_image.caption), (
                "non_production", evidence_id, "Supporting response through status changes",
            ))
            self.assertIn(evidence_id, saved.evidence)
            self.assertTrue(evidence_path.exists())

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        saved_put = lambda response: response.request.method == "PUT" and response.url.endswith(f"/reports/{report_id}")
        status = page.locator("#findings tr").first.locator("select").last
        with page.expect_response(saved_put):
            status.select_option("open_previously_discovered")
        assert_supporting_survives("open_previously_discovered")

        status = page.locator("#findings tr").first.locator("select").last
        with page.expect_response(saved_put):
            status.select_option("open_new")
        assert_supporting_survives("open_new")

    def test_switching_from_resolved_to_closed_removes_only_generated_remediation(self) -> None:
        """Closed shares Resolved's five sections but must not carry the app-generated claim that
        remediation occurred. This exercises the client provisioning path, not just server models."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        status = page.locator("#findings tr").first.locator("select").last
        status.select_option("resolved")
        page.get_by_role("button", name="Change the status").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        status = page.locator("#findings tr").first.locator("select").last
        status.select_option("closed")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        page.reload()
        stored = main.workspace.load(report_id).vulnerabilities[0]
        remediation = next(content for content in stored.contents if content.type == "recommended_remediation")
        self.assertEqual(stored.status, "closed")
        self.assertEqual(
            [content.type for content in stored.contents],
            ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
        )
        self.assertEqual(remediation.fragments[0].runs, [], "Closed retained a false generated remediation claim")
        self.assertIsNone(remediation.fragments[0].generated)

    def test_gdt_closed_finding_keeps_pasted_evidence_without_asia_cvss_fields(self) -> None:
        """GDT and Closed were added together, but exercise different rules: GDT must remain a
        non-Asia segment while Closed must retain the proof image that receives a paste."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.get_by_label("Segment").select_option("GDT")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        status = page.locator("#findings tr").first.locator("select").last
        status.select_option("closed")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        additional = page.locator('[data-content-type="additional_information"]')
        self.assertEqual(additional.locator(".fragment-head .tag").all_text_contents(), ["Severity Review Tickets"])
        self.arm_evidence(self.evidence_ids()[0])
        self.paste_png()
        page.locator(".image-preview").first.wait_for(timeout=8_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=8_000)

        page.reload()
        page.locator(".image-preview").first.wait_for(timeout=5_000)
        stored = main.workspace.load(report_id)
        finding = stored.vulnerabilities[0]
        self.assertEqual(stored.engagement.segment, "GDT")
        self.assertEqual(finding.status, "closed")
        self.assertEqual(
            [content.type for content in finding.contents],
            ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
        )
        evidence_ids = [
            fragment.evidence_id
            for content in finding.contents
            if content.type.endswith("proof_of_concept")
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment) and fragment.evidence_id
        ]
        self.assertEqual(evidence_ids, list(stored.evidence), "the pasted file must remain referenced after reload")

    def test_changing_a_finding_status_in_the_browser_keeps_last_years_proof(self) -> None:
        """The editor hides the previous proof when a finding becomes "open new". Deleting it would
        make a mis-click on a dropdown unrecoverable, so the work has to come back with the status."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Last year's step")]
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#findings tr")
        status = page.locator("#findings tr").first.locator("select").last
        saved_put = lambda response: response.request.method == "PUT" and response.url.endswith(f"/reports/{report_id}")
        with page.expect_response(saved_put):
            status.select_option("open_new")
            page.click('[data-dialog-action="confirm"]')

        hidden = read_json(main.workspace.find_path(report_id))
        carried = [
            content for content in hidden["vulnerabilities"][0]["contents"]
            if content["type"] == "previous_proof_of_concept"
        ]
        self.assertTrue(carried, "the section is kept out of sight, not thrown away")

        with page.expect_response(saved_put):
            status.select_option("open_previously_discovered")

        restored = read_json(main.workspace.find_path(report_id))
        previous_content = next(
            content for content in restored["vulnerabilities"][0]["contents"]
            if content["type"] == "previous_proof_of_concept"
        )
        steps = [
            run["text"]
            for fragment in previous_content["fragments"] if fragment["type"] == "numbered_list"
            for item in fragment["items"] for run in item["runs"]
        ]
        self.assertIn("Last year's step", steps, "the tester's previous proof survived the round trip")

    def test_a_status_change_with_nothing_written_asks_for_no_confirmation(self) -> None:
        """The warning is about losing work. An untouched finding has none, so stopping to ask
        trains the tester to dismiss the dialog that will one day matter."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#findings tr")
        status = page.locator("#findings tr").first.locator("select").last
        status.select_option("open_new")
        # The confirmation is added to the page inside the change handler, so it would be here already;
        # checked on this page, because after Next the editor could never show it.
        self.assertEqual(page.locator("[data-dialog]").count(), 0, "nothing was written, so nothing needed confirming")
        page.locator("#next").click()
        page.wait_for_url("**/edit", timeout=10_000)
        self.assertEqual(read_json(main.workspace.find_path(report_id))["vulnerabilities"][0]["status"], "open_new")

    def test_the_fragments_provisioning_guarantees_cannot_be_deleted(self) -> None:
        """Provisioning puts these back on the next save, so offering a delete would look like the
        editor silently discarded the change."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Original step")]
        image_data = png_bytes(2, 2)
        history = next(fragment for fragment in previous.fragments if fragment.type == "image")
        history.environment = "production"
        history.evidence_id = "ev_history"
        history.caption = "Original response"
        report.evidence["ev_history"] = EvidenceItem(file="evidence/ev_history.png", original_name="history.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data).hexdigest(), uploaded_at=report.saved_at)
        (main.workspace.find_path(report_id).parent / "evidence" / "ev_history.png").write_bytes(image_data)
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        for section, kind in (("Previous Proof of Concept", "numbered list"),):
            block = page.locator(".content-block").filter(has_text=section)
            card = block.locator(".fragment").filter(has=page.locator(f'.tag:text-is("{kind}")'))
            self.assertTrue(card.locator("button.danger").is_disabled(), f"{section} {kind} must not be deletable")
        history = page.locator(".content-block").filter(has_text="Previous Proof of Concept").locator(".evidence-tile")
        self.assertTrue(history.locator("button.danger").is_disabled(), "the historical image must not be deletable")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        card = proof.locator(".fragment").filter(has=page.locator('.tag:text-is("numbered list")'))
        self.assertTrue(card.locator("button.danger").is_disabled(), "proof of concept numbered list must not be deletable")
        self.assertTrue(proof.locator(".evidence-tile button.danger").first.is_disabled(), "the required evidence must not be deletable")

        # Only the last one of each is guaranteed, so a second is the tester's to remove.
        proof.locator('select.add-fragment').select_option("numbered_list")
        cards = proof.locator('.fragment').filter(has=page.locator('.tag:text-is("numbered list")'))
        self.assertEqual(cards.count(), 2)
        self.assertFalse(cards.last.locator("button.danger").is_disabled(), "a second steps list is deletable")
        self.assertFalse(cards.first.locator("button.danger").is_disabled(), "neither one is required once there are two")

    def test_switching_library_entries_reoffers_poc_for_the_same_channel(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        first = main.library.get("VDB-015")
        finding.title = first["title"]
        finding.library_ref = LibraryRef(library_id=first["library_id"], source_id=first["source_id"], inserted_at=report.saved_at)
        finding.poc_variants = ["web"]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        second_title = "Deprecated Pragma Header in Use"
        page.get_by_role("button", name="Edit finding name").click()
        title = page.get_by_role("combobox", name="Finding Name")
        title.fill(second_title)
        page.locator('.row-library-results [role="option"]').filter(has_text=second_title).click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        self.assertEqual(proof.locator(".poc-offer").count(), 1)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].poc_variants, [])

    def _assert_library_variant_preserves_supporting_image(self, button_name: str, keeps_tester_step: bool) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        finding = report.vulnerabilities[0]
        entry = main.library.get("VDB-015")
        finding.title = entry["title"]
        finding.library_ref = LibraryRef(library_id=entry["library_id"], source_id=entry["source_id"], inserted_at=report.saved_at)
        finding.poc_variants = []
        finding.poc_variant_declined = []
        acceptance.provision(report)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        steps = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list")
        steps.items[0].runs = [Run(text="Existing tester step")]

        image_data = png_bytes(2, 2)
        evidence_id = f"ev_library_{'merge' if keeps_tester_step else 'replace'}"
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name=f"{evidence_id}.png",
            width_px=2,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        supporting = ImageFragment(
            frag_id=f"f_library_{'merge' if keeps_tester_step else 'replace'}",
            type="image",
            environment="non_production",
            evidence_id=evidence_id,
            caption="Supporting response beside library steps",
        )
        proof.fragments.append(supporting)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        offer = page.locator(".content-block").filter(has_text="Proof of Concept").last.locator(".poc-offer")
        self.assertEqual(offer.count(), 1)
        offer.get_by_role("button", name=button_name, exact=True).click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        saved = main.workspace.load(report_id)
        saved_finding = saved.vulnerabilities[0]
        saved_proof = next(content for content in saved_finding.contents if content.type == "proof_of_concept")
        saved_image = next(fragment for fragment in saved_proof.fragments if fragment.type == "image" and fragment.frag_id == supporting.frag_id)
        self.assertEqual((saved_image.environment, saved_image.evidence_id, saved_image.caption), (
            "non_production", evidence_id, "Supporting response beside library steps",
        ))
        step_text = [
            run.text
            for fragment in saved_proof.fragments if fragment.type == "numbered_list"
            for item in fragment.items for run in item.runs
        ]
        self.assertEqual("Existing tester step" in step_text, keeps_tester_step)
        self.assertEqual(saved_finding.poc_variants, ["web"])
        self.assertIn(evidence_id, saved.evidence)
        self.assertTrue(evidence_path.exists())

    def test_replacing_library_steps_preserves_a_supporting_image(self) -> None:
        self._assert_library_variant_preserves_supporting_image("Use saved steps", False)

    def test_merging_library_steps_preserves_a_supporting_image(self) -> None:
        self._assert_library_variant_preserves_supporting_image("Add below", True)

    def test_poc_add_below_does_not_cross_an_intervening_note(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        entry = main.library.get("VDB-015")
        finding.library_ref = LibraryRef(library_id=entry["library_id"], source_id=entry["source_id"], inserted_at=report.saved_at)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        steps = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list")
        steps.items[0].runs = [Run(text="Existing step")]
        image_index = next(index for index, fragment in enumerate(proof.fragments) if fragment.type == "image")
        proof.fragments.insert(image_index, NoteFragment(frag_id="f_stop_note", type="note", runs=[Run(text="Stop after the existing procedure")]))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        proof_block = page.locator(".content-block").filter(has_text="Proof of Concept").last
        proof_block.get_by_role("button", name="Add below").click()
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url("**/findings", timeout=10_000)

        proof = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "proof_of_concept")
        self.assertEqual([fragment.type for fragment in proof.fragments], ["numbered_list", "note", "numbered_list", "image"])
        self.assertEqual(proof.fragments[2].items[0].runs[0].text, "Browse to the assistant page as a standard user.")

    def test_library_step_offer_appears_only_on_the_proof_of_concept(self) -> None:
        """The offer replaces this engagement's steps. Previous Proof of Concept is the record of
        the engagement before it, so an offer there would invite overwriting history."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        finding.library_ref = LibraryRef(library_id="VDB-043", source_id="VDB-043", inserted_at=report.saved_at)
        finding.poc_variants = []
        finding.poc_variant_declined = []
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        previous = page.locator(".content-block").filter(has_text="Previous Proof of Concept")
        self.assertEqual(proof.locator(".poc-offer").count(), 1, "the offer belongs on the proof of concept")
        self.assertEqual(previous.locator(".poc-offer").count(), 0, "history must never be offered a replacement")

    def test_editor_keeps_a_carried_previous_proof_image_outside_the_retest_scope(self) -> None:
        """The finding covers production only, so the old editor overwrote a carried non-production
        label on render and autosaved the corruption. History belongs to the tester, not the scope."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Original reproduction step")]
        image_data = png_bytes(2, 2)
        history = next(fragment for fragment in previous.fragments if fragment.type == "image")
        history.environment = "non_production"
        history.evidence_id = "ev_history"
        history.caption = "Original non-production response"
        report.evidence["ev_history"] = EvidenceItem(file="evidence/ev_history.png", original_name="history.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data).hexdigest(), uploaded_at=report.saved_at)
        (main.workspace.find_path(report_id).parent / "evidence" / "ev_history.png").write_bytes(image_data)
        acceptance.provision(report)
        main.workspace.save(report)
        self.assertEqual(
            next(fragment for fragment in previous.fragments if fragment.type == "image").environment,
            "non_production",
            "the server must not relabel a carried image either",
        )

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        block = page.locator(".content-block").filter(has_text="Previous Proof of Concept")
        page.wait_for_selector("#issue-count")
        # A single-environment finding renders a fixed label instead of a select, so the presence of
        # the select is itself the assertion that history was not forced into the current scope.
        self.assertEqual(block.locator(".evidence-environment").input_value(), "non_production")
        self.assertEqual(block.locator(".evidence-environment-value").count(), 0)

    def test_pasting_a_numbered_list_strips_the_markers_the_gutter_already_draws(self) -> None:
        """The visible numbering is a separate gutter, never the field's value, so a pasted "1."
        renders as "1. 1.". A separator is required, which is what keeps an IP address intact."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        steps = page.locator('.content-block[data-content-type="proof_of_concept"] .list-textarea').first
        steps.click()
        page.evaluate(
            """() => {
              const field = document.querySelector('.content-block[data-content-type="proof_of_concept"] .list-textarea');
              field.focus();
              field.setSelectionRange(0, field.value.length);
              const transfer = new DataTransfer();
              transfer.setData("text/plain", "1. Alpha step\\n2) Beta step\\n(3) Gamma step\\n- Delta step\\n\\u2022 Epsilon step\\n1.2.3.4 is the host");
              field.dispatchEvent(new ClipboardEvent("paste", {clipboardData: transfer, bubbles: true, cancelable: true}));
            }"""
        )
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        proof = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "proof_of_concept")
        steps_fragment = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list")
        self.assertEqual(
            ["".join(run.text for run in item.runs) for item in steps_fragment.items],
            ["Alpha step", "Beta step", "Gamma step", "Delta step", "Epsilon step", "1.2.3.4 is the host"],
            "a marker survived, or the host address lost its leading number",
        )

    def test_pasting_marker_like_text_mid_item_does_not_delete_it(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, _ = self._complete_finding(report_id)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        field = page.locator('.content-block[data-content-type="proof_of_concept"] .list-textarea').first
        field.fill("Send parameter ")
        page.evaluate(
            """() => {
              const field = document.querySelector('.content-block[data-content-type="proof_of_concept"] .list-textarea');
              field.setSelectionRange(field.value.length, field.value.length);
              const transfer = new DataTransfer();
              transfer.setData("text/plain", "1. value");
              field.dispatchEvent(new ClipboardEvent("paste", {clipboardData: transfer, bubbles: true, cancelable: true}));
            }"""
        )
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        proof = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "proof_of_concept")
        first_item = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0]
        self.assertEqual("".join(run.text for run in first_item.runs), "Send parameter 1. value")

    def test_the_conclusion_offer_puts_the_last_step_in_front_of_the_sentence(self) -> None:
        """The step shares the sentence's paragraph rather than taking one of its own, so the client
        has to find the sentence as a tail. Get that wrong and the browser either stacks a second
        paragraph or stops recognising the sentence the server still maintains."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        self._fill_retest_history(report, finding)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        steps = next(fragment for fragment in proof.fragments if fragment.type == "numbered_list")
        steps.items = [
            ListItem(runs=[Run(text="Log in as a standard user.")]),
            ListItem(runs=[Run(text="Observe the balance of another user.")]),
            ListItem(runs=[]),
        ]
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        offer = conclusion.locator("[data-conclusion-step]")
        self.assertEqual(offer.count(), 1, "the last written step was not offered")
        self.assertIn("Observe the balance of another user.", offer.inner_text(), "a trailing blank item was quoted")

        fragments_before = conclusion.locator(".fragment").count()
        offer.get_by_role("button", name="Use it").click()
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        self.assertEqual(conclusion.locator(".fragment").count(), fragments_before, "the step took a paragraph of its own")
        saved = main.workspace.load(report_id).vulnerabilities[0]
        paragraph = next(content for content in saved.contents if content.type == "in_conclusion").fragments[0]
        self.assertEqual(
            "".join(run.text for run in paragraph.runs),
            f'Observe the balance of another user. The finding "{saved.title}" is still Open.',
            "the step did not land in front of the sentence in the same paragraph",
        )
        self.assertEqual(saved.conclusion_offer_resolved, ["Observe the balance of another user."])
        self.assertEqual(conclusion.locator("[data-conclusion-step]").count(), 0, "an answered offer came back")

    def test_the_conclusion_offer_uses_only_the_last_line_of_multiline_poc_prose(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        self._fill_retest_history(report, finding)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof.fragments.append(NoteFragment(
            frag_id="f_multiline_note",
            type="note",
            runs=[Run(text="First note line\nLast note line\n")],
        ))
        acceptance.provision(report)
        main.workspace.save(report)

        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
        offer = self.page.locator("[data-conclusion-step]")
        offer.wait_for()
        self.assertIn('"Last note line"', offer.inner_text())
        self.assertNotIn("First note line", offer.inner_text())

    def test_the_default_conclusion_still_gets_offered_the_last_step(self) -> None:
        """The whole sequence: a conclusion that holds nothing but the standard sentence is exactly
        the state where quoting the last proof step is most useful, so the offer has to survive it."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        self._fill_retest_history(report, finding)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items = [
            ListItem(runs=[Run(text="Log in as a standard user.")]),
            ListItem(runs=[Run(text="Observe the balance of another user.")]),
        ]
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertEqual(conclusion.locator(".rich").first.text_content(), 'The finding "Browser finding" is still Open.')
        offer = conclusion.locator("[data-conclusion-step]")
        self.assertEqual(offer.count(), 1, "a conclusion at its default was not offered the last step")
        self.assertIn("Observe the balance of another user.", offer.inner_text())

        # Dismiss has to work for this sitting, or a standing offer would redraw itself unanswered.
        conclusion.get_by_role("button", name="Dismiss").click()
        expect(conclusion.locator("[data-conclusion-step]"), "dismissing the step offer did nothing").to_have_count(0)

        # But the conclusion is still boilerplate, so reopening the report asks once more.
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertEqual(conclusion.locator("[data-conclusion-step]").count(), 1, "a conclusion left at its default stopped being offered the step")

    def _conclusion_step_report(self):
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        self._fill_retest_history(report, finding)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items = [
            ListItem(runs=[Run(text="Log in as a standard user.")]),
            ListItem(runs=[Run(text="Observe the balance of another user.")]),
        ]
        acceptance.provision(report)
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        return report_id, page

    def test_editing_the_last_proof_step_updates_the_conclusion_offer_live(self) -> None:
        """Every other test of this offer reloads the page, so none of them would notice the banner
        going stale against the step it quotes."""
        _report_id, page = self._conclusion_step_report()
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertIn("Observe the balance of another user.", conclusion.locator("[data-conclusion-step]").inner_text())

        steps = page.locator('.content-block[data-content-type="proof_of_concept"] .list-textarea').last
        # One textarea holds every item as a line, so the first line has to be carried along.
        steps.fill("Log in as a standard user.\nWithdraw from the other user's account.")
        steps.blur()
        expect(conclusion.locator("[data-conclusion-step]"), "the offer still quotes the step the tester replaced").to_contain_text("Withdraw from the other user's account.")

    def test_deleting_the_last_proof_step_moves_the_conclusion_offer_to_the_one_above(self) -> None:
        _report_id, page = self._conclusion_step_report()
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertIn("Observe the balance of another user.", conclusion.locator("[data-conclusion-step]").inner_text())

        steps = page.locator('.content-block[data-content-type="proof_of_concept"] .list-textarea').last
        # Drops the second line only; the list still has a step, so the offer should move up to it.
        steps.fill("Log in as a standard user.")
        steps.blur()
        expect(conclusion.locator("[data-conclusion-step]"), "emptying the quoted step left the offer pointing at text that is gone").to_contain_text("Log in as a standard user.")

    def test_the_conclusion_offer_follows_the_proof_step_while_it_is_still_being_typed(self) -> None:
        """Blurring first is what the other tests do, and it hid this: the refresh used to skip every
        block whenever any field held the caret, so the quote went stale until the tester clicked away."""
        _report_id, page = self._conclusion_step_report()
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        steps = page.locator('.content-block[data-content-type="proof_of_concept"] .list-textarea').last
        steps.fill("Log in as a standard user.\nWithdraw from the other user's account.")
        expect(conclusion.locator("[data-conclusion-step]"), "the offer only caught up after the field lost focus").to_contain_text("Withdraw from the other user's account.")

        self.assertEqual(steps.evaluate("el => document.activeElement === el"), True, "the caret left the field, so this proves nothing")
        self.assertIn(
            "Withdraw from the other user's account.",
            conclusion.locator("[data-conclusion-step]").inner_text(),
            "the offer only caught up after the field lost focus",
        )

    def test_a_status_round_trip_empties_the_conclusion_and_re_offers_both_prompts(self) -> None:
        """Open (New) drops the conclusion outright, so coming back leaves an empty section: the
        standard sentence is offered first, and accepting it then offers the last proof step."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        conclusion = self._fill_retest_history(report, finding)
        conclusion.fragments[0].runs = [Run(text="My own conclusion.")]
        # Already answered once, which is the state that was wrongly silencing the offer for good.
        finding.conclusion_offer_resolved = ["Observe the balance of another user."]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items = [
            ListItem(runs=[Run(text="Observe the balance of another user.")]),
        ]
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#findings tr")
        status = page.locator("#findings tr").first.locator("select").last
        saved_put = lambda response: response.request.method == "PUT" and response.url.endswith(f"/reports/{report_id}")
        with page.expect_response(saved_put):
            status.select_option("open_new")
            page.click('[data-dialog-action="confirm"]')
        self.assertNotIn(
            "in_conclusion",
            [content.type for content in main.workspace.load(report_id).vulnerabilities[0].contents],
            "Open (New) kept a conclusion describing a status it no longer has",
        )

        with page.expect_response(saved_put):
            status.select_option("open_previously_discovered")
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        conclusion_block = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertEqual(conclusion_block.locator(".rich").first.text_content(), "", "the conclusion came back with text in it")
        self.assertEqual(conclusion_block.locator("[data-conclusion-restore]").count(), 1, "an empty conclusion was not offered the standard sentence")

        conclusion_block.get_by_role("button", name="Put it back").click()
        expect(conclusion_block.locator(".rich").first).to_have_text('The finding "Browser finding" is still Open.')
        self.assertEqual(conclusion_block.locator("[data-conclusion-restore]").count(), 0, "the restore offer stayed after being accepted")
        self.assertEqual(conclusion_block.locator("[data-conclusion-step]").count(), 1, "the last proof step was not offered once the default was in place")

    def test_what_surrounds_the_default_conclusion_decides_whether_it_still_counts(self) -> None:
        """The app's own sentence is only boilerplate while it stands alone in its paragraph. A quoted
        step or appended prose is the tester's own words; trailing whitespace is not."""
        cases = [
            # name, how the paragraph's runs change, still just the default, page-load timeout
            ("quoted step in front", lambda runs: [Run(text="Observe the balance of another user. "), *runs], False, 30_000),
            # Short, so a pattern that backtracks on trailing whitespace fails fast instead of hanging.
            ("trailing whitespace", lambda runs: [*runs, Run(text="  \n")], True, 2_000),
            ("appended prose", lambda runs: [*runs, Run(text=" Additional tester prose.")], False, 30_000),
        ]
        for name, change, still_default, timeout in cases:
            with self.subTest(case=name):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                finding.status = "open_previously_discovered"
                conclusion = self._fill_retest_history(report, finding)
                conclusion.fragments[0].runs = change(conclusion.fragments[0].runs)
                acceptance.provision(report)
                main.workspace.save(report)

                expected_issue = f"{finding.title}: in_conclusion still holds the default sentence"
                server_has_issue = expected_issue in generation_issues(main.workspace.load(report_id))
                self.page.goto(f"{self.base_url}/reports/{report_id}/edit", timeout=timeout)
                self.page.wait_for_selector("#issue-count")
                self.assertEqual(
                    (
                        server_has_issue,
                        self.page.locator("#issue-count").get_attribute("data-state"),
                        self.page.locator("#generate-report").is_disabled(),
                        self.page.locator(".review-row", has_text="In Conclusion").count() > 0,
                    ),
                    (still_default, "issues" if still_default else "ready", still_default, still_default),
                )

    def test_a_table_edit_on_screen_survives_adding_a_row(self) -> None:
        """Add row redraws from the model, so a keystroke that has not reached it yet must be flushed first."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        description = page.locator(".content-block").filter(has_text="Description").first
        description.get_by_role("combobox", name="Add fragment to Description").select_option("table")
        cell = page.locator(".table-cell-input").last
        cell.wait_for()
        # The state the save-while-typing race leaves behind: on screen, but not in the model.
        cell.evaluate("node => { node.value = 'UNCOMMITTED'; }")
        description.get_by_role("button", name="Add row").click()
        page.wait_for_function("() => document.querySelectorAll('.table-cell-input').length > 2")
        self.assertIn(
            "UNCOMMITTED",
            page.locator(".table-cell-input").evaluate_all("nodes => nodes.map(node => node.value)"),
            "the redraw dropped an edit that was still only on screen",
        )

    def test_folding_a_section_leaves_its_header_under_the_pointer(self) -> None:
        """Lists size themselves a frame after the redraw, so a section above the one being folded
        grows once the scroll has already been put back. The correction has to outlast that."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        description = next(content for content in finding.contents if content.type == "description")
        description.fragments.append(ListFragment(
            frag_id="f_tall_list", type="numbered_list",
            items=[ListItem(runs=[Run(text=f"Step {number}")]) for number in range(30)],
        ))
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        moved = page.evaluate(
            """async () => {
              const pane = document.querySelector("#finding-editor");
              const settle = () => new Promise(done => setTimeout(done, 300));
              const toggle = type => pane.querySelector(`[data-content-type="${type}"] > .content-toggle`);
              for (const type of [...pane.querySelectorAll(".content-block")].map(block => block.dataset.contentType)) {
                if (!toggle(type).closest(".content-block").classList.contains("is-expanded")) toggle(type).click();
                await settle();
              }
              toggle("proof_of_concept").click();
              await settle();
              // Parked well down the pane, so the tall description above it is what moves.
              pane.scrollTop += toggle("proof_of_concept").getBoundingClientRect().top - pane.getBoundingClientRect().top - 300;
              await settle();
              const before = toggle("proof_of_concept").getBoundingClientRect().top;
              toggle("proof_of_concept").click();
              await settle();
              return Math.round(toggle("proof_of_concept").getBoundingClientRect().top - before);
            }"""
        )
        self.assertLessEqual(abs(moved), 4, f"the section header slid {moved}px out from under the pointer")

    def test_taking_a_conclusion_prompt_leaves_the_section_where_it_was(self) -> None:
        """Every prompt button ends in a redraw, and the redraw puts the scroll back before the
        sections have grown to full height, so the position it asks for does not exist yet."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        finding.status = "open_previously_discovered"
        main.provision(finding)
        description = next(content for content in finding.contents if content.type == "description")
        description.fragments.append(ListFragment(
            frag_id="f_tall_list", type="numbered_list",
            items=[ListItem(runs=[Run(text=f"Step {number}")]) for number in range(30)],
        ))
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = [Run(text="The account remained reachable after the fix window closed.")]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("[data-conclusion-sentence]")
        # Clicked through the DOM: Playwright scrolls a button into view first, which would move the
        # very thing being measured.
        moved = page.evaluate(
            """async () => {
              const pane = document.querySelector("#finding-editor");
              const settle = () => new Promise(done => setTimeout(done, 300));
              const header = () => pane.querySelector('[data-content-type="in_conclusion"] > .content-toggle');
              pane.scrollTop += header().getBoundingClientRect().top - pane.getBoundingClientRect().top - 200;
              await settle();
              const before = header().getBoundingClientRect().top;
              const tallBefore = pane.scrollHeight;
              [...pane.querySelectorAll("button")].find(button => button.textContent.trim() === "Add it to the end").click();
              await settle();
              return {moved: Math.round(header().getBoundingClientRect().top - before),
                      lost: Math.round(Math.max(0, tallBefore - pane.scrollHeight))};
            }"""
        )
        # Taking the prompt removes the banner, and the pane is already at its end, so the content
        # below cannot hold the view still. It may give up that much and no more.
        self.assertLessEqual(
            abs(moved["moved"]), moved["lost"] + 4,
            f"the section slid {moved['moved']}px while the pane lost only {moved['lost']}px",
        )

    def test_a_written_conclusion_without_the_sentence_is_offered_it(self) -> None:
        """Their wording is the conclusion, so the sentence is offered rather than written for them."""
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        finding.status = "open_previously_discovered"
        main.provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = [Run(text="The account remained reachable after the fix window closed.")]
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("[data-conclusion-sentence]")
        page.get_by_role("button", name="Add it to the end").click()
        page.wait_for_selector("[data-conclusion-sentence]", state="detached")
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=15_000)

        saved = main.workspace.load(report_id).vulnerabilities[0]
        text = "".join(
            run.text
            for content in saved.contents if content.type == "in_conclusion"
            for fragment in content.fragments for run in fragment.runs
        )
        self.assertTrue(text.startswith("The account remained reachable"), "the tester's wording was not kept")
        self.assertTrue(text.rstrip().endswith("is still Open."), f"the sentence was not appended: {text!r}")

    def _library_finding(self, report_id: str, library_id: str = "VDB-047"):
        """A finding whose Description and Remediation hold that entry's own content, as an insert leaves it."""
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        entry = main.library.get(library_id)
        finding.library_ref = LibraryRef(library_id=library_id, source_id=library_id, inserted_at=report.saved_at)
        finding.likelihood = finding.impact = finding.severity = "low"
        for content in entry["contents"]:
            section = next(candidate for candidate in finding.contents if candidate.type == content["type"])
            section.fragments = [fragment.model_copy(deep=True) for fragment in Content.model_validate(content).fragments]
        main.workspace.save(report)
        return report, finding

    def test_an_edited_library_section_is_offered_back_once_the_field_is_left(self) -> None:
        """The offer keys off the content itself, so a section that no longer matches its entry is
        offerable however it got that way. Typing never redraws the pane -- it would destroy the
        caret -- so the banner waits for the field to be left, but not for a reload."""
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "content matching the library was offered back")

        block.locator(".rich").first.click()
        page.keyboard.type("Changed. ")
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "the banner moved while the caret was in the field")

        page.locator("body").click(position={"x": 5, "y": 5})
        expect(block.locator("[data-content-offer]"), "an edited section was not offered the library version").to_have_count(1)

    def test_dismissing_an_offer_keeps_it_hidden_until_the_section_changes_again(self) -> None:
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        block.locator(".rich").first.click()
        page.keyboard.type("Changed. ")
        page.locator("body").click(position={"x": 5, "y": 5})
        block.locator("[data-content-offer]").wait_for()
        block.get_by_role("button", name="Keep mine").click()
        page.locator("#save-button").click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "dismissing did nothing")

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "a dismissal did not survive a reload")

        block.locator(".rich").first.click()
        page.keyboard.type("More. ")
        page.locator("body").click(position={"x": 5, "y": 5})
        expect(block.locator("[data-content-offer]"), "editing a dismissed section did not offer it again").to_have_count(1)

    def test_refreshing_offers_never_changes_the_report(self) -> None:
        """The refresh runs inside a reportchange listener. A write there would call scheduleSave,
        which dispatches reportchange again -- an unbounded save loop eating the one backup file."""
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        # main.dataset.report is only ever read, so comparing it proved nothing. A write inside the
        # listener goes through scheduleSave, which marks the page unsaved synchronously and then PUTs.
        puts = []
        page.on("request", lambda request: request.method == "PUT" and puts.append(request.url))
        save_state = page.locator("#save-button")
        self.assertNotEqual(save_state.get_attribute("data-save-state"), "unsaved")
        page.evaluate("document.dispatchEvent(new Event('reportchange'))")
        self.assertNotEqual(save_state.get_attribute("data-save-state"), "unsaved", "the offer refresh changed the report")
        self.assertEqual(puts, [], "the offer refresh saved the report")

    def test_emptying_the_installed_steps_offers_them_again(self) -> None:
        """A decline is permanent, an install is not: the record of installing describes content that
        is no longer there. The two neighbouring tests only pass because their fixture types a step."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.tested_channels = ["web", "api"]
        report.scope_targets.append(ScopeTarget(target_id="tgt_api", environment="production", channel="api", value="https://prod-api.example.test"))
        finding.scope = Scope(mode="custom", target_ids=["tgt_browser", "tgt_api"])
        finding.library_ref = LibraryRef(library_id="VDB-036", source_id="VDB-036", inserted_at=report.saved_at)
        finding.poc_variants = ["web", "api"]
        finding.poc_variant_declined = []
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items = [ListItem(runs=[])]
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        offer = page.locator('.content-block[data-content-type="proof_of_concept"] .poc-offer')
        self.assertEqual(offer.count(), 1, "steps that were installed and then deleted were not offered again")
        self.assertEqual(offer.get_attribute("data-poc-offer"), "web api")

    def test_browser_readiness_verdict_matches_server_generation_issues(self) -> None:
        """The scope and completeness rules live in both Python and JavaScript. If they ever
        disagree the tester is told a report is ready that the server then refuses, so pin
        the two together over the cases where the rules are easiest to get wrong."""

        def unchanged(report, finding):
            return None

        def blank_caption(report, finding):
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            next(fragment for fragment in proof.fragments if fragment.type == "image").caption = "   "

        def placeholder_text(report, finding):
            next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="(insert version here)")]

        def no_affected_location(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[])

        def missing_rating(report, finding):
            finding.severity = None

        def untouched_supporting_slot(report, finding):
            # The finding covers production only, so an empty non-production slot is a supporting
            # image nobody has started: both sides leave it out rather than demand it.
            report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
            report.engagement.tested_environments = ["production", "non_production"]
            report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            proof.fragments.append(ImageFragment(frag_id="f_supporting", type="image", environment="non_production", evidence_id=None, caption=""))

        def started_supporting_image_without_an_upload(report, finding):
            untouched_supporting_slot(report, finding)
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            next(fragment for fragment in proof.fragments if fragment.frag_id == "f_supporting").caption = "Same response in UAT"

        def untested_environment_image(report, finding):
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            proof.fragments.append(ImageFragment(frag_id="f_untested", type="image", environment="non_production", evidence_id=None, caption="From before Non-Production was unticked"))

        # Every case above runs on the open_new finding ready_report builds, which has no
        # in_conclusion section at all. These two are the first that make the section exist, so
        # without them the conclusion rules are invisible to this contract in both directions.
        def default_conclusion_left_in_place(report, finding):
            finding.status = "open_previously_discovered"
            self._fill_retest_history(report, finding)

        def conclusion_section_emptied(report, finding):
            finding.status = "open_previously_discovered"
            self._fill_retest_history(report, finding).fragments = []

        def quoted_step_before_default_conclusion(report, finding):
            # The only case where the sentence is not the whole paragraph. A client that still
            # matches whole paragraphs reports nothing here while the server reports an issue.
            finding.status = "open_previously_discovered"
            conclusion = self._fill_retest_history(report, finding)
            conclusion.fragments[0].runs = [Run(text="Observe the balance of another user. "), *conclusion.fragments[0].runs]

        def duplicate_additional_locations(report, finding):
            finding.scope = Scope(mode="custom", target_ids=["tgt_browser"], custom_locations={"production": {"web": ["https://dupe.test", "  https://dupe.test  "]}})

        def carried_section_holding_work(report, finding):
            # Flipping to "open new" hides the previous proof; neither side may then ask for it.
            finding.status = "open_previously_discovered"
            main.provision(finding)
            previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
            next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Last year's step")]
            finding.status = "open_new"

        def previous_proof_image_without_an_environment(report, finding):
            finding.status = "open_previously_discovered"
            main.provision(finding)
            previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
            next(fragment for fragment in previous.fragments if fragment.type == "image").environment = None

        # The fixture is JH, where the pair is neither shown nor required, so both cases have to
        # move the segment or the rule is invisible to this test in either language.
        def asia_without_cvss(report, finding):
            report.engagement.segment = "Asia"

        def asia_with_cvss(report, finding):
            report.engagement.segment = "Asia"
            finding.cvss_score = "9.8"
            finding.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"

        # The editor opens for a report with no findings, so both sides must call it ready.
        def no_findings(report, finding):
            report.vulnerabilities = []

        # Scope-rule drift is invisible here: a finding with no location cannot open the editor, so
        # the loop below never reaches the comparison. Those cases live in the Findings-gate test.
        cases = [unchanged, blank_caption, placeholder_text, no_affected_location, missing_rating, untouched_supporting_slot, started_supporting_image_without_an_upload, untested_environment_image, default_conclusion_left_in_place, conclusion_section_emptied, quoted_step_before_default_conclusion, duplicate_additional_locations, carried_section_holding_work, previous_proof_image_without_an_environment, asia_without_cvss, asia_with_cvss, no_findings]
        for case in cases:
            with self.subTest(case=case.__name__):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                case(report, finding)
                # Mirror the save route so both sides judge the same canonical state.
                acceptance.provision(report)
                main.workspace.save(report)

                server_issues = generation_issues(main.workspace.load(report_id))
                self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
                if "/findings" in self.page.url:
                    # The server refused to open the editor, so it must have had a reason.
                    self.assertTrue(server_issues, f"{case.__name__}: editor was blocked but the server reports no issues")
                    continue

                self.page.wait_for_selector("#issue-count")
                browser_state = self.page.locator("#issue-count").get_attribute("data-state")
                self.assertEqual(
                    browser_state,
                    "ready" if not server_issues else "issues",
                    f"{case.__name__}: browser says {browser_state!r} but the server reports {server_issues}",
                )
                self.assertEqual(
                    self.page.get_by_role("button", name="Generate Report").is_enabled(),
                    not server_issues,
                    f"{case.__name__}: generate button does not match server readiness",
                )

    def test_additional_information_shows_only_the_fields_that_apply(self) -> None:
        """The section has no visibility rule of its own: it appears when at least one of its fields
        does. That leaves exactly one hidden cell, and a rule stated twice could not."""
        cases = [
            ("JH", "open_new", []),
            ("JH", "open_previously_discovered", ["Severity Review Tickets"]),
            ("JH", "resolved", ["Severity Review Tickets"]),
            ("Asia", "open_new", ["CVSS Score", "CVSS Vector"]),
            ("Asia", "open_previously_discovered", ["Severity Review Tickets", "CVSS Score", "CVSS Vector"]),
            ("Asia", "resolved", ["Severity Review Tickets", "CVSS Score", "CVSS Vector"]),
        ]
        for segment, status, expected in cases:
            with self.subTest(segment=segment, status=status):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                report.engagement.segment = segment
                finding.status = status
                acceptance.provision(report)
                main.workspace.save(report)

                self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
                self.page.wait_for_selector("#issue-count")
                block = self.page.locator('[data-content-type="additional_information"]')
                if not expected:
                    self.assertEqual(block.count(), 0, "the section appeared with nothing visible inside it")
                    continue
                self.assertEqual(block.count(), 1, "the section is missing while a field applies")
                self.assertEqual(block.locator(".fragment-head .tag").all_text_contents(), expected)

    def test_additional_information_pairs_its_fields_two_to_a_row(self) -> None:
        """Which of the three fields exist depends on the segment and the status, so the odd one out
        takes the whole row rather than leaving a half-empty column beside it."""
        measure = """() => {
          const cards = [...document.querySelectorAll('[data-content-type="additional_information"] .fragment')];
          const rows = new Map();
          for (const card of cards) {
            const top = Math.round(card.getBoundingClientRect().top);
            const key = [...rows.keys()].find(value => Math.abs(value - top) < 4) ?? top;
            rows.set(key, [...(rows.get(key) || []), card.querySelector(".fragment-head .tag").textContent]);
          }
          return [...rows.entries()].sort((left, right) => left[0] - right[0]).map(entry => entry[1]);
        }"""
        cases = [
            ("JH", "open_previously_discovered", [["Severity Review Tickets"]]),
            ("Asia", "open_new", [["CVSS Score", "CVSS Vector"]]),
            ("Asia", "open_previously_discovered", [["Severity Review Tickets", "CVSS Score"], ["CVSS Vector"]]),
        ]
        page = self.page
        page.set_viewport_size({"width": 1440, "height": 900})
        for segment, status, expected in cases:
            with self.subTest(segment=segment, status=status):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                report.engagement.segment = segment
                finding.status = status
                acceptance.provision(report)
                main.workspace.save(report)

                page.goto(f"{self.base_url}/reports/{report_id}/edit")
                page.wait_for_selector('[data-content-type="additional_information"] .fragment')
                # Grouped by the top edge each card lands on, so this reads the layout rather than
                # the class names that were meant to produce it.
                self.assertEqual(page.evaluate(measure), expected)

        # A textarea opens at two rows and nothing else in the row does, so the tickets box would
        # stand 16px taller than the field beside it.
        heights = page.evaluate(
            """() => Object.fromEntries([...document.querySelectorAll('[data-content-type="additional_information"] .fragment')]
                 .map(card => [card.querySelector(".tag").textContent,
                               Math.round(card.querySelector(".additional-input").getBoundingClientRect().height)]))"""
        )
        self.assertEqual(
            heights["Severity Review Tickets"], heights["CVSS Score"],
            f"the boxes sharing a row are different heights: {heights}",
        )

        # Too narrow to carry two fields, so the pair stacks the way the content sections do.
        # Layout is read synchronously and the stacking is a container query, so no wait is needed.
        page.set_viewport_size({"width": 700, "height": 900})
        self.assertEqual(
            page.evaluate(measure),
            [["Severity Review Tickets"], ["CVSS Score"], ["CVSS Vector"]],
            "the columns survived a pane too narrow to read them in",
        )

    def test_a_typed_cvss_value_survives_a_reload_and_a_trip_off_asia(self) -> None:
        """Keeping the value is the whole of the keep-and-hide rule: nothing clears it, so moving
        the segment away and back has to return it untouched."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        acceptance.provision(report)
        main.workspace.save(report)

        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.page.wait_for_selector('[data-content-type="additional_information"]')
        self.page.fill('[data-fragment-id$=":cvss_score"] .additional-input', "9.8")
        self.page.fill('[data-fragment-id$=":cvss_vector"] .additional-input', "CVSS:3.1/AV:N")
        self.page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=10_000)

        stored = main.workspace.load(report_id)
        self.assertEqual((stored.vulnerabilities[0].cvss_score, stored.vulnerabilities[0].cvss_vector), ("9.8", "CVSS:3.1/AV:N"))

        stored.engagement.segment = "JH"
        main.workspace.save(stored)
        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.page.wait_for_selector("#issue-count")
        self.assertEqual(self.page.locator('[data-fragment-id$=":cvss_score"]').count(), 0, "a JH report drew the field")
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].cvss_score, "9.8", "hiding the field cleared it")

    def test_a_cvss_review_jump_focuses_the_missing_field_card(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        finding.cvss_score = ""
        finding.cvss_vector = ""
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        page.get_by_role("button", name="Go to Additional Information").first.click()
        target = page.locator('[data-fragment-id$=":cvss_score"]')
        page.wait_for_selector('[data-fragment-id$=":cvss_score"].is-review-target', timeout=5_000)
        self.assertTrue(target.evaluate("node => node === document.activeElement"))

    def test_additional_information_validation_message_matches_the_server(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        finding.cvss_score = "9.8"
        finding.cvss_vector = "CVSS:3.1/AV:N"
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        score = page.get_by_role("textbox", name="CVSS Score")
        candidate = main.workspace.load(report_id)
        for invalid_value in ("9.8a", "9.8Ν"):
            with self.subTest(invalid_value=invalid_value):
                score.fill(invalid_value)
                candidate.vulnerabilities[0].cvss_score = invalid_value
                self.assertEqual(
                    score.evaluate("input => input.validationMessage"),
                    finding_input_issues(candidate)[0],
                )

    def test_additional_information_uses_the_servers_unicode_categories(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        finding.cvss_score = "9.8"
        finding.cvss_vector = "CVSS:3.1/AV:N"
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        candidate = main.workspace.load(report_id)
        valid_values = {"cvss_score": "9.8", "cvss_vector": "CVSS:3.1/AV:N"}
        cases = (
            ("CVSS Score", "cvss_score", f"9.{chr(0x11DE0)}"),
            ("CVSS Vector", "cvss_vector", f"CVSS:3.1/AV:{chr(0x088F)}"),
        )
        for label, key, invalid_value in cases:
            with self.subTest(label=label):
                page.get_by_role("textbox", name=label).fill(invalid_value)
                setattr(candidate.vulnerabilities[0], key, invalid_value)
                server_issue = finding_input_issues(candidate)[0]
                browser_issue = page.get_by_role("textbox", name=label).evaluate("input => input.validationMessage")
                setattr(candidate.vulnerabilities[0], key, valid_values[key])
                self.assertEqual(
                    browser_issue,
                    server_issue,
                )

    def test_invalid_cvss_blocks_generation_until_corrected(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        finding.cvss_score = "9.8"
        finding.cvss_vector = "CVSS:3.1/AV:N"
        acceptance.provision(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector('#issue-count[data-state="ready"]')
        score = page.get_by_role("textbox", name="CVSS Score")
        score.fill("9.8a")
        page.wait_for_selector('#issue-count[data-state="issues"]', timeout=5_000)
        self.assertFalse(page.get_by_role("button", name="Generate Report").is_enabled())
        score.fill("9.8")
        page.wait_for_selector('#issue-count[data-state="ready"]')
        self.assertTrue(page.get_by_role("button", name="Generate Report").is_enabled())

    def test_browser_findings_gate_matches_server_finding_completeness(self) -> None:
        """The sibling of the readiness contract test, for the rules it cannot see.

        A finding with no location never opens the editor, so the readiness panel is the wrong
        place to catch `scopeHasLocation` drifting from `scope_has_location`. The observable that
        does move is the Findings gate: whether Next carries the tester through to Content. If the
        client is laxer than the server the tester is bounced straight back, and if it is stricter
        they are stranded on a report the server would have accepted."""

        def selected_target(report, finding):
            finding.scope = Scope(mode="custom", target_ids=["tgt_browser"])

        def typed_endpoint_only(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["https://typed.example.test/admin"]}})

        def comment_only(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["# ask the owner which host"]}})

        def whitespace_only(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["   ", "\t"]}})

        def outside_coverage(report, finding):
            # Non-production is not tested on this report, so the line resolves to nothing.
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"non_production": {"web": ["https://uat.example.test"]}})

        def comment_beside_a_real_endpoint(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["# the note", "https://real.example.test"]}})

        def nothing_at_all(report, finding):
            finding.scope = Scope(mode="custom", target_ids=[])

        # The gate counts findings as well as checking them: none at all is a report the tester may generate.
        def no_findings(report, finding):
            report.vulnerabilities = []

        for case in [selected_target, typed_endpoint_only, comment_only, whitespace_only, outside_coverage, comment_beside_a_real_endpoint, nothing_at_all, no_findings]:
            with self.subTest(case=case.__name__):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                case(report, finding)
                acceptance.provision(report)
                main.workspace.save(report)

                stored = main.workspace.load(report_id)
                server_allows = all(main.finding_is_complete(item, stored) for item in stored.vulnerabilities)

                page = self.page
                page.goto(f"{self.base_url}/reports/{report_id}/findings")
                page.wait_for_selector("#finding-summary b")
                # Watch for the navigation request, not the resulting URL: when the client is laxer
                # than the server it still fires the request and the server's redirect hides it, so
                # the landing page looks identical whether or not the two agree. A refusal marks the
                # table instead, so each case waits for whichever happens first, not for a timeout.
                edit_requests = []
                watcher = lambda request: request.url.rstrip("/").endswith("/edit") and edit_requests.append(request.url)
                page.on("request", watcher)
                refused = page.locator('#findings[data-validation-attempted="true"]')
                self.assertEqual(refused.count(), 0, "the gate was marked before Next was pressed")
                page.locator("#next").click()
                deadline = time.monotonic() + 10
                while not edit_requests and not self._count_or_zero(refused):
                    self.assertLess(time.monotonic(), deadline, f"{case.__name__}: Next neither navigated nor refused")
                    page.wait_for_timeout(25)
                page.remove_listener("request", watcher)
                client_allows = bool(edit_requests)

                self.assertEqual(
                    client_allows,
                    server_allows,
                    f"{case.__name__}: the Findings gate {'let the tester through' if client_allows else 'refused'} "
                    f"but finding_is_complete says {server_allows}",
                )

    def test_deleting_a_finding_with_work_in_it_asks_first(self) -> None:
        """Nothing on the server stops a delete, so the confirmation is the only guard."""
        report_id = self.ready_report(include_finding=True)
        report, _ = self._complete_finding(report_id)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#findings button.danger")
        page.locator("#findings button.danger").first.click()
        page.wait_for_selector("[data-dialog]")
        self.assertIn("screenshot", page.locator("[data-dialog] .vr-dialog").inner_text())
        page.click('[data-dialog-action="cancel"]')
        page.wait_for_selector("[data-dialog]", state="detached")
        self.assertEqual(page.locator("#findings button.danger").count(), 1, "cancelling still deleted the finding")

        page.locator("#findings button.danger").first.click()
        page.click('[data-dialog-action="confirm"]')
        page.wait_for_selector("#save-button[data-save-state='saved']", timeout=15000)
        self.assertEqual(main.workspace.load(report_id).vulnerabilities, [])
        self.assertEqual(main.workspace.load(report_id).evidence, {}, "deleting the finding left its evidence behind")

    def _generatable_report(self) -> str:
        """A report with one complete finding, with Word patched out so generating runs on every platform."""
        word = patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents)
        word.start()
        self.addCleanup(word.stop)
        report_id = self.ready_report(include_finding=True)
        report, _ = self._complete_finding(report_id)
        main.workspace.save(report)
        return report_id

    def _hold_generation(self, report_id: str) -> None:
        """Park the page's generate request until it calls window.releaseGenerate()."""
        self.page.evaluate(
            """reportId => {
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init = {}) => {
                    const url = typeof input === "string" ? input : input.url;
                    if (url.startsWith(`/reports/${reportId}/generate`) && init.method === "POST") {
                        return new Promise(resolve => { window.releaseGenerate = () => resolve(originalFetch(input, init)); });
                    }
                    return originalFetch(input, init);
                };
            }""",
            report_id,
        )

    def _expect_generated(self):
        return self.page.expect_response(lambda response: "/generate" in response.url and response.request.method == "POST", timeout=15_000)

    def test_generate_button_holds_its_place_and_width_from_click_to_finish(self) -> None:
        """The success notice once shared the bottom bar and pushed the button left, and the shorter busy label narrowed it."""
        report_id = self._generatable_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        button = page.locator("#generate-report")
        expect(button).to_be_enabled()
        idle = button.bounding_box()
        self._hold_generation(report_id)
        button.click()
        page.wait_for_function("typeof window.releaseGenerate === 'function'")
        expect(button).to_have_text("Generating...")
        self.assertEqual(button.bounding_box(), idle, "the button changed size or place while generating")
        with self._expect_generated() as generated:
            page.evaluate("window.releaseGenerate()")
        self.assertTrue(generated.value.ok)
        expect(button).to_have_text("Generate Report")
        self.assertEqual(button.bounding_box(), idle, "the button moved once the report was generated")

    def test_word_report_popup_copies_its_path_or_selects_it_when_the_browser_refuses(self) -> None:
        report_id = self._generatable_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        # Stand in for the browser's clipboard, so the test never writes to the machine's real one.
        rows = [
            ("copied", "text => { window.copiedText = text; return Promise.resolve(); }", "Copied", "window.copiedText"),
            ("refused", "() => Promise.reject(new DOMException('Write permission denied.', 'NotAllowedError'))", "Copy failed", "getSelection().toString()"),
        ]
        for case, write_text, label, read_back in rows:
            with self.subTest(clipboard=case):
                page.evaluate(f"() => {{ navigator.clipboard.writeText = {write_text}; }}")
                with self._expect_generated() as generated:
                    page.get_by_role("button", name="Generate Report").click()
                path = generated.value.json()["path"]
                popup = page.get_by_role("dialog", name="Your Word report is ready")
                popup.get_by_role("button", name="Copy path").click()
                expect(popup.get_by_role("button", name=label)).to_be_visible()
                self.assertEqual(page.evaluate(read_back), path)
                popup.get_by_role("button", name="OK").click()
                expect(popup).to_be_hidden()

    def test_word_report_popup_waits_for_a_prompt_the_tester_has_open(self) -> None:
        """Generating takes a while, and a prompt opened meanwhile must not be answered for the tester."""
        report_id = self._generatable_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self._hold_generation(report_id)
        page.get_by_role("button", name="Generate Report").click()
        page.wait_for_function("typeof window.releaseGenerate === 'function'")
        page.evaluate("() => { window.earlierAnswer = window.vrDialog.confirm({title: 'Earlier question', message: 'Asked while the report was generating.'}); }")
        earlier = page.get_by_role("dialog", name="Earlier question")
        expect(earlier).to_be_visible()
        with self._expect_generated():
            page.evaluate("window.releaseGenerate()")
        expect(page.locator("#generate-report")).to_have_text("Generate Report")
        expect(earlier).to_be_visible()
        popup = page.get_by_role("dialog", name="Your Word report is ready")
        expect(popup).to_have_count(0)
        earlier.get_by_role("button", name="OK").click()
        self.assertTrue(page.evaluate("window.earlierAnswer"))
        expect(popup).to_be_visible()

    def test_complete_report_saves_generated_docx_to_generated_folder(self) -> None:
        # The server runs in this process, so patching Word out here lets the test run on every platform.
        word = patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents)
        word.start()
        self.addCleanup(word.stop)
        self.page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 60000")
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        # The file name carries the report year; pin it so the test does not expire with the calendar.
        report.engagement.report_date = date(2026, 1, 3)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image_data = png_bytes(2, 2)
        evidence_id = "ev_browser_generate"
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data).hexdigest(), uploaded_at=report.saved_at)
        draft_path = main.workspace.find_path(report_id)
        evidence_path = draft_path.parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        generate = page.get_by_role("button", name="Generate Report")
        self.assertTrue(generate.is_enabled())
        page.evaluate(
            """reportId => {
                const originalFetch = window.fetch.bind(window);
                window.generateRequestOrder = [];
                window.fetch = (input, init = {}) => {
                    const url = typeof input === "string" ? input : input.url;
                    if (url === `/reports/${reportId}` && init.method === "PUT") {
                        window.generateRequestOrder.push("PUT");
                        return new Promise(resolve => {
                            window.releaseGenerateSave = () => resolve(originalFetch(input, init));
                        });
                    }
                    if (url === `/reports/${reportId}/generate` && init.method === "POST") {
                        window.generateRequestOrder.push("POST");
                    }
                    return originalFetch(input, init);
                };
            }""",
            report_id,
        )
        description = page.locator(".content-block").filter(has_text="Description").locator(".rich").first
        description.fill("Saved immediately before generation")
        self.assertEqual(page.locator("#save-button").get_attribute("data-save-state"), "unsaved")
        page.evaluate(
            "window.VulnReportDiagnostics.show(new Error('Keep this warning'), 'unrelated_warning', {title:'Unrelated warning', kind:'warning'})"
        )
        generate.click()
        page.locator("#generate-report").filter(has_text="Saving...").wait_for()
        self.assertEqual(page.evaluate("window.generateRequestOrder"), ["PUT"])
        page.evaluate("window.releaseGenerateSave()")
        popup = page.get_by_role("dialog", name="Your Word report is ready")
        popup.wait_for(timeout=15_000)
        self.assertEqual(page.evaluate("window.generateRequestOrder"), ["PUT", "POST"])
        page.get_by_role("heading", name="Unrelated warning").wait_for()
        persisted_description = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "description")
        self.assertEqual(persisted_description.fragments[0].runs[0].text, "Saved immediately before generation")
        output_path = main.GENERATED / "JH - Browser QA - Annual Pentest 2026.docx"
        popup_text = popup.inner_text()
        self.assertIn(f'"{output_path.name}"', popup_text)
        self.assertIn(str(output_path), popup_text)
        rendered = Document(output_path)
        text = "\n".join([*(paragraph.text for paragraph in rendered.paragraphs), *(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)])
        self.assertIn("Browser finding", text)
        self.assertNotIn("{{", text)

    def test_editable_import_restores_a_supporting_image_from_generated_docx(self) -> None:
        word = patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents)
        word.start()
        self.addCleanup(word.stop)
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.report_date = date(2026, 1, 3)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 3), end_date=date(2026, 1, 4))
        report.scope_targets.append(ScopeTarget(
            target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"
        ))
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        image_data = png_bytes(3, 2)
        evidence_id = "ev_import_supporting"
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.write_bytes(image_data)
        report.evidence[evidence_id] = EvidenceItem(
            file=f"evidence/{evidence_id}.png",
            original_name="import-supporting.png",
            width_px=3,
            height_px=2,
            sha256=hashlib.sha256(image_data).hexdigest(),
            uploaded_at=report.saved_at,
        )
        proof.fragments.append(ImageFragment(
            frag_id="f_import_supporting",
            type="image",
            environment="non_production",
            evidence_id=evidence_id,
            caption="Supporting response survives editable import",
        ))
        main.workspace.save(report)
        self.assertEqual(generation_issues(report), [])

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        with page.expect_response(lambda response: response.url.endswith(f"/reports/{report_id}/generate") and response.request.method == "POST") as generated_response:
            page.get_by_role("button", name="Generate Report").click()
        generated = generated_response.value.json()
        generated_path = Path(generated["path"])
        self.assertTrue(generated_path.is_file())

        page.goto(f"{self.base_url}/")
        page.locator("#import-report").set_input_files({
            "name": generated_path.name,
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": generated_path.read_bytes(),
        })
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("button", name="Import as editable draft").click()
        result = page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for(timeout=15_000)
        result.get_by_role("button", name="Open Setup").click()
        page.wait_for_url("**/reports/*/setup")
        imported_id = page.url.split("/reports/")[1].split("/")[0]

        imported = main.workspace.load(imported_id)
        imported_finding = imported.vulnerabilities[0]
        imported_proof = next(content for content in imported_finding.contents if content.type == "proof_of_concept")
        imported_image = next(
            fragment for fragment in imported_proof.fragments
            if fragment.type == "image" and fragment.caption == "Supporting response survives editable import"
        )
        targets = {target.target_id: target for target in imported.scope_targets}
        affected = {targets[target_id].environment for target_id in imported_finding.scope.target_ids}
        self.assertNotIn("non_production", affected, "the imported supporting image became an affected location")
        self.assertEqual(imported_image.environment, "non_production")
        self.assertIsNotNone(imported_image.evidence_id)
        imported_evidence = imported.evidence[imported_image.evidence_id]
        self.assertTrue((main.workspace.find_path(imported_id).parent / imported_evidence.file).is_file())

    def test_list_textareas_show_markers_and_store_non_empty_lines(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        description = page.locator(".content-block").filter(has_text="Description")
        description.get_by_role("combobox", name="Add fragment to Description").select_option("numbered_list")
        description.get_by_role("combobox", name="Add fragment to Description").select_option("bulleted_list")

        numbered = description.get_by_role("textbox", name="Numbered list items")
        bulleted = description.get_by_role("textbox", name="Bulleted list items")
        self.assertLessEqual(numbered.evaluate("input => input.offsetHeight"), 40)
        self.assertLessEqual(bulleted.evaluate("input => input.offsetHeight"), 40)
        long_step = "Review the complete account authorization response and confirm that a customer cannot retrieve another user's account details even when the supplied identifier is valid and correctly formatted."
        numbered.fill(f"Authenticate as a customer\n\n{long_step}\nChange the account identifier")
        bulleted.fill("Enforce object authorization\nLog denied requests\nAdd regression coverage")
        numbered_markers = numbered.locator("xpath=..").locator(".list-marker")
        bulleted_markers = bulleted.locator("xpath=..").locator(".list-marker")
        self.assertEqual(numbered_markers.all_text_contents(), ["1.", "", "2.", "3."])
        self.assertEqual(bulleted_markers.all_text_contents(), ["•", "•", "•"])
        self.assertLess(numbered.locator("xpath=..").locator(".list-gutter").evaluate("gutter => gutter.getBoundingClientRect().width"), 32)
        self.assertLess(bulleted.locator("xpath=..").locator(".list-gutter").evaluate("gutter => gutter.getBoundingClientRect().width"), 32)
        numbered_tops = numbered_markers.evaluate_all("markers => markers.map(marker => marker.getBoundingClientRect().top)")
        self.assertGreater(numbered_tops[3] - numbered_tops[2], numbered_tops[1] - numbered_tops[0])
        self.assertEqual(description.get_by_text("Add item", exact=True).count(), 0)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function("input => input.scrollHeight <= input.offsetHeight", arg=numbered.element_handle())
        self.assertFalse(numbered.evaluate("input => input.getBoundingClientRect().right > document.documentElement.clientWidth"))
        self.assertTrue(numbered.evaluate("input => input.parentElement.querySelector('.list-marker:last-child').getBoundingClientRect().bottom <= input.getBoundingClientRect().bottom"))
        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        persisted = main.workspace.load(report_id)
        fragments = next(content for content in persisted.vulnerabilities[0].contents if content.type == "description").fragments
        numbered_fragment = next(fragment for fragment in fragments if fragment.type == "numbered_list")
        bulleted_fragment = next(fragment for fragment in fragments if fragment.type == "bulleted_list")
        self.assertEqual([item.runs[0].text for item in numbered_fragment.items], ["Authenticate as a customer", long_step, "Change the account identifier"])
        self.assertEqual([item.runs[0].text for item in bulleted_fragment.items], ["Enforce object authorization", "Log denied requests", "Add regression coverage"])

    def test_custom_affected_endpoints_use_one_autogrowing_textarea_per_environment(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        report.scope_targets.append(ScopeTarget(target_id="tgt_browser_uat", environment="non_production", channel="web", value="https://test.example.test"))
        main.workspace.save(report)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        production = page.get_by_role("textbox", name="Production affected endpoints", exact=True)
        non_production = page.get_by_role("textbox", name="Non-Production affected endpoints", exact=True)
        self.assertLessEqual(production.evaluate("input => input.offsetHeight"), 32)
        self.assertLessEqual(non_production.evaluate("input => input.offsetHeight"), 32)
        long_endpoint = "https://prod.example.test/api/v1/accounts/1234567890/transactions?include=beneficiaries,payments,statements,and-a-long-wrapped-query-value"
        production.fill(f"{long_endpoint}\n\nPOST /api/v1/transfers/validate")
        non_production.fill("https://test.example.test/debug/error\nGET /api/v1/health/details")
        self.assertEqual(production.locator("xpath=..").locator(".affected-endpoint-marker").all_text_contents(), ["•", "", "•"])
        self.assertEqual(non_production.locator("xpath=..").locator(".affected-endpoint-marker").all_text_contents(), ["•", "•"])
        self.assertGreater(production.evaluate("input => input.offsetHeight"), 32)
        self.assertEqual(page.get_by_role("button", name="Add custom location").count(), 0)
        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        persisted = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(persisted.scope.custom_locations["production"]["web"], [long_endpoint, "POST /api/v1/transfers/validate"])
        self.assertEqual(persisted.scope.custom_locations["non_production"]["web"], ["https://test.example.test/debug/error", "GET /api/v1/health/details"])
        self.assertEqual(persisted.scope.target_ids, ["tgt_browser"])

    def test_manager_actions_and_legacy_repair(self) -> None:
        report_id = self.ready_report()
        legacy = main.workspace.create_report()
        legacy_path = main.workspace.find_path(legacy.report_id)
        legacy_draft = read_json(legacy_path)
        legacy_draft["vulnerabilities"] = [{
            "uid": "v_legacy",
            "contents": [
                {"type": "description", "fragments": [{"frag_id": "f_duplicate", "type": "paragraph", "runs": []}]},
                {"type": "proof_of_concept", "fragments": [{"frag_id": "f_duplicate", "type": "paragraph", "runs": []}]},
            ],
        }]
        atomic_write_json(legacy_path, legacy_draft)

        page = self.page
        page.goto(f"{self.base_url}/")
        legacy_row = page.locator(".legacy-report").filter(has_text=legacy.report_id)
        legacy_row.get_by_role("button", name="Repair duplicate IDs").click()
        page.get_by_text("Legacy draft repaired.").wait_for()

        page.locator(".app-group").filter(has_text=report_id).evaluate("element => { element.open = true; }")
        report_row = page.locator(".report-row").filter(has_text=report_id)
        report_row.get_by_role("button", name="Rename", exact=True).click()
        report_row.get_by_label("Application name").fill("Renamed in browser")
        report_row.get_by_role("button", name="Save").click()
        page.get_by_text("Report renamed.").wait_for()
        report_group = page.locator(".app-group").filter(has_text=report_id)
        report_group.evaluate("element => { element.open = true; }")
        report_row = page.locator(".report-row").filter(has_text=report_id)
        report_row.get_by_text("Renamed in browser", exact=True).wait_for()

        with page.expect_download() as download_info:
            report_row.get_by_role("link", name="Export", exact=True).click()
        download = download_info.value
        self.assertTrue(download.suggested_filename.endswith(".zip"))

        report_row.get_by_role("button", name="Duplicate", exact=True).click()
        page.wait_for_url("**/setup")
        duplicate_id = page.url.split("/reports/")[1].split("/")[0]
        self.assertNotEqual(duplicate_id, report_id)

        page.goto(f"{self.base_url}/")
        page.locator("#import-report").set_input_files(download.path())
        page.wait_for_url("**/setup")
        imported_id = page.url.split("/reports/")[1].split("/")[0]
        self.assertNotIn(imported_id, {report_id, duplicate_id})

        page.goto(f"{self.base_url}/")
        page.locator(".app-group").filter(has_text=report_id).locator("summary").click()
        report_row = page.locator(".report-row").filter(has_text=report_id)
        report_row.get_by_role("button", name="Delete", exact=True).click()
        page.click('[data-dialog-action="confirm"]')
        page.get_by_text("Report deleted.").wait_for()
        page.locator(".report-row").filter(has_text=report_id).wait_for(state="detached")

    def test_docx_import_offers_both_modes_and_backing_out_sends_no_second_request(self) -> None:
        """Cancel and Escape both back out after the one classifying request: nothing is imported and
        the file input is cleared. The .zip name on a Word file shows the dialog follows the bytes."""
        document = self.importable_docx()
        cases = [
            ("Cancel button", "report.zip", "application/zip", lambda dialog: dialog.get_by_role("button", name="Cancel").click()),
            ("Escape key", "report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", lambda dialog: self.page.keyboard.press("Escape")),
        ]
        for way, name, mime, back_out in cases:
            with self.subTest(way=way):
                before = set(self.root.glob("apps/**/draft.json"))
                requests = []
                watcher = lambda request: requests.append(request) if request.method == "POST" and request.url.endswith("/reports/import") else None
                self.page.on("request", watcher)
                self.page.goto(f"{self.base_url}/")
                self.page.locator("#import-report").set_input_files({"name": name, "mimeType": mime, "buffer": document})

                dialog = self.page.get_by_role("dialog")
                dialog.get_by_role("heading", name="Import report DOCX").wait_for()
                self.assertTrue(dialog.get_by_role("button", name="Import as editable draft").is_visible())
                self.assertTrue(dialog.get_by_role("button", name="Import as retest draft").is_visible())
                back_out(dialog)
                self.page.get_by_text("Import cancelled.").wait_for()
                self.page.remove_listener("request", watcher)
                self.assertEqual(len(requests), 1)
                self.assertEqual(set(self.root.glob("apps/**/draft.json")), before)
                self.assertEqual(self.page.locator("#import-report").input_value(), "")

    def test_a_failed_second_import_request_after_mode_choice_can_be_retried(self) -> None:
        """The first /reports/import call only classifies the file; the mode choice fires a second
        call. If that second call fails (a dropped connection, a server error), the tester must see
        the failure and be able to retry without reloading or re-picking a mode from scratch."""
        document = self.importable_docx()
        before = set(self.root.glob("apps/**/draft.json"))
        attempt = {"count": 0}

        def flaky_second_call(route) -> None:
            attempt["count"] += 1
            if attempt["count"] == 1:
                route.continue_()
            else:
                route.abort()

        self.page.route("**/reports/import", flaky_second_call)
        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("heading", name="Import report DOCX").wait_for()
        dialog.get_by_role("button", name="Import as editable draft").click()

        diagnostic = self.page.locator("#app-diagnostics")
        diagnostic.get_by_role("heading", name="Operation failed").wait_for()
        self.assertEqual(set(self.root.glob("apps/**/draft.json")), before, "a failed second call must not leave a partial report on disk")
        self.assertEqual(self.page.locator("#import-report").input_value(), "", "the file input clears so the same file can be re-picked")

        self.page.unroute("**/reports/import", flaky_second_call)
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("heading", name="Import report DOCX").wait_for()
        dialog.get_by_role("button", name="Import as editable draft").click()
        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        after = set(self.root.glob("apps/**/draft.json"))
        self.assertEqual(len(after - before), 1, "the retry must succeed and write exactly one report")

    def test_reselecting_a_file_while_the_mode_dialog_is_open_replaces_it_cleanly(self) -> None:
        """The mode-choice dialog is a JS singleton: opening a second one settles whatever is
        already open as "cancel". Re-picking the file input while dialog A is still awaiting an
        answer fires a second onchange concurrently with the first still suspended mid-await, so
        this proves the abandoned first import never completes and exactly one report is written."""
        first_document = self.importable_docx()
        second_document = self.importable_docx()
        before = set(self.root.glob("apps/**/draft.json"))
        self.page.goto(f"{self.base_url}/")

        self.page.locator("#import-report").set_input_files({
            "name": "first.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": first_document,
        })
        self.page.get_by_role("dialog").get_by_role("heading", name="Import report DOCX").wait_for()

        # Re-select before answering dialog A; this fires a second onchange while the first is
        # still suspended awaiting the user's mode choice.
        self.page.locator("#import-report").set_input_files({
            "name": "second.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": second_document,
        })
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("heading", name="Import report DOCX").wait_for()
        self.assertEqual(dialog.count(), 1, "the abandoned first dialog must not linger alongside a second")
        dialog.get_by_role("button", name="Import as editable draft").click()

        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        result.get_by_role("button", name="Stay on reports").click()
        self.page.get_by_text("Report imported.").wait_for()

        self.assertEqual(self.page.get_by_role("dialog").count(), 0, "no stray dialog is left open")
        self.assertEqual(self.page.locator("#import-report").input_value(), "")
        after = set(self.root.glob("apps/**/draft.json"))
        self.assertEqual(len(after - before), 1, "the abandoned first selection must not also import")

    def test_editable_import_of_an_asia_cvss_finding_reaches_ready_state(self) -> None:
        """The Section/CVSS table round trip is parser-tested in isolation, and the Asia CVSS
        readiness rule is contract-tested against a directly-saved report. Neither proves that an
        editable DOCX import of the same finding lands the browser at the same "ready" verdict, so
        this drives the real upload and checks Generate is enabled with nothing chosen by hand,
        network access included: the cover gives it back."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        report.engagement.segment = "Asia"
        report.engagement.network = "External"
        finding.cvss_score = "9.8"
        finding.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        acceptance.provision(report)
        main.workspace.save(report)
        server_issues = generation_issues(main.workspace.load(report_id))
        self.assertEqual(server_issues, [], "fixture must itself be generation-clean")
        document = render_report_docx(
            report,
            main_template_path(report, Path(__file__).resolve().parent.parent / "resources"),
            main.workspace.find_path(report_id).parent,
        )

        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "asia.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as editable draft").click()
        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        result.get_by_role("button", name="Open Setup").click()
        self.page.wait_for_url("**/reports/*/setup")
        imported_id = self.page.url.split("/reports/")[1].split("/")[0]
        self.assertEqual(self.page.get_by_label("Network Access").input_value(), "External")

        self.page.goto(f"{self.base_url}/reports/{imported_id}/edit")
        self.page.wait_for_selector("#issue-count")
        self.assertEqual(self.page.locator("#issue-count").get_attribute("data-state"), "ready")
        self.assertTrue(self.page.get_by_role("button", name="Generate Report").is_enabled())

    def test_retest_docx_import_discloses_rewrites_and_opens_setup(self) -> None:
        document = self.importable_docx()
        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as retest draft").click()

        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as retest draft").wait_for()
        self.assertIn(
            f"1 {STATUS_LABELS['open_new']} finding was changed to {STATUS_LABELS['open_previously_discovered']} for retesting: Browser finding.",
            result.text_content(),
        )
        result.get_by_role("button", name="Open Setup").click()

        self.page.wait_for_url("**/reports/*/setup")
        imported_id = self.page.url.split("/reports/")[1].split("/")[0]
        self.assertEqual(main.workspace.load(imported_id).vulnerabilities[0].status, "open_previously_discovered")

    def test_retest_docx_import_drops_and_discloses_a_closed_finding(self) -> None:
        """Closed is intentionally absent from a retest draft, but the summary must name that
        choice so a tester does not mistake the omitted finding for an import data-loss bug."""
        source_id = self.ready_report(include_finding=True)
        source = main.workspace.load(source_id)
        closed = Vulnerability(
            uid="v_closed_import",
            display_id="002",
            title="Closed browser finding",
            likelihood="low",
            impact="low",
            severity="low",
            status="closed",
            scope=Scope(mode="custom", target_ids=["tgt_browser"]),
        )
        main.provision(closed)
        source.vulnerabilities.append(closed)
        main.workspace.save(source)
        document = render_report_docx(
            source,
            main_template_path(source, Path(__file__).resolve().parent.parent / "resources"),
            main.workspace.find_path(source_id).parent,
            allow_incomplete=True,
        )

        self.page.goto(f"{self.base_url}/")
        self.page.locator("#import-report").set_input_files({
            "name": "mixed-status.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as retest draft").click()
        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as retest draft").wait_for()
        self.assertIn("1 Resolved or Closed finding was not included: Closed browser finding.", result.text_content())
        result.get_by_role("button", name="Open Setup").click()
        self.page.wait_for_url("**/reports/*/setup")
        imported_id = self.page.url.split("/reports/")[1].split("/")[0]
        imported = main.workspace.load(imported_id)
        self.assertEqual([finding.title for finding in imported.vulnerabilities], ["Browser finding"])
        self.assertEqual(imported.vulnerabilities[0].status, "open_previously_discovered")

    def test_docx_import_warning_text_is_rendered_safely(self) -> None:
        responses = [
            {"source": "docx", "mode_required": True},
            {
                "report_id": "r_safe_warning", "source": "docx", "mode": "retest",
                "summary": {
                    "retained": 0, "dropped_resolved": ["Fixed issue"], "statuses_rewritten": [],
                    "warnings": ['<img src=x onerror="window.__warningExecuted=true">'],
                },
            },
        ]

        def respond(route) -> None:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(responses.pop(0)))

        self.page.route("**/reports/import", respond)
        self.page.goto(f"{self.base_url}/")
        self.page.evaluate("window.__warningExecuted = false")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx", "mimeType": "application/octet-stream", "buffer": b"classified by server",
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as retest draft").click()

        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as retest draft").wait_for()
        self.assertIn("1 Resolved or Closed finding was not included: Fixed issue.", result.text_content())
        self.assertIn('<img src=x onerror="window.__warningExecuted=true">', result.text_content())
        self.assertEqual(result.locator("img").count(), 0)
        self.assertFalse(self.page.evaluate("window.__warningExecuted"))

    def test_editable_docx_import_shows_warnings_and_stay_reveals_the_report(self) -> None:
        document = self.importable_docx()
        before = {path.parent.name for path in self.root.glob("apps/**/draft.json")}
        self.page.goto(f"{self.base_url}/")
        self.page.locator("#app-search").fill("No matching application")
        self.page.locator("#import-report").set_input_files({
            "name": "report.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": document,
        })
        self.page.get_by_role("dialog").get_by_role("button", name="Import as editable draft").click()

        result = self.page.get_by_role("dialog")
        result.get_by_role("heading", name="Imported as editable draft").wait_for()
        self.assertIn("rendered Word copies", result.text_content())
        after = {path.parent.name for path in self.root.glob("apps/**/draft.json")}
        imported_folder = (after - before).pop()
        imported_id = main.workspace.load_path(next(self.root.glob(f"apps/**/{imported_folder}/draft.json"))).report_id
        result.get_by_role("button", name="Stay on reports").click()

        self.page.get_by_text("Report imported.").wait_for()
        row = self.page.locator(f'[data-report-id="{imported_id}"]')
        self.assertTrue(row.is_visible())
        self.assertTrue(row.evaluate("element => element.closest('details').open"))
        self.assertTrue(row.locator(".report-name").evaluate("element => document.activeElement === element"))

    def test_manager_import_error_shows_structured_diagnostics(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/")
        page.locator("#import-report").set_input_files({
            "name": "invalid-report.json",
            "mimeType": "application/json",
            "buffer": b"not valid JSON",
        })

        diagnostic = page.locator("#app-diagnostics")
        diagnostic.get_by_role("heading", name="Operation failed").wait_for()
        text = diagnostic.text_content()
        self.assertIn("import_report", text)
        self.assertIn("422", text)
        self.assertIn("Code", text)
        self.assertRegex(text, r"[0-9a-f]{12}")
        self.assertTrue(page.get_by_text("Select a valid VulnReport ZIP or JSON export, or a report DOCX").is_visible())


if __name__ == "__main__":
    unittest.main()