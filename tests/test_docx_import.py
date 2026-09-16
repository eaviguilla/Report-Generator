"""Reading a generated report back in.

Every test here renders with ``render_report_docx`` directly. The generate *routes* call Word
through ``update_docx_bytes_with_word`` and return 422 on any machine without it, so going through
them would test the environment rather than the document.
"""
from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.docx_import import ReportImportError, classify_paragraph, numbering_formats, parse_report_docx
from app.docx_report import generation_issues, render_report_docx
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
    TableFragment,
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

    def _import(self, name: str, data: bytes):
        return self.client.post("/reports/import", files={"file": (name, data, "application/octet-stream")})

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
