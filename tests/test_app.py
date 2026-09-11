from __future__ import annotations

import json
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

from app import main
from app.library import Library
from app.storage import atomic_write_json, read_json
from app.workspace import StaleReportError, Workspace, safe_name
from app.models import Report, Run
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
        self.assertEqual(original_path.parent.parent.name, "X_unnamed")
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

    def test_workspace_migrates_legacy_test_type_and_empty_lists(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["engagement"].pop("test_type")
        draft["engagement"]["tested_channels"] = ["web", "api"]
        draft["vulnerabilities"] = [{
            "uid": "v_legacy",
            "contents": [{"type": "description", "fragments": [{"frag_id": "f_list", "type": "numbered_list", "items": []}]}],
        }]
        atomic_write_json(path, draft)

        migrated = main.workspace.load(report_id)

        self.assertEqual(migrated.engagement.test_type, "web_api")
        self.assertEqual(len(migrated.vulnerabilities[0].contents[0].fragments[0].items), 1)

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
        report["vulnerabilities"] = [{"uid": "v_gate", "title": "Complete finding", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_new", "scope": {"mode": "custom", "custom_locations": {"production": ["https://prod.example.test"]}}}]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit").status_code, 200)

    def test_new_engagement_defaults_optional_setup_details(self) -> None:
        report_id = self.new_report()
        engagement = main.workspace.load(report_id).engagement
        self.assertIsNone(engagement.segment)
        self.assertIsNone(engagement.report_type)
        self.assertEqual(engagement.limitations, "N/A")
        self.assertEqual([(account.user_role, account.username) for account in engagement.test_accounts], [("N/A", "N/A")])

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
            "test_type": "mobile",
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
        web["engagement"]["test_type"] = "web"
        web["scope_text"] = {"production": {"web": "https://example.test/path?x=1&y=2"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=web).status_code, 200)

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
            "scope": {"mode": "custom", "custom_locations": {"production": ["https://prod.example.test"]}},
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

        with (
            patch.object(main, "update_docx_bytes_with_word", side_effect=lambda contents: contents),
            patch.object(main, "reveal_generated_report") as reveal,
        ):
            saved = self.client.post(f"/reports/{report_id}/generate")
        self.assertEqual(saved.status_code, 200)
        output_path = main.workspace.find_path(report_id).parent / "JH - Generated Report - Annual Pentest 2026.docx"
        self.assertEqual(saved.json(), {
            "filename": output_path.name,
            "path": str(output_path),
            "folder_opened": True,
        })
        self.assertTrue(output_path.is_file())
        self.assertTrue(output_path.read_bytes().startswith(b"PK"))
        reveal.assert_called_once_with(output_path)

    def test_library_rejects_invalid_documents(self) -> None:
        path = Path(self.temp_dir.name) / "invalid-library.json"
        path.write_text('{"schema_version":"1.4","entry_count":1,"entries":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            Library(path)

    def test_preferences_recover_from_invalid_json_shape(self) -> None:
        path = Path(self.temp_dir.name) / "prefs.json"
        path.write_text('{"schema_version":"1.4","tester":"invalid"}', encoding="utf-8")
        identity = Identity("QA Tester", "QA Tester", "test")
        with patch("app.tester_identity.resolve_identity", return_value=identity):
            prefs = load_or_bootstrap(path)
        self.assertEqual(prefs["tester"]["display_name"], "QA Tester")
        self.assertEqual(prefs["library_path"], "vuln_library.json")
        self.assertTrue(path.with_suffix(".corrupt.json").is_file())

    def test_reports_browser_visit_redirects_to_manager(self) -> None:
        response = self.client.get("/reports", headers={"accept": "text/html"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

    def test_in_conclusion_uses_current_title_and_bold_status(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{"uid": "v_conclusion", "title": "Known issue", "likelihood": "low", "impact": "low", "severity": "low", "status": "open_previously_discovered", "scope": {"mode": "custom", "custom_locations": {"production": ["https://prod.example.test"]}}}]
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