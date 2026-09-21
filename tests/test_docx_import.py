"""Reading a generated report back in.

Every test here renders with ``render_report_docx`` directly. The generate *routes* call Word
through ``update_docx_bytes_with_word`` and return 422 on any machine without it, so going through
them would test the environment rather than the document.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import get_args
from unittest.mock import patch

from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.docx_import import NETWORK_IMPORT_WARNING, ReportImportError, ReportImportLimitError, _ticket_lines, classify_paragraph, numbering_formats, parse_report_docx
from app.docx_report import generation_issues, main_template_path, render_report_docx
from app.report_service import RESOLVED_REMEDIATION, finding_input_issues
from app.workspace import Workspace
from app.models import (
    CodeFragment,
    Content,
    Engagement,
    EvidenceItem,
    ImageFragment,
    InstanceTitleFragment,
    ListFragment,
    ListItem,
    NoteFragment,
    ParagraphFragment,
    Report,
    Run,
    Scope,
    ScopeTarget,
    Segment,
    TableFragment,
    TestAccount,
    TestWindow,
    Vulnerability,
)

TEMPLATE = Path(__file__).resolve().parent.parent / "resources" / "MAIN.docx"


class FragmentRecognitionTests(unittest.TestCase):
    """The importer recognises a fragment by the component that produced it, so these pin the
    signals that survive generation. A template edit that erases one fails here rather than
    silently mislabelling every fragment in every future import."""

    @staticmethod
    def _report(folder: Path) -> Report:
        (folder / "evidence").mkdir()
        buffer = BytesIO()
        Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
        (folder / "evidence" / "ev_shot.png").write_bytes(buffer.getvalue())
        now = datetime.now().astimezone()
        report = Report(
            report_id="r_import", app_id="CI-IMPORT", saved_at=now,
            engagement=Engagement(
                app_name="Northstar Banking", ci_number="CI-IMPORT", segment="JH",
                report_type="annual_pentest", report_date=date(2026, 9, 9), tester="QA Tester",
                tested_environments=["production"], tested_channels=["web"],
                test_windows={"production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))},
            ),
            scope_targets=[ScopeTarget(target_id="t_web", environment="production", channel="web", value="https://prod.example.test")],
            evidence={"ev_shot": EvidenceItem(file="evidence/ev_shot.png", original_name="shot.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)},
        )
        report.vulnerabilities = [Vulnerability(
            uid="v_all", display_id="001", title="Authorization bypass",
            likelihood="high", impact="high", severity="high", status="open_new",
            scope=Scope(mode="custom", target_ids=["t_web"]),
            contents=[
                Content(type="description", fragments=[
                    ParagraphFragment(frag_id="f_para", type="paragraph", runs=[Run(text="A justified paragraph.")]),
                    NoteFragment(frag_id="f_note", type="note", runs=[Run(text="Validate independently.")]),
                    ListFragment(frag_id="f_bullet", type="bulleted_list", items=[ListItem(runs=[Run(text="A bullet.")])]),
                ]),
                Content(type="recommended_remediation", fragments=[
                    ParagraphFragment(frag_id="f_rem", type="paragraph", runs=[Run(text="Apply controls.")]),
                ]),
                Content(type="proof_of_concept", fragments=[
                    ListFragment(frag_id="f_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request.")])]),
                    InstanceTitleFragment(frag_id="f_title", type="instance_title", text="First instance"),
                    CodeFragment(frag_id="f_code", type="code_block", caption="Request", text="GET /accounts/123"),
                    TableFragment(frag_id="f_table", type="table", caption="Results",
                                  header=[ListItem(runs=[Run(text="Header")])],
                                  rows=[[ListItem(runs=[Run(text="Cell")])]]),
                    ImageFragment(frag_id="f_image", type="image", environment="production",
                                  evidence_id="ev_shot", caption="Production response"),
                ]),
            ],
        )]
        return report

    def _rendered(self, folder: Path):
        return Document(BytesIO(render_report_docx(self._report(folder), TEMPLATE, folder)))

    def _retest_report(self, folder: Path, tickets: str = "") -> Report:
        """Generation-clean and previously discovered, so it renders ``retest_finding.docx``.

        The shared fixture is ``open_new``, which renders ``new_finding.docx`` and carries no ticket
        paragraph at all, so nothing already here can reach this."""
        report = self._report(folder)
        finding = report.vulnerabilities[0]
        finding.status = "open_previously_discovered"
        finding.severity_review_tickets = tickets
        finding.contents.append(Content(type="previous_proof_of_concept", fragments=[
            ListFragment(frag_id="f_prev", type="numbered_list", items=[ListItem(runs=[Run(text="Last year's step.")])]),
        ]))
        finding.contents.append(Content(type="in_conclusion", fragments=[
            ParagraphFragment(frag_id="f_conc", type="paragraph", runs=[Run(text="Still reachable on retest.")]),
        ]))
        return report

    @staticmethod
    def _normalized_retest_projection(payload: dict, evidence: dict[str, bytes], summary: dict) -> dict:
        report = Report.model_validate(payload)
        target_indexes = {target.target_id: index for index, target in enumerate(report.scope_targets)}

        def fragment_value(fragment) -> dict:
            value = fragment.model_dump(mode="json", exclude={"frag_id", "evidence_id"}, exclude_none=True)
            return value

        return {
            "engagement": report.engagement.model_dump(mode="json"),
            "targets": [
                target.model_dump(mode="json", exclude={"target_id"})
                for target in report.scope_targets
            ],
            "findings": [{
                "display_id": finding.display_id,
                "title": finding.title,
                "likelihood": finding.likelihood,
                "impact": finding.impact,
                "severity": finding.severity,
                "status": finding.status,
                "scope_targets": [target_indexes[target_id] for target_id in finding.scope.target_ids],
                "tickets": finding.severity_review_tickets,
                "cvss_score": finding.cvss_score,
                "cvss_vector": finding.cvss_vector,
                "contents": [
                    {"type": content.type, "fragments": [fragment_value(fragment) for fragment in content.fragments]}
                    for content in finding.contents
                ],
            } for finding in report.vulnerabilities],
            "evidence": sorted((hashlib.sha256(data).hexdigest(), len(data)) for data in evidence.values()),
            "summary": summary,
        }

    def test_both_import_modes_default_network_and_say_so(self) -> None:
        """Retest is the default mode, so warning only on the editable path would leave the
        commoner one silent about a value it quietly defaulted."""
        for mode in ("retest", "editable"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                data = render_report_docx(self._report(folder), TEMPLATE, folder)

                payload, _evidence, summary = parse_report_docx(data, mode=mode)

                self.assertEqual(Report.model_validate(payload).engagement.network, "Internal")
                self.assertIn(NETWORK_IMPORT_WARNING, summary["warnings"])
                self.assertNotIn("network", payload["engagement"])
                self.assertNotIn("network access", summary.get("restored_engagement", []))

    def test_severity_review_tickets_survive_a_round_trip(self) -> None:
        """Rendered with the prefix, read back without it. Asserting either half alone would pass
        while the two disagreed, which is the only failure worth catching here."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._retest_report(folder, tickets="1234\n5678\n90123")
            self.assertEqual(generation_issues(report), [])
            document = render_report_docx(report, TEMPLATE, folder)
            self.assertIn("GRIMPEN-1234", "\n".join(item.text for item in Document(BytesIO(document)).paragraphs))

            payload, _evidence, _summary = parse_report_docx(document)
            self.assertEqual(payload["vulnerabilities"][0]["severity_review_tickets"], "1234\n5678\n90123")

    def test_retest_default_preserves_the_retest_projection_except_named_neutral_fixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)

            payload, evidence, summary = parse_report_docx(data)
            projection = self._normalized_retest_projection(payload, evidence, summary)

            self.assertEqual(projection["engagement"], {
                "app_name": "Northstar Banking", "app_owner": "", "ci_number": "", "bsn_number": "",
                "segment": "JH", "report_type": None, "report_date": None, "tester": "",
                "network": "Internal",
                "tested_environments": ["production"], "tested_channels": ["web"],
                "non_production_label": "NON-PROD", "start_date": None, "end_date": None,
                "test_windows": {}, "test_accounts": [{"user_role": "N/A", "username": "N/A"}],
                "limitations": "N/A", "classification": "Confidential", "template_set": "default-v1",
            })
            self.assertEqual(projection["targets"], [{
                "environment": "production", "channel": "web",
                "value": "https://prod.example.test", "description": "", "order": 0,
            }])
            finding = projection["findings"][0]
            self.assertEqual(
                {key: finding[key] for key in ("display_id", "title", "likelihood", "impact", "severity", "status", "scope_targets")},
                {"display_id": "001", "title": "Authorization bypass", "likelihood": "high", "impact": "high",
                 "severity": "high", "status": "open_previously_discovered", "scope_targets": [0]},
            )
            self.assertEqual([content["type"] for content in finding["contents"]], [
                "description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion",
            ])
            self.assertEqual(
                [fragment["type"] for fragment in finding["contents"][2]["fragments"]],
                ["numbered_list", "instance_title", "code_block", "table", "image"],
            )
            self.assertEqual([fragment["type"] for fragment in finding["contents"][3]["fragments"]], ["numbered_list", "image"])
            self.assertEqual(len(projection["evidence"]), 1)
            self.assertEqual(projection["summary"], {
                "retained": 1, "dropped_resolved": [], "statuses_rewritten": ["Authorization bypass"],
                "warnings": [NETWORK_IMPORT_WARNING],
            })

    def test_retest_mode_and_omitted_mode_are_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)

            implicit = parse_report_docx(data)
            explicit = parse_report_docx(data, mode="retest")

            self.assertEqual(
                self._normalized_retest_projection(*implicit),
                self._normalized_retest_projection(*explicit),
            )

    def test_duplicate_title_asia_rows_pair_by_occurrence(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.segment = "Asia"
            first = report.vulnerabilities[0]
            first.cvss_score = "3.1"
            first.cvss_vector = "CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N"
            second = copy.deepcopy(first)
            second.uid = "v_duplicate"
            second.display_id = "002"
            second.cvss_score = "8.1"
            second.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N"
            for content in second.contents:
                for fragment in content.fragments:
                    fragment.frag_id += "_duplicate"
            report.vulnerabilities = [first, second]

            payload, _evidence, _summary = parse_report_docx(
                render_report_docx(report, main_template_path(report, resources), folder),
            )

            self.assertEqual(
                [(finding["display_id"], finding["cvss_score"], finding["cvss_vector"]) for finding in payload["vulnerabilities"]],
                [("001", first.cvss_score, first.cvss_vector), ("002", second.cvss_score, second.cvss_vector)],
            )

    def test_an_empty_ticket_value_prints_n_a_and_imports_as_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            document = render_report_docx(self._retest_report(folder), TEMPLATE, folder)
            payload, _evidence, _summary = parse_report_docx(document)
            self.assertEqual(payload["vulnerabilities"][0]["severity_review_tickets"], "")
            # The label is the template's, not a fragment the tester wrote.
            conclusion = next(content for content in payload["vulnerabilities"][0]["contents"] if content["type"] == "in_conclusion")
            self.assertEqual(conclusion["fragments"], [])

    def test_ticket_formats_from_older_reports_normalise_to_bare_digits(self) -> None:
        """Liberal in what it accepts, strict in what survives. The last case is the point: mining
        digits out of surrounding text would invent 2024 as a ticket, and a fabricated reference in
        a delivered report reads exactly as plausibly as a real one."""
        for printed, expected in (
            ("GRIMPEN-1234\nGRIMPEN-5678", "1234\n5678"),
            ("3454, 3453, 2323", "3454\n3453\n2323"),
            ("GRIMPEN-1234; 5678", "1234\n5678"),
            ("3523", "3523"),
            ("OLDKEY-3523", "3523"),
            ("  3523  ", "3523"),
            ("GRIMPEN-3523 (closed 2024)", ""),
            ("N/A", ""),
            ("", ""),
        ):
            with self.subTest(printed=printed):
                self.assertEqual(_ticket_lines(printed), expected)

    def test_cvss_values_are_read_back_from_the_row_that_names_the_finding(self) -> None:
        """The table carries a row per rendered finding while the importer drops every Resolved one,
        so a Resolved finding first in the document is what proves the match is not positional."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._retest_report(folder)
            report.engagement.segment = "Asia"
            retained = report.vulnerabilities[0]
            retained.severity = retained.likelihood = retained.impact = "low"
            retained.cvss_score, retained.cvss_vector = "3.1", "CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N"
            resolved = copy.deepcopy(retained)
            resolved.uid, resolved.display_id, resolved.title = "v_done", "002", "Fixed last year"
            resolved.status = "resolved"
            resolved.severity = resolved.likelihood = resolved.impact = "critical"
            resolved.cvss_score, resolved.cvss_vector = "9.8", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
            # Critical sorts above low, so the dropped finding owns the first row of the table.
            report.vulnerabilities = [retained, resolved]
            resources = Path(__file__).resolve().parent.parent / "resources"
            document = render_report_docx(report, main_template_path(report, resources), folder, allow_incomplete=True)

            payload, _evidence, summary = parse_report_docx(document)
            imported = payload["vulnerabilities"]
            self.assertEqual([finding["title"] for finding in imported], ["Authorization bypass"])
            self.assertEqual(imported[0]["cvss_score"], "3.1", "the dropped finding's row was taken by position")
            self.assertEqual(imported[0]["cvss_vector"], "CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N")
            self.assertIn("Fixed last year", summary["dropped_resolved"])

    def test_cvss_round_trip_preserves_every_value_save_validation_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._retest_report(folder)
            report.engagement.segment = "Asia"
            finding = report.vulnerabilities[0]
            finding.cvss_score = "٩.٨"
            finding.cvss_vector = "CVSS:3.1/AV:Ν"
            self.assertEqual(finding_input_issues(report), [])

            resources = Path(__file__).resolve().parent.parent / "resources"
            document = render_report_docx(report, main_template_path(report, resources), folder)
            payload, _evidence, _summary = parse_report_docx(document)
            imported = payload["vulnerabilities"][0]
            self.assertEqual(
                (imported["cvss_score"], imported["cvss_vector"]),
                (finding.cvss_score, finding.cvss_vector),
            )

    def test_a_template_without_the_section_table_imports_with_the_fields_empty(self) -> None:
        """Three of the four templates have no such table, so its absence is normal and never raises."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            document = render_report_docx(self._retest_report(folder), TEMPLATE, folder)
            payload, _evidence, _summary = parse_report_docx(document)
            finding = payload["vulnerabilities"][0]
            self.assertEqual((finding["cvss_score"], finding["cvss_vector"]), ("", ""))

    def _non_production_report(self, folder: Path, label: str) -> Report:
        """The production fixture never prints a non-production heading, so it cannot catch a
        mislabelled round trip."""
        report = self._report(folder)
        report.engagement.non_production_label = label
        report.engagement.tested_environments = ["production", "non_production"]
        report.engagement.test_windows["non_production"] = TestWindow(start_date=date(2026, 8, 3), end_date=date(2026, 8, 4))
        report.scope_targets.append(
            ScopeTarget(target_id="t_web_np", environment="non_production", channel="web", value="https://uat.example.test")
        )
        finding = report.vulnerabilities[0]
        finding.scope = Scope(mode="custom", target_ids=["t_web", "t_web_np"])
        proof = next(content for content in finding.contents if content.type == "proof_of_concept")
        proof.fragments.append(ImageFragment(
            frag_id="f_image_np", type="image", environment="non_production",
            evidence_id="ev_shot", caption="Non-production response",
        ))
        return report

    def test_a_non_production_evidence_image_keeps_its_environment_through_a_round_trip(self) -> None:
        """The heading above the screenshots is the label's only appearance in the document: the
        scope rows read "Non-Production Environment" from the template, not the tester's label. Miss
        it and the images below inherit the previous environment, so non-prod evidence files as prod."""
        for label in ("NON-PROD", "STAGE", "TEST/MO"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                report = self._non_production_report(folder, label)
                document = render_report_docx(report, TEMPLATE, folder)
                payload, _evidence, _summary = parse_report_docx(document)

                self.assertEqual(payload["engagement"]["non_production_label"], label, "the label was not recovered")
                fragments = [
                    fragment for finding in payload["vulnerabilities"]
                    for content in finding["contents"] if content["type"] == "previous_proof_of_concept"
                    for fragment in content["fragments"]
                ]
                environments = [fragment["environment"] for fragment in fragments if fragment["type"] == "image"]
                self.assertIn("non_production", environments, "non-production evidence came back filed elsewhere")
                stray = [fragment for fragment in fragments if fragment["type"] == "instance_title" and fragment["text"].rstrip(":").upper() == label]
                self.assertEqual(stray, [], "the environment heading survived as a visible fragment")

    def test_every_fragment_type_is_recognisable_in_a_generated_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            document = self._rendered(Path(temporary_directory))
            formats = numbering_formats(document)
            found = {}
            for paragraph in document.paragraphs:
                text = paragraph.text.strip()
                kind = classify_paragraph(paragraph, formats)
                if paragraph._p.findall(".//" + qn("a:blip")):
                    found["image"] = kind
                for marker, expected in (
                    ("A justified paragraph.", "paragraph"),
                    ("Validate independently.", "note"),
                    ("A bullet.", "bulleted_list"),
                    ("Send the request.", "numbered_list"),
                    ("Instance 1: First instance", "instance_title"),
                    ("GET /accounts/123", "code_block"),
                    ("Request", "caption"),
                ):
                    if text == marker or (marker == "Validate independently." and text.endswith(marker)):
                        found[expected] = kind
            for expected, actual in found.items():
                self.assertEqual(actual, expected, f"{expected} was read as {actual}")
            self.assertEqual(
                set(found),
                {"paragraph", "note", "bulleted_list", "numbered_list", "instance_title", "code_block", "caption", "image"},
                "a fragment type never appeared in the rendered document",
            )

    def test_a_table_is_a_body_element_not_a_paragraph(self) -> None:
        """``table_fragment.docx`` adds no paragraph style of its own, so a table is only ever found
        structurally."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            document = self._rendered(Path(temporary_directory))
            cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
            self.assertIn("Cell", cells)

    def test_list_format_is_resolved_rather_than_read_from_the_numbering_id(self) -> None:
        """Merging the components renumbers the lists, so trusting ``numId`` swaps bulleted and
        numbered lists. Only the resolved format survives."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            document = self._rendered(Path(temporary_directory))
            formats = numbering_formats(document)
            by_text = {}
            for paragraph in document.paragraphs:
                properties = paragraph._p.find(qn("w:pPr"))
                numbering = properties.find(qn("w:numPr")) if properties is not None else None
                if numbering is None:
                    continue
                number_id = numbering.find(qn("w:numId")).get(qn("w:val"))
                by_text[paragraph.text.strip()] = (number_id, formats.get(number_id))
            self.assertEqual(by_text["A bullet."][1], "bullet")
            self.assertEqual(by_text["Send the request."][1], "decimal")
            self.assertNotEqual(by_text["A bullet."][0], by_text["Send the request."][0])


    def test_a_generated_report_reads_back_into_a_valid_draft(self) -> None:
        """The proof of concept the document carries is the latest one, so it becomes the draft's
        *previous* proof of concept and the retest starts with an empty one."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)
            payload, evidence, summary = parse_report_docx(data)

            self.assertEqual(payload["engagement"]["app_name"], "Northstar Banking")
            self.assertEqual(payload["engagement"]["segment"], "JH")
            self.assertEqual(payload["engagement"]["report_type"], None, "the report type is the tester's to choose")
            self.assertEqual(payload["engagement"]["test_windows"], {}, "test dates describe the previous engagement")
            self.assertEqual([target["value"] for target in payload["scope_targets"]], ["https://prod.example.test"])

            finding = payload["vulnerabilities"][0]
            self.assertEqual(finding["title"], "Authorization bypass")
            self.assertEqual(finding["display_id"], "001")
            self.assertEqual(finding["severity"], "high")
            self.assertEqual(finding["status"], "open_previously_discovered")
            self.assertEqual(summary["statuses_rewritten"], ["Authorization bypass"])

            sections = {content["type"]: [fragment["type"] for fragment in content["fragments"]] for content in finding["contents"]}
            self.assertEqual(sections["description"], ["paragraph", "note", "bulleted_list"])
            self.assertEqual(
                sections["previous_proof_of_concept"],
                ["numbered_list", "instance_title", "code_block", "table", "image"],
                "the document's proof of concept becomes the draft's previous one, in order",
            )
            self.assertEqual(
                sections["proof_of_concept"],
                ["numbered_list", "image"],
                "the retest starts empty, with somewhere to write and one slot per affected environment",
            )

            self.assertEqual(len(evidence), 1)
            record = payload["evidence"][next(iter(evidence))]
            self.assertEqual(record["sha256"], hashlib.sha256(next(iter(evidence.values()))).hexdigest())
            Report.model_validate(payload)

    def test_editable_mode_keeps_the_source_status_and_proof_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)

            payload, evidence, _summary = parse_report_docx(data, mode="editable")

            finding = payload["vulnerabilities"][0]
            self.assertEqual(finding["status"], "open_new")
            sections = {content["type"]: content["fragments"] for content in finding["contents"]}
            self.assertNotIn("previous_proof_of_concept", sections)
            self.assertEqual(
                [fragment["type"] for fragment in sections["proof_of_concept"]],
                ["numbered_list", "instance_title", "code_block", "table", "image"],
            )
            self.assertEqual(len(evidence), 1)
            Report.model_validate(payload)

    def test_editable_mode_restores_every_printed_engagement_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.app_owner = "Application Owner"
            report.engagement.limitations = "No SMS access"
            report.engagement.test_windows["production"].test_time = "22:00 EST"
            report.engagement.test_accounts = [
                TestAccount(user_role="Administrator", username="alice"),
                TestAccount(user_role="Viewer", username="bob"),
            ]

            payload, _evidence, _summary = parse_report_docx(
                render_report_docx(report, TEMPLATE, folder), mode="editable",
            )

            engagement = payload["engagement"]
            self.assertEqual(engagement["app_name"], "Northstar Banking")
            self.assertEqual(engagement["app_owner"], "Application Owner")
            self.assertEqual(engagement["segment"], "JH")
            self.assertEqual(engagement["report_type"], "annual_pentest")
            self.assertEqual(engagement["report_date"], "2026-09-09")
            self.assertEqual(engagement["tester"], "QA Tester")
            self.assertEqual(engagement["test_windows"]["production"], {
                "start_date": "2026-08-01", "end_date": "2026-08-02", "test_time": "22:00 EST",
            })
            self.assertEqual(engagement["test_accounts"], [
                {"user_role": "Administrator", "username": "alice"},
                {"user_role": "Viewer", "username": "bob"},
            ])
            self.assertEqual(engagement["limitations"], "No SMS access")
            self.assertEqual((engagement.get("ci_number", ""), engagement.get("bsn_number", "")), ("", ""))
            Report.model_validate(payload)

    def test_editable_mode_preserves_visible_whitespace_in_user_fields(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.limitations = "No SMS access\nRead only after  17:00"
            report.engagement.tested_channels = ["api", "thick_client"]
            report.scope_targets = [
                ScopeTarget(target_id="t_api", environment="production", channel="api", value="POST  /v1/pay"),
                ScopeTarget(
                    target_id="t_component", environment="production", channel="thick_client",
                    value="Acme.exe", description="Desktop  client",
                ),
            ]
            report.vulnerabilities[0].scope.target_ids = ["t_api", "t_component"]

            payload, _evidence, _summary = parse_report_docx(
                render_report_docx(report, main_template_path(report, resources), folder),
                mode="editable",
            )

            self.assertEqual(payload["engagement"]["limitations"], report.engagement.limitations)
            targets = {target["channel"]: target for target in payload["scope_targets"]}
            self.assertEqual(targets["api"]["value"], "POST  /v1/pay")
            self.assertEqual(targets["thick_client"]["description"], "Desktop  client")

    def test_editable_mode_rejects_invalid_nonempty_finding_scalars(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        cases = ("display_id", "cvss_score", "severity_review_tickets")
        for field in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                report = self._retest_report(folder, tickets="1234")
                report.engagement.segment = "Asia"
                finding = report.vulnerabilities[0]
                finding.cvss_score = "8.1"
                finding.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N"
                document = Document(BytesIO(render_report_docx(report, main_template_path(report, resources), folder)))
                if field == "display_id":
                    summary = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Findings")
                    summary.rows[1].cells[4].text = "ABC"
                    detail = next(table for table in document.tables if any(row.cells[0].text.strip() == "Location" for row in table.rows))
                    next(row for row in detail.rows if row.cells[0].text.strip() == "ID").cells[1].text = "ABC"
                elif field == "cvss_score":
                    cvss = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Section")
                    cvss.rows[1].cells[3].text = "8.1?"
                else:
                    paragraph = next(paragraph for paragraph in document.paragraphs if "GRIMPEN-1234" in paragraph.text)
                    paragraph.text = "GRIMPEN-1234\nnot-a-ticket"
                output = BytesIO()
                document.save(output)

                with self.assertRaises(ReportImportError):
                    parse_report_docx(output.getvalue(), mode="editable")

    def test_editable_scope_recovers_all_four_template_variants(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        cases = (
            ("web", "JH", "https://prod.example.test", ""),
            ("api", "Asia", "/v1/accounts/{id}", ""),
            ("thick_client", "JH", "Acme.exe", "Desktop client"),
            ("mobile", "Asia", "Acme.ipa", "iOS client"),
        )
        for channel, segment, value, description in cases:
            with self.subTest(channel=channel, segment=segment), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                report = self._report(folder)
                report.engagement.segment = segment
                report.engagement.tested_channels = [channel]
                report.scope_targets = [ScopeTarget(
                    target_id="t_scope", environment="production", channel=channel,
                    value=value, description=description,
                )]
                report.vulnerabilities[0].scope.target_ids = ["t_scope"]
                if segment == "Asia":
                    report.vulnerabilities[0].cvss_score = "8.1"
                    report.vulnerabilities[0].cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N"

                data = render_report_docx(report, main_template_path(report, resources), folder)
                payload, _evidence, summary = parse_report_docx(data, mode="editable")

                self.assertEqual(payload["engagement"]["tested_channels"], [channel])
                self.assertEqual(payload["scope_targets"][0]["value"], value)
                self.assertEqual(payload["scope_targets"][0]["description"], description)
                self.assertFalse(any("Review the environment" in warning or "review the app type" in warning for warning in summary["warnings"]))
                self.assertTrue(any("rendered Word copies" in warning for warning in summary["warnings"]))
                Report.model_validate(payload)

    def test_non_production_component_environment_uses_finding_evidence_when_dates_are_missing(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.tested_environments = ["non_production"]
            report.engagement.tested_channels = ["thick_client"]
            report.engagement.test_windows = {}
            report.scope_targets = [ScopeTarget(
                target_id="t_component", environment="non_production", channel="thick_client",
                value="Acme.Staging.exe", description="UAT desktop client",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_component"]

            payload, _evidence, summary = parse_report_docx(
                render_report_docx(report, main_template_path(report, resources), folder, allow_incomplete=True),
                mode="editable",
            )

            self.assertEqual(payload["scope_targets"], [{
                **payload["scope_targets"][0],
                "environment": "non_production",
                "channel": "thick_client",
                "value": "Acme.Staging.exe",
                "description": "UAT desktop client",
                "order": 0,
            }])
            self.assertEqual(payload["vulnerabilities"][0]["scope"]["target_ids"], [payload["scope_targets"][0]["target_id"]])
            self.assertFalse(any("Review the environment" in warning for warning in summary["warnings"]))

    def test_component_environment_defaults_once_when_both_environments_are_observed(self) -> None:
        resources = Path(__file__).resolve().parent.parent / "resources"
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.tested_environments = ["production", "non_production"]
            report.engagement.tested_channels = ["thick_client"]
            report.engagement.test_windows["non_production"] = TestWindow(
                start_date=date(2026, 8, 3), end_date=date(2026, 8, 4),
            )
            report.scope_targets = [ScopeTarget(
                target_id="t_component", environment="non_production", channel="thick_client",
                value="Acme.exe", description="Desktop client",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_component"]

            payload, _evidence, summary = parse_report_docx(
                render_report_docx(report, main_template_path(report, resources), folder, allow_incomplete=True),
                mode="editable",
            )

            self.assertEqual(len(payload["scope_targets"]), 2)
            targets = {target["environment"]: target for target in payload["scope_targets"]}
            self.assertEqual(targets["production"]["description"], "Desktop client")
            self.assertEqual(targets["non_production"]["description"], "")
            self.assertEqual(payload["vulnerabilities"][0]["scope"]["target_ids"], [targets["non_production"]["target_id"]])
            self.assertTrue(any('component "Acme.exe"' in warning for warning in summary["warnings"]))
            self.assertTrue(any('"Acme.exe"; it was added' in warning for warning in summary["warnings"]))

    def test_editable_mode_keeps_all_statuses_and_printed_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            open_new = report.vulnerabilities[0]

            previously_discovered = copy.deepcopy(open_new)
            previously_discovered.uid = "v_previous"
            previously_discovered.display_id = "002"
            previously_discovered.title = "Previously discovered issue"
            previously_discovered.status = "open_previously_discovered"
            previously_discovered.contents.extend([
                Content(type="previous_proof_of_concept", fragments=[
                    ListFragment(frag_id="f_previous_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Prior evidence.")])]),
                ]),
                Content(type="in_conclusion", fragments=[
                    ParagraphFragment(frag_id="f_previous_conclusion", type="paragraph", runs=[Run(text="Still open.")]),
                ]),
            ])
            for content in previously_discovered.contents:
                for fragment in content.fragments:
                    fragment.frag_id += "_previous"

            resolved = copy.deepcopy(previously_discovered)
            resolved.uid = "v_resolved"
            resolved.display_id = "003"
            resolved.title = "Resolved issue"
            resolved.status = "resolved"
            for content in resolved.contents:
                for fragment in content.fragments:
                    fragment.frag_id += "_resolved"
            remediation = next(content for content in resolved.contents if content.type == "recommended_remediation")
            remediation.fragments = [ParagraphFragment(
                frag_id="f_resolved_remediation",
                type="paragraph",
                runs=[Run(text=RESOLVED_REMEDIATION)],
                generated="resolved_remediation",
            )]
            resolved_on_non_prod = copy.deepcopy(previously_discovered)
            resolved_on_non_prod.uid = "v_non_prod"
            resolved_on_non_prod.display_id = "004"
            resolved_on_non_prod.title = "Fixed in the lower region only"
            resolved_on_non_prod.status = "open_resolved_on_non_prod"
            for content in resolved_on_non_prod.contents:
                for fragment in content.fragments:
                    fragment.frag_id += "_non_prod"
            report.vulnerabilities = [open_new, previously_discovered, resolved, resolved_on_non_prod]

            data = render_report_docx(report, TEMPLATE, folder)
            payload, evidence, summary = parse_report_docx(data, mode="editable")

            findings = {finding["title"]: finding for finding in payload["vulnerabilities"]}
            self.assertEqual({title: finding["status"] for title, finding in findings.items()}, {
                "Authorization bypass": "open_new",
                "Previously discovered issue": "open_previously_discovered",
                "Resolved issue": "resolved",
                "Fixed in the lower region only": "open_resolved_on_non_prod",
            })
            self.assertEqual(
                [content["type"] for content in findings["Fixed in the lower region only"]["contents"]],
                ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
                "the fourth status prints what previously discovered prints",
            )
            self.assertEqual(
                [content["type"] for content in findings["Authorization bypass"]["contents"]],
                ["description", "recommended_remediation", "proof_of_concept"],
            )
            self.assertEqual(
                [content["type"] for content in findings["Previously discovered issue"]["contents"]],
                ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
            )
            resolved_remediation = next(
                content for content in findings["Resolved issue"]["contents"]
                if content["type"] == "recommended_remediation"
            )
            self.assertEqual(resolved_remediation["fragments"][0]["generated"], "resolved_remediation")
            referenced = {
                fragment["evidence_id"]
                for finding in findings.values()
                for content in finding["contents"]
                for fragment in content["fragments"]
                if fragment["type"] == "image" and fragment["evidence_id"]
            }
            self.assertEqual(referenced, set(payload["evidence"]))
            self.assertEqual(referenced, set(evidence))
            self.assertEqual(summary["retained"], 4)
            Report.model_validate(payload)

    def test_editable_mode_rejects_edited_resolved_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._retest_report(folder)
            report.vulnerabilities[0].status = "resolved"
            remediation = next(content for content in report.vulnerabilities[0].contents if content.type == "recommended_remediation")
            remediation.fragments = [ParagraphFragment(
                frag_id="f_resolved_remediation",
                type="paragraph",
                runs=[Run(text="Keep this manually edited advice.")],
            )]

            data = render_report_docx(report, TEMPLATE, folder, allow_incomplete=True)
            with self.assertRaisesRegex(ReportImportError, "edited remediation while Resolved"):
                parse_report_docx(data, mode="editable")

    def test_an_unmatched_api_location_becomes_a_visible_review_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.tested_channels = ["api"]
            report.scope_targets = [ScopeTarget(
                target_id="t_api", environment="production", channel="api", value="/v1/accounts/{id}",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_api"]
            document = Document(BytesIO(render_report_docx(report, TEMPLATE, folder)))
            detail = next(table for table in document.tables if any(row.cells[0].text.strip() == "Location" for row in table.rows))
            production = next(row for row in detail.rows if row.cells[1].text.startswith("Production Environment"))
            production.cells[1].paragraphs[1].text = "/v1/accounts/{account_id}"
            output = BytesIO()
            document.save(output)

            payload, _evidence, summary = parse_report_docx(output.getvalue(), mode="editable")

            finding = payload["vulnerabilities"][0]
            selected = next(target for target in payload["scope_targets"] if target["target_id"] in finding["scope"]["target_ids"])
            self.assertEqual((selected["channel"], selected["value"]), ("api", "/v1/accounts/{account_id}"))
            self.assertEqual(finding["scope"]["custom_locations"], {})
            self.assertTrue(any("review the app type" in warning for warning in summary["warnings"]))
            Report.model_validate(payload)

    def test_retest_summary_discloses_shared_scope_corrections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            report.engagement.tested_channels = ["api"]
            report.scope_targets = [ScopeTarget(
                target_id="t_api", environment="production", channel="api", value="/v1/accounts/{id}",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_api"]
            document = Document(BytesIO(render_report_docx(report, TEMPLATE, folder)))
            detail = next(table for table in document.tables if any(row.cells[0].text.strip() == "Location" for row in table.rows))
            production = next(row for row in detail.rows if row.cells[1].text.startswith("Production Environment"))
            production.cells[1].paragraphs[1].text = "/v1/accounts/{account_id}"
            output = BytesIO()
            document.save(output)

            _payload, _evidence, summary = parse_report_docx(output.getvalue())

            self.assertEqual(summary["retained"], 1)
            self.assertTrue(any("review the app type" in warning for warning in summary["warnings"]))

    def test_wrapped_scope_and_location_text_stays_one_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            value = "https://prod.example.test/" + "very-long-segment/" * 8
            report.scope_targets[0].value = value

            payload, _evidence, _summary = parse_report_docx(
                render_report_docx(report, TEMPLATE, folder), mode="editable",
            )

            self.assertEqual([target["value"] for target in payload["scope_targets"]], [value])
            self.assertEqual(payload["vulnerabilities"][0]["scope"]["target_ids"], [payload["scope_targets"][0]["target_id"]])

    def test_note_runs_and_numbered_list_boundaries_survive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            description = next(content for content in report.vulnerabilities[0].contents if content.type == "description")
            note = next(fragment for fragment in description.fragments if fragment.type == "note")
            note.runs = [Run(text="Validate ", bold=True), Run(text="independently.", italic=True)]
            proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
            image = next(fragment for fragment in proof.fragments if fragment.type == "image")
            proof.fragments = [
                ListFragment(frag_id="f_first", type="numbered_list", items=[
                    ListItem(runs=[Run(text="Step one.")]), ListItem(runs=[Run(text="Step two.")]),
                ]),
                image,
                ListFragment(frag_id="f_continued", type="numbered_list", continue_numbering=True, items=[
                    ListItem(runs=[Run(text="Step three.")]),
                ]),
                ListFragment(frag_id="f_restarted", type="numbered_list", items=[
                    ListItem(runs=[Run(text="New step one.")]),
                ]),
            ]

            payload, _evidence, _summary = parse_report_docx(
                render_report_docx(report, TEMPLATE, folder), mode="editable",
            )

            imported_description = payload["vulnerabilities"][0]["contents"][0]["fragments"]
            imported_note = next(fragment for fragment in imported_description if fragment["type"] == "note")
            self.assertEqual(imported_note["runs"], [
                {"text": "Validate ", "bold": True, "italic": True},
                {"text": "independently.", "italic": True},
            ])
            imported_proof = next(
                content for content in payload["vulnerabilities"][0]["contents"]
                if content["type"] == "proof_of_concept"
            )
            lists = [fragment for fragment in imported_proof["fragments"] if fragment["type"] == "numbered_list"]
            self.assertEqual([len(fragment["items"]) for fragment in lists], [2, 1, 1])
            self.assertEqual([fragment.get("continue_numbering", False) for fragment in lists], [False, True, False])

    def test_editable_image_preserves_embedded_png_bytes_and_display_width(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)
            document = Document(BytesIO(data))
            paragraph = next(paragraph for paragraph in document.paragraphs if paragraph._p.findall(".//" + qn("a:blip")))
            blip = paragraph._p.find(".//" + qn("a:blip"))
            expected = document.part.related_parts[blip.get(qn("r:embed"))].blob

            payload, evidence, _summary = parse_report_docx(data, mode="editable")

            image = next(
                fragment
                for content in payload["vulnerabilities"][0]["contents"]
                for fragment in content["fragments"]
                if fragment["type"] == "image"
            )
            self.assertEqual(evidence[image["evidence_id"]], expected)
            self.assertEqual(image["width_mm"], 155.0)

    def test_docx_resource_limits_reject_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)
            cases = (
                {"max_package_bytes": len(data) - 1},
                {"max_files": 1},
                {"max_uncompressed_bytes": 1},
                {"max_image_bytes": 1},
                {"max_image_pixels": 1},
                {"max_evidence_bytes": 1},
            )
            for limits in cases:
                with self.subTest(limits=limits), self.assertRaises(ReportImportLimitError):
                    parse_report_docx(data, mode="editable", **limits)

    def test_oversized_media_member_rejects_before_python_docx_materializes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            data = render_report_docx(self._report(folder), TEMPLATE, folder)

            with patch("app.docx_import.Document") as document, self.assertRaises(ReportImportLimitError):
                parse_report_docx(data, mode="editable", max_image_bytes=1)

            document.assert_not_called()

    def test_editable_mode_rejects_image_width_above_renderer_maximum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            document = Document(BytesIO(render_report_docx(self._report(folder), TEMPLATE, folder)))
            paragraph = next(paragraph for paragraph in document.paragraphs if paragraph._p.findall(".//" + qn("a:blip")))
            extent = paragraph._p.find(".//" + qn("wp:extent"))
            original_width, original_height = int(extent.get("cx")), int(extent.get("cy"))
            oversized_width = 156 * 36_000
            extent.set("cx", str(oversized_width))
            extent.set("cy", str(round(original_height * oversized_width / original_width)))
            output = BytesIO()
            document.save(output)

            with self.assertRaisesRegex(ReportImportError, "155 mm"):
                parse_report_docx(output.getvalue(), mode="editable")

    def test_editable_mode_rejects_rotated_evidence_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            document = Document(BytesIO(render_report_docx(self._report(folder), TEMPLATE, folder)))
            paragraph = next(paragraph for paragraph in document.paragraphs if paragraph._p.findall(".//" + qn("a:blip")))
            paragraph._p.find(".//" + qn("a:xfrm")).set("rot", "60000")
            output = BytesIO()
            document.save(output)

            with self.assertRaisesRegex(ReportImportError, "Rotated or flipped"):
                parse_report_docx(output.getvalue(), mode="editable")

    def test_the_note_prefix_is_not_kept_as_content(self) -> None:
        """``Note: `` is printed by note_fragment.docx, so keeping it would render ``Note: Note: ``
        the next time the report is generated."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            payload, _, _ = parse_report_docx(render_report_docx(self._report(folder), TEMPLATE, folder))
            description = payload["vulnerabilities"][0]["contents"][0]["fragments"]
            note = next(fragment for fragment in description if fragment["type"] == "note")
            self.assertEqual("".join(run["text"] for run in note["runs"]), "Validate independently.")

    def test_two_findings_may_share_a_title(self) -> None:
        """Nothing stops a tester naming two findings the same. Keying the summary by title gave
        both the last row's number, and the import then failed on a duplicate finding number."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = self._report(folder)
            twin = copy.deepcopy(report.vulnerabilities[0])
            twin.uid, twin.display_id = "v_twin", "002"
            for content in twin.contents:
                for fragment in content.fragments:
                    fragment.frag_id += "_twin"
            report.vulnerabilities.append(twin)

            payload, _, _ = parse_report_docx(render_report_docx(report, TEMPLATE, folder))
            self.assertEqual([finding["display_id"] for finding in payload["vulnerabilities"]], ["001", "002"])
            Report.model_validate(payload)

    def test_a_file_that_is_not_a_word_document_is_refused_by_name(self) -> None:
        with self.assertRaises(ReportImportError):
            parse_report_docx(b"not a document")


class ImportRouteTests(unittest.TestCase):
    """A .docx is itself a ZIP, so the sharpest risk here is the new branch stealing the bundle's."""

    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        main.workspace = Workspace(Path(self.root.name), "QA Tester")
        self.client = TestClient(main.app)

    @staticmethod
    def _docx() -> bytes:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            return render_report_docx(FragmentRecognitionTests._report(folder), TEMPLATE, folder)

    def _import(self, name: str, data: bytes, mode: str | None = None):
        form = {"docx_mode": mode} if mode is not None else None
        return self.client.post(
            "/reports/import",
            data=form,
            files={"file": (name, data, "application/octet-stream")},
        )

    def test_a_generated_report_imports_as_a_retest_draft(self) -> None:
        response = self._import("report.docx", self._docx())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "docx")
        self.assertEqual(response.json()["summary"]["statuses_rewritten"], ["Authorization bypass"])

        report = main.workspace.load(response.json()["report_id"])
        finding = report.vulnerabilities[0]
        sections = {content.type: [fragment.type for fragment in content.fragments] for content in finding.contents}
        self.assertEqual(sections["previous_proof_of_concept"][-1], "image", "the carried evidence came across")
        self.assertEqual(sections["proof_of_concept"], ["numbered_list", "image"], "the retest gets somewhere to write and to paste")
        self.assertIn(
            "Authorization bypass: Production evidence image required",
            generation_issues(report),
            "last year's screenshot must not stand in for this year's proof",
        )
        stored = main.workspace.find_path(report.report_id).parent / "evidence"
        self.assertEqual(len(list(stored.glob("*.png"))), 1)

    def test_a_retest_inherits_every_status_except_open_new(self) -> None:
        """A retest re-tests the distinction last year's status recorded, so only Open (New) is
        meaningless on one. Before this, anything outside a two-name set was dropped and reported as
        resolved - which would have eaten a finding for carrying a status added after it was written."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            carried = report.vulnerabilities[0]
            carried.status = "open_resolved_on_non_prod"
            carried.contents.extend([
                Content(type="previous_proof_of_concept", fragments=[
                    ListFragment(frag_id="f_prior", type="numbered_list", items=[ListItem(runs=[Run(text="Prior evidence.")])]),
                ]),
                Content(type="in_conclusion", fragments=[
                    ParagraphFragment(frag_id="f_prior_conclusion", type="paragraph", runs=[Run(text="Open in production.")]),
                ]),
            ])

            payload, _, summary = parse_report_docx(render_report_docx(report, TEMPLATE, folder), mode="retest")

            finding = payload["vulnerabilities"][0]
            self.assertEqual(finding["status"], "open_resolved_on_non_prod", "the retest lost the status it inherited")
            self.assertEqual(summary["dropped_resolved"], [], "an open finding was dropped and called resolved")
            self.assertEqual(summary["statuses_rewritten"], [], "nothing changed, so nothing may be reported as changed")

    def test_every_segment_the_model_allows_parses_back_out_of_a_title(self) -> None:
        """The title parser holds the segment set a second time, as a literal tuple, and the two
        copies have no other guard. Driving this from the Literal is what catches a segment added to
        one and not the other -- a miss loses segment, app name and report type together, and raises
        nothing, because the unknown-report-type error sits inside the branch a failed match never
        enters."""
        resources = Path(__file__).resolve().parent.parent / "resources"
        for segment in get_args(Segment):
            with self.subTest(segment=segment), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                report = FragmentRecognitionTests._report(folder)
                report.engagement.segment = segment
                if segment == "Asia":
                    report.vulnerabilities[0].cvss_score = "9.8"
                    report.vulnerabilities[0].cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"

                document = render_report_docx(report, main_template_path(report, resources), folder)
                payload, _, _ = parse_report_docx(document, mode="editable")

                engagement = payload["engagement"]
                self.assertEqual(engagement["segment"], segment)
                self.assertEqual(engagement["app_name"], "Northstar Banking")
                self.assertEqual(engagement["report_type"], "annual_pentest")

    def test_gdt_titles_round_trip_every_report_type_label(self) -> None:
        """The title parser receives report type only as a display label, so each label must map
        back to its stored value once the GDT segment has passed the cover-title gate."""
        for report_type in ("annual_pentest", "retest", "deployment_pentest", "new_test"):
            with self.subTest(report_type=report_type), tempfile.TemporaryDirectory() as temporary_directory:
                folder = Path(temporary_directory)
                report = FragmentRecognitionTests._report(folder)
                report.engagement.segment = "GDT"
                report.engagement.report_type = report_type

                payload, _, _ = parse_report_docx(render_report_docx(report, TEMPLATE, folder), mode="editable")

                engagement = payload["engagement"]
                self.assertEqual(engagement["segment"], "GDT")
                self.assertEqual(engagement["report_type"], report_type)

    def test_a_retest_drops_closed_findings_and_keeps_the_open_ones(self) -> None:
        """Closed borrows exactly one rule from Resolved -- the retest drop -- and a dropped finding
        takes its evidence and typed work with it, so the summary is its only trace."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            kept = report.vulnerabilities[0]
            kept.status = "open_resolved_on_non_prod"
            kept.contents.extend([
                Content(type="previous_proof_of_concept", fragments=[
                    ListFragment(frag_id="f_prior", type="numbered_list", items=[ListItem(runs=[Run(text="Prior evidence.")])]),
                ]),
                Content(type="in_conclusion", fragments=[
                    ParagraphFragment(frag_id="f_prior_conclusion", type="paragraph", runs=[Run(text="Open in production.")]),
                ]),
            ])
            shut = copy.deepcopy(kept)
            shut.uid, shut.display_id, shut.title, shut.status = "v_shut", "002", "Closed last year", "closed"
            report.vulnerabilities = [kept, shut]

            document = render_report_docx(report, TEMPLATE, folder)
            self.assertIn("Closed", "\n".join(item.text for table in Document(BytesIO(document)).tables for row in table.rows for item in row.cells))

            payload, _, summary = parse_report_docx(document, mode="retest")

            self.assertEqual([finding["title"] for finding in payload["vulnerabilities"]], ["Authorization bypass"])
            self.assertEqual(summary["dropped_resolved"], ["Closed last year"])

    def test_an_editable_import_keeps_a_closed_finding_as_closed(self) -> None:
        """Editable mode is the recovery path for anything a retest drops, so the status has to
        survive it rather than downgrading to previously discovered."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            finding = report.vulnerabilities[0]
            finding.status = "closed"
            finding.contents.extend([
                Content(type="previous_proof_of_concept", fragments=[
                    ListFragment(frag_id="f_prior", type="numbered_list", items=[ListItem(runs=[Run(text="Prior evidence.")])]),
                ]),
                Content(type="in_conclusion", fragments=[
                    ParagraphFragment(frag_id="f_prior_conclusion", type="paragraph", runs=[Run(text="Shut without a fix.")]),
                ]),
            ])

            payload, _, summary = parse_report_docx(render_report_docx(report, TEMPLATE, folder), mode="editable")

            self.assertEqual(payload["vulnerabilities"][0]["status"], "closed")
            # A recognised label warns about nothing; an unrecognised one downgrades and says so.
            self.assertEqual([warning for warning in summary["warnings"] if "imported as" in warning], [])

    def test_prompt_classifies_a_docx_without_creating_a_report(self) -> None:
        response = self._import("misleading.zip", self._docx(), "prompt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"source": "docx", "mode_required": True})
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_route_imports_editable_then_first_put_preserves_visible_semantics(self) -> None:
        response = self._import("report.docx", self._docx(), "editable")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["mode"], "editable")
        self.assertTrue(any("rendered Word copies" in warning for warning in result["summary"]["warnings"]))

        imported = main.workspace.load(result["report_id"])
        self.assertEqual(imported.vulnerabilities[0].status, "open_new")
        target_ids = [target.target_id for target in imported.scope_targets]
        before = main._editable_user_projection(imported)
        previous_revision = imported.saved_at
        payload = imported.model_dump(mode="json", by_alias=True)
        payload["scope_text"] = main.scope_text_from_targets(imported.scope_targets)
        saved = self.client.put(f"/reports/{imported.report_id}", json=payload)

        self.assertEqual(saved.status_code, 200, saved.text)
        after = main.workspace.load(imported.report_id)
        self.assertEqual([target.target_id for target in after.scope_targets], target_ids)
        self.assertEqual(main._editable_user_projection(after), before)
        self.assertEqual(after.app_id, "Northstar_Banking")
        self.assertGreater(after.saved_at, previous_revision)

    def test_explicit_docx_mode_is_rejected_for_a_bundle(self) -> None:
        created = self.client.get("/new", follow_redirects=False)
        report_id = created.headers["location"].split("/")[2]
        exported = self.client.get(f"/reports/{report_id}/export")

        response = self._import("report.docx", exported.content, "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("not a report DOCX", response.json()["detail"])

    def test_prompted_bundle_imports_without_a_mode_round_trip(self) -> None:
        created = self.client.get("/new", follow_redirects=False)
        report_id = created.headers["location"].split("/")[2]
        exported = self.client.get(f"/reports/{report_id}/export")

        response = self._import("misleading.docx", exported.content, "prompt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "bundle")
        self.assertNotIn("mode_required", response.json())

    def test_unknown_docx_mode_is_rejected_without_writing(self) -> None:
        before = set(Path(self.root.name).glob("apps/**/draft.json"))
        response = self._import("report.docx", self._docx(), "replace")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Unknown DOCX import mode", response.json()["detail"])
        self.assertEqual(set(Path(self.root.name).glob("apps/**/draft.json")), before)

    def test_an_unrecognised_status_is_assumed_rather_than_refusing_the_document(self) -> None:
        """A report written by an older version, or edited by hand, must still import. Only the
        summary cell is changed here, so the detail cell still reads the original label - which is
        the case that has to stop being an inconsistency."""
        document = Document(BytesIO(self._docx()))
        summary = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Findings")
        title = summary.rows[1].cells[0].text.strip()
        summary.rows[1].cells[5].text = "Pending"
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 200)
        draft = json.loads(next(Path(self.root.name).glob("apps/**/draft.json")).read_text())
        assumed = next(finding for finding in draft["vulnerabilities"] if finding["title"] == title)
        self.assertEqual(assumed["status"], "open_previously_discovered")
        self.assertEqual(
            [content["type"] for content in assumed["contents"]],
            ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"],
            "provisioning rebuilds to the status's shape, so what the importer hands over must match it",
        )
        warnings = response.json()["summary"]["warnings"]
        self.assertTrue(
            any(title in warning and "Pending" in warning for warning in warnings),
            f"the assumption was made silently: {warnings}",
        )

    def test_truncated_location_row_is_rejected_without_writing(self) -> None:
        document = Document(BytesIO(self._docx()))
        location_row = next(
            row
            for table in document.tables
            for row in table.rows
            if row.cells and row.cells[0].text.strip() == "Location"
        )
        location_row._tr.remove(location_row.cells[-1]._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid Location row", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_truncated_component_row_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            report.engagement.tested_channels = ["thick_client"]
            report.scope_targets = [ScopeTarget(
                target_id="t_component",
                environment="production",
                channel="thick_client",
                value="Acme.exe",
                description="Desktop client",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_component"]
            document = Document(BytesIO(render_report_docx(
                report,
                main_template_path(report, Path(__file__).resolve().parent.parent / "resources"),
                folder,
            )))
        component = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Component")
        component.rows[1]._tr.remove(component.rows[1].cells[-1]._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid Component row", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_component_table_with_both_channel_markers_is_rejected_without_writing(self) -> None:
        """Mutual exclusion between Mobile and Thick Client is a Setup-page UI rule only; nothing on
        the load path enforces it. A hand-edited document naming both markers must still be refused
        at import, since the parser cannot otherwise decide which channel the one Component table
        belongs to."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            report.engagement.tested_channels = ["thick_client"]
            report.scope_targets = [ScopeTarget(
                target_id="t_component",
                environment="production",
                channel="thick_client",
                value="Acme.exe",
                description="Desktop client",
            )]
            report.vulnerabilities[0].scope.target_ids = ["t_component"]
            document = Document(BytesIO(render_report_docx(
                report,
                main_template_path(report, Path(__file__).resolve().parent.parent / "resources"),
                folder,
            )))
        marker_paragraph = next(p for p in document.paragraphs if "Thick Client Application Binary" in p.text)
        duplicate = copy.deepcopy(marker_paragraph._p)
        for node in duplicate.findall(".//" + qn("w:t")):
            if node.text == "Thick Client ":
                node.text = "Mobile "
        marker_paragraph._p.addnext(duplicate)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("does not identify exactly one supported app type", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_truncated_asia_section_row_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            report = FragmentRecognitionTests._report(folder)
            report.engagement.segment = "Asia"
            finding = report.vulnerabilities[0]
            finding.cvss_score = "8.1"
            finding.cvss_vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N"
            document = Document(BytesIO(render_report_docx(
                report,
                main_template_path(report, Path(__file__).resolve().parent.parent / "resources"),
                folder,
            )))
        section = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Section")
        section.rows[1]._tr.remove(section.rows[1].cells[-1]._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid Section row", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_empty_limitations_row_is_rejected_without_writing(self) -> None:
        document = Document(BytesIO(self._docx()))
        limitations = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Limitations")
        limitations.rows[1]._tr.remove(limitations.rows[1].cells[0]._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid Limitations row", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_empty_scope_row_is_rejected_without_writing(self) -> None:
        document = Document(BytesIO(self._docx()))
        scope = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "URL(s) in Scope")
        value_row = next(row for row in scope.rows[1:] if row.cells[0].text.strip() == "https://prod.example.test")
        value_row._tr.remove(value_row.cells[0]._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid URL(s) in Scope row", response.json()["detail"])
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_empty_table_header_row_does_not_break_lookup(self) -> None:
        document = Document(BytesIO(self._docx()))
        limitations = next(table for table in document.tables if table.rows[0].cells[0].text.strip() == "Limitations")
        header_row = limitations.rows[0]
        for cell in tuple(header_row.cells):
            header_row._tr.remove(cell._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertNotEqual(response.status_code, 500, response.text)

    def test_empty_finding_detail_row_is_skipped_without_crashing(self) -> None:
        document = Document(BytesIO(self._docx()))
        detail = next(
            table
            for table in document.tables
            if any(row.cells and row.cells[0].text.strip() == "Location" for row in table.rows)
        )
        empty_row = detail.add_row()
        for cell in tuple(empty_row.cells):
            empty_row._tr.remove(cell._tc)
        output = BytesIO()
        document.save(output)

        response = self._import("report.docx", output.getvalue(), "editable")

        self.assertEqual(response.status_code, 200, response.text)

    def test_docx_parser_limits_surface_as_payload_too_large(self) -> None:
        with patch.object(main, "MAX_BUNDLE_FILES", 1):
            response = self._import("report.docx", self._docx(), "editable")
        self.assertEqual(response.status_code, 413)

    def test_editable_preflight_rejects_scope_reconciliation_loss(self) -> None:
        payload, _evidence, _summary = parse_report_docx(self._docx(), mode="editable")
        duplicate = copy.deepcopy(payload["scope_targets"][0])
        duplicate["target_id"] = "tgt_duplicate"
        payload["scope_targets"].append(duplicate)
        payload["vulnerabilities"][0]["scope"]["target_ids"].append("tgt_duplicate")

        with self.assertRaisesRegex(ValueError, "Scope reconciliation would alter imported locations"):
            main.finalize_editable_import(payload)

    def test_editable_import_rolls_back_when_an_evidence_write_fails(self) -> None:
        with patch("app.workspace.atomic_write_bytes", side_effect=OSError("disk full")):
            response = self._import("report.docx", self._docx(), "editable")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(Path(self.root.name).glob("apps/**/draft.json")), [])

    def test_a_bundle_still_takes_the_bundle_branch(self) -> None:
        created = self.client.get("/new", follow_redirects=False)
        report_id = created.headers["location"].split("/")[2]
        exported = self.client.get(f"/reports/{report_id}/export")
        response = self._import("report.zip", exported.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "bundle")

    def test_a_truncated_document_is_refused_rather_than_crashing(self) -> None:
        response = self._import("report.docx", self._docx()[: 4_000])
        self.assertEqual(response.status_code, 422)

    def test_the_wrong_kind_of_file_is_named_rather_than_decoded(self) -> None:
        """Every non-ZIP falls through to the JSON branch, so without this a tester who picks a PDF
        is told "Expecting value: line 1 column 1"."""
        cases = {
            b"%PDF-1.4\ntrailer<</Root 1 0 R>>\n%%EOF\n": "this is a PDF",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 20: "not a VulnReport ZIP",
            b"": "the file is empty",
        }
        for data, expected in cases.items():
            with self.subTest(expected=expected):
                response = self._import("report.docx", data)
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected, response.json()["error"]["message"])


if __name__ == "__main__":
    unittest.main()
