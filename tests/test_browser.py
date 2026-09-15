from __future__ import annotations

import base64
import socket
import hashlib
import tempfile
import threading
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from docx import Document
from PIL import Image
from playwright.sync_api import sync_playwright

from app import main
from app.docx_report import generation_issues
from app.storage import atomic_write_json, read_json
from app.workspace import Workspace
from app.models import EvidenceItem, ImageFragment, LibraryRef, Run, Scope, ScopeTarget, TestWindow, Vulnerability


class BrowserWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_workspace = main.workspace
        main.workspace = Workspace(Path(self.temp_dir.name), "Browser QA")
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            self.port = port_socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        for _ in range(40):
            try:
                urlopen(f"http://127.0.0.1:{self.port}/", timeout=0.2).close()
                break
            except URLError:
                threading.Event().wait(0.05)
        else:
            self.fail("Browser test server did not start")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.page = self.browser.new_page()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def ready_report(self, include_finding: bool = False) -> str:
        report = main.workspace.create_report()
        report.app_id = "CI-BROWSER"
        report.engagement.app_name = "Browser QA"
        report.engagement.ci_number = "CI-BROWSER"
        report.engagement.segment = "JH"
        report.engagement.report_type = "annual_pentest"
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

    def tearDown(self) -> None:
        self.browser.close()
        self.playwright.stop()
        self.server.should_exit = True
        self.server_thread.join(timeout=3)
        main.workspace = self.original_workspace
        self.temp_dir.cleanup()

    def test_setup_inputs_report_character_and_date_errors_before_save(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")

        field_cases = [
            ("Application Name", "Bad/App", "Portal-2: (Web)", 'Application name contains invalid character: "/" (slash)'),
            ("CI Number", "CI_123", "CI-123", 'CI number contains invalid character: "_" (underscore)'),
            ("BSN Number", "BSN.123", "BSN-123", 'BSN number contains invalid character: "." (period)'),
            ("Application Owner", "Owner 2", "Anne-Marie Owner", 'Application owner contains invalid character: "2" (digit two)'),
            ("Tester", "QA_Tester", "QA Tester", 'Tester contains invalid character: "_" (underscore)'),
            ("Production time", "08:00_17:00", "08:00-17:00", 'Production time contains invalid character: "_" (underscore)'),
            ("User role 1", "Admin_2", "Admin-2 / QA", 'User role 1 contains invalid character: "_" (underscore)'),
            ("Username 1", "bad user", "DOMAIN\\qa.user@example", 'Username 1 contains invalid character: " " (space)'),
            ("Limitations", "No testing: production", "No API - version 2. (Read only) & 'approved' / \"reviewed\"", 'Limitations contains invalid character: ":" (colon)'),
        ]
        for label, invalid_value, valid_value, expected_message in field_cases:
            with self.subTest(label=label):
                field = page.get_by_label(label, exact=True)
                field.fill(invalid_value)
                self.assertEqual(field.evaluate("input => input.validationMessage"), expected_message)
                field.fill(valid_value)
                self.assertEqual(field.evaluate("input => input.validationMessage"), "")

            application_name = page.get_by_label("Application Name")
            application_name.fill("Bad/_App/")
            self.assertEqual(
                application_name.evaluate("input => input.validationMessage"),
                'Application name contains invalid characters: "/" (slash), "_" (underscore)',
            )

        production_start = page.get_by_label("Production start date", exact=True)
        production_end = page.get_by_label("Production end date", exact=True)
        production_start.fill("2026-01-01")
        self.assertEqual(production_end.get_attribute("min"), "2026-01-01")
        production_end.fill("2026-01-01")
        self.assertEqual(production_start.get_attribute("max"), "2026-01-01")
        self.assertEqual(production_start.evaluate("input => input.validationMessage"), "")
        self.assertEqual(production_end.evaluate("input => input.validationMessage"), "")
        production_start.fill("2026-01-02")
        self.assertIn("after", production_start.evaluate("input => input.validationMessage"))
        self.assertIn("after", production_end.evaluate("input => input.validationMessage"))
        self.assertTrue(production_start.evaluate("input => input.validity.rangeOverflow"))
        production_start.fill("2026-01-01")
        self.assertEqual(production_start.evaluate("input => input.validationMessage"), "")
        self.assertEqual(production_end.evaluate("input => input.validationMessage"), "")

        page.get_by_label("Application Name").fill("Bad/App")
        page.get_by_role("button", name="Next: Findings").click()
        self.assertIn("/setup", page.url)
        self.assertIn("Application name", page.locator("#setup-validation-note").inner_text())

    def test_authoring_workflow_autosave_fragments_and_manager_grouping(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Segment").select_option("JH")
        page.get_by_label("Application Name").fill("Browser QA")
        page.get_by_label("Report Type").select_option("annual_pentest")
        page.get_by_label("CI Number").fill("CI-BROWSER")
        page.get_by_label("BSN Number").fill("BSN-BROWSER")
        page.get_by_label("Application Owner").fill("QA")
        page.locator('input[aria-label="Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Production end date"]').fill("2026-01-02")
        page.locator('input[aria-label="Non-Production start date"]').fill("2026-01-01")
        page.locator('input[aria-label="Non-Production end date"]').fill("2026-01-02")
        self.assertEqual(page.get_by_role("textbox", name="Production time", exact=True).input_value(), "Any time")
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
        page.wait_for_url(f"**/reports/*/findings")
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

    def test_transient_autosave_failure_retries_without_another_edit(self) -> None:
        page = self.page
        page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 100")
        page.goto(f"{self.base_url}/new")
        report_id = page.url.split("/")[4]
        put_count = 0

        def fail_first_put(route) -> None:
            nonlocal put_count
            if route.request.method == "PUT":
                put_count += 1
                if put_count == 1:
                    route.abort()
                    return
            route.continue_()

        page.route(f"**/reports/{report_id}", fail_first_put)
        page.get_by_label("Application Name").fill("Retry QA")
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        self.assertEqual(put_count, 2)
        self.assertEqual(main.workspace.load(report_id).engagement.app_name, "Retry QA")
        self.assertEqual(page.locator("#app-diagnostics").count(), 0)

    def test_unavailable_browser_recovery_storage_is_reported_without_blocking_server_save(self) -> None:
        page = self.page
        page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 100")
        page.add_init_script(
            "Object.defineProperty(window, 'localStorage', {configurable:true, get(){throw new DOMException('blocked', 'SecurityError')}})"
        )
        page.goto(f"{self.base_url}/new")
        report_id = page.url.split("/")[4]
        put_count = 0

        def fail_first_put(route) -> None:
            nonlocal put_count
            if route.request.method == "PUT":
                put_count += 1
                if put_count == 1:
                    route.abort()
                    return
            route.continue_()

        page.route(f"**/reports/{report_id}", fail_first_put)

        warning = page.locator("#app-diagnostics")
        warning.get_by_role("heading", name="Browser recovery unavailable").wait_for()
        self.assertIn("Server saves still work", warning.text_content())

        page.get_by_label("Application Name").fill("Storage Warning QA")
        page.locator("#save-button").click()
        page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).engagement.app_name, "Storage Warning QA")
        self.assertEqual(put_count, 2)
        warning.get_by_role("heading", name="Browser recovery unavailable").wait_for()

    def test_recovery_actions_report_late_storage_failures_without_losing_the_draft(self) -> None:
        report_id = self.ready_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["app_owner"] = "Recover me"
        draft_key = f"vulnreport-pending:{report_id}:orphan"
        envelope = {
            "schemaVersion": 1,
            "reportId": report_id,
            "tabId": "orphan",
            "baseSavedAt": report["saved_at"],
            "capturedAt": report["saved_at"],
            "editRevision": 1,
            "report": report,
        }
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/setup")
        page.evaluate("([key, draft]) => localStorage.setItem(key, JSON.stringify(draft))", [draft_key, envelope])
        page.reload()

        page.evaluate(
            """() => {
                const original = Storage.prototype.setItem;
                Storage.prototype.setItem = function(key, value) {
                    if (key.startsWith('vulnreport-recovery:')) throw new DOMException('blocked', 'SecurityError');
                    return original.call(this, key, value);
                };
            }"""
        )
        page.get_by_role("button", name="Restore", exact=True).click()
        page.get_by_role("heading", name="Browser recovery unavailable").wait_for()
        self.assertIsNotNone(page.evaluate("key => localStorage.getItem(key)", draft_key))

        page.reload()
        page.evaluate(
            """() => {
                const original = Storage.prototype.removeItem;
                Storage.prototype.removeItem = function(key) {
                    if (key.includes(':orphan')) throw new DOMException('blocked', 'SecurityError');
                    return original.call(this, key);
                };
            }"""
        )
        page.get_by_role("button", name="Discard", exact=True).click()
        page.get_by_role("heading", name="Browser recovery unavailable").wait_for()
        self.assertIsNotNone(page.evaluate("key => localStorage.getItem(key)", draft_key))

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

    def test_segment_and_report_type_are_required(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        self.assertEqual(page.get_by_label("Segment").locator("option").all_text_contents(), ["Select segment", "JH", "GWAM", "Asia"])
        self.assertEqual(page.get_by_label("Report Type").locator("option").all_text_contents(), ["Select report type", "Annual Pentest", "Retest", "Deployment Pentest", "New Test"])
        page.get_by_label("Application Name").fill("Required Fields")
        page.get_by_label("CI Number").fill("CI-REQUIRED")
        page.locator('input[aria-label$="start date"]').evaluate_all("inputs => inputs.forEach(input => { input.value = '2026-01-01'; input.dispatchEvent(new Event('input', {bubbles:true})); })")
        page.locator('input[aria-label$="end date"]').evaluate_all("inputs => inputs.forEach(input => { input.value = '2026-01-02'; input.dispatchEvent(new Event('input', {bubbles:true})); })")
        page.get_by_role("textbox", name="Web", exact=True).nth(0).fill("https://prod.example.test")
        page.get_by_role("textbox", name="Web", exact=True).nth(1).fill("https://test.example.test")
        page.get_by_role("button", name="Next: Findings").click()
        self.assertIn("/setup", page.url)
        self.assertIn("segment", page.locator("#setup-validation-note").text_content())
        self.assertIn("report type", page.locator("#setup-validation-note").text_content())

        page.get_by_label("Segment").select_option("GWAM")
        page.get_by_label("Report Type").select_option("new_test")
        page.get_by_role("button", name="Next: Findings").click()
        page.wait_for_url("**/findings")

    def test_mobile_scope_allows_names_and_rejects_unapproved_special_characters(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/new")
        page.get_by_label("Test Mobile").check()
        page.get_by_label("Test Web").uncheck()
        mobile = page.get_by_role("textbox", name="Mobile", exact=True).first

        mobile.fill("# ignored ! []\nClient's \"Mobile\" App: iOS/Android_v2.1, QA-&")
        self.assertEqual(mobile.evaluate("input => input.validationMessage"), "")

        mobile.fill("Mobile App!")
        self.assertEqual(
            mobile.evaluate("input => input.validationMessage"),
            'Production Mobile scope contains invalid character: "!" (exclamation mark)',
        )
        self.assertEqual(mobile.get_attribute("aria-invalid"), "true")

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
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        page.locator('input[type="file"]').first.set_input_files({"name": "proof.png", "mimeType": "image/png", "buffer": image_data.getvalue()})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        page.reload()
        self.assertEqual(page.locator(".content-block").filter(has_text="Description").locator(".rich").first.text_content(), "Unsaved description")
        self.assertEqual(page.locator(".image-preview").count(), 1)

    def paste_png(self, selector: str | None = None) -> None:
        """Dispatch a genuine paste event carrying a PNG, on one card or on the page itself."""
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        self.page.evaluate(
            """([selector, encoded]) => {
                const transfer = new DataTransfer();
                transfer.items.add(new File([Uint8Array.from(atob(encoded), character => character.charCodeAt(0))], "pasted.png", {type: "image/png"}));
                const target = selector ? document.querySelector(selector) : document.body;
                target.dispatchEvent(new ClipboardEvent("paste", {clipboardData: transfer, bubbles: true, cancelable: true}));
            }""",
            [selector, base64.b64encode(image_data.getvalue()).decode()],
        )

    def test_pasting_a_screenshot_attaches_it_as_evidence(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        self.assertIn("paste", page.locator(".evidence-thumb").first.inner_text().lower(), "an empty slot must say how to paste")
        self.paste_png(".evidence-tile")
        page.locator(".image-preview").first.wait_for(timeout=5_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        page.reload()
        self.assertEqual(page.locator(".image-preview").count(), 1)
        self.assertEqual(page.locator(".evidence-thumb span").count(), 0, "the prompt stayed on a filled slot")

    def test_pasting_with_nothing_focused_fills_the_first_empty_slot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=5_000)
        self.paste_png()
        page.locator(".image-preview").first.wait_for(timeout=5_000)
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)

        page.reload()
        proof = page.locator(".content-block").filter(has_text="Proof of Concept").last
        self.assertEqual(proof.locator(".image-preview").count(), 1)

    def test_leaving_a_page_mid_upload_keeps_the_screenshot(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.locator(".evidence-tile").first.wait_for(timeout=8_000)
        # Holds the upload open so Previous is clicked while the POST is still in flight.
        page.evaluate(
            """() => {
                const original = window.fetch;
                window.fetch = (url, options) => String(url).endsWith("/evidence") && options?.method === "POST"
                    ? new Promise(resolve => setTimeout(() => resolve(original(url, options)), 1500))
                    : original(url, options);
            }"""
        )
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        page.locator('input[type="file"]').first.set_input_files({"name": "proof.png", "mimeType": "image/png", "buffer": image_data.getvalue()})
        page.wait_for_selector("#save-button[data-save-state='saving']", timeout=5_000)
        page.get_by_role("button", name="Previous: Findings").click()
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

        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        image_cards.nth(0).locator(".evidence-caption").fill("Production transaction response")
        image_cards.nth(0).locator('input[type="file"]').set_input_files({"name": "prod.png", "mimeType": "image/png", "buffer": image_data.getvalue()})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(page.get_by_text("Production evidence image required", exact=True).count(), 0)
        self.assertTrue(page.get_by_text("Non-Production evidence image required", exact=True).is_visible())

        image_cards = proof.locator(".evidence-tile")
        image_cards.nth(1).locator(".evidence-caption").fill("Non-Production transaction response")
        image_cards.nth(1).locator('input[type="file"]').set_input_files({"name": "uat.png", "mimeType": "image/png", "buffer": image_data.getvalue()})
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(page.get_by_text("Non-Production evidence image required", exact=True).count(), 0)

        proof.get_by_role("combobox", name="Add fragment to Proof of Concept").select_option("image")
        image_cards = proof.locator(".evidence-tile")
        self.assertEqual(image_cards.count(), 3)
        self.assertEqual(proof.locator(".evidence-environment").last.input_value(), "production")

    def test_stale_save_keeps_local_recovery_until_confirmed(self) -> None:
        report_id = self.ready_report()
        first_page = self.page
        stale_page = self.browser.new_page()
        first_page.goto(f"{self.base_url}/reports/{report_id}/setup")
        stale_page.goto(f"{self.base_url}/reports/{report_id}/setup")

        first_page.get_by_label("Application Owner").fill("First tab")
        first_page.get_by_role("button", name="Save").click()
        first_page.get_by_role("button", name="Saved").wait_for()
        stale_page.get_by_label("Application Owner").fill("Unsaved stale tab")
        stale_page.get_by_role("button", name="Save").click()
        conflict = stale_page.locator("#app-diagnostics")
        conflict.get_by_role("heading", name="Save conflict").wait_for()
        self.assertIn("save_report", conflict.text_content())
        self.assertIn("409", conflict.text_content())
        self.assertIn("save_report", conflict.locator(".diagnostic-code").text_content())

        local_draft = stale_page.evaluate(
            "prefix => { const key = Object.keys(localStorage).find(candidate => candidate.startsWith(prefix)); return key ? localStorage.getItem(key) : null; }",
            f"vulnreport-pending:{report_id}:",
        )
        self.assertIn("Unsaved stale tab", local_draft)
        conflict.get_by_role("button", name="Save my version").click()
        stale_page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(stale_page.locator("#app-diagnostics").count(), 0)
        self.assertEqual(main.workspace.load(report_id).engagement.app_owner, "Unsaved stale tab")

        stale_page.get_by_label("Application Owner").fill("Saved after conflict")
        stale_page.get_by_role("button", name="Save").click()
        stale_page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        self.assertEqual(main.workspace.load(report_id).engagement.app_owner, "Saved after conflict")
        stale_page.close()

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

    def test_saving_one_tab_keeps_the_other_tabs_recovery_snapshot(self) -> None:
        report_id = self.ready_report()
        first_page = self.page
        second_page = self.browser.new_page()
        first_page.goto(f"{self.base_url}/reports/{report_id}/setup")
        second_page.goto(f"{self.base_url}/reports/{report_id}/setup")
        first_tab_id = first_page.evaluate("sessionStorage.getItem('vulnreport-tab-id')")
        second_tab_id = second_page.evaluate("sessionStorage.getItem('vulnreport-tab-id')")
        self.assertNotEqual(
            first_tab_id,
            second_tab_id,
        )

        prefix = f"vulnreport-pending:{report_id}:"
        first_page.evaluate(
            "([firstKey, secondKey]) => { localStorage.setItem(firstKey, 'First tab pending'); localStorage.setItem(secondKey, 'Second tab pending'); }",
            [f"{prefix}{first_tab_id}", f"{prefix}{second_tab_id}"],
        )
        first_page.get_by_label("Application Owner").fill("First tab pending")
        first_page.locator("#save-button").click()
        first_page.locator('#save-button[data-save-state="saved"]').wait_for(timeout=5_000)

        remaining = first_page.evaluate(
            "prefix => Object.keys(localStorage).filter(key => key.startsWith(prefix)).map(key => localStorage.getItem(key))",
            prefix,
        )
        self.assertEqual(len(remaining), 1)
        self.assertIn("Second tab pending", remaining[0])
        second_page.close()

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

    def test_a_collapsed_finding_stays_collapsed_when_the_table_rebuilds(self) -> None:
        """Typing the first vuln ID rebuilds the table, which used to re-open the first finding."""
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        expanded = page.locator("#findings > tr.finding-expanded")
        expanded.wait_for()
        # Driven directly because the fold toggle's actionability check does not settle headless.
        page.evaluate("() => document.querySelector('.finding-fold-toggle').click()")
        self.assertEqual(expanded.count(), 0)

        vuln_id = page.locator("#findings input[inputmode='numeric']")
        vuln_id.fill("1234")
        vuln_id.blur()
        page.locator("#findings .finding-id-display").wait_for()
        self.assertEqual(expanded.count(), 0, "the collapsed finding re-opened when the table rebuilt")

    def test_previous_saves_before_library_replacement_and_next_navigation(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        evidence_id = "ev_previous_navigation"
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data.getvalue()).hexdigest(), uploaded_at=report.saved_at)
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data.getvalue())
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
        page.wait_for_timeout(250)
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

    def test_invalid_findings_block_navigation_but_content_allows_back(self) -> None:
        findings_report_id = self.ready_report()
        page = self.page
        page.goto(f"{self.base_url}/reports/{findings_report_id}/findings")
        page.get_by_role("button", name="Add finding").click()

        previous = page.get_by_role("button", name="Previous: Setup")
        self.assertIsNone(previous.get_attribute("href"))
        previous.click(button="middle")
        page.wait_for_timeout(200)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))

        previous.click()
        page.wait_for_timeout(200)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))
        self.assertFalse(page.locator("#finding-validation-note").is_hidden())

        page.get_by_role("button", name="Next: Content", exact=False).click()
        page.wait_for_timeout(200)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))

        content_report_id = self.ready_report(include_finding=True)
        page.goto(f"{self.base_url}/reports/{content_report_id}/edit")
        self.assertEqual(page.locator("#issue-count").get_attribute("data-state"), "issues")
        # Going back from Content is never gated: the tester is on their way to fix the gaps.
        page.get_by_role("button", name="Previous: Findings").click()
        page.wait_for_url(f"**/reports/{content_report_id}/findings")

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

    def test_using_the_library_remediation_offer_does_not_gain_empty_paragraph(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        # A title match only applies metadata now; content offers live on the Content page.
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        title = "Session Token Remains Valid after Session Expiry Message"
        page.get_by_role("button", name="Edit finding name").click()
        search = page.get_by_role("combobox", name="Finding Name")
        search.fill(title)
        page.locator('.row-library-results [role="option"]').filter(has_text=title).click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        # VDB-047 carries no default ratings, so restore them before Content so /edit doesn't
        # redirect on an incomplete finding; the offer under test is unrelated to this rating.
        report = main.workspace.load(report_id)
        report.vulnerabilities[0].likelihood = "low"
        report.vulnerabilities[0].impact = "low"
        report.vulnerabilities[0].severity = "low"
        main.workspace.save(report)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        remediation_block = page.locator(".content-block").filter(has_text="Recommended Remediation")
        remediation_block.get_by_role("button", name="Fill from library").click()
        # The autosave is debounced, so wait for it to leave and re-enter "saved" before asserting.
        page.wait_for_selector('#save-button:not([data-save-state="saved"])', timeout=5_000)
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        # "Use library version" copies only the library's own fragments, with no stray empty paragraph appended.
        report = main.workspace.load(report_id)
        remediation = next(
            content
            for content in report.vulnerabilities[0].contents
            if content.type == "recommended_remediation"
        )
        self.assertEqual(
            [fragment.type for fragment in remediation.fragments],
            ["bulleted_list", "note"],
        )

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

    def test_in_conclusion_seed_is_editable_and_accepts_more_fragments(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        report.vulnerabilities[0].status = "open_previously_discovered"
        main.provision(report.vulnerabilities[0])
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        conclusion = page.locator(".content-block").filter(has_text="In Conclusion")
        self.assertTrue(conclusion.get_by_text("Include a brief justification or explanation.", exact=True).is_visible())
        self.assertEqual(conclusion.locator(".fragment").count(), 1)
        self.assertEqual(conclusion.locator(".rich").first.text_content(), 'The finding "Browser finding" is still Open.')
        self.assertEqual(conclusion.locator(".generated-conclusion").count(), 0)
        conclusion.locator(".rich").first.fill("Testing confirmed that compensating controls reduce the exposure. The issue remains open pending remediation.")
        conclusion.get_by_role("combobox", name="Add fragment to In Conclusion").select_option("note")
        conclusion.locator(".fragment").last.locator(".rich").fill("Monitor the control until permanent remediation is complete.")

        page.get_by_role("button", name="Save").click()
        page.get_by_role("button", name="Saved").wait_for(timeout=5_000)
        page.reload()
        conclusion = page.locator(".content-block").filter(has_text="In Conclusion")
        self.assertEqual(conclusion.locator(".rich").first.text_content(), "Testing confirmed that compensating controls reduce the exposure. The issue remains open pending remediation.")
        self.assertEqual(conclusion.locator(".rich").nth(1).text_content(), "Monitor the control until permanent remediation is complete.")
        self.assertEqual(conclusion.locator(".generated-conclusion").count(), 0)

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
        self.assertGreaterEqual(page.locator(".fragment input.instance-title-input").count(), 1)
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
            ["fragment-drag-handle", "tag", "toolbar", "fragment-move-up", "fragment-move-down", "danger fragment-delete"],
        )
        self.assertEqual(header.locator(".toolbar").get_by_role("button").count(), 3)
        self.assertEqual(
            header.locator(".toolbar").get_by_role("button").evaluate_all("buttons => buttons.map(button => button.title)"),
            ["Bold", "Italic", "Underline"],
        )

    def _complete_finding(self, report_id: str):
        """Fill the seeded finding in so both sides consider the report ready to generate."""
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        evidence_id = "ev_contract"
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data.getvalue()).hexdigest(), uploaded_at=report.saved_at)
        evidence_path = main.workspace.find_path(report_id).parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data.getvalue())
        return report, finding

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
        main.provision_report(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        offer = page.locator(".poc-offer")
        self.assertEqual(offer.count(), 1, "the api steps are still missing")
        self.assertEqual(offer.get_attribute("data-poc-offer"), "api")

        report = main.workspace.load(report_id)
        report.vulnerabilities[0].scope = Scope(mode="custom", target_ids=["tgt_browser"])
        main.provision_report(report)
        main.workspace.save(report)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        self.assertEqual(page.locator(".poc-offer").count(), 0, "web is already installed, so nothing is left to offer")

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
        main.provision_report(report)
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

    def test_the_fragments_provisioning_guarantees_cannot_be_deleted(self) -> None:
        """Provisioning puts these back on the next save, so offering a delete would look like the
        editor silently discarded the change."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Original step")]
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        history = next(fragment for fragment in previous.fragments if fragment.type == "image")
        history.environment = "production"
        history.evidence_id = "ev_history"
        history.caption = "Original response"
        report.evidence["ev_history"] = EvidenceItem(file="evidence/ev_history.png", original_name="history.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data.getvalue()).hexdigest(), uploaded_at=report.saved_at)
        (main.workspace.find_path(report_id).parent / "evidence" / "ev_history.png").write_bytes(image_data.getvalue())
        main.provision_report(report)
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
        main.provision_report(report)
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
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        history = next(fragment for fragment in previous.fragments if fragment.type == "image")
        history.environment = "non_production"
        history.evidence_id = "ev_history"
        history.caption = "Original non-production response"
        report.evidence["ev_history"] = EvidenceItem(file="evidence/ev_history.png", original_name="history.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data.getvalue()).hexdigest(), uploaded_at=report.saved_at)
        (main.workspace.find_path(report_id).parent / "evidence" / "ev_history.png").write_bytes(image_data.getvalue())
        main.provision_report(report)
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

        def stale_image_for_unaffected_environment(report, finding):
            # The finding covers production only; the lower-region image is left over from a
            # scope change and belongs to neither side's idea of "required".
            report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
            report.engagement.tested_environments = ["production", "non_production"]
            report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            proof.fragments.append(ImageFragment(frag_id="f_stale", type="image", environment="non_production", evidence_id=None, caption=""))

        cases = [unchanged, blank_caption, placeholder_text, no_affected_location, missing_rating, stale_image_for_unaffected_environment]
        for case in cases:
            with self.subTest(case=case.__name__):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                case(report, finding)
                # Mirror the save route so both sides judge the same canonical state.
                main.provision_report(report)
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

    def test_complete_report_saves_generated_docx_to_generated_folder(self) -> None:
        self.page.add_init_script("window.VULNREPORT_AUTOSAVE_IDLE_MS = 60000")
        report_id = self.ready_report(include_finding=True)
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        evidence_id = "ev_browser_generate"
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        report.evidence[evidence_id] = EvidenceItem(file=f"evidence/{evidence_id}.png", original_name="proof.png", width_px=2, height_px=2, sha256=hashlib.sha256(image_data.getvalue()).hexdigest(), uploaded_at=report.saved_at)
        draft_path = main.workspace.find_path(report_id)
        evidence_path = draft_path.parent / "evidence" / f"{evidence_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(image_data.getvalue())
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
        page.locator("#generate-status").wait_for(state="visible", timeout=60_000)
        self.assertEqual(page.evaluate("window.generateRequestOrder"), ["PUT", "POST"])
        page.get_by_role("heading", name="Unrelated warning").wait_for()
        persisted_description = next(content for content in main.workspace.load(report_id).vulnerabilities[0].contents if content.type == "description")
        self.assertEqual(persisted_description.fragments[0].runs[0].text, "Saved immediately before generation")
        output_path = main.GENERATED / "JH - Browser QA - Annual Pentest 2026.docx"
        status_text = page.locator("#generate-status").inner_text()
        self.assertIn(output_path.name, status_text)
        self.assertIn("generated", status_text)
        rendered = Document(output_path)
        text = "\n".join([*(paragraph.text for paragraph in rendered.paragraphs), *(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)])
        self.assertIn("Browser finding", text)
        self.assertNotIn("{{", text)
        output_path.unlink()

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