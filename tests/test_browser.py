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
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from docx import Document
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app import main
from app.docx_report import generation_issues
from app.report_service import status_conclusion_runs
from app.storage import atomic_write_json, read_json
from app.workspace import Workspace
from app.models import Content, EvidenceItem, ImageFragment, LibraryRef, ListFragment, ListItem, NoteFragment, Run, Scope, ScopeTarget, TestWindow, Vulnerability


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
            ("Limitations", "No testing @ production", "No API - version 2. (Read only) & 'approved' / \"reviewed\"; see scope: prod only.", 'Limitations contains invalid character: "@" (at sign)'),
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

    def test_upload_attempt_during_conflict_keeps_the_resolution_state(self) -> None:
        report_id = self.ready_report(include_finding=True)
        stale_page = self.page
        current_page = self.browser.new_page()
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
        page.wait_for_timeout(300)
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
        page.wait_for_timeout(200)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))
        # Both Back controls share one handler, so the stepper only has to still be wired.
        self.assertEqual(page.locator("nav.stepper .back-link").count(), 1)

        # The forward gate is what refuses, and what reveals the incomplete fields.
        page.get_by_role("button", name="Next: Content", exact=False).click()
        page.wait_for_timeout(200)
        self.assertTrue(page.url.endswith(f"/reports/{findings_report_id}/findings"))
        self.assertFalse(page.locator("#finding-validation-note").is_hidden())

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
        self.assertNotIn("Add at least one complete finding", note.inner_text())

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

    def test_adding_library_remediation_below_drops_blank_starter(self) -> None:
        report_id = self.ready_report(include_finding=True)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        title = "Session Token Remains Valid after Session Expiry Message"
        page.get_by_role("button", name="Edit finding name").click()
        search = page.get_by_role("combobox", name="Finding Name")
        search.fill(title)
        page.locator('.row-library-results [role="option"]').filter(has_text=title).click()
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)

        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        finding.likelihood = finding.impact = finding.severity = "low"
        main.workspace.save(report)

        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        remediation_block = page.locator(".content-block").filter(has_text="Recommended Remediation")
        remediation_block.get_by_role("button", name="Add below").click()
        page.wait_for_selector('#save-button:not([data-save-state="saved"])', timeout=5_000)
        page.wait_for_selector('#save-button[data-save-state="saved"]', timeout=10_000)
        page.reload()

        remediation = next(
            content
            for content in main.workspace.load(report_id).vulnerabilities[0].contents
            if content.type == "recommended_remediation"
        )
        self.assertEqual(
            [fragment.type for fragment in remediation.fragments],
            ["bulleted_list", "note"],
        )

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
        page.wait_for_timeout(300)
        self.assertEqual(conclusion.locator(".rich").first.text_content(), 'The finding "Browser finding" is still Open.')
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
            ["fragment-drag-handle", "tag", "toolbar", "fragment-move-up", "fragment-move-down", "danger fragment-delete"],
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
            'Non-Production name contains invalid character: "@" (at sign)',
        )
        typed.fill("MY LAB/2")
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
        page.wait_for_timeout(400)
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
        page = self._setup_page(report_id)
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

    def test_a_dismissed_limitation_offer_does_not_come_back_while_the_page_is_open(self) -> None:
        page = self._retest_setup(self.ready_report(), ["production"])
        page.locator("#limitations-offer").wait_for()
        page.locator("#limitations-offer").get_by_role("button", name="Dismiss").click()
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

        page.get_by_label("Limitations").click()
        page.get_by_label("Limitations").blur()
        page.wait_for_timeout(300)
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
        page.get_by_label("Limitations").fill(prose)
        page.get_by_label("Limitations").blur()
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#limitations-offer").count(), 0)

        page.locator(".coverage-name").select_option("STAGE")
        page.wait_for_timeout(500)
        self.assertEqual(page.locator("#limitations-offer").count(), 0, "a rename offered to rewrite the tester's own wording")
        self.assertEqual(page.get_by_label("Limitations").input_value(), prose)

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
        page.wait_for_timeout(300)
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
        main.provision_report(report)
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

    def test_changing_a_finding_status_in_the_browser_keeps_last_years_proof(self) -> None:
        """The editor hides the previous proof when a finding becomes "open new". Deleting it would
        make a mis-click on a dropdown unrecoverable, so the work has to come back with the status."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        main.provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Last year's step")]
        main.provision_report(report)
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
        main.provision_report(report)
        main.workspace.save(report)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/findings")
        page.wait_for_selector("#findings tr")
        status = page.locator("#findings tr").first.locator("select").last
        status.select_option("open_new")
        # A modal would swallow this click, so arriving at the editor is itself the assertion that
        # no dialog stood in the way.
        page.locator("#next").click()
        page.wait_for_url("**/edit", timeout=10_000)
        self.assertEqual(page.locator('[data-dialog-action="confirm"]').count(), 0, "nothing was written, so nothing needed confirming")
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
        main.provision_report(report)
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
        main.provision_report(report)
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
        main.provision_report(report)
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
        page.wait_for_timeout(300)
        self.assertEqual(conclusion.locator("[data-conclusion-step]").count(), 0, "dismissing the step offer did nothing")

        # But the conclusion is still boilerplate, so reopening the report asks once more.
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        conclusion = page.locator('.content-block[data-content-type="in_conclusion"]')
        self.assertEqual(conclusion.locator("[data-conclusion-step]").count(), 1, "a conclusion left at its default stopped being offered the step")

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
        main.provision_report(report)
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
        page.wait_for_timeout(400)
        self.assertEqual(conclusion_block.locator(".rich").first.text_content(), 'The finding "Browser finding" is still Open.')
        self.assertEqual(conclusion_block.locator("[data-conclusion-restore]").count(), 0, "the restore offer stayed after being accepted")
        self.assertEqual(conclusion_block.locator("[data-conclusion-step]").count(), 1, "the last proof step was not offered once the default was in place")

    def test_a_quoted_step_discharges_the_default_conclusion(self) -> None:
        """The step is the tester's own words, so the paragraph is no longer nothing but boilerplate."""
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        conclusion = self._fill_retest_history(report, finding)
        conclusion.fragments[0].runs = [Run(text="Observe the balance of another user. "), *conclusion.fragments[0].runs]
        main.provision_report(report)
        main.workspace.save(report)

        expected_issue = f"{finding.title}: in_conclusion still holds the default sentence"
        server_has_issue = expected_issue in generation_issues(main.workspace.load(report_id))
        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.page.wait_for_selector("#issue-count")
        conclusion_rows = self.page.locator(".review-row", has_text="In Conclusion").count()
        self.assertEqual(
            (
                server_has_issue,
                self.page.locator("#issue-count").get_attribute("data-state"),
                self.page.locator("#generate-report").is_disabled(),
                conclusion_rows,
            ),
            (False, "ready", False, 0),
        )

    def test_trailing_whitespace_cannot_hang_or_disguise_the_default_conclusion(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        conclusion = self._fill_retest_history(report, finding)
        conclusion.fragments[0].runs.append(Run(text="  \n"))
        main.provision_report(report)
        main.workspace.save(report)

        expected_issue = f"{finding.title}: in_conclusion still holds the default sentence"
        server_has_issue = expected_issue in generation_issues(main.workspace.load(report_id))
        self.page.goto(f"{self.base_url}/reports/{report_id}/edit", timeout=2_000)
        self.page.wait_for_selector("#issue-count")
        self.assertEqual(
            (
                server_has_issue,
                self.page.locator("#issue-count").get_attribute("data-state"),
                self.page.locator("#generate-report").is_disabled(),
            ),
            (True, "issues", True),
        )

    def test_appended_prose_discharges_the_default_conclusion(self) -> None:
        report_id = self.ready_report(include_finding=True)
        report, finding = self._complete_finding(report_id)
        finding.status = "open_previously_discovered"
        conclusion = self._fill_retest_history(report, finding)
        conclusion.fragments[0].runs.append(Run(text=" Additional tester prose."))
        main.provision_report(report)
        main.workspace.save(report)

        expected_issue = f"{finding.title}: in_conclusion still holds the default sentence"
        server_has_issue = expected_issue in generation_issues(main.workspace.load(report_id))
        self.page.goto(f"{self.base_url}/reports/{report_id}/edit")
        self.page.wait_for_selector("#issue-count")
        self.assertEqual(
            (
                server_has_issue,
                self.page.locator("#issue-count").get_attribute("data-state"),
                self.page.locator("#generate-report").is_disabled(),
            ),
            (False, "ready", False),
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

    def test_editing_a_library_section_offers_it_back(self) -> None:
        """The offer now keys off the content itself, so a section that no longer matches its entry
        is offerable however it got that way -- edited, emptied, or left behind by a reopen."""
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "content matching the library was offered back")

        block.locator(".rich").first.click()
        page.keyboard.type("Changed. ")
        page.locator("body").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(400)
        self.assertEqual(block.locator("[data-content-offer]").count(), 1, "an edited section was not offered the library version")

    def test_the_offer_appears_without_a_reload_once_the_field_is_left(self) -> None:
        """Typing never redraws the pane -- it would destroy the caret -- so before this the banner
        waited for a section toggle or a page reload."""
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)

        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        block = page.locator('.content-block[data-content-type="description"]')
        block.locator(".rich").first.click()
        page.keyboard.type("Changed. ")
        self.assertEqual(block.locator("[data-content-offer]").count(), 0, "the banner moved while the caret was in the field")

        page.locator("body").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(400)
        self.assertEqual(block.locator("[data-content-offer]").count(), 1, "the banner still needs a reload to appear")

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
        page.wait_for_timeout(400)
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
        page.wait_for_timeout(400)
        self.assertEqual(block.locator("[data-content-offer]").count(), 1, "editing a dismissed section did not offer it again")

    def test_refreshing_offers_never_changes_the_report(self) -> None:
        """The refresh runs inside a reportchange listener. A write there would call scheduleSave,
        which dispatches reportchange again -- an unbounded save loop eating the one backup file."""
        report_id = self.ready_report(include_finding=True)
        self._library_finding(report_id)
        page = self.page
        page.goto(f"{self.base_url}/reports/{report_id}/edit")
        page.wait_for_selector("#issue-count")
        before = page.evaluate("JSON.stringify(JSON.parse(document.querySelector('main').dataset.report))")
        page.evaluate("document.dispatchEvent(new Event('reportchange'))")
        page.wait_for_timeout(300)
        after = page.evaluate("JSON.stringify(JSON.parse(document.querySelector('main').dataset.report))")
        self.assertEqual(before, after)

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
        main.provision_report(report)
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

        def stale_image_for_unaffected_environment(report, finding):
            # The finding covers production only; the lower-region image is left over from a
            # scope change and belongs to neither side's idea of "required".
            report.scope_targets.append(ScopeTarget(target_id="tgt_uat", environment="non_production", channel="web", value="https://uat.example.test"))
            report.engagement.tested_environments = ["production", "non_production"]
            report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
            proof = next(content for content in finding.contents if content.type == "proof_of_concept")
            proof.fragments.append(ImageFragment(frag_id="f_stale", type="image", environment="non_production", evidence_id=None, caption=""))

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

        # Scope-rule drift is invisible here: a finding with no location cannot open the editor, so
        # the loop below never reaches the comparison. Those cases live in the Findings-gate test.
        cases = [unchanged, blank_caption, placeholder_text, no_affected_location, missing_rating, stale_image_for_unaffected_environment, default_conclusion_left_in_place, conclusion_section_emptied, quoted_step_before_default_conclusion, duplicate_additional_locations, carried_section_holding_work, previous_proof_image_without_an_environment]
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

    def test_browser_findings_gate_matches_server_finding_completeness(self) -> None:
        """The sibling of the readiness contract test, for the rules it cannot see.

        A finding with no location never opens the editor, so the readiness panel is the wrong
        place to catch `scopeHasLocation` drifting from `scope_has_location`. The observable that
        does move is the Findings gate: whether Next carries the tester through to Content. If the
        client is laxer than the server the tester is bounced straight back, and if it is stricter
        they are stranded on a report the server would have accepted."""

        def selected_target(finding):
            finding.scope = Scope(mode="custom", target_ids=["tgt_browser"])

        def typed_endpoint_only(finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["https://typed.example.test/admin"]}})

        def comment_only(finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["# ask the owner which host"]}})

        def whitespace_only(finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["   ", "\t"]}})

        def outside_coverage(finding):
            # Non-production is not tested on this report, so the line resolves to nothing.
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"non_production": {"web": ["https://uat.example.test"]}})

        def comment_beside_a_real_endpoint(finding):
            finding.scope = Scope(mode="custom", target_ids=[], custom_locations={"production": {"web": ["# the note", "https://real.example.test"]}})

        def nothing_at_all(finding):
            finding.scope = Scope(mode="custom", target_ids=[])

        for case in [selected_target, typed_endpoint_only, comment_only, whitespace_only, outside_coverage, comment_beside_a_real_endpoint, nothing_at_all]:
            with self.subTest(case=case.__name__):
                report_id = self.ready_report(include_finding=True)
                report, finding = self._complete_finding(report_id)
                case(finding)
                main.provision_report(report)
                main.workspace.save(report)

                stored = main.workspace.load(report_id)
                server_allows = main.finding_is_complete(stored.vulnerabilities[0], stored)

                page = self.page
                page.goto(f"{self.base_url}/reports/{report_id}/findings")
                page.wait_for_selector("#findings tr")
                # Watch for the navigation request, not the resulting URL: when the client is laxer
                # than the server it still fires the request and the server's redirect hides it, so
                # the landing page looks identical whether or not the two agree.
                try:
                    with page.expect_request(lambda request: request.url.rstrip("/").endswith("/edit"), timeout=3_000):
                        page.locator("#next").click()
                    client_allows = True
                except PlaywrightTimeoutError:
                    client_allows = False

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