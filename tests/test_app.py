from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
import zipfile
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from docx import Document
from docx.oxml.ns import qn
from PIL import Image
from pydantic import ValidationError

from app import main
from app.docx_report import _finding_locations, _metadata, generation_issues
from app.library import Library
from app.report_service import affected_channels, applicable_poc_variants, apply_poc_variant, provision, scope_has_location
from app.storage import atomic_write_json, read_json
from app.workspace import StaleReportError, Workspace, safe_name
from app.models import ImageFragment, ListFragment, ListItem, ParagraphFragment, Report, Run, Scope, ScopeTarget, TestWindow, Vulnerability, resolve_tested_channels
from app.tester_identity import Identity, load_or_bootstrap


class ReportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_workspace = main.workspace
        main.workspace = Workspace(Path(self.temp_dir.name), "QA Tester")
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.workspace = self.original_workspace
        self.temp_dir.cleanup()

    def new_report(self) -> str:
        response = self.client.get("/new", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        return response.headers["location"].split("/")[2]

    def test_safe_name_rejects_windows_device_names_with_extensions(self) -> None:
        self.assertEqual(safe_name("CON.txt", "fallback"), "fallback")
        self.assertEqual(safe_name("normal name", "fallback"), "normal_name")

    def test_report_management_lifecycle(self) -> None:
        report_id = self.new_report()
        original_path = main.workspace.find_path(report_id)
        # Both segments are provisional until the name and report type exist.
        self.assertEqual(original_path.parent.parent.name, "unnamed")
        self.assertEqual(original_path.parent.name[7:], f"_Report_{report_id[2:]}")
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["app_name"] = "Regression Report"
        report["engagement"]["ci_number"] = "CI-TEST-01"
        report["engagement"]["segment"] = "JH"
        report["engagement"]["report_type"] = "annual_pentest"
        report["engagement"]["report_date"] = "2026-09-08"
        report["scope_text"] = {
            "production": {"web": "https://prod.example.test"},
            "non_production": {"web": "https://test.example.test"},
        }
        report["vulnerabilities"] = [{
            "uid": "v_test",
            "title": "Regression finding",
            "likelihood": "low",
            "impact": "medium",
            "severity": "medium",
            "status": "open_new",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {}, "custom_locations": {}},
            "contents": [],
        }]
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)
        persisted = main.workspace.load(report_id)
        self.assertEqual(persisted.engagement.app_name, "Regression Report")
        self.assertEqual(len(persisted.scope_targets), 2)
        self.assertEqual([content.type for content in persisted.vulnerabilities[0].contents], ["description", "recommended_remediation", "proof_of_concept"])
        self.assertNotEqual(main.workspace.find_path(report_id), original_path)
        self.assertFalse(original_path.exists())
        settled = main.workspace.find_path(report_id)
        self.assertEqual(settled.parent.parent.name, "Regression_Report")
        self.assertEqual(settled.parent.name, f"2026-09_Annual_Pentest_{report_id[2:]}")

        listed = self.client.get("/reports")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["report_id"], report_id)

        exported = self.client.get(f"/reports/{report_id}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertIn('filename="JH - Regression Report - Annual Pentest 2026.zip"', exported.headers["content-disposition"])
        self.assertEqual(exported.headers["content-type"], "application/zip")

        imported = self.client.post("/reports/import", files={"file": ("report.zip", exported.content, "application/zip")})
        self.assertEqual(imported.status_code, 200)
        imported_id = imported.json()["report_id"]
        self.assertNotEqual(imported_id, report_id)
        self.assertEqual(main.workspace.load(imported_id).engagement.app_name, "Regression Report")

        renamed = self.client.patch(f"/reports/{report_id}/name", json={"app_name": "Renamed report"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(main.workspace.load(report_id).engagement.app_name, "Renamed report")
        # A settled folder name is a filing decision made once; the manager groups by the live name,
        # so the drift is invisible and nothing on disk has to churn.
        self.assertEqual(main.workspace.find_path(report_id).parent.parent.name, "Regression_Report")
        self.assertEqual(self.client.patch(f"/reports/{report_id}/name", json={"app_name": " "}).status_code, 422)

        duplicated = self.client.post(f"/reports/{report_id}/duplicate")
        self.assertEqual(duplicated.status_code, 200)
        duplicate_id = duplicated.json()["report_id"]
        self.assertNotEqual(duplicate_id, report_id)
        self.assertEqual(main.workspace.load(duplicate_id).engagement.app_name, "Renamed report")

        self.assertEqual(self.client.delete(f"/reports/{report_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/reports/{imported_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/reports/{duplicate_id}").status_code, 200)
        self.assertEqual(self.client.get("/reports").json(), [])

    def test_import_rejects_invalid_json(self) -> None:
        response = self.client.post("/reports/import", files={"file": ("invalid.json", b"not json", "application/json")})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/reports/import", files={"file": ("invalid.json", b'{"schema_version":"1.4"}', "application/json")})
        self.assertEqual(response.status_code, 422)

        report = main.workspace.create_report().model_dump(mode="json", by_alias=True)
        response = self.client.post("/reports/import", files={"file": ("legacy.json", json.dumps(report).encode(), "application/json")})
        self.assertEqual(response.status_code, 200)

    def test_import_and_image_upload_limits(self) -> None:
        report_id = self.new_report()
        with patch.object(main, "MAX_BUNDLE_BYTES", 4):
            response = self.client.post("/reports/import", files={"file": ("large.json", b"12345", "application/json")})
        self.assertEqual(response.status_code, 413)

        with patch.object(main, "MAX_IMAGE_BYTES", 4):
            response = self.client.post(f"/reports/{report_id}/evidence", files={"file": ("large.png", b"12345", "image/png")})
        self.assertEqual(response.status_code, 413)

    def test_json_routes_reject_malformed_and_non_object_bodies(self) -> None:
        report_id = self.new_report()
        headers = {"content-type": "application/json"}
        self.assertEqual(self.client.put(f"/reports/{report_id}", content=b"{", headers=headers).status_code, 422)
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=[]).status_code, 422)
        self.assertEqual(self.client.patch(f"/reports/{report_id}/name", content=b"{", headers=headers).status_code, 422)
        self.assertEqual(self.client.patch(f"/reports/{report_id}/name", json=[]).status_code, 422)
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["scope_text"] = {"production": "not-an-object"}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 422)

    def test_setup_input_validation_rejects_unapproved_characters_and_date_order(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        field_cases = [
            ("app_name", "Bad/App", 'Application name contains invalid character: "/" (slash)'),
            ("ci_number", "CI_123", 'CI number contains invalid character: "_" (underscore)'),
            ("bsn_number", "BSN.123", 'BSN number contains invalid character: "." (period)'),
            ("app_owner", "Owner 2", 'Application owner contains invalid character: "2" (digit two)'),
            ("tester", "QA_Tester", 'Tester contains invalid character: "_" (underscore)'),
            ("limitations", "No testing: production", 'Limitations contains invalid character: ":" (colon)'),
        ]
        for field, value, expected_issue in field_cases:
            with self.subTest(field=field):
                candidate = deepcopy(report)
                candidate["engagement"][field] = value
                response = self.client.put(f"/reports/{report_id}", json=candidate)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_setup")
                self.assertIn(expected_issue, response.json()["error"]["message"])

        nested_cases = [
            ({"test_windows": {"production": {"test_time": "08:00_17:00"}}}, 'Production time contains invalid character: "_" (underscore)'),
            ({"test_accounts": [{"user_role": "Admin_2", "username": "N/A"}]}, 'User role 1 contains invalid character: "_" (underscore)'),
            ({"test_accounts": [{"user_role": "Admin", "username": "bad user"}]}, 'Username 1 contains invalid character: " " (space)'),
            ({"test_windows": {"production": {"start_date": "2026-01-02", "end_date": "2026-01-01"}}}, "start date"),
        ]
        for engagement_update, expected_issue in nested_cases:
            with self.subTest(issue=expected_issue):
                candidate = deepcopy(report)
                candidate["engagement"].update(engagement_update)
                response = self.client.put(f"/reports/{report_id}", json=candidate)
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected_issue, response.json()["error"]["message"])

        candidate = deepcopy(report)
        candidate["engagement"].update({
            "app_name": "Portal-2: (Web)",
            "ci_number": "CI-123",
            "bsn_number": "BSN-456",
            "app_owner": "Anne-Marie Owner",
            "tester": "QA Tester",
            "test_windows": {
                "production": {"start_date": "2026-01-01", "end_date": "2026-01-01", "test_time": "08:00-17:00"},
                "non_production": {"start_date": "2026-01-03", "end_date": "2026-01-04", "test_time": "Any time"},
            },
            "test_accounts": [{"user_role": "Admin-2 / QA", "username": "DOMAIN\\qa.user@example"}],
            "limitations": "No API - version 2. (Read only) & 'approved' / \"reviewed\"",
        })
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=candidate).status_code, 200)
        renamed = self.client.patch(f"/reports/{report_id}/name", json={"app_name": "Bad/App"})
        self.assertEqual(renamed.status_code, 422)
        self.assertEqual(renamed.json()["detail"], 'Application name contains invalid character: "/" (slash)')

    def test_unexpected_errors_return_diagnostics_and_write_referenced_log(self) -> None:
        client = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main.workspace, "load", side_effect=RuntimeError("internal diagnostic detail")):
            response = client.get("/reports/r_diagnostic/setup", headers={"accept": "application/json"})

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["detail"], "Unexpected error. Check the application log for details.")
        diagnostic = payload["error"]
        self.assertEqual(diagnostic["code"], "unexpected_error")
        self.assertEqual(diagnostic["function"], "setup")
        self.assertEqual(diagnostic["exception_type"], "RuntimeError")
        self.assertRegex(diagnostic["reference"], r"^[0-9a-f]{12}$")
        self.assertNotIn("internal diagnostic detail", response.text)
        self.assertEqual(response.headers["X-VulnReport-Error"], diagnostic["reference"])

        log_text = main.ERROR_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn(diagnostic["reference"], log_text)
        self.assertIn("RuntimeError: internal diagnostic detail", log_text)

    def test_report_rejects_invalid_evidence_metadata_and_references(self) -> None:
        report = main.workspace.create_report().model_dump(mode="json", by_alias=True)
        report["evidence"]["ev_invalid"] = {
            "file": "../outside.png",
            "original_name": "outside.png",
            "width_px": 1,
            "height_px": 1,
            "sha256": "0" * 64,
            "uploaded_at": report["saved_at"],
        }
        with self.assertRaises(ValueError):
            Report.model_validate(report)

    def test_report_rejects_unsafe_and_duplicate_identifiers(self) -> None:
        report = main.workspace.create_report().model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{"uid": 'v_unsafe" onclick="alert(1)'}, {"uid": "v_duplicate"}, {"uid": "v_duplicate"}]
        with self.assertRaises(ValueError):
            Report.model_validate(report)

        report = main.workspace.create_report().model_dump(mode="json", by_alias=True)
        report["engagement"]["test_windows"] = {"production": {"start_date": "2026-01-02", "end_date": "2026-01-01"}}
        with self.assertRaises(ValueError):
            Report.model_validate(report)

        report["evidence"] = {}
        report["vulnerabilities"] = [{"uid": "v_image", "contents": [{"type": "description", "fragments": [{"frag_id": "f_image", "type": "image", "evidence_id": "ev_missing"}]}]}]
        with self.assertRaises(ValueError):
            Report.model_validate(report)

    def test_legacy_duplicate_fragment_repair(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["vulnerabilities"] = [{"uid": "v_legacy", "contents": [{"type": "description", "fragments": [{"frag_id": "f_duplicate", "type": "paragraph", "runs": []}]}, {"type": "proof_of_concept", "fragments": [{"frag_id": "f_duplicate", "type": "paragraph", "runs": []}]}]}]
        atomic_write_json(path, draft)
        legacy = self.client.get("/reports/legacy")
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()[0]["report_id"], report_id)
        self.assertTrue(legacy.json()[0]["repairable"])
        self.assertEqual(self.client.get("/reports").json(), [])
        direct = self.client.get(f"/reports/{report_id}/setup", headers={"accept": "text/html"})
        self.assertEqual(direct.status_code, 422)
        self.assertIn('href="/"', direct.text)
        self.assertEqual(self.client.post(f"/reports/{report_id}/repair").status_code, 200)
        fragments = [fragment.frag_id for content in main.workspace.load(report_id).vulnerabilities[0].contents for fragment in content.fragments]
        self.assertEqual(len(fragments), len(set(fragments)))

    def test_workspace_restores_legacy_app_types_and_repairs_empty_lists(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["engagement"].pop("tested_channels")
        draft["engagement"]["tested_channels"] = ["web", "mobile"]
        draft["vulnerabilities"] = [{
            "uid": "v_legacy",
            "contents": [{"type": "description", "fragments": [{"frag_id": "f_list", "type": "numbered_list", "items": []}]}],
        }]
        atomic_write_json(path, draft)

        migrated = main.workspace.load(report_id)

        # The retired token could not express web+mobile at all; the list restores it losslessly.
        self.assertEqual(migrated.engagement.tested_channels, ["web", "mobile"])
        self.assertEqual(len(migrated.vulnerabilities[0].contents[0].fragments[0].items), 1)

    def test_the_retired_test_type_token_migrates_on_every_entry_path(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["engagement"].pop("tested_channels")
        draft["engagement"]["test_type"] = "web_api"
        draft["vulnerabilities"] = [{"uid": "v_poc", "poc_variant": "web_api", "poc_variant_declined": ["mobile"]}]
        atomic_write_json(path, draft)

        loaded = main.workspace.load(report_id)
        self.assertEqual(loaded.engagement.tested_channels, ["web", "api"])
        self.assertEqual(loaded.vulnerabilities[0].poc_variants, ["web", "api"])
        self.assertEqual(loaded.vulnerabilities[0].poc_variant_declined, ["mobile"])

        # import_report never goes through load_path, so the model validator is what has to cover it.
        payload = loaded.model_dump(mode="json", by_alias=True)
        payload["engagement"].pop("tested_channels")
        payload["engagement"]["test_type"] = "mobile"
        payload["report_id"] = "r_importedtypes"
        imported = main.workspace.import_report(payload)
        self.assertEqual(imported.engagement.tested_channels, ["mobile"])

    def test_a_report_cannot_cover_no_app_type_at_all(self) -> None:
        report_id = self.new_report()
        payload = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        payload["engagement"]["tested_channels"] = []
        payload["report_id"] = "r_nochannels"
        with self.assertRaises(ValidationError):
            main.workspace.import_report(payload)

    def test_app_types_fall_back_to_the_reports_own_targets_not_to_web(self) -> None:
        """A payload carrying no app-type information at all must not narrow the report to web and
        delete every API target it already holds."""
        resolved = resolve_tested_channels({
            "scope_targets": [
                {"target_id": "tgt_a", "environment": "production", "channel": "api", "value": "POST /v1/pay"},
                {"target_id": "tgt_m", "environment": "production", "channel": "mobile", "value": "Wallet app"},
            ],
        })
        self.assertEqual(resolved, ["api", "mobile"])
        self.assertEqual(resolve_tested_channels({}), ["web"])
        # Present-but-empty is a deliberate choice and must stay empty for the field's floor to catch it.
        self.assertEqual(resolve_tested_channels({"engagement": {"tested_channels": []}}), [])
        # A bare string is the one malformed shape the retired migration produced.
        self.assertEqual(resolve_tested_channels({"engagement": {"tested_channels": "web"}}), ["web"])
        # Both keys can only coexist in a hand-edited file; union is the only rule that drops nothing.
        self.assertEqual(resolve_tested_channels({"engagement": {"tested_channels": ["mobile"], "test_type": "web_api"}}), ["web", "api", "mobile"])

    def test_workflow_routes_enforce_setup_and_finding_gates(self) -> None:
        report_id = self.new_report()
        self.assertEqual(self.client.get(f"/reports/{report_id}/findings", follow_redirects=False).headers["location"], f"/reports/{report_id}/setup?incomplete=setup")
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit", follow_redirects=False).headers["location"], f"/reports/{report_id}/setup?incomplete=setup")

        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Gate Test", "ci_number": "CI-GATE"})
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/findings", follow_redirects=False).headers["location"], f"/reports/{report_id}/setup?incomplete=setup")

        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["test_windows"] = {
            "production": {"start_date": "2026-01-01", "end_date": "2026-01-02", "test_time": "Any time"},
            "non_production": {"start_date": "2026-01-01", "end_date": "2026-01-02", "test_time": "7:00 EST"},
        }
        report["engagement"].update({"segment": "JH", "report_type": "annual_pentest"})
        report["scope_text"] = {
            "production": {"web": "https://prod.example.test"},
            "non_production": {"web": "https://test.example.test"},
        }
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/findings").status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit", follow_redirects=False).headers["location"], f"/reports/{report_id}/findings?incomplete=findings")

        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{"uid": "v_gate", "title": "Complete finding", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_new", "scope": {"mode": "custom", "custom_locations": {"production": {"web": ["https://prod.example.test"]}}}}]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit").status_code, 200)

    def test_new_engagement_defaults_optional_setup_details(self) -> None:
        report_id = self.new_report()
        engagement = main.workspace.load(report_id).engagement
        self.assertIsNone(engagement.segment)
        self.assertIsNone(engagement.report_type)
        self.assertEqual(engagement.limitations, "N/A")
        self.assertEqual([(account.user_role, account.username) for account in engagement.test_accounts], [("N/A", "N/A")])

    def test_affected_channels_resolve_the_proof_of_concept_variants(self) -> None:
        report = main.workspace.create_report()
        report.engagement.tested_channels = ["web", "api"]
        report.scope_targets = [
            ScopeTarget(target_id="tgt_web", environment="production", channel="web", value="https://prod.example.test"),
            ScopeTarget(target_id="tgt_api", environment="production", channel="api", value="POST /v1/pay"),
        ]
        finding = Vulnerability(uid="v_chan", title="Finding")
        report.vulnerabilities = [finding]
        entry = {"web": [1], "api": [1]}

        finding.scope = Scope(mode="custom", target_ids=["tgt_api"])
        self.assertEqual(applicable_poc_variants(finding, report, entry), ["api"])

        # A mixed finding now offers every app type it touches, in canonical order, instead of nothing.
        finding.scope = Scope(mode="custom", target_ids=["tgt_api", "tgt_web"])
        self.assertEqual(applicable_poc_variants(finding, report, entry), ["web", "api"])

        # A typed-in endpoint now carries its own app type, so it resolves like a selected target.
        finding.scope = Scope(mode="custom", custom_locations={"production": {"web": ["https://typed.example.test"]}})
        self.assertEqual(applicable_poc_variants(finding, report, entry), ["web"])

        # No draft on disk exercises the non-custom modes, so they are covered here deliberately.
        finding.scope = Scope(mode="all")
        self.assertEqual(applicable_poc_variants(finding, report, entry), ["web", "api"])

        # An app type the entry has no steps for is never offered.
        self.assertEqual(applicable_poc_variants(finding, report, {"api": [1]}), ["api"])

        finding.scope = Scope(mode="custom")
        self.assertEqual(applicable_poc_variants(finding, report, entry), [])

    def test_reopening_a_finding_clears_the_resolved_remediation_boilerplate(self) -> None:
        """Resolving replaces the remediation with a sentence saying none was needed. Reopening has
        to take it back out, or the finding ships claiming it was fixed."""
        finding = Vulnerability(uid="v_reopen", title="Finding", status="open_previously_discovered")
        provision(finding)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        remediation.fragments = [ParagraphFragment(frag_id="f_mine", type="paragraph", runs=[Run(text="Rotate the signing key.")])]

        finding.status = "resolved"
        provision(finding)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        self.assertEqual([run.text for run in remediation.fragments[0].runs], ["None, the vulnerability has been remediated."])

        finding.status = "open_previously_discovered"
        provision(finding)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        self.assertEqual([fragment.type for fragment in remediation.fragments], ["paragraph"])
        self.assertEqual(remediation.fragments[0].runs, [], "the resolved boilerplate outlived the resolved status")

    def test_a_testers_own_remediation_survives_provisioning(self) -> None:
        """The boilerplate is recognised by its marker, not its wording, so a tester who writes that
        same sentence on an open finding keeps it."""
        finding = Vulnerability(uid="v_keep", title="Finding", status="open_new")
        provision(finding)
        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        remediation.fragments = [ParagraphFragment(frag_id="f_typed", type="paragraph", runs=[Run(text="None, the vulnerability has been remediated.")])]

        provision(finding)

        remediation = next(content for content in finding.contents if content.type == "recommended_remediation")
        self.assertEqual(remediation.fragments[0].frag_id, "f_typed")

    def test_applying_a_proof_of_concept_keeps_images_and_leaves_the_previous_one_alone(self) -> None:
        finding = Vulnerability(uid="v_poc", title="Finding", status="open_previously_discovered")
        provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        previous.fragments = [ListFragment(frag_id="f_old", type="numbered_list", items=[ListItem(runs=[Run(text="Old evidence")])])]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof.fragments = [
            ListFragment(frag_id="f_mine", type="numbered_list", items=[ListItem(runs=[Run(text="My own step")])]),
            ImageFragment(frag_id="f_shot", type="image", environment="production", evidence_id="ev_keepme", caption="Screenshot"),
        ]
        steps = [ListFragment(frag_id="f_lib", type="numbered_list", items=[ListItem(runs=[Run(text="Library step")])])]

        apply_poc_variant(finding, steps, ["web"])

        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        self.assertEqual([fragment.type for fragment in proof.fragments], ["numbered_list", "image"])
        self.assertEqual(proof.fragments[0].items[0].runs[0].text, "Library step")
        self.assertEqual(proof.fragments[1].evidence_id, "ev_keepme")
        self.assertNotEqual(proof.fragments[0].frag_id, "f_lib")
        self.assertEqual(previous.fragments[0].items[0].runs[0].text, "Old evidence")
        self.assertEqual(finding.poc_variants, ["web"])

    def test_installing_several_app_types_yields_one_continuously_numbered_list(self) -> None:
        """Two list fragments each restart at 1 in the generated document, so appended steps have to
        collapse into a single list to read as one procedure."""
        finding = Vulnerability(uid="v_multi", title="Finding")
        provision(finding)
        steps = [
            ListFragment(frag_id="f_web", type="numbered_list", items=[ListItem(runs=[Run(text="Open the browser")]), ListItem(runs=[Run(text="Proxy it")])]),
            ListFragment(frag_id="f_api", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request")])]),
        ]

        apply_poc_variant(finding, steps, ["web", "api"], "merge")

        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        lists = [fragment for fragment in proof.fragments if fragment.type == "numbered_list"]
        self.assertEqual(len(lists), 1)
        self.assertEqual([item.runs[0].text for item in lists[0].items], ["Open the browser", "Proxy it", "Send the request"])
        self.assertEqual(finding.poc_variants, ["web", "api"])

    def test_a_proof_of_concept_always_keeps_a_steps_list(self) -> None:
        """Steps are the substance of a proof of concept, so neither deleting the list nor replacing
        it from a library entry that carries none may leave the section without one."""
        finding = Vulnerability(uid="v_steps", title="Finding", status="open_previously_discovered")
        provision(finding)
        for content in finding.contents:
            if content.type.endswith("proof_of_concept"):
                content.fragments = [fragment for fragment in content.fragments if fragment.type != "numbered_list"]

        provision(finding)
        for content in finding.contents:
            if content.type.endswith("proof_of_concept"):
                self.assertEqual(content.fragments[0].type, "numbered_list", f"{content.type} was left with no steps")

        apply_poc_variant(finding, [ParagraphFragment(frag_id="f_prose", type="paragraph", runs=[Run(text="Prose only")])], ["web"])
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        self.assertEqual([fragment.type for fragment in proof.fragments], ["numbered_list", "paragraph", "image"])

    def test_asset_version_follows_a_static_edit_without_a_restart(self) -> None:
        """Frozen at import, the token keeps serving a cached script for the life of the process, so
        an edited page looks unchanged until the tester reloads by hand."""
        pattern = re.compile(r"app\.css\?v=(\d+)")
        static = Path(main.__file__).resolve().parent / "web" / "static"
        script = static / "app.js"
        stamps = script.stat()
        newest = max(path.stat().st_mtime for path in static.glob("*.*"))
        before = pattern.search(self.client.get("/").text).group(1)
        try:
            os.utime(script, (stamps.st_atime, newest + 60))
            after = pattern.search(self.client.get("/").text).group(1)
        finally:
            os.utime(script, (stamps.st_atime, stamps.st_mtime))
        self.assertNotEqual(before, after)

    def test_installing_one_app_type_leaves_another_refusal_standing(self) -> None:
        finding = Vulnerability(uid="v_memory", title="Finding", poc_variant_declined=["api", "web"])
        provision(finding)
        apply_poc_variant(finding, [ListFragment(frag_id="f_new", type="numbered_list", items=[ListItem(runs=[Run(text="Step")])])], ["web"])
        # Declining API and accepting Web are independent decisions now that variants are per app type.
        self.assertEqual(finding.poc_variant_declined, ["api"])
        self.assertEqual(finding.poc_variants, ["web"])

    def test_report_filename_uses_segment_type_and_report_year(self) -> None:
        report = main.workspace.create_report()
        report.engagement.segment = "Asia"
        report.engagement.app_name = 'Payments: Portal / APAC'
        report.engagement.report_date = date(2026, 9, 8)
        expected_labels = {
            "annual_pentest": "Annual Pentest",
            "retest": "Retest",
            "deployment_pentest": "Deployment Pentest",
            "new_test": "New Test",
        }
        for report_type, label in expected_labels.items():
            report.engagement.report_type = report_type
            self.assertEqual(main.report_export_filename(report), f"Asia - Payments Portal APAC - {label} 2026.zip")

    def test_non_custom_scope_modes_resolve_report_targets(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Scope Modes",
            "ci_number": "CI-SCOPE",
            "segment": "GWAM",
            "report_type": "deployment_pentest",
            "test_windows": {
                "production": {"start_date": "2026-01-01", "end_date": "2026-01-02"},
                "non_production": {"start_date": "2026-01-01", "end_date": "2026-01-02"},
            },
        })
        report["scope_text"] = {
            "production": {"web": "https://prod.example.test"},
            "non_production": {"web": "https://test.example.test"},
        }
        report["vulnerabilities"] = [{
            "uid": f"v_{mode}",
            "title": mode,
            "likelihood": "low",
            "impact": "low",
            "severity": "low",
            "status": "open_new",
            "scope": {"mode": mode},
        } for mode in ("all", "all_production", "all_non_production")]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit").status_code, 200)

    def test_mobile_scope_uses_character_allowlist_instead_of_url_validation(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Mobile Scope",
            "ci_number": "CI-MOBILE",
            "segment": "JH",
            "report_type": "annual_pentest",
            "tested_channels": ["mobile"],
            "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-01-01", "end_date": "2026-01-01"}},
        })
        allowed_target = "Client's \"Mobile\" App: iOS/Android_v2.1, QA-&"
        report["scope_text"] = {"production": {"mobile": f"# ignored ! []\n{allowed_target}"}}

        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["report"]["scope_targets"][0]["value"], allowed_target)

        invalid = saved.json()["report"]
        invalid["scope_text"] = {"production": {"mobile": "Mobile App!"}}
        rejected = self.client.put(f"/reports/{report_id}", json=invalid)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "invalid_scope")
        self.assertIn('Production Mobile scope contains invalid character: "!" (exclamation mark)', rejected.json()["error"]["message"])

        web = saved.json()["report"]
        web["engagement"]["tested_channels"] = ["web"]
        web["scope_text"] = {"production": {"web": "https://example.test/path?x=1&y=2"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=web).status_code, 200)
        # Narrowing with no finding to strand is allowed and silent server-side; warning the tester
        # before it happens is the Setup page's job.
        self.assertEqual([target.channel for target in main.workspace.load(report_id).scope_targets], ["web"])

    def test_image_slots_follow_affected_environments_and_allow_multiple(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Evidence Environments", "ci_number": "CI-EVIDENCE"})
        report["scope_text"] = {
            "production": {"web": "https://prod.example.test"},
            "non_production": {"web": "https://test.example.test"},
        }
        first_save = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(first_save.status_code, 200)
        report = first_save.json()["report"]
        targets = {target["environment"]: target["target_id"] for target in report["scope_targets"]}
        report["vulnerabilities"] = [
            {
                "uid": "v_evidence",
                "title": "Environment evidence",
                "likelihood": "low",
                "impact": "low",
                "severity": "low",
                "status": "open_new",
                "scope": {"mode": "custom", "target_ids": [targets["production"]]},
            },
            {
                "uid": "v_evidence_uat",
                "title": "Non-Production evidence",
                "likelihood": "low",
                "impact": "low",
                "severity": "low",
                "status": "open_new",
                "scope": {"mode": "custom", "target_ids": [targets["non_production"]]},
            },
        ]
        production_save = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(production_save.status_code, 200)
        finding = next(item for item in production_save.json()["report"]["vulnerabilities"] if item["uid"] == "v_evidence")
        images = [fragment for content in finding["contents"] for fragment in content["fragments"] if fragment["type"] == "image"]
        self.assertEqual([image["environment"] for image in images], ["production"])
        non_production_finding = next(item for item in production_save.json()["report"]["vulnerabilities"] if item["uid"] == "v_evidence_uat")
        non_production_images = [fragment for content in non_production_finding["contents"] for fragment in content["fragments"] if fragment["type"] == "image"]
        self.assertEqual([image["environment"] for image in non_production_images], ["non_production"])

        report = production_save.json()["report"]
        report["vulnerabilities"][0]["scope"]["target_ids"].append(targets["non_production"])
        both_save = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(both_save.status_code, 200)
        finding = both_save.json()["report"]["vulnerabilities"][0]
        proof = next(content for content in finding["contents"] if content["type"] == "proof_of_concept")
        images = [fragment for fragment in proof["fragments"] if fragment["type"] == "image"]
        self.assertEqual([image["environment"] for image in images], ["production", "non_production"])

        report = both_save.json()["report"]
        proof = next(content for content in report["vulnerabilities"][0]["contents"] if content["type"] == "proof_of_concept")
        proof["fragments"].append({"frag_id": "f_extra_prod", "type": "image", "environment": "production", "caption": "Additional production evidence"})
        multiple_save = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(multiple_save.status_code, 200)
        proof = next(content for content in multiple_save.json()["report"]["vulnerabilities"][0]["contents"] if content["type"] == "proof_of_concept")
        self.assertEqual([fragment["environment"] for fragment in proof["fragments"] if fragment["type"] == "image"].count("production"), 2)

    def test_save_rejects_stale_writes_and_removed_scope_references(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Safety Test", "ci_number": "CI-SAFETY"})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": ""}}
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        current = saved.json()["report"]
        stale = deepcopy(current)
        current["engagement"]["app_owner"] = "Current tester"
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)
        stale["engagement"]["app_owner"] = "Stale tester"
        conflict = self.client.put(f"/reports/{report_id}", json=stale)
        self.assertEqual(conflict.status_code, 409)
        diagnostic = conflict.json()["error"]
        self.assertEqual(diagnostic["code"], "stale_report")
        self.assertEqual(diagnostic["function"], "save_report")
        self.assertEqual(diagnostic["status"], 409)
        self.assertTrue(diagnostic["recoverable"])
        self.assertEqual(diagnostic["latest_saved_at"], main.workspace.load(report_id).saved_at.isoformat())
        self.assertRegex(diagnostic["reference"], r"^[0-9a-f]{12}$")
        self.assertNotIn("report", diagnostic)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        target_id = current["scope_targets"][0]["target_id"]
        current["vulnerabilities"] = [{"uid": "v_scope", "title": "Scoped finding", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_new", "scope": {"mode": "custom", "target_ids": [target_id], "location_values": {target_id: "https://prod.example.test"}}}]
        saved = self.client.put(f"/reports/{report_id}", json=current)
        self.assertEqual(saved.status_code, 200)
        unsafe = saved.json()["report"]
        unsafe["scope_text"] = {"production": {"web": ""}, "non_production": {"web": ""}}
        rejected = self.client.put(f"/reports/{report_id}", json=unsafe)
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("Scoped finding", rejected.json()["detail"])

    def test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected(self) -> None:
        """A finding scoped to "all non-production" holds no target IDs, so only a
        before-and-after location check can notice that Setup just stranded it."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Coverage Test", "ci_number": "CI-COVER", "tested_environments": ["production", "non_production"]})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": "https://uat.example.test"}}
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        current = saved.json()["report"]
        current["vulnerabilities"] = [{"uid": "v_lower", "title": "Lower region finding", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_new", "scope": {"mode": "all_non_production"}}]
        saved = self.client.put(f"/reports/{report_id}", json=current)
        self.assertEqual(saved.status_code, 200)

        # The tester unchecks Non-Production on Setup.
        narrowed = saved.json()["report"]
        narrowed["engagement"]["tested_environments"] = ["production"]
        narrowed["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": "https://uat.example.test"}}
        rejected = self.client.put(f"/reports/{report_id}", json=narrowed)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "referenced_scope_removed")
        self.assertIn("Lower region finding", rejected.json()["detail"])

        # Narrowing that leaves the finding a location is still allowed.
        widened = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        widened["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": "https://uat.example.test\nhttps://staging.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=widened).status_code, 200)

    def test_narrowing_the_surface_drops_typed_locations_for_removed_channels(self) -> None:
        """A typed API endpoint left on a web-only engagement would print a location that is out of scope."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Typed Scope", "ci_number": "CI-TYPED", "tested_channels": ["web", "api"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://web.example.test", "api": "POST /v1/pay"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_typed", "title": "Typed finding", "likelihood": "high", "impact": "high", "severity": "high",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {},
                      "custom_locations": {"production": {"web": ["https://web.example.test/a"], "api": ["POST /v1/typed"]}}},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        narrowed = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        narrowed["engagement"]["tested_channels"] = ["web"]
        narrowed["scope_text"] = {"production": {"web": "https://web.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=narrowed).status_code, 200)

        scope = main.workspace.load(report_id).vulnerabilities[0].scope
        self.assertEqual(scope.custom_locations, {"production": {"web": ["https://web.example.test/a"]}})
        self.assertEqual(affected_channels(main.workspace.load(report_id).vulnerabilities[0], main.workspace.load(report_id)), ["web"])

    def test_dropping_an_app_type_that_held_a_findings_only_location_is_rejected(self) -> None:
        """A finding located only by typed API endpoints loses every location when API is dropped,
        which strands it exactly as removing a selected target would."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Typed Only", "ci_number": "CI-ONLY", "tested_channels": ["web", "api"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://web.example.test", "api": "POST /v1/pay"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_api_only", "title": "API only finding", "likelihood": "high", "impact": "high", "severity": "high",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {},
                      "custom_locations": {"production": {"api": ["POST /v1/only"]}}},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        narrowed = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        narrowed["engagement"]["tested_channels"] = ["web"]
        narrowed["scope_text"] = {"production": {"web": "https://web.example.test"}}
        rejected = self.client.put(f"/reports/{report_id}", json=narrowed)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "referenced_scope_removed")
        self.assertIn("API only finding", rejected.json()["detail"])

        # The draft on disk still has the finding and its location, so nothing was stranded.
        kept = main.workspace.load(report_id)
        self.assertTrue(scope_has_location(kept.vulnerabilities[0], kept))

    def test_narrowing_the_environments_keeps_an_uploaded_screenshot_where_it_belongs(self) -> None:
        """Relabelling a non-production screenshot as Production would file the tester's evidence
        under a heading it never came from, and leave a second Production slot demanding another."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Evidence Home", "ci_number": "CI-EV", "tested_environments": ["production", "non_production"]})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": "https://uat.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        buffer = BytesIO()
        Image.new("RGB", (16, 16), "red").save(buffer, format="PNG")
        upload = self.client.post(f"/reports/{report_id}/evidence", files={"file": ("shot.png", buffer.getvalue(), "image/png")})
        self.assertEqual(upload.status_code, 200)
        evidence_id = upload.json()["evidence"]["evidence_id"]

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_shot", "title": "Shot finding", "likelihood": "high", "impact": "high", "severity": "high",
            "status": "open_new", "scope": {"mode": "all"},
            "contents": [{"type": "proof_of_concept", "fragments": [
                {"frag_id": "f_steps", "type": "numbered_list", "items": [{"runs": [{"text": "step"}]}]},
                {"frag_id": "f_uat", "type": "image", "environment": "non_production", "evidence_id": evidence_id, "caption": "UAT screenshot", "width_mm": None},
            ]}],
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        narrowed = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        narrowed["engagement"]["tested_environments"] = ["production"]
        narrowed["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=narrowed).status_code, 200)

        finding = main.workspace.load(report_id).vulnerabilities[0]
        carried = next(fragment for content in finding.contents for fragment in content.fragments if fragment.frag_id == "f_uat")
        self.assertEqual(carried.environment, "non_production", "an uploaded screenshot keeps the environment it was taken in")
        production_slots = [
            fragment for content in finding.contents if content.type == "proof_of_concept"
            for fragment in content.fragments
            if isinstance(fragment, ImageFragment) and fragment.environment == "production"
        ]
        self.assertEqual(len(production_slots), 1, "narrowing must not leave two Production slots to fill")

    def test_an_empty_slot_for_a_dropped_environment_stops_being_asked_for(self) -> None:
        """An untouched slot for an environment the finding no longer affects is nobody's to fill."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Slot Drop", "ci_number": "CI-SLOT", "tested_environments": ["production", "non_production"]})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}, "non_production": {"web": "https://uat.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_slots", "title": "Slot finding", "likelihood": "high", "impact": "high", "severity": "high",
            "status": "open_new", "scope": {"mode": "all"},
            "contents": [{"type": "proof_of_concept", "fragments": [
                {"frag_id": "f_steps", "type": "numbered_list", "items": [{"runs": [{"text": "step"}]}]}]}],
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)
        both = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(
            sorted(fragment.environment for content in both.contents for fragment in content.fragments if isinstance(fragment, ImageFragment)),
            ["non_production", "production"],
        )

        narrowed = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        narrowed["engagement"]["tested_environments"] = ["production"]
        narrowed["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=narrowed).status_code, 200)

        finding = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual(
            [fragment.environment for content in finding.contents for fragment in content.fragments if isinstance(fragment, ImageFragment)],
            ["production"],
        )

    def test_a_status_change_does_not_destroy_the_previous_proof_or_conclusion(self) -> None:
        """Switching a finding to "open new" hides last year's proof; it must not delete it, because
        switching back is a correction the tester is allowed to make."""
        finding = Vulnerability(uid="v_carry", title="Carried finding", status="open_previously_discovered")
        provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        previous.fragments = [ListFragment(frag_id="f_last", type="numbered_list", items=[ListItem(runs=[Run(text="Last year's proof")])])]
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments = [ParagraphFragment(frag_id="f_note", type="paragraph", runs=[Run(text="Hand written conclusion")])]

        finding.status = "open_new"
        provision(finding)
        self.assertNotIn("previous_proof_of_concept", [content.type for content in finding.contents[:3]])

        finding.status = "open_previously_discovered"
        provision(finding)
        restored = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        self.assertEqual(
            [run.text for fragment in restored.fragments if isinstance(fragment, ListFragment) for item in fragment.items for run in item.runs],
            ["Last year's proof"],
        )
        restored_conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        self.assertIn(
            "Hand written conclusion",
            [run.text for fragment in restored_conclusion.fragments for run in getattr(fragment, "runs", [])],
        )

    def test_a_carried_section_is_not_asked_to_be_completed(self) -> None:
        """A section the status does not print is kept for safekeeping, so its empty fragments must
        not block a document that will never contain them."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Carry", "ci_number": "CI-CARRY", "segment": "JH", "report_type": "annual_pentest",
            "tester": "QA Tester", "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-01-01", "end_date": "2026-01-05", "test_time": "Any time"}},
        })
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_carry", "title": "Carry finding", "likelihood": "low", "impact": "low", "severity": "low",
            "status": "open_new", "scope": {"mode": "all"},
            "contents": [
                {"type": "description", "fragments": [{"frag_id": "f_d", "type": "paragraph", "runs": [{"text": "described"}]}]},
                {"type": "recommended_remediation", "fragments": [{"frag_id": "f_r", "type": "paragraph", "runs": [{"text": "fix it"}]}]},
                {"type": "in_conclusion", "fragments": [
                    {"frag_id": "f_written", "type": "paragraph", "runs": [{"text": "kept text"}]},
                    {"frag_id": "f_blank", "type": "note", "runs": []},
                ]},
            ],
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        saved = main.workspace.load(report_id)
        self.assertIn("in_conclusion", [content.type for content in saved.vulnerabilities[0].contents])
        self.assertNotIn("Carry finding: in_conclusion text is required", generation_issues(saved))

    def test_the_previous_proof_slot_is_born_with_an_environment(self) -> None:
        """Provisioning creates this slot, so provisioning owes it the environment that generation
        then demands; nothing else ever assigns one."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Prev Env", "ci_number": "CI-PREV", "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_prev", "title": "Previously discovered", "likelihood": "low", "impact": "low", "severity": "low",
            "status": "open_previously_discovered", "scope": {"mode": "all"},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        saved = main.workspace.load(report_id)
        previous = next(content for content in saved.vulnerabilities[0].contents if content.type == "previous_proof_of_concept")
        slots = [fragment for fragment in previous.fragments if isinstance(fragment, ImageFragment)]
        self.assertTrue(slots, "provisioning creates a previous-proof image slot")
        self.assertTrue(all(fragment.environment for fragment in slots), "an app-created slot must not be born without an environment")
        self.assertNotIn(
            "Previously discovered: environment/image/caption required for image fragment",
            generation_issues(saved),
        )

    def test_generator_locations_use_typed_endpoints_grouped_by_channel(self) -> None:
        """custom_locations is keyed by channel, so a flat read would print "web" and "api"
        instead of the endpoints, and per-channel ordering would interleave the two lists."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Locations", "ci_number": "CI-LOC", "tested_channels": ["web", "api"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://a.example.test\nhttps://b.example.test", "api": "POST /v1/one"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_loc", "title": "Typed", "likelihood": "low", "impact": "low", "severity": "low",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {},
                      "custom_locations": {"production": {"web": ["https://a.example.test/admin"], "api": ["POST /v1/typed"]}}},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)
        stored = main.workspace.load(report_id)
        self.assertEqual(
            _finding_locations(stored, stored.vulnerabilities[0])["production"],
            ["https://a.example.test/admin", "POST /v1/typed"],
        )

        widened = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        widened["vulnerabilities"][0]["scope"] = {"mode": "all", "target_ids": [], "location_values": {}, "custom_locations": {}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=widened).status_code, 200)
        stored = main.workspace.load(report_id)
        self.assertEqual(
            _finding_locations(stored, stored.vulnerabilities[0])["production"],
            ["https://a.example.test", "https://b.example.test", "POST /v1/one"],
        )

    def test_untested_environment_contributes_no_dates_to_the_document(self) -> None:
        """Its window stays stored so re-checking restores it, but the report must not claim it was tested."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Coverage", "ci_number": "CI-COV", "tested_environments": ["production", "non_production"],
            "test_windows": {
                "production": {"start_date": "2026-08-01", "end_date": "2026-08-05", "test_time": "Any time"},
                "non_production": {"start_date": "2026-07-01", "end_date": "2026-07-05", "test_time": "Evenings only"},
            },
        })
        report["scope_text"] = {"production": {"web": "https://p.example.test"}, "non_production": {"web": "https://n.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(_metadata(main.workspace.load(report_id))["non-prod-time"], "Evenings only")

        narrowed = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        narrowed["engagement"]["tested_environments"] = ["production"]
        narrowed["scope_text"] = {"production": {"web": "https://p.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=narrowed).status_code, 200)
        stored = main.workspace.load(report_id)
        metadata = _metadata(stored)
        self.assertEqual([metadata["non-prod-start"], metadata["non-prod-end"], metadata["non-prod-time"]], ["N/A", "N/A", "N/A"])
        self.assertIn("non_production", stored.engagement.test_windows, "the window must survive for a re-check")

    def test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything(self) -> None:
        """The Findings page labels them "additional", and writes them without switching the
        scope to custom, so an all-scoped finding must still print what the tester typed."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Additional", "ci_number": "CI-ADD", "tested_channels": ["web"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://main.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        current["vulnerabilities"] = [{
            "uid": "v_all", "title": "Everywhere", "likelihood": "low", "impact": "low", "severity": "low",
            "scope": {"mode": "all", "target_ids": [], "location_values": {},
                      "custom_locations": {"production": {"web": ["https://main.example.test/admin"]}}},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)
        stored = main.workspace.load(report_id)
        self.assertEqual(stored.vulnerabilities[0].scope.mode, "all")
        self.assertEqual(
            _finding_locations(stored, stored.vulnerabilities[0])["production"],
            ["https://main.example.test", "https://main.example.test/admin"],
        )

    def test_repeated_scope_lines_collapse_and_stay_saveable(self) -> None:
        """Target IDs are reused by value, so a pasted duplicate line once made every
        later save fail with "duplicate scope target id"."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Dupes", "ci_number": "CI-DUPE"})
        pasted = "https://same.example.test\nhttps://other.example.test\nhttps://same.example.test\n  https://same.example.test  "
        report["scope_text"] = {"production": {"web": pasted}}
        first = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            [target["value"] for target in first.json()["report"]["scope_targets"]],
            ["https://same.example.test", "https://other.example.test"],
        )
        original_ids = [target["target_id"] for target in first.json()["report"]["scope_targets"]]

        for _ in range(3):
            again = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
            again["scope_text"] = {"production": {"web": pasted}}
            response = self.client.put(f"/reports/{report_id}", json=again)
            self.assertEqual(response.status_code, 200)
            self.assertEqual([target["target_id"] for target in response.json()["report"]["scope_targets"]], original_ids)

    def test_two_findings_cannot_share_a_finding_number(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Numbering", "ci_number": "CI-NUM"})
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        report["vulnerabilities"] = [
            {"uid": "v_one", "display_id": "1", "title": "First", "status": "open_new", "scope": {"mode": "all"}},
            {"uid": "v_two", "display_id": "1", "title": "Second", "status": "open_new", "scope": {"mode": "all"}},
        ]
        rejected = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("same finding number", json.dumps(rejected.json()))

    def test_setup_completes_without_a_ci_or_bsn_number(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "No Identifier", "ci_number": "", "bsn_number": "",
            "segment": "JH", "report_type": "annual_pentest", "tester": "QA Tester",
            "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-08-01", "end_date": "2026-08-02", "test_time": "Any time"}},
        })
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        stored = main.workspace.load(report_id)
        self.assertTrue(main.setup_is_complete(stored), "a report without a CI or BSN number should still be complete")
        self.assertEqual(self.client.get(f"/reports/{report_id}/findings", follow_redirects=False).status_code, 200)

    def test_workspace_compare_and_swap_allows_only_one_concurrent_writer(self) -> None:
        report = main.workspace.create_report()
        expected_saved_at = report.saved_at
        copies = [report.model_copy(deep=True), report.model_copy(deep=True)]
        workspaces = [Workspace(Path(self.temp_dir.name), "QA Tester"), Workspace(Path(self.temp_dir.name), "QA Tester")]
        barrier = threading.Barrier(3)
        outcomes = []

        def write(copy_index: int) -> None:
            copies[copy_index].engagement.app_owner = f"Writer {copy_index}"
            barrier.wait()
            try:
                workspaces[copy_index].save_if_current(copies[copy_index], expected_saved_at)
                outcomes.append("saved")
            except StaleReportError:
                outcomes.append("stale")

        threads = [threading.Thread(target=write, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["saved", "stale"])

    def test_library_evidence_and_missing_report_routes(self) -> None:
        report_id = self.new_report()
        entries = self.client.get("/library/search?q=")
        self.assertEqual(entries.status_code, 200)
        self.assertTrue(entries.json())
        inserted = self.client.post(f"/reports/{report_id}/library/{entries.json()[0]['library_id']}")
        self.assertEqual(inserted.status_code, 200)
        self.assertIn("saved_at", inserted.json())
        self.assertIn("finding", inserted.json())
        revision = inserted.json()["saved_at"]
        inserted_again = self.client.post(f"/reports/{report_id}/library/{entries.json()[0]['library_id']}", headers={"X-Report-Saved-At": revision})
        self.assertEqual(inserted_again.status_code, 200)
        fragment_ids = [fragment.frag_id for finding in main.workspace.load(report_id).vulnerabilities for content in finding.contents for fragment in content.fragments]
        self.assertEqual(len(fragment_ids), len(set(fragment_ids)))
        self.assertEqual(self.client.post(f"/reports/{report_id}/library/not-found").status_code, 404)

        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        uploaded = self.client.post(f"/reports/{report_id}/evidence", files={"file": ("../proof.png", image_data.getvalue(), "image/png")})
        self.assertEqual(uploaded.status_code, 200)
        self.assertIn("saved_at", uploaded.json())
        self.assertEqual(uploaded.json()["evidence"]["original_name"], "proof.png")
        evidence_id = uploaded.json()["evidence"]["evidence_id"]
        evidence = self.client.get(f"/reports/{report_id}/evidence/{evidence_id}")
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.headers["content-type"], "image/png")
        exported = self.client.get(f"/reports/{report_id}/export")
        imported = self.client.post("/reports/import", files={"file": ("evidence-report.zip", exported.content, "application/zip")})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{imported.json()['report_id']}/evidence/{evidence_id}").content, evidence.content)
        tampered = BytesIO()
        with zipfile.ZipFile(BytesIO(exported.content)) as source_archive, zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as target_archive:
            for name in source_archive.namelist():
                contents = source_archive.read(name)
                target_archive.writestr(name, contents + b"tampered" if name.startswith("evidence/") else contents)
        rejected = self.client.post("/reports/import", files={"file": ("tampered.zip", tampered.getvalue(), "application/zip")})
        self.assertEqual(rejected.status_code, 422)
        duplicate = self.client.post(f"/reports/{report_id}/duplicate")
        self.assertEqual(duplicate.status_code, 200)
        duplicate_id = duplicate.json()["report_id"]
        self.assertEqual(self.client.get(f"/reports/{duplicate_id}/evidence/{evidence_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/reports/{duplicate_id}").status_code, 200)
        self.assertEqual(self.client.post(f"/reports/{report_id}/evidence", files={"file": ("bad.txt", b"not an image", "text/plain")}).status_code, 400)
        self.assertEqual(self.client.get(f"/reports/{report_id}/evidence/not-found").status_code, 404)

        missing = "r_does_not_exist"
        self.assertEqual(self.client.get(f"/reports/{missing}/export").status_code, 404)
        self.assertEqual(self.client.put(f"/reports/{missing}", json={}).status_code, 404)
        self.assertEqual(self.client.delete(f"/reports/{missing}").status_code, 404)
        browser_404 = self.client.get(f"/reports/{missing}/setup", headers={"accept": "text/html"})
        self.assertEqual(browser_404.status_code, 404)
        self.assertIn('href="/"', browser_404.text)

    def test_stale_evidence_upload_does_not_leave_an_orphan_file(self) -> None:
        report_id = self.new_report()
        stale = main.workspace.load(report_id)
        current = main.workspace.load(report_id)
        current.engagement.app_name = "Moved Report"
        current.app_id = "CI-MOVED"
        main.workspace.save_if_current(current, current.saved_at)
        relative_file = "evidence/ev_stale.png"

        with self.assertRaises(StaleReportError):
            main.workspace.save_evidence_if_current(
                stale,
                stale.saved_at,
                relative_file,
                b"image",
                1024,
            )

        self.assertEqual(list(Path(self.temp_dir.name).glob(f"apps/**/{relative_file}")), [])

    def test_library_content_does_not_gain_empty_starter_fragments(self) -> None:
        report_id = self.new_report()
        inserted = self.client.post(f"/reports/{report_id}/library/VDB-047")

        self.assertEqual(inserted.status_code, 200)
        remediation = next(
            content
            for content in inserted.json()["finding"]["contents"]
            if content["type"] == "recommended_remediation"
        )
        self.assertEqual(
            [fragment["type"] for fragment in remediation["fragments"]],
            ["bulleted_list", "note"],
        )

    def test_a_library_finding_still_needs_an_affected_location(self) -> None:
        """Scope defaults to "all", which would read as a deliberate every-target choice and walk
        a freshly inserted finding straight past the affected-location gate."""
        report_id = self.new_report()
        report = main.workspace.load(report_id)
        report.engagement.segment = "JH"
        report.engagement.app_name = "Gate"
        report.engagement.report_type = "annual_pentest"
        report.engagement.tester = "QA Tester"
        report.engagement.tested_environments = ["production"]
        report.engagement.test_windows = {"production": TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))}
        report.scope_targets = [ScopeTarget(target_id="tgt_gate", environment="production", channel="web", value="https://prod.example.test")]
        main.workspace.save(report)

        inserted = self.client.post(f"/reports/{report_id}/library/VDB-047")
        self.assertEqual(inserted.status_code, 200)
        self.assertEqual(inserted.json()["finding"]["scope"]["mode"], "custom")

        editor = self.client.get(f"/reports/{report_id}/edit", follow_redirects=False)
        self.assertEqual(editor.status_code, 303)
        self.assertIn("incomplete=findings", editor.headers["location"])

    def test_generate_docx_route_uses_template_and_report_filename(self) -> None:
        report_id = self.new_report()
        incomplete = self.client.get(f"/reports/{report_id}/generate")
        self.assertEqual(incomplete.status_code, 422)
        self.assertIn("issues", incomplete.json()["detail"])
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "segment": "JH",
            "report_type": "annual_pentest",
            "app_name": "Generated Report",
            "ci_number": "CI-GENERATE",
            "report_date": "2026-09-09",
            "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-09-01", "end_date": "2026-09-02", "test_time": "Any time"}},
        })
        report["scope_text"] = {"production": {"web": "https://prod.example.test"}}
        report["vulnerabilities"] = [{
            "uid": "v_generate",
            "title": "Generated finding",
            "likelihood": "low",
            "impact": "low",
            "severity": "low",
            "status": "open_new",
            "scope": {"mode": "custom", "custom_locations": {"production": {"web": ["https://prod.example.test"]}}},
        }]
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        image_data = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
        uploaded = self.client.post(f"/reports/{report_id}/evidence", files={"file": ("proof.png", image_data.getvalue(), "image/png")})
        self.assertEqual(uploaded.status_code, 200)
        evidence_id = uploaded.json()["evidence"]["evidence_id"]
        report = main.workspace.load(report_id)
        finding = report.vulnerabilities[0]
        next(content for content in finding.contents if content.type == "description").fragments[0].runs = [Run(text="Complete description")]
        next(content for content in finding.contents if content.type == "recommended_remediation").fragments[0].runs = [Run(text="Complete remediation")]
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        next(fragment for fragment in proof.fragments if fragment.type == "numbered_list").items[0].runs = [Run(text="Complete proof step")]
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        image.evidence_id = evidence_id
        image.caption = "Production proof"
        main.workspace.save_if_current(report, report.saved_at)

        generated = self.client.get(f"/reports/{report_id}/generate")
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertIn('filename="JH - Generated Report - Annual Pentest 2026.docx"', generated.headers["content-disposition"])
        rendered = Document(BytesIO(generated.content))
        text = "\n".join([*(paragraph.text for paragraph in rendered.paragraphs), *(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)])
        self.assertIn("Generated finding", text)
        self.assertNotIn("{{", text)
        toc_entries = []
        for paragraph in rendered.element.body.iter(qn("w:p")):
            style = paragraph.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
            if style is not None and style.get(qn("w:val"), "").startswith("TOC"):
                entry = "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
                if entry:
                    toc_entries.append(entry)
        self.assertTrue(any("Generated finding" in entry for entry in toc_entries))
        caption = next(paragraph for paragraph in rendered.paragraphs if paragraph.text.endswith("Production proof"))
        self.assertEqual(caption.text, "Figure 2 Production proof")
        self.assertEqual(
            [node.text for node in caption._p.iter(qn("w:instrText"))],
            [r" SEQ Figure \* ARABIC "],
        )
        shape = rendered.inline_shapes[0]
        self.assertIsNone(shape._inline.graphic.graphicData.pic.spPr.find(qn("a:ln")))
        relationship_id = shape._inline.graphic.graphicData.pic.blipFill.blip.get(qn("r:embed"))
        bordered_image = Image.open(BytesIO(rendered.part.related_parts[relationship_id].blob)).convert("RGB")
        width, height = bordered_image.size
        self.assertTrue(all(bordered_image.getpixel((x, 0)) == (0, 0, 0) for x in range(width)))
        self.assertTrue(all(bordered_image.getpixel((x, height - 1)) == (0, 0, 0) for x in range(width)))
        self.assertTrue(all(bordered_image.getpixel((0, y)) == (0, 0, 0) for y in range(height)))
        self.assertTrue(all(bordered_image.getpixel((width - 1, y)) == (0, 0, 0) for y in range(height)))
        image_paragraph = next(shape._inline.iterancestors(qn("w:p")))
        self.assertEqual(image_paragraph.find(qn("w:pPr") + "/" + qn("w:jc")).get(qn("w:val")), "center")

        with patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents):
            saved = self.client.post(f"/reports/{report_id}/generate")
        self.assertEqual(saved.status_code, 200)
        # Generated reports land in one shared folder at the project root.
        output_path = main.GENERATED / "JH - Generated Report - Annual Pentest 2026.docx"
        self.assertEqual(saved.json(), {
            "filename": output_path.name,
            "path": str(output_path),
            "folder": str(main.GENERATED),
        })
        self.assertTrue(output_path.is_file())
        self.assertTrue(output_path.read_bytes().startswith(b"PK"))

        # Regenerating keeps the earlier export instead of overwriting it.
        with patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents):
            again = self.client.post(f"/reports/{report_id}/generate")
        second_path = main.GENERATED / "JH - Generated Report - Annual Pentest 2026 (2).docx"
        self.assertEqual(again.json()["filename"], second_path.name)
        self.assertTrue(second_path.is_file())
        self.assertTrue(output_path.is_file())
        output_path.unlink()
        second_path.unlink()

    def test_library_rejects_invalid_documents(self) -> None:
        path = Path(self.temp_dir.name) / "invalid-library.json"
        path.write_text('{"schema_version":"1.4","entry_count":1,"entries":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            Library(path)

    def test_an_unreadable_library_does_not_stop_the_app_from_starting(self) -> None:
        path = Path(self.temp_dir.name) / "broken-library.json"
        path.write_text('{"schema_version":"1.4","entry_count":9,"entries":[]}', encoding="utf-8")
        recovered = Library.load_or_empty(path)
        self.assertEqual(recovered.entries, [])
        self.assertIn("broken-library.json", recovered.load_error)
        self.assertEqual(recovered.search(""), [])
        self.assertIsNone(recovered.get("VDB-001"))

    def test_the_shipped_library_still_validates(self) -> None:
        # The library loads at import time, so a malformed file stops every report, not one request.
        shipped = Library(Path(main.__file__).resolve().parent.parent / "resources" / "vuln_library.json")
        self.assertTrue(shipped.entries)
        self.assertFalse(shipped.load_error)

    def test_a_proof_of_concept_set_must_have_steps_and_unique_ids_within_itself(self) -> None:
        step = {"frag_id": "f_step1", "type": "numbered_list", "items": [{"runs": [{"text": "Intercept the request"}]}]}
        entry = {"library_id": "VDB-900", "source_id": 900, "title": "Sample", "contents": [], "proof_of_concept": {"web": [step]}}
        document = {"schema_version": "1.4", "entry_count": 1, "entries": [entry]}
        path = Path(self.temp_dir.name) / "poc-library.json"

        def write(value: dict) -> Library:
            path.write_text(json.dumps(value), encoding="utf-8")
            return Library(path)

        self.assertEqual(write(document).entries[0]["proof_of_concept"]["web"][0]["frag_id"], "f_step1")

        # The same id may repeat across app types, because only one set is ever copied into a finding.
        shared = deepcopy(document)
        shared["entries"][0]["proof_of_concept"]["api"] = [deepcopy(step)]
        self.assertEqual(len(write(shared).entries[0]["proof_of_concept"]), 2)

        duplicated = deepcopy(document)
        duplicated["entries"][0]["proof_of_concept"]["web"] = [step, deepcopy(step)]
        path.write_text(json.dumps(duplicated), encoding="utf-8")
        with self.assertRaises(ValueError):
            Library(path)

        empty = deepcopy(document)
        empty["entries"][0]["proof_of_concept"]["api"] = []
        path.write_text(json.dumps(empty), encoding="utf-8")
        with self.assertRaises(ValueError):
            Library(path)

    def test_preferences_recover_from_invalid_json_shape(self) -> None:
        path = Path(self.temp_dir.name) / "prefs.json"
        path.write_text('{"schema_version":"1.4","tester":"invalid"}', encoding="utf-8")
        identity = Identity("QA Tester", "QA Tester", "test")
        with patch("app.tester_identity.resolve_identity", return_value=identity):
            prefs = load_or_bootstrap(path)
        self.assertEqual(prefs["tester"]["display_name"], "QA Tester")
        self.assertEqual(prefs["library_path"], "resources/vuln_library.json")
        self.assertTrue(path.with_suffix(".corrupt.json").is_file())

    def test_reports_browser_visit_redirects_to_manager(self) -> None:
        response = self.client.get("/reports", headers={"accept": "text/html"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

    def test_in_conclusion_uses_current_title_and_bold_status(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{"uid": "v_conclusion", "title": "Known issue", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_previously_discovered", "scope": {"mode": "custom", "custom_locations": {"production": {"web": ["https://prod.example.test"]}}}}]
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)
        finding = saved.json()["report"]["vulnerabilities"][0]
        conclusion = next(content for content in finding["contents"] if content["type"] == "in_conclusion")
        self.assertEqual(len(conclusion["fragments"]), 1)
        self.assertIsNone(conclusion["fragments"][0]["generated"])
        self.assertEqual(conclusion["fragments"][0]["runs"], [{"text": 'The finding "Known issue" is still ', "bold": False, "italic": False, "underline": False}, {"text": "Open", "bold": True, "italic": False, "underline": False}, {"text": ".", "bold": False, "italic": False, "underline": False}])

        finding["title"] = "Remediated issue"
        finding["status"] = "resolved"
        resolved = self.client.put(f"/reports/{report_id}", json=saved.json()["report"] | {"vulnerabilities": [finding]})
        self.assertEqual(resolved.status_code, 200)
        conclusion = next(content for content in resolved.json()["report"]["vulnerabilities"][0]["contents"] if content["type"] == "in_conclusion")
        self.assertEqual(conclusion["fragments"][0]["runs"], [{"text": 'The finding "Remediated issue" is ', "bold": False, "italic": False, "underline": False}, {"text": "Resolved", "bold": True, "italic": False, "underline": False}, {"text": ".", "bold": False, "italic": False, "underline": False}])

        custom_runs = [{"text": "Additional validation was completed. The issue remains accepted by the owner."}]
        resolved_report = resolved.json()["report"]
        resolved_report["vulnerabilities"][0]["contents"][-1]["fragments"][0]["runs"] = custom_runs
        resolved_report["vulnerabilities"][0]["title"] = "Renamed after tester edit"
        preserved = self.client.put(f"/reports/{report_id}", json=resolved_report)
        self.assertEqual(preserved.status_code, 200)
        conclusion = next(content for content in preserved.json()["report"]["vulnerabilities"][0]["contents"] if content["type"] == "in_conclusion")
        self.assertEqual(conclusion["fragments"][0]["runs"][0]["text"], custom_runs[0]["text"])

    def test_direct_report_url_redirects_or_shows_navigable_not_found(self) -> None:
        report_id = self.new_report()
        opened = self.client.get(f"/reports/{report_id}", follow_redirects=False)
        self.assertEqual(opened.status_code, 303)
        self.assertEqual(opened.headers["location"], f"/reports/{report_id}/setup")
        missing = self.client.get("/reports/anystring", headers={"accept": "text/html"})
        self.assertEqual(missing.status_code, 404)
        self.assertIn('href="/"', missing.text)


if __name__ == "__main__":
    unittest.main()