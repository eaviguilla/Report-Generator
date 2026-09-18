from __future__ import annotations

import asyncio
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

from fastapi import HTTPException
from fastapi.testclient import TestClient
from docx import Document
from docx.oxml.ns import qn
from PIL import Image
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app import main
from app import docx_report, models, report_service
from app.docx_report import _finding_locations, _metadata, generation_issues
from app.library import Library
from app.report_service import affected_channels, affected_environments, applicable_poc_variants, apply_poc_variant, provision, scope_has_location
from app.storage import atomic_write_json, read_json
from app.workspace import StaleReportError, Workspace, safe_name
from app.models import Content, ImageFragment, ListFragment, ListItem, NoteFragment, ParagraphFragment, Report, Run, Scope, ScopeTarget, TestWindow, Vulnerability, resolve_tested_channels
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

    def test_additional_information_fields_default_empty_and_survive_a_save(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["vulnerabilities"] = [{
            "uid": "v_legacy",
            "title": "Drafted before the three fields existed",
            "status": "open_previously_discovered",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {}, "custom_locations": {}},
            "contents": [],
        }]
        atomic_write_json(path, draft)
        loaded = main.workspace.load(report_id).vulnerabilities[0]
        self.assertEqual((loaded.severity_review_tickets, loaded.cvss_score, loaded.cvss_vector), ("", "", ""))

        vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"][0].update(severity_review_tickets="1234\n5678", cvss_score="9.8", cvss_vector=vector)
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)
        returned = saved.json()["report"]["vulnerabilities"][0]
        self.assertEqual((returned["severity_review_tickets"], returned["cvss_score"], returned["cvss_vector"]), ("1234\n5678", "9.8", vector))
        self.assertEqual(main.workspace.load(report_id).vulnerabilities[0].severity_review_tickets, "1234\n5678")

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

    def test_disconnected_json_body_is_a_client_error(self) -> None:
        class DisconnectedRequest:
            async def body(self):
                raise ClientDisconnect()

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(main.read_json_object(DisconnectedRequest()))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Request body was interrupted")

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
            ("limitations", "No testing @ production", 'Limitations contains invalid character: "@" (at sign)'),
            ("non_production_label", "UAT@2", 'Non-Production name contains invalid character: "@" (at sign)'),
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
                "non_production": {"start_date": "2026-01-03", "end_date": "2026-01-04", "test_time": "Anytime"},
            },
            "test_accounts": [{"user_role": "Admin-2 / QA", "username": "DOMAIN\\qa.user@example"}],
            "limitations": "No API - version 2. (Read only) & 'approved' / \"reviewed\"",
        })
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=candidate).status_code, 200)
        renamed = self.client.patch(f"/reports/{report_id}/name", json={"app_name": "Bad/App"})
        self.assertEqual(renamed.status_code, 422)
        self.assertEqual(renamed.json()["detail"], 'Application name contains invalid character: "/" (slash)')

    def test_additional_information_input_validation_rejects_unapproved_characters(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{
            "uid": "v_rules",
            "title": "Character rule finding",
            "status": "open_previously_discovered",
            "scope": {"mode": "custom", "target_ids": [], "location_values": {}, "custom_locations": {}},
            "contents": [],
        }]
        cases = [
            ("cvss_score", "9.8a", 'CVSS Score contains invalid character: "a" (latin small letter a)'),
            ("cvss_score", "9,8", 'CVSS Score contains invalid character: "," (comma)'),
            ("cvss_vector", "CVSS:3.1/AV:N_", 'CVSS Vector contains invalid character: "_" (underscore)'),
            ("cvss_vector", "CVSS:3.1 AV:N", 'CVSS Vector contains invalid character: " " (space)'),
            # The prefix belongs to the document; typing it into the draft is an error, not a shortcut.
            ("severity_review_tickets", "1234-5678", 'Severity Review Tickets contains invalid character: "-" (hyphen)'),
            ("severity_review_tickets", "1234 5678", 'Severity Review Tickets contains invalid character: " " (space)'),
        ]
        for field, value, expected_issue in cases:
            with self.subTest(field=field, value=value):
                candidate = deepcopy(report)
                candidate["vulnerabilities"][0][field] = value
                response = self.client.put(f"/reports/{report_id}", json=candidate)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_finding")
                self.assertIn(expected_issue, response.json()["error"]["message"])

        candidate = deepcopy(report)
        candidate["vulnerabilities"][0].update(
            severity_review_tickets="1234\n56789",
            cvss_score="10.0",
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        )
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=candidate).status_code, 200)

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

    def test_the_remediation_repair_only_touches_paragraphs(self) -> None:
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        boilerplate = report_service.RESOLVED_REMEDIATION
        draft["vulnerabilities"] = [
            {
                "uid": "v_note",
                "status": "open_new",
                "contents": [{
                    "type": "recommended_remediation",
                    "fragments": [{"frag_id": "f_note", "type": "note", "runs": [{"text": boilerplate}]}],
                }],
            },
            {
                "uid": "v_paragraph",
                "status": "open_new",
                "contents": [{
                    "type": "recommended_remediation",
                    "fragments": [{"frag_id": "f_paragraph", "type": "paragraph", "runs": [{"text": boilerplate}]}],
                }],
            },
        ]
        atomic_write_json(path, draft)

        loaded = main.workspace.load(report_id)
        note = loaded.vulnerabilities[0].contents[0].fragments[0]
        paragraph = loaded.vulnerabilities[1].contents[0].fragments[0]

        self.assertEqual("".join(run.text for run in note.runs), boilerplate)
        self.assertEqual(paragraph.runs, [])

    def test_a_legacy_all_scope_loads_as_explicit_custom_targets(self) -> None:
        """A retired mode carrying no IDs resolved its locations on every read. Relabelling it
        without resolving first would leave the finding with no location at all."""
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["scope_targets"] = [
            {"target_id": "tgt_api", "environment": "production", "channel": "api", "value": "POST /v1/pay", "order": 0},
            {"target_id": "tgt_web", "environment": "production", "channel": "web", "value": "https://prod.example.test", "order": 0},
        ]
        draft["vulnerabilities"] = [{"uid": "v_legacy", "title": "Legacy", "scope": {"mode": "all", "target_ids": []}}]
        atomic_write_json(path, draft)

        scope = main.workspace.load(report_id).vulnerabilities[0].scope
        self.assertEqual(scope.mode, "custom")
        # Channel order, not storage order, so the generated document prints what it always printed.
        self.assertEqual(scope.target_ids, ["tgt_web", "tgt_api"])

    def test_a_legacy_scope_drops_target_ids_that_no_longer_exist(self) -> None:
        """target_ids were never validated while the mode was not custom, so a stale one could
        accumulate. Carrying it into a custom scope would demote the whole draft to the legacy list."""
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["scope_targets"] = [{"target_id": "tgt_live", "environment": "production", "channel": "web", "value": "https://prod.example.test", "order": 0}]
        draft["vulnerabilities"] = [{"uid": "v_stale", "title": "Stale", "scope": {"mode": "all", "target_ids": ["tgt_gone"]}}]
        atomic_write_json(path, draft)

        scope = main.workspace.load(report_id).vulnerabilities[0].scope
        self.assertEqual(scope.target_ids, ["tgt_live"])

    def test_a_scope_mode_that_escapes_the_migration_still_loads(self) -> None:
        """The field coercion is the net under the report-level migration. It degrades to a visibly
        incomplete finding rather than a ValidationError, which would hide the report entirely."""
        self.assertEqual(Scope.model_validate({"mode": "all"}).mode, "custom")
        # The coercion never runs when mode is absent; the default supplies it there.
        self.assertEqual(Scope().mode, "custom")

    def test_a_repaired_draft_keeps_its_migrated_scope_on_disk(self) -> None:
        """repair_duplicate_fragment_ids validates and then persists the raw draft, so a migration
        living only in the model would be written straight back out."""
        report_id = self.new_report()
        path = main.workspace.find_path(report_id)
        draft = read_json(path)
        draft["scope_targets"] = [{"target_id": "tgt_one", "environment": "production", "channel": "web", "value": "https://prod.example.test", "order": 0}]
        draft["vulnerabilities"] = [{
            "uid": "v_dupe", "title": "Dupe", "scope": {"mode": "all", "target_ids": []},
            "contents": [{"type": "description", "fragments": [
                {"frag_id": "f_same", "type": "paragraph", "runs": []},
                {"frag_id": "f_same", "type": "paragraph", "runs": []},
            ]}],
        }]
        atomic_write_json(path, draft)

        main.workspace.repair_duplicate_fragment_ids(report_id)

        written = read_json(path)["vulnerabilities"][0]["scope"]
        self.assertEqual(written["mode"], "custom")
        self.assertEqual(written["target_ids"], ["tgt_one"])

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

    def test_thick_client_widens_the_channel_set_without_disturbing_the_existing_three(self) -> None:
        """Widening a Literal is only safe if every value that validated before still does, and if
        the canonical order absorbs the new member without reordering the old ones."""
        self.assertEqual(models.CHANNELS, ("web", "api", "mobile", "thick_client"))
        self.assertEqual(models.COMPONENT_CHANNELS, ("mobile", "thick_client"))
        # Twin of channelLabels in app.js. Every channel needs an entry or a message prints "undefined".
        self.assertEqual(sorted(models.CHANNEL_LABELS), sorted(models.CHANNELS))

        # A draft written before description existed still validates, and identity is unaffected.
        target = ScopeTarget(target_id="tgt_thick", environment="production", channel="thick_client", value="Acme.exe")
        self.assertEqual(target.description, "")

        # Present-only-in-targets fallback and the legacy test_type union both still resolve.
        self.assertEqual(resolve_tested_channels({"scope_targets": [
            {"target_id": "tgt_t", "environment": "production", "channel": "thick_client", "value": "Acme.exe"},
            {"target_id": "tgt_w", "environment": "production", "channel": "web", "value": "https://prod.example.test"},
        ]}), ["web", "thick_client"])
        self.assertEqual(resolve_tested_channels({"engagement": {"test_type": "web_api"}}), ["web", "api"])

        # A retired scope mode resolves in canonical order, and thick client files last.
        mapping = {
            "scope_targets": [
                {"target_id": "tgt_thick", "environment": "production", "channel": "thick_client", "value": "Acme.exe"},
                {"target_id": "tgt_web", "environment": "production", "channel": "web", "value": "https://prod.example.test"},
                {"target_id": "tgt_mobile", "environment": "production", "channel": "mobile", "value": "Wallet app"},
            ],
            "vulnerabilities": [{"uid": "v_all", "scope": {"mode": "all"}}],
        }
        models.normalise_scope_modes(mapping)
        self.assertEqual(mapping["vulnerabilities"][0]["scope"]["target_ids"], ["tgt_web", "tgt_mobile", "tgt_thick"])

    def test_the_library_editor_offers_every_channel_the_model_knows(self) -> None:
        """Third copy of the channel list, in a page that cannot import app.js. Drift here silently
        drops a whole app type's saved steps on save, and no browser test loads that page."""
        template = (Path(main.__file__).parent / "web" / "templates" / "library_editor.html").read_text(encoding="utf-8")
        variants = re.search(r"const variants = \[(.*?)\]", template).group(1)
        for channel in models.CHANNELS:
            self.assertIn(f'"{channel}"', variants)
            self.assertIn(f'id="poc_{channel}"', template)

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
            "production": {"start_date": "2026-01-01", "end_date": "2026-01-02", "test_time": "Anytime"},
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
        self.assertEqual(engagement.non_production_label, "NON-PROD")
        self.assertEqual([(account.user_role, account.username) for account in engagement.test_accounts], [("N/A", "N/A")])

    def test_a_retired_non_production_label_still_loads_and_saves(self) -> None:
        """The label stopped being a closed set. Widening is only safe if every value that validated
        before still does, so this asserts on a label the dropdown can no longer produce."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["non_production_label"] = "TEST/MO"
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        self.assertEqual(main.workspace.load(report_id).engagement.non_production_label, "TEST/MO")

    def test_the_non_production_name_is_only_validated_when_that_environment_is_covered(self) -> None:
        """An unticked Non-Production leaves the field disabled, and a disabled input is exempt from
        browser validation -- so validating it here would 422 a save the client could not block."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"]["non_production_label"] = "UAT@2"
        report["engagement"]["tested_environments"] = ["production"]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

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

        # Both app types selected, so the next assertion has a two-channel finding to narrow.
        finding.scope = Scope(mode="custom", target_ids=["tgt_web", "tgt_api"])

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

    def test_merging_poc_steps_keeps_them_below_an_intervening_note(self) -> None:
        finding = Vulnerability(uid="v_order", title="Finding")
        provision(finding)
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        image = next(fragment for fragment in proof.fragments if fragment.type == "image")
        proof.fragments = [
            ListFragment(frag_id="f_existing", type="numbered_list", items=[ListItem(runs=[Run(text="Existing step")])]),
            NoteFragment(frag_id="f_stop", type="note", runs=[Run(text="Stop after the existing procedure")]),
            image,
        ]
        steps = [ListFragment(frag_id="f_library", type="numbered_list", items=[ListItem(runs=[Run(text="Library step")])])]

        apply_poc_variant(finding, steps, ["web"], "merge")

        self.assertEqual([fragment.type for fragment in proof.fragments], ["numbered_list", "note", "numbered_list", "image"])
        self.assertEqual(proof.fragments[2].items[0].runs[0].text, "Library step")

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

    def test_the_environment_modes_freeze_to_the_targets_they_resolved_to(self) -> None:
        """The retired modes re-resolved against the report's targets on every read, so a finding
        could silently widen when Setup grew. They now freeze to the IDs they stood for."""
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

        stored = main.workspace.load(report_id)
        by_environment = {target.environment: target.target_id for target in stored.scope_targets}
        resolved = {finding.title: (finding.scope.mode, finding.scope.target_ids) for finding in stored.vulnerabilities}
        self.assertEqual(resolved["all"], ("custom", [by_environment["production"], by_environment["non_production"]]))
        self.assertEqual(resolved["all_production"], ("custom", [by_environment["production"]]))
        self.assertEqual(resolved["all_non_production"], ("custom", [by_environment["non_production"]]))

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

    def _component_scope_payload(self, report_id: str, channel: str, scope_text) -> dict:
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Binary Scope",
            "ci_number": "CI-BINARY",
            "segment": "JH",
            "report_type": "annual_pentest",
            "tested_channels": [channel],
            "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-01-01", "end_date": "2026-01-01"}},
        })
        report["scope_text"] = {"production": {channel: scope_text}}
        return report

    def test_component_scope_pairs_each_line_with_its_description_by_raw_index(self) -> None:
        """Pairing after cleaning would let one commented component line shift every description
        below it onto the wrong binary -- wrong, silent, and printed into the delivered report."""
        report_id = self.new_report()
        saved = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "thick_client", {
            "component": "# not a binary\nAcme.exe\n\nAcme.Updater.exe",
            "description": "# ignored\nMain client\n\nBackground updater",
        }))
        self.assertEqual(saved.status_code, 200)
        stored = main.workspace.load(report_id)
        self.assertEqual([(target.value, target.description, target.order) for target in stored.scope_targets], [
            ("Acme.exe", "Main client", 0),
            ("Acme.Updater.exe", "Background updater", 1),
        ])

        # Identity is the (environment, channel, value) triple, so retyping a description alone must
        # not remint the ID and strand every finding that selected the target.
        before = {target.value: target.target_id for target in stored.scope_targets}
        payload = self._component_scope_payload(report_id, "thick_client", {
            "component": "Acme.exe\nAcme.Updater.exe",
            "description": "Main desktop client\nBackground updater",
        })
        payload["saved_at"] = stored.saved_at.isoformat()
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=payload).status_code, 200)
        after = main.workspace.load(report_id)
        self.assertEqual({target.value: target.target_id for target in after.scope_targets}, before)
        self.assertEqual(after.scope_targets[0].description, "Main desktop client")

    def test_component_scope_ignores_an_unpaired_description_and_refuses_a_repeat(self) -> None:
        report_id = self.new_report()
        # A description with no component at its index names nothing, so it creates no target.
        orphan = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "mobile", {
            "component": "Wallet app",
            "description": "Android build\nOrphaned line",
        }))
        self.assertEqual(orphan.status_code, 200)
        self.assertEqual([(target.value, target.description) for target in main.workspace.load(report_id).scope_targets], [("Wallet app", "Android build")])

        # Two builds of one name would silently lose the second row and its description.
        repeated = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "mobile", {
            "component": "Wallet app\nWallet app",
            "description": "Android build\niOS build",
        }))
        self.assertEqual(repeated.status_code, 422)
        self.assertEqual(repeated.json()["error"]["code"], "invalid_scope")
        self.assertIn('Production Mobile scope lists the same component twice: "Wallet app"', repeated.json()["error"]["message"])

    def test_component_scope_shares_one_widened_character_set_across_both_boxes(self) -> None:
        """A strict superset of the retired mobile set: an install path must be typable, and the
        message must name which of the two boxes rejected it."""
        report_id = self.new_report()
        allowed = "C:\\Program Files\\Acme\\acme.exe [x64]"
        saved = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "thick_client", {
            "component": allowed,
            "description": "Client's \"main\" binary; build 2.1 (x64)",
        }))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(main.workspace.load(report_id).scope_targets[0].value, allowed)

        rejected = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "thick_client", {
            "component": "Acme.exe",
            "description": "Crashes on start!",
        }))
        self.assertEqual(rejected.status_code, 422)
        self.assertIn('Production Thick Client scope description contains invalid character: "!" (exclamation mark)', rejected.json()["error"]["message"])

        # The plain string form is still valid for every channel, so a browser cached from before
        # this shape existed degrades rather than 422ing.
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "thick_client", "Acme.exe")).status_code, 200)
        self.assertEqual([(target.value, target.description) for target in main.workspace.load(report_id).scope_targets], [("Acme.exe", "")])

    def test_component_scope_rejects_unicode_separators_instead_of_creating_hidden_rows(self) -> None:
        report_id = self.new_report()
        response = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "mobile", {
            "component": "Alpha\u2028Beta",
            "description": "One\u2028Two",
        }))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_scope")
        self.assertIn('"\u2028" (line separator)', response.json()["error"]["message"])

    def test_component_scope_accepts_null_legacy_pair_fields_as_blank(self) -> None:
        report_id = self.new_report()
        payload = self._component_scope_payload(report_id, "mobile", {
            "component": "Wallet app",
            "description": "Production build",
        })
        payload["engagement"]["tested_environments"] = ["production", "non_production"]
        payload["engagement"]["test_windows"]["non_production"] = {"start_date": "2026-01-02", "end_date": "2026-01-02"}
        payload["scope_text"]["non_production"] = {"mobile": {"component": None, "description": None}}

        response = self.client.put(f"/reports/{report_id}", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(target.environment, target.channel, target.value, target.description) for target in main.workspace.load(report_id).scope_targets],
            [("production", "mobile", "Wallet app", "Production build")],
        )

    def test_component_scope_still_rejects_non_text_pair_fields(self) -> None:
        report_id = self.new_report()
        response = self.client.put(f"/reports/{report_id}", json=self._component_scope_payload(report_id, "mobile", {
            "component": ["Wallet app"],
            "description": {},
        }))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_scope")
        self.assertEqual(response.json()["error"]["message"], "scope target values must be text")

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

    def test_coverage_change_that_strands_a_finding_is_rejected(self) -> None:
        """Losing every location is the one outcome a save still refuses. Losing some of several is
        purged instead, so the refusal has to survive only for the finding left with none."""
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

    def test_removing_one_of_several_scope_lines_still_saves(self) -> None:
        """A finding holding four locations used to be refused outright when any one of them went,
        with no dialog first and no way forward but unticking it by hand on every finding."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Partial", "ci_number": "CI-PART", "tested_channels": ["web"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://one.example.test\nhttps://two.example.test\nhttps://three.example.test"}}
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        current = saved.json()["report"]
        all_ids = [target["target_id"] for target in current["scope_targets"]]
        current["vulnerabilities"] = [{
            "uid": "v_many", "title": "Many locations", "likelihood": "low", "impact": "low", "severity": "low",
            "status": "open_new", "scope": {"mode": "custom", "target_ids": all_ids, "location_values": {}, "custom_locations": {}},
        }]
        saved = self.client.put(f"/reports/{report_id}", json=current)
        self.assertEqual(saved.status_code, 200)

        narrowed = saved.json()["report"]
        narrowed["scope_text"] = {"production": {"web": "https://one.example.test\nhttps://two.example.test"}}
        accepted = self.client.put(f"/reports/{report_id}", json=narrowed)
        self.assertEqual(accepted.status_code, 200)

        stored = main.workspace.load(report_id)
        surviving = {target.target_id for target in stored.scope_targets}
        self.assertEqual(len(surviving), 2)
        # The dropped ID is gone rather than left dangling, which validate_references would reject.
        self.assertEqual(set(stored.vulnerabilities[0].scope.target_ids), surviving)

    def test_removing_a_findings_only_location_is_still_refused(self) -> None:
        """The relaxation must not reach the case it was never about: a finding left with nothing."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Only", "ci_number": "CI-ONLY", "tested_channels": ["web"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://only.example.test\nhttps://other.example.test"}}
        saved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(saved.status_code, 200)

        current = saved.json()["report"]
        only_id = next(target["target_id"] for target in current["scope_targets"] if target["value"] == "https://only.example.test")
        current["vulnerabilities"] = [{
            "uid": "v_one", "title": "Single location", "likelihood": "low", "impact": "low", "severity": "low",
            "status": "open_new", "scope": {"mode": "custom", "target_ids": [only_id], "location_values": {}, "custom_locations": {}},
        }]
        saved = self.client.put(f"/reports/{report_id}", json=current)
        self.assertEqual(saved.status_code, 200)

        narrowed = saved.json()["report"]
        narrowed["scope_text"] = {"production": {"web": "https://other.example.test"}}
        rejected = self.client.put(f"/reports/{report_id}", json=narrowed)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "referenced_scope_removed")
        self.assertIn("Single location", rejected.json()["detail"])

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

    def test_a_status_change_keeps_the_previous_proof_but_not_the_conclusion(self) -> None:
        """Switching a finding to "open new" hides last year's proof; it must not delete it, because
        switching back is a correction the tester is allowed to make. The conclusion is the exception:
        it is a statement about the status, so keeping it would preserve a sentence now made false."""
        finding = Vulnerability(uid="v_carry", title="Carried finding", status="open_previously_discovered")
        provision(finding)
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        previous.fragments = [ListFragment(frag_id="f_last", type="numbered_list", items=[ListItem(runs=[Run(text="Last year's proof")])])]
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments = [ParagraphFragment(frag_id="f_note", type="paragraph", runs=[Run(text="Hand written conclusion")])]

        finding.status = "open_new"
        provision(finding)
        self.assertNotIn("previous_proof_of_concept", [content.type for content in finding.contents[:3]])
        self.assertNotIn("in_conclusion", [content.type for content in finding.contents], "a conclusion outlived the status it described")

        finding.status = "open_previously_discovered"
        provision(finding)
        restored = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        self.assertEqual(
            [run.text for fragment in restored.fragments if isinstance(fragment, ListFragment) for item in fragment.items for run in item.runs],
            ["Last year's proof"],
        )
        restored_conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        self.assertEqual(
            [run.text for fragment in restored_conclusion.fragments for run in getattr(fragment, "runs", [])],
            [],
            "the section comes back empty, so the Content page can offer the standard sentence",
        )

    def test_a_carried_section_is_not_asked_to_be_completed(self) -> None:
        """A section the status does not print is kept for safekeeping, so its empty fragments must
        not block a document that will never contain them."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": "Carry", "ci_number": "CI-CARRY", "segment": "JH", "report_type": "annual_pentest",
            "tester": "QA Tester", "tested_environments": ["production"],
            "test_windows": {"production": {"start_date": "2026-01-01", "end_date": "2026-01-05", "test_time": "Anytime"}},
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
                {"type": "previous_proof_of_concept", "fragments": [
                    {"frag_id": "f_written", "type": "numbered_list", "items": [{"runs": [{"text": "kept text"}]}]},
                    {"frag_id": "f_blank", "type": "note", "runs": []},
                ]},
            ],
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)

        saved = main.workspace.load(report_id)
        self.assertIn("previous_proof_of_concept", [content.type for content in saved.vulnerabilities[0].contents])
        self.assertNotIn("Carry finding: previous_proof_of_concept text is required", generation_issues(saved))

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
                "production": {"start_date": "2026-08-01", "end_date": "2026-08-05", "test_time": "Anytime"},
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

    def test_typed_endpoints_print_alongside_selected_targets(self) -> None:
        """A typed-in endpoint is "additional" to whatever the finding selected, so both print."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({"app_name": "Additional", "ci_number": "CI-ADD", "tested_channels": ["web"], "tested_environments": ["production"]})
        report["scope_text"] = {"production": {"web": "https://main.example.test"}}
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        current = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        target_id = current["scope_targets"][0]["target_id"]
        current["vulnerabilities"] = [{
            "uid": "v_all", "title": "Everywhere", "likelihood": "low", "impact": "low", "severity": "low",
            "scope": {"mode": "custom", "target_ids": [target_id], "location_values": {},
                      "custom_locations": {"production": {"web": ["https://main.example.test/admin"]}}},
        }]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=current).status_code, 200)
        stored = main.workspace.load(report_id)
        self.assertEqual(
            _finding_locations(stored, stored.vulnerabilities[0])["production"],
            ["https://main.example.test", "https://main.example.test/admin"],
        )

    def _report_with_one_target(self, name: str, channels=("web",), environments=("production",)) -> tuple[str, str]:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["engagement"].update({
            "app_name": name, "ci_number": "CI-LOC", "segment": "JH", "report_type": "annual_pentest",
            "tester": "QA Tester", "tested_channels": list(channels), "tested_environments": list(environments),
            "test_windows": {environment: {"start_date": "2026-01-01", "end_date": "2026-01-05", "test_time": "Anytime"} for environment in environments},
        })
        report["scope_text"] = {
            environment: {channel: f"https://{channel}.{environment}.test" for channel in channels}
            for environment in environments
        }
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)
        return report_id, main.workspace.load(report_id).scope_targets[0].target_id

    def _located_finding(self, custom=None, target_ids=None) -> dict:
        return {
            "uid": "v_loc", "title": "Located finding", "likelihood": "low", "impact": "low", "severity": "low",
            "status": "open_new",
            "scope": {"mode": "custom", "target_ids": target_ids or [], "location_values": {}, "custom_locations": custom or {}},
            "contents": [
                {"type": "description", "fragments": [{"frag_id": "f_d", "type": "paragraph", "runs": [{"text": "d"}]}]},
                {"type": "recommended_remediation", "fragments": [{"frag_id": "f_r", "type": "paragraph", "runs": [{"text": "r"}]}]},
                {"type": "proof_of_concept", "fragments": [{"frag_id": "f_l", "type": "numbered_list", "items": [{"runs": [{"text": "s"}]}]}]},
            ],
        }

    def test_a_commented_additional_location_is_a_note_not_a_location(self) -> None:
        """The scope textarea treats a "#" line as a note. The additional-locations box is the same
        box to a tester, so a note there must not stand in for an affected location or print as one."""
        report_id, _ = self._report_with_one_target("Noted")
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [self._located_finding(custom={"production": {"web": ["# ask the app owner which host"]}})]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        stored = main.workspace.load(report_id)
        finding = stored.vulnerabilities[0]
        self.assertFalse(scope_has_location(finding, stored), "a note is not a location")
        self.assertEqual(_finding_locations(stored, finding)["production"], [], "a note must not print as a location")
        self.assertEqual(
            self.client.get(f"/reports/{report_id}/edit", follow_redirects=False).status_code,
            303,
            "the Content page is closed to a finding whose only location is a note",
        )
        # The note itself is kept, so the tester's reminder survives the round trip.
        self.assertEqual(finding.scope.custom_locations["production"]["web"], ["# ask the app owner which host"])

    def test_additional_locations_collapse_repeats_and_stray_spacing(self) -> None:
        """Scope targets already dedupe and trim. The same place typed twice in the other box would
        otherwise print twice in the document."""
        report_id, _ = self._report_with_one_target("Repeats")
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [self._located_finding(
            custom={"production": {"web": ["https://dupe.test", "https://dupe.test", "  https://dupe.test  ", ""]}})]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        stored = main.workspace.load(report_id)
        self.assertEqual(_finding_locations(stored, stored.vulnerabilities[0])["production"], ["https://dupe.test"])

    def test_an_additional_location_outside_the_coverage_is_not_a_location(self) -> None:
        """Only Setup decides what was tested. A line left under an environment or app type the
        engagement no longer covers must not carry a finding into the Content page."""
        report_id, _ = self._report_with_one_target("Uncovered")
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [self._located_finding(custom={"non_production": {"web": ["https://uat.example.test"]}})]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        stored = main.workspace.load(report_id)
        finding = stored.vulnerabilities[0]
        self.assertEqual(affected_environments(finding, stored), [])
        self.assertFalse(scope_has_location(finding, stored))
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit", follow_redirects=False).status_code, 303)

    def test_an_additional_location_alone_opens_the_content_page(self) -> None:
        """The counterpart to the three above: a typed endpoint really is an affected location, and
        a finding that has only one must not be held back."""
        report_id, _ = self._report_with_one_target("Typed only")
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [self._located_finding(custom={"production": {"web": ["https://web.production.test/admin"]}})]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 200)

        stored = main.workspace.load(report_id)
        self.assertTrue(scope_has_location(stored.vulnerabilities[0], stored))
        self.assertEqual(self.client.get(f"/reports/{report_id}/edit", follow_redirects=False).status_code, 200)

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
            "test_windows": {"production": {"start_date": "2026-08-01", "end_date": "2026-08-02", "test_time": "Anytime"}},
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

    def test_a_library_insert_does_not_offer_back_the_content_it_just_copied(self) -> None:
        """The finding arrives holding the entry's own description and remediation, so the Content
        page must not greet the tester with an offer to install what is already there. The
        proof-of-concept offer is tracked by poc_variants instead, so it is not this field's to mark."""
        report_id = self.new_report()
        finding = self.client.post(f"/reports/{report_id}/library/VDB-047").json()["finding"]

        entry = main.library.get("VDB-047")
        supplied = [
            content["type"]
            for content in entry["contents"]
            if content["type"] in ("description", "recommended_remediation") and content["fragments"]
        ]
        self.assertIn("recommended_remediation", supplied, "the fixture no longer exercises this")
        for content_type in supplied:
            self.assertEqual(
                finding["content_offer_resolved"].get(content_type),
                "VDB-047",
                f"{content_type} would be offered content it already holds",
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

    def _component_scope_report(self, report_id: str, channel: str, description: str) -> Report:
        report = main.workspace.load(report_id)
        report.engagement.segment = "JH"
        report.engagement.app_name = "Binary"
        report.engagement.report_type = "annual_pentest"
        report.engagement.tester = "QA Tester"
        report.engagement.tested_environments = ["production"]
        report.engagement.tested_channels = [channel]
        report.engagement.test_windows = {"production": TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))}
        report.scope_targets = [ScopeTarget(target_id="tgt_bin", environment="production", channel=channel, value="Acme.exe", description=description)]
        return report

    def test_mobile_and_thick_client_together_block_setup_without_stranding_the_draft(self) -> None:
        """The rule lives only in setup_issues. Raising on the load path would demote the draft to
        the manager's legacy list, where the checkboxes that caused it cannot be reached."""
        report_id = self.new_report()
        report = self._component_scope_report(report_id, "thick_client", "Windows desktop client")
        report.engagement.tested_channels = ["mobile", "thick_client"]
        report.scope_targets.append(ScopeTarget(target_id="tgt_app", environment="production", channel="mobile", value="Wallet app", description="Android build"))

        self.assertIn("only one of Mobile and Thick Client -- deselect the other", report_service.setup_issues(report))
        self.assertFalse(report_service.setup_is_complete(report))

        # Savable and loadable: the tester must be able to reach Setup and untick one.
        main.workspace.save(report)
        self.assertEqual(main.workspace.load(report_id).engagement.tested_channels, ["mobile", "thick_client"])
        self.assertIn("incomplete=setup", self.client.get(f"/reports/{report_id}/findings", follow_redirects=False).headers["location"])
        self.assertIn("only one of Mobile and Thick Client -- deselect the other", generation_issues(main.workspace.load(report_id)))

        # The union branch of resolve_tested_channels can produce the illegal pair from a file that
        # never submitted it. That file must still open.
        payload = report.model_dump(mode="json", by_alias=True)
        payload["engagement"]["tested_channels"] = ["thick_client"]
        payload["engagement"]["test_type"] = "mobile"
        payload["report_id"] = "r_unioned"
        self.assertEqual(main.workspace.import_report(payload).engagement.tested_channels, ["mobile", "thick_client"])

    def test_a_component_without_a_description_blocks_setup_and_names_itself(self) -> None:
        """A blank description would reach the binaries table as an empty cell. Naming the component
        is the point: a tally cannot say which of ten rows is missing one."""
        report_id = self.new_report()
        self.assertTrue(report_service.setup_is_complete(self._component_scope_report(report_id, "thick_client", "Windows desktop client")))

        blank = self._component_scope_report(report_id, "thick_client", "")
        self.assertEqual(report_service.setup_issues(blank), ['production Thick Client description for "Acme.exe"'])
        self.assertFalse(report_service.setup_is_complete(blank))

        mobile = self._component_scope_report(report_id, "mobile", "")
        self.assertEqual(report_service.setup_issues(mobile), ['production Mobile description for "Acme.exe"'])

        # Web and API carry locations, not components, so the rule never fires for them.
        web = self._component_scope_report(report_id, "web", "")
        web.scope_targets[0].value = "https://prod.example.test"
        self.assertEqual(report_service.setup_issues(web), [])

        # The existing per-environment check still counts value alone.
        empty = self._component_scope_report(report_id, "thick_client", "Windows desktop client")
        empty.scope_targets = []
        self.assertIn("production scope target", report_service.setup_issues(empty))

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
            "test_windows": {"production": {"start_date": "2026-09-01", "end_date": "2026-09-02", "test_time": "Anytime"}},
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
        self.assertEqual(caption.text, "Figure 2. Production proof")
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
        self.assertEqual(conclusion["fragments"][0]["runs"], [], "the app wrote a conclusion instead of offering one")

        # Accepting the Content page's offer is what puts the sentence there; from then on it tracks.
        conclusion["fragments"][0]["runs"] = [{"text": 'The finding "Known issue" is still '}, {"text": "Open", "bold": True}, {"text": "."}]
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

    def test_the_conclusion_recogniser_matches_what_the_builder_writes(self) -> None:
        """Four spellings of one sentence, linked only by this regex. If the two drift apart, every
        default on disk stops being recognised and freezes at the title and status it was stored with."""
        for title in (
            "Plain title",
            'A "quoted" title',
            "Line one\nLine two",
            'Quoted phrase " is Open. still title',
            "Regex . * + ? [ ] ( ) metacharacters",
        ):
            for status_word in ("Open", "Resolved"):
                with self.subTest(title=title, status=status_word):
                    runs = report_service.status_conclusion_runs(title, status_word)
                    written = "".join(run.text for run in runs)
                    self.assertTrue(
                        report_service.STATUS_CONCLUSION_PATTERN.fullmatch(written),
                        f"the builder wrote {written!r}, which its own recogniser rejects",
                    )
                    self.assertEqual(report_service.default_conclusion_span(written), (0, len(written)))

    def test_an_emptied_conclusion_paragraph_is_not_refilled(self) -> None:
        """The app used to claim the first text-less paragraph, which wrote boilerplate above a
        conclusion the tester had just written. A paragraph they emptied is theirs to leave empty."""
        finding = Vulnerability(uid="v_conc", title="Emptied", status="open_previously_discovered")
        provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = report_service.status_conclusion_runs("Emptied", "Open")
        self.assertTrue(report_service.is_default_status_conclusion(conclusion.fragments[0]))

        conclusion.fragments[0].runs = [Run(text="The finding was confirmed exploitable on retest.")]
        conclusion.fragments.insert(0, ParagraphFragment(frag_id="f_quoted", type="paragraph", runs=[]))
        provision(finding)

        self.assertEqual(conclusion.fragments[0].runs, [], "the emptied paragraph was refilled with boilerplate")
        self.assertEqual(
            "".join(run.text for run in conclusion.fragments[1].runs),
            "The finding was confirmed exploitable on retest.",
            "the tester's conclusion was disturbed",
        )

    def test_a_conclusion_section_is_created_empty_rather_than_written_for_you(self) -> None:
        """A DOCX import arrives with an empty in_conclusion and a status that prints it, so the
        section has to exist -- but the sentence is offered on the Content page, never written here."""
        finding = Vulnerability(uid="v_imported", title="Imported", status="open_previously_discovered")
        finding.contents = [Content(type="in_conclusion", fragments=[])]
        provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        self.assertEqual([fragment.type for fragment in conclusion.fragments], ["paragraph"])
        self.assertEqual(conclusion.fragments[0].runs, [], "the app wrote the sentence instead of offering it")

    def test_the_default_conclusion_blocks_generation_until_it_is_replaced(self) -> None:
        report = main.workspace.load(self.new_report())
        finding = Vulnerability(uid="v_owes", title="Owes a conclusion", status="open_previously_discovered")
        report.vulnerabilities = [finding]
        provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = report_service.status_conclusion_runs("Owes a conclusion", "Open")

        self.assertIn(
            "Owes a conclusion: in_conclusion still holds the default sentence",
            generation_issues(report),
            "the app's own sentence counts as a finished conclusion",
        )

        conclusion.fragments[0].runs = [Run(text="The finding is still reachable from the internet.")]
        self.assertNotIn(
            "Owes a conclusion: in_conclusion still holds the default sentence",
            generation_issues(report),
            "a written conclusion still reports as unwritten",
        )

        conclusion.fragments = []
        self.assertIn(
            "Owes a conclusion: in_conclusion needs at least one fragment",
            generation_issues(report),
            "deleting the paragraph would discharge the requirement and print N/A",
        )

    def test_cvss_blocks_generation_only_on_asia_reports(self) -> None:
        """A JH report never shows the pair, so requiring it would block every tester on a field
        their page does not draw."""
        report = main.workspace.load(self.new_report())
        finding = Vulnerability(uid="v_cvss", title="Needs a score", status="open_new")
        report.vulnerabilities = [finding]
        provision(finding)
        expected = ["Needs a score: CVSS Score is required", "Needs a score: CVSS Vector is required"]

        report.engagement.segment = "JH"
        self.assertEqual([issue for issue in generation_issues(report) if "CVSS" in issue], [])

        report.engagement.segment = "Asia"
        self.assertEqual([issue for issue in generation_issues(report) if "CVSS" in issue], expected)

        # Whitespace is not a score, and autosave stores whatever the tester has typed so far.
        finding.cvss_score = "  "
        finding.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        self.assertEqual([issue for issue in generation_issues(report) if "CVSS" in issue], expected[:1])

        finding.cvss_score = "9.8"
        self.assertEqual([issue for issue in generation_issues(report) if "CVSS" in issue], [])

        # Never required, whatever the segment or the status.
        self.assertEqual([issue for issue in generation_issues(report) if "Severity Review" in issue], [])

    def test_an_open_new_finding_never_owes_a_conclusion(self) -> None:
        """open_new does not print the section, and a carried one is kept for safekeeping, not completing."""
        report = main.workspace.load(self.new_report())
        finding = Vulnerability(uid="v_new", title="Brand new", status="open_previously_discovered")
        report.vulnerabilities = [finding]
        provision(finding)
        finding.status = "open_new"
        provision(finding)
        self.assertEqual(
            [issue for issue in generation_issues(report) if "in_conclusion" in issue],
            [],
            "an unprinted conclusion was reported as incomplete",
        )

    def test_a_quoted_step_in_front_of_the_sentence_keeps_the_sentence_live(self) -> None:
        """The step shares the sentence's paragraph, so the sentence is a tail rather than the whole
        text. If only a whole-paragraph match counted, accepting the offer would freeze the sentence
        at the title and status it was stored with, and silently discharge the replace-it rule."""
        finding = Vulnerability(uid="v_quoted", title="Before rename", status="open_previously_discovered")
        provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        paragraph = conclusion.fragments[0]
        paragraph.runs = [Run(text="Observe the balance of another user. ", italic=True), *report_service.status_conclusion_runs("Before rename", "Open")]

        finding.title = "After rename"
        finding.status = "resolved"
        provision(finding)

        self.assertEqual(
            "".join(run.text for run in paragraph.runs),
            'Observe the balance of another user. The finding "After rename" is Resolved.',
            "the sentence stopped tracking the finding once a step sat in front of it",
        )
        self.assertTrue(paragraph.runs[0].italic, "the quoted step lost the tester's formatting")
        self.assertFalse(
            report_service.is_default_status_conclusion(paragraph),
            "a paragraph carrying a quoted step is not purely the app's own sentence",
        )

    def test_text_either_side_of_the_sentence_discharges_the_default(self) -> None:
        """Only a bare sentence is boilerplate; a quoted step or trailing prose is the tester's own words."""
        report = main.workspace.load(self.new_report())
        finding = Vulnerability(uid="v_owes_still", title="Quoted", status="open_previously_discovered")
        report.vulnerabilities = [finding]
        provision(finding)
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        issue = "Quoted: in_conclusion still holds the default sentence"

        conclusion.fragments[0].runs = report_service.status_conclusion_runs("Quoted", "Open")
        self.assertIn(issue, generation_issues(report), "the app's own sentence counts as a finished conclusion")

        conclusion.fragments[0].runs = [Run(text="Observe the balance. "), *report_service.status_conclusion_runs("Quoted", "Open")]
        self.assertNotIn(issue, generation_issues(report), "a quoted step in front was treated as boilerplate")

        conclusion.fragments[0].runs = [*report_service.status_conclusion_runs("Quoted", "Open"), Run(text=" The account was fully exposed.")]
        self.assertNotIn(issue, generation_issues(report), "prose after the sentence was treated as boilerplate")

    def test_a_list_fragment_without_the_continue_key_loads_and_gains_the_default(self) -> None:
        """Every list fragment on disk predates this field, so the model default is the whole
        migration. A load_path repair would rewrite the file to write a value nothing was missing."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{
            "uid": "v_lists", "title": "Lists", "status": "open_new",
            "likelihood": "low", "impact": "low", "severity": "low",
            "contents": [{"type": "description", "fragments": [
                {"frag_id": "f_old", "type": "numbered_list", "items": [{"runs": [{"text": "Step"}]}]},
                {"frag_id": "f_set", "type": "numbered_list", "continue_numbering": True, "items": [{"runs": [{"text": "Next"}]}]},
            ]}],
        }]
        stored = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(stored.status_code, 200)

        fragments = next(
            content for content in stored.json()["report"]["vulnerabilities"][0]["contents"]
            if content["type"] == "description"
        )["fragments"]
        by_id = {fragment["frag_id"]: fragment for fragment in fragments}
        self.assertIs(by_id["f_old"]["continue_numbering"], False, "a fragment without the key did not gain the default")
        self.assertIs(by_id["f_set"]["continue_numbering"], True, "an explicit value did not survive the round trip")

    def test_the_conclusion_offer_memory_round_trips_and_refuses_null(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{
            "uid": "v_offer", "title": "Offer memory", "status": "open_previously_discovered",
            "likelihood": "low", "impact": "low", "severity": "low",
            "conclusion_offer_resolved": ["Observe the balance of another user."],
        }]
        stored = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(
            stored.json()["report"]["vulnerabilities"][0]["conclusion_offer_resolved"],
            ["Observe the balance of another user."],
            "the server did not echo the offer memory back",
        )

        report["vulnerabilities"][0]["conclusion_offer_resolved"] = None
        report["saved_at"] = stored.json()["report"]["saved_at"]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 422, "null must not validate")

    def test_the_content_offer_fingerprint_round_trips_and_refuses_null(self) -> None:
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{
            "uid": "v_fingerprint", "title": "Fingerprinted", "status": "open_new",
            "likelihood": "low", "impact": "low", "severity": "low",
            "content_offer_dismissed": {"description": "412-1a2b3c4d"},
        }]
        stored = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(
            stored.json()["report"]["vulnerabilities"][0]["content_offer_dismissed"],
            {"description": "412-1a2b3c4d"},
            "the server did not echo the dismissal fingerprint back",
        )

        report["vulnerabilities"][0]["content_offer_dismissed"] = None
        report["saved_at"] = stored.json()["report"]["saved_at"]
        self.assertEqual(self.client.put(f"/reports/{report_id}", json=report).status_code, 422, "null must not validate")

    def test_a_status_change_leaves_the_content_offer_memory_untouched(self) -> None:
        """The offer records the tester's answer. provision runs on both sides on every save, so if
        it ever cleared these the browser and the server would take turns wiping each other's copy."""
        report_id = self.new_report()
        report = main.workspace.load(report_id).model_dump(mode="json", by_alias=True)
        report["vulnerabilities"] = [{
            "uid": "v_memory", "title": "Memory", "status": "resolved",
            "likelihood": "low", "impact": "low", "severity": "low",
            "content_offer_resolved": {"description": "VDB-047"},
            "content_offer_dismissed": {"description": "412-1a2b3c4d"},
        }]
        resolved = self.client.put(f"/reports/{report_id}", json=report)
        self.assertEqual(resolved.status_code, 200)

        reopened_body = resolved.json()["report"]
        reopened_body["vulnerabilities"][0]["status"] = "open_previously_discovered"
        reopened = self.client.put(f"/reports/{report_id}", json=reopened_body)
        self.assertEqual(reopened.status_code, 200)

        finding = reopened.json()["report"]["vulnerabilities"][0]
        self.assertEqual(finding["content_offer_resolved"], {"description": "VDB-047"})
        self.assertEqual(finding["content_offer_dismissed"], {"description": "412-1a2b3c4d"})

    def test_direct_report_url_redirects_or_shows_navigable_not_found(self) -> None:
        report_id = self.new_report()
        opened = self.client.get(f"/reports/{report_id}", follow_redirects=False)
        self.assertEqual(opened.status_code, 303)
        self.assertEqual(opened.headers["location"], f"/reports/{report_id}/setup")
        missing = self.client.get("/reports/anystring", headers={"accept": "text/html"})
        self.assertEqual(missing.status_code, 404)
        self.assertIn('href="/"', missing.text)


class TwinRuleTests(unittest.TestCase):
    """A rule living in two languages is only as findable as the pointers between its halves.

    `docs/DATA_MAP.md` section 12 lists roughly thirty such pairs and only one of them has a
    behavioural drift guard. These tests do not check that the halves agree -- that needs a browser
    -- but they do keep the pointers honest, so a rename cannot quietly orphan one side."""

    MODULES = {"report_service": report_service, "models": models, "docx_report": docx_report}
    # `models.py` reads as module.symbol to the regex below but names a file, not a rule.
    FILE_SUFFIXES = {"py", "js", "md"}

    def named_symbols(self, text: str) -> list[tuple[str, str]]:
        return [
            (module_name, symbol)
            for module_name, symbol in re.findall(r"\b(report_service|models|docx_report)\.(\w+)", text)
            if symbol not in self.FILE_SUFFIXES
        ]

    def twin_comments(self) -> list[str]:
        source = (Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        return [line.strip() for line in source.splitlines() if "Twin of" in line]

    def test_every_twin_comment_points_at_a_symbol_that_still_exists(self) -> None:
        comments = self.twin_comments()
        # A floor, so deleting the comments cannot turn this test green by having nothing to check.
        self.assertGreaterEqual(len(comments), 15, "the twin markers in app.js have gone missing")
        checked = 0
        for comment in comments:
            for module_name, symbol in self.named_symbols(comment):
                checked += 1
                self.assertTrue(
                    hasattr(self.MODULES[module_name], symbol),
                    f"app.js claims a twin of {module_name}.{symbol}, which no longer exists: {comment}",
                )
        self.assertGreaterEqual(checked, 12, "no twin markers named a Python symbol, so nothing was verified")

    def test_the_data_map_twin_table_names_symbols_that_still_exist(self) -> None:
        """Section 12 is hand-maintained prose. Renaming a rule and forgetting the table is exactly
        how it came to claim `validateCurrentPage` was assigned in only one place."""
        data_map = (Path(__file__).resolve().parent.parent / "docs" / "DATA_MAP.md").read_text(encoding="utf-8")
        section = data_map.split("## 12. Rules that exist twice", 1)[1].split("## 13.", 1)[0]
        # Only the Python column is checkable from here; the JavaScript half has no importable names.
        rows = [line for line in section.splitlines() if line.startswith("| `") or line.startswith("| ")]
        self.assertGreaterEqual(len(rows), 20, "the twin table in DATA_MAP.md has shrunk unexpectedly")
        missing = []
        for row in rows:
            for module_name, symbol in self.named_symbols(row):
                if not hasattr(self.MODULES[module_name], symbol):
                    missing.append(f"{module_name}.{symbol}")
        self.assertEqual(missing, [], f"DATA_MAP section 12 names Python symbols that no longer exist: {missing}")


if __name__ == "__main__":
    unittest.main()