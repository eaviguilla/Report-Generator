from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from PIL import Image

from app.docx_report import (
    LOCATION_WRAP_CHARACTERS,
    SCOPE_WRAP_CHARACTERS,
    ReportGenerationError,
    _wrap_long_value,
    generation_issues,
    render_report_docx,
)
from app.report_service import provision, sync_evidence_image_slots
from app.models import CodeFragment, Content, Engagement, EvidenceItem, ImageFragment, InstanceTitleFragment, ListFragment, ListItem, NoteFragment, ParagraphFragment, Report, Run, Scope, ScopeTarget, TableFragment, TestAccount, TestWindow, Vulnerability


def _keeps_next(element) -> bool:
    properties = element.find(qn("w:pPr"))
    return properties is not None and properties.find(qn("w:keepNext")) is not None


def _is_blank_paragraph(element) -> bool:
    return element.tag == qn("w:p") and not "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


class DocxReportTests(unittest.TestCase):
    def test_renders_template_with_repeated_findings_and_no_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            evidence_folder = report_folder / "evidence"
            evidence_folder.mkdir()
            evidence = BytesIO()
            Image.new("RGB", (40, 20), "white").save(evidence, format="PNG")
            for evidence_id in ("ev_prod", "ev_prod_extra", "ev_uat", "ev_prod_second", "ev_prev"):
                (evidence_folder / f"{evidence_id}.png").write_bytes(evidence.getvalue())

            now = datetime.now().astimezone()
            report = Report(
                report_id="r_docx_test",
                app_id="CI-DOCX",
                saved_at=now,
                engagement=Engagement(
                    app_name="Northstar Banking",
                    ci_number="CI-DOCX",
                    app_owner="Avery Morgan",
                    segment="JH",
                    report_type="annual_pentest",
                    report_date=date(2026, 9, 9),
                    tester="QA Tester",
                    tested_environments=["production", "non_production"],
                    tested_channels=["web", "api"],
                    test_windows={
                        "production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), test_time="22:00 EST"),
                        "non_production": TestWindow(start_date=date(2026, 7, 28), end_date=date(2026, 7, 30), test_time="Anytime"),
                    },
                    test_accounts=[TestAccount(user_role="Customer", username="qa.customer"), TestAccount(user_role="Admin", username="qa.admin")],
                    limitations="No destructive testing.",
                ),
                scope_targets=[
                    ScopeTarget(target_id="t_prod_web", environment="production", channel="web", value="https://prod.example.test"),
                    ScopeTarget(target_id="t_prod_web_2", environment="production", channel="web", value="https://admin.example.test", order=1),
                    ScopeTarget(target_id="t_prod_api", environment="production", channel="api", value="https://prod-api.example.test", order=1),
                    ScopeTarget(target_id="t_prod_api_2", environment="production", channel="api", value="https://prod-api.example.test/v2", order=2),
                    ScopeTarget(target_id="t_uat_web", environment="non_production", channel="web", value="https://uat.example.test"),
                    ScopeTarget(target_id="t_uat_web_2", environment="non_production", channel="web", value="https://staging.example.test", order=1),
                    ScopeTarget(target_id="t_uat_api", environment="non_production", channel="api", value="https://uat-api.example.test"),
                    ScopeTarget(target_id="t_uat_api_2", environment="non_production", channel="api", value="https://uat-api.example.test/v2", order=1),
                ],
                evidence={
                    evidence_id: EvidenceItem(file=f"evidence/{evidence_id}.png", original_name=f"{evidence_id}.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)
                    for evidence_id in ("ev_prod", "ev_prod_extra", "ev_uat", "ev_prod_second", "ev_prev")
                },
            )
            report.vulnerabilities = [
                self._finding("v_high_1", "Authorization bypass", "high", "001", ["t_prod_web", "t_prod_api", "t_uat_api"], [
                    ImageFragment(frag_id="f_img_prod", type="image", environment="production", evidence_id="ev_prod", caption="Production response"),
                    ImageFragment(frag_id="f_img_prod_extra", type="image", environment="production", evidence_id="ev_prod_extra", caption="Additional production response"),
                    ImageFragment(frag_id="f_img_uat", type="image", environment="non_production", evidence_id="ev_uat", caption="Non-Production response"),
                ], likelihood="critical", impact="low"),
                self._finding("v_high_2", "Session fixation", "high", "002", ["t_prod_web", "t_prod_api"], [
                    ImageFragment(frag_id="f_img_prod_2", type="image", environment="production", evidence_id="ev_prod_second", caption="Additional production response"),
                ], likelihood="medium", impact="informational"),
            ]
            report.vulnerabilities[1].status = "resolved"
            provision(report.vulnerabilities[1])
            # The app's own conclusion sentence now blocks generation, so this finding writes its own.
            conclusion = next(content for content in report.vulnerabilities[1].contents if content.type == "in_conclusion")
            conclusion.fragments[0].runs = [Run(text="Session fixation was remediated and could not be reproduced on retest.")]
            previous = next(content for content in report.vulnerabilities[1].contents if content.type == "previous_proof_of_concept")
            next(fragment for fragment in previous.fragments if isinstance(fragment, ListFragment)).items = [
                ListItem(runs=[Run(text="Reproduce the previously reported behavior.")]),
                ListItem(runs=[Run(text="Record the original vulnerable response.")]),
            ]
            # Non-production is outside this finding's scope, so this also pins that history is not
            # filtered by the current engagement.
            previous_image = next(fragment for fragment in previous.fragments if isinstance(fragment, ImageFragment))
            previous_image.environment = "non_production"
            previous_image.evidence_id = "ev_prev"
            previous_image.caption = "Original non-production response"

            template = Path(__file__).resolve().parent.parent / "resources" / "MAIN_TEST.docx"
            generated = render_report_docx(report, template, report_folder)
            rendered = Document(BytesIO(generated))
            text = "\n".join([*(paragraph.text for paragraph in rendered.paragraphs), *(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)])
            self.assertNotIn("{{", text)
            self.assertNotIn("-fragments-here", text.casefold())
            self.assertEqual(text.count("Authorization bypass"), 2)
            self.assertEqual(text.count("Session fixation"), 3)
            summary = next(table for table in rendered.tables if table.cell(0, 0).text == "Findings")
            self.assertEqual(len(summary.rows), 3)
            expected_rating_colors = {
                "Authorization bypass": (RGBColor(192, 0, 0), RGBColor(112, 173, 71), RGBColor(237, 125, 49)),
                "Session fixation": (RGBColor(255, 192, 0), RGBColor(81, 81, 81), RGBColor(237, 125, 49)),
            }
            for row in summary.rows[1:]:
                self.assertEqual(
                    tuple(row.cells[index].paragraphs[0].runs[0].font.color.rgb for index in (1, 2, 3)),
                    expected_rating_colors[row.cells[0].text],
                )
                for index in (1, 2, 3):
                    rating_run = next(run for run in row.cells[index].paragraphs[0].runs if run.text)
                    self.assertEqual(rating_run.font.size, Pt(12))
            self.assertEqual(len(rendered.inline_shapes), 5)
            paragraph_texts = [paragraph.text for paragraph in rendered.paragraphs]
            self.assertEqual(paragraph_texts.count("PROD:"), 2)
            # The evidence label follows the engagement's chosen non-production name. The second
            # occurrence is the carried previous proof of concept, which the retest no longer covers.
            self.assertEqual(paragraph_texts.count("UAT:"), 2)
            self.assertEqual(paragraph_texts.count("NON-PROD:"), 0)

            # The component template is the only supported one, so the checks below share this render.
            component_generated = generated
            component_document = rendered
            template_document = Document(Path("resources/MAIN_TEST.docx"))
            template_revision = next(
                table for table in template_document.tables if table.cell(0, 0).text == "Version"
            )
            rendered_revision = next(
                table for table in component_document.tables if table.cell(0, 0).text == "Version"
            )
            self.assertEqual(
                [child.tag for child in rendered_revision._tbl.iterchildren()],
                [child.tag for child in template_revision._tbl.iterchildren()],
            )
            self.assertEqual(
                sum(1 for _ in rendered_revision._tbl.iter(qn("w:tr"))),
                sum(1 for _ in template_revision._tbl.iter(qn("w:tr"))),
            )
            revision_text = " ".join(
                node.text or "" for node in rendered_revision._tbl.iter(qn("w:t"))
            )
            self.assertIn("1.0", revision_text)
            self.assertIn("New Report", revision_text)
            self.assertIn("September 9, 2026", revision_text)
            self.assertIn("QA Tester", revision_text)
            self.assertNotIn("{{", revision_text)
            template_header_footer_parts = {
                str(part.partname): part
                for part in template_document.part.package.parts
                if "/header" in str(part.partname) or "/footer" in str(part.partname)
            }
            rendered_header_footer_parts = {
                str(part.partname): part
                for part in component_document.part.package.parts
                if "/header" in str(part.partname) or "/footer" in str(part.partname)
            }
            self.assertEqual(rendered_header_footer_parts.keys(), template_header_footer_parts.keys())
            for part_name, template_part in template_header_footer_parts.items():
                template_text = "".join(node.text or "" for node in template_part._element.iter(qn("w:t")))
                if "{{" not in template_text:
                    continue
                rendered_text = "".join(
                    node.text or ""
                    for node in rendered_header_footer_parts[part_name]._element.iter(qn("w:t"))
                )
                self.assertNotIn("{{", rendered_text)
                self.assertIn("Northstar Banking", rendered_text)
            page_number_starts = [
                page_numbering.get(qn("w:start")) if page_numbering is not None else None
                for section_properties in component_document.element.body.iter(qn("w:sectPr"))
                if not any(
                    ancestor.tag == qn("w:sectPrChange")
                    for ancestor in section_properties.iterancestors()
                )
                for page_numbering in [section_properties.find(qn("w:pgNumType"))]
            ]
            self.assertEqual(
                page_number_starts,
                [None, "1", "1", None, None, None, None, None, None, None],
            )
            component_text = "\n".join(
                [
                    *(paragraph.text for paragraph in component_document.paragraphs),
                    *(cell.text for table in component_document.tables for row in table.rows for cell in row.cells),
                ]
            )
            self.assertNotIn("{{", component_text)
            self.assertEqual(sum(paragraph.text == "High Findings" for paragraph in component_document.paragraphs), 1)
            self.assertEqual(sum(paragraph.text == "Previous Proof of Concept: " for paragraph in component_document.paragraphs), 1)
            self.assertEqual(sum(paragraph.text == "In Conclusion: " for paragraph in component_document.paragraphs), 1)
            self.assertEqual(len(component_document.inline_shapes), 5)
            self._assert_image_fragment_format(component_document)
            web_scope = next(table for table in component_document.tables if table.cell(0, 0).text == "URL(s) in Scope")
            api_scope = next(table for table in component_document.tables if table.cell(0, 0).text == "API Routes")
            expected_scope_lines = [
                (web_scope.cell(2, 0), ["https://prod.example.test", "https://admin.example.test"]),
                (web_scope.cell(4, 0), ["https://uat.example.test", "https://staging.example.test"]),
                (api_scope.cell(2, 0), ["https://prod-api.example.test", "https://prod-api.example.test/v2"]),
                (api_scope.cell(4, 0), ["https://uat-api.example.test", "https://uat-api.example.test/v2"]),
            ]
            for cell, expected_lines in expected_scope_lines:
                self.assertEqual([paragraph.text for paragraph in cell.paragraphs], expected_lines)
                self.assertTrue(all(paragraph.style.name == "List Bullet 2" for paragraph in cell.paragraphs))
            for vulnerability_id in ("001", "002"):
                details = next(
                    table
                    for table in component_document.tables
                    if len(table.rows) >= 5
                    and table.cell(0, 0).text == "Severity"
                    and table.cell(1, 1).text == vulnerability_id
                )
                production_location = details.cell(3, 1)
                self.assertEqual(
                    production_location.text,
                    "Production Environment:\nhttps://prod.example.test\nhttps://prod-api.example.test",
                )
                # The glyph comes from the list style, so short locations need no manual break.
                self.assertEqual(len(production_location._tc.findall(".//" + qn("w:br"))), 0)
                bullets = [item for item in production_location.paragraphs if item.style.name == "List Paragraph"]
                self.assertEqual(len(bullets), 2)
                self.assertTrue(all(item._p.find(qn("w:pPr")).find(qn("w:numPr")) is not None for item in bullets))
            section_titles = {
                "Recommended Remediation:",
                "Proof of Concept:",
                "In Conclusion:",
                "Severity Review Ticket (if applicable):",
            }
            for paragraph in component_document.paragraphs:
                if paragraph.text.strip() in section_titles:
                    previous = paragraph._p.getprevious()
                    blank_count = 0
                    while (
                        previous is not None
                        and previous.tag == qn("w:p")
                        and not "".join(node.text or "" for node in previous.iter(qn("w:t"))).strip()
                    ):
                        blank_count += 1
                        previous = previous.getprevious()
                    self.assertLessEqual(blank_count, 1)
            description = next(paragraph for paragraph in component_document.paragraphs if paragraph.text == "A complete description.")
            following = description._p.getnext()
            self.assertEqual(following.tag, qn("w:p"))
            self.assertEqual("".join(node.text or "" for node in following.iter(qn("w:t"))), "")
            component_summary = next(table for table in component_document.tables if table.cell(0, 0).text == "Findings")
            for row in component_summary.rows[1:]:
                for index in (1, 2, 3):
                    rating_run = next(run for run in row.cells[index].paragraphs[0].runs if run.text)
                    self.assertEqual(rating_run.font.size, Pt(12))
            self.assertTrue(any(paragraph.text == "Request" and paragraph.style.name == "Figures and Tables" for paragraph in component_document.paragraphs))
            image_caption = next(paragraph for paragraph in component_document.paragraphs if paragraph.text.endswith("Production response"))
            self.assertEqual(image_caption.style.name, "Figures and Tables")
            self.assertTrue(image_caption._p.getprevious().xpath(".//w:drawing"))
            self.assertEqual(image_caption.text, "Figure 2. Production response")
            self.assertEqual(
                [node.text for node in image_caption._p.iter(qn("w:instrText"))],
                [r" SEQ Figure \* ARABIC "],
            )
            component_code = next(paragraph for paragraph in component_document.paragraphs if paragraph.text == "GET /accounts/123")
            self.assertEqual(component_code.runs[0].font.name, "Consolas")
            note = next(paragraph for paragraph in component_document.paragraphs if paragraph.text == "Note: Validate the result independently.")
            self.assertTrue(all(run.italic for run in note.runs if run.text))
            generated_table = next(table for table in component_document.tables if table.cell(0, 0).text == "Generated Header")
            self.assertEqual(sum(int(column.get(qn("w:w"))) for column in generated_table._tbl.tblGrid.iterchildren(qn("w:gridCol"))), 9994)
            with ZipFile(BytesIO(component_generated)) as archive:
                self.assertIn("word/document.xml", archive.namelist())

    def test_template_without_the_findings_anchor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            report = Report(
                report_id="r_legacy_template",
                app_id="CI-DOCX",
                saved_at=datetime.now().astimezone(),
                engagement=Engagement(app_name="Northstar Banking"),
            )
            template = Path(__file__).resolve().parent.parent / "resources" / "fixtures" / "report-name.docx"
            with self.assertRaises(ReportGenerationError) as raised:
                render_report_docx(report, template, report_folder, allow_incomplete=True)
            self.assertIn("{{findings}}", str(raised.exception))

    def test_image_left_behind_for_an_unaffected_environment_is_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            evidence_folder = report_folder / "evidence"
            evidence_folder.mkdir()
            buffer = BytesIO()
            Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
            for evidence_id in ("ev_prod", "ev_stale"):
                (evidence_folder / f"{evidence_id}.png").write_bytes(buffer.getvalue())
            now = datetime.now().astimezone()
            report = Report(
                report_id="r_stale_image",
                app_id="CI-DOCX",
                saved_at=now,
                engagement=Engagement(
                    app_name="Northstar Banking",
                    ci_number="CI-DOCX",
                    segment="JH",
                    report_type="annual_pentest",
                    report_date=date(2026, 9, 9),
                    tester="QA Tester",
                    tested_environments=["production", "non_production"],
                    tested_channels=["web"],
                    test_windows={
                        "production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), test_time="22:00 EST"),
                        "non_production": TestWindow(start_date=date(2026, 7, 28), end_date=date(2026, 7, 30), test_time="Anytime"),
                    },
                ),
                scope_targets=[
                    ScopeTarget(target_id="t_prod", environment="production", channel="web", value="https://prod.example.test"),
                    ScopeTarget(target_id="t_uat", environment="non_production", channel="web", value="https://uat.example.test"),
                ],
                evidence={
                    evidence_id: EvidenceItem(file=f"evidence/{evidence_id}.png", original_name=f"{evidence_id}.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)
                    for evidence_id in ("ev_prod", "ev_stale")
                },
            )
            # The finding covers production only, but a non-production image is still attached.
            report.vulnerabilities = [
                self._finding("v_prod_only", "Authorization bypass", "high", "001", ["t_prod"], [
                    ImageFragment(frag_id="f_img_prod", type="image", environment="production", evidence_id="ev_prod", caption="Production response"),
                    ImageFragment(frag_id="f_img_stale", type="image", environment="non_production", evidence_id="ev_stale", caption="Stale lower-region response"),
                ]),
            ]
            self.assertEqual(generation_issues(report), [])

            template = Path(__file__).resolve().parent.parent / "resources" / "MAIN_TEST.docx"
            rendered = Document(BytesIO(render_report_docx(report, template, report_folder)))
            paragraph_texts = [paragraph.text for paragraph in rendered.paragraphs]
            self.assertEqual(paragraph_texts.count("PROD:"), 1)
            self.assertEqual(paragraph_texts.count("UAT:"), 0)
            self.assertEqual(len(rendered.inline_shapes), 1)
            self.assertNotIn("Stale lower-region response", "\n".join(paragraph_texts))

    def _retest_report(self, report_folder: Path, evidence_ids: tuple[str, ...]) -> Report:
        """A production-only finding in an engagement that also tested non-production."""
        evidence_folder = report_folder / "evidence"
        evidence_folder.mkdir()
        buffer = BytesIO()
        Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
        for evidence_id in evidence_ids:
            (evidence_folder / f"{evidence_id}.png").write_bytes(buffer.getvalue())
        now = datetime.now().astimezone()
        return Report(
            report_id="r_retest",
            app_id="CI-DOCX",
            saved_at=now,
            engagement=Engagement(
                app_name="Northstar Banking",
                ci_number="CI-DOCX",
                segment="JH",
                report_type="retest",
                report_date=date(2026, 9, 9),
                tester="QA Tester",
                tested_environments=["production"],
                tested_channels=["web"],
                test_windows={"production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), test_time="22:00 EST")},
            ),
            scope_targets=[ScopeTarget(target_id="t_prod", environment="production", channel="web", value="https://prod.example.test")],
            evidence={
                evidence_id: EvidenceItem(file=f"evidence/{evidence_id}.png", original_name=f"{evidence_id}.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)
                for evidence_id in evidence_ids
            },
        )

    @staticmethod
    def _carry_history(finding: Vulnerability, environment: str, evidence_id: str) -> ImageFragment:
        """Promote a finding to previously discovered and fill the seeded previous proof of concept."""
        finding.status = "open_previously_discovered"
        provision(finding)
        # Promoting the status seeds a conclusion, and the app's own sentence blocks generation.
        conclusion = next(content for content in finding.contents if content.type == "in_conclusion")
        conclusion.fragments[0].runs = [Run(text="The original finding remains exploitable on retest.")]
        previous = next(content for content in finding.contents if content.type == "previous_proof_of_concept")
        next(fragment for fragment in previous.fragments if isinstance(fragment, ListFragment)).items = [ListItem(runs=[Run(text="Reproduce the original finding.")])]
        history = next(fragment for fragment in previous.fragments if isinstance(fragment, ImageFragment))
        history.environment = environment
        history.evidence_id = evidence_id
        history.caption = "Original non-production response"
        return history

    def test_previous_proof_of_concept_image_survives_a_narrower_retest(self) -> None:
        """A retest is usually narrower than the test before it, so gating history on the current
        scope would hide, relabel, or drop evidence the previous engagement actually gathered."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            report = self._retest_report(report_folder, ("ev_prod", "ev_history"))
            report.vulnerabilities = [
                self._finding("v_retest", "Authorization bypass", "high", "001", ["t_prod"], [
                    ImageFragment(frag_id="f_img_prod", type="image", environment="production", evidence_id="ev_prod", caption="Production response"),
                ]),
            ]
            finding = report.vulnerabilities[0]
            history = self._carry_history(finding, "non_production", "ev_history")

            sync_evidence_image_slots(finding, report)
            self.assertEqual(history.environment, "non_production", "a carried image keeps the environment it was found in")
            self.assertEqual(generation_issues(report), [])

            template = Path(__file__).resolve().parent.parent / "resources" / "MAIN_TEST.docx"
            rendered = Document(BytesIO(render_report_docx(report, template, report_folder)))
            paragraph_texts = [paragraph.text for paragraph in rendered.paragraphs]
            self.assertEqual(paragraph_texts.count("UAT:"), 1, "the carried non-production image must still be labelled and rendered")
            self.assertEqual(len(rendered.inline_shapes), 2)

    def test_previous_evidence_does_not_satisfy_the_retest_requirement(self) -> None:
        """Last year's screenshot is not this year's proof, so it must not silently stand in for it."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            report = self._retest_report(report_folder, ("ev_history",))
            report.vulnerabilities = [self._finding("v_retest", "Authorization bypass", "high", "001", ["t_prod"], [])]
            self._carry_history(report.vulnerabilities[0], "production", "ev_history")

            self.assertIn("Authorization bypass: Production evidence image required", generation_issues(report))

    def test_affected_locations_are_real_bullets_and_long_paths_wrap_on_a_slash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            (report_folder / "evidence").mkdir()
            buffer = BytesIO()
            Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
            (report_folder / "evidence" / "ev_wrap.png").write_bytes(buffer.getvalue())
            now = datetime.now().astimezone()
            web_target = "https://prod.example.test/accounts/123/details/extra/settings/preferences/alerts/email"
            api_target = "https://api.example.test/v2/customers/profile/settings/advanced/notifications/preferences"
            report = Report(
                report_id="r_wrap", app_id="CI-DOCX", saved_at=now,
                engagement=Engagement(
                    app_name="Northstar Banking", ci_number="CI-DOCX", segment="JH", report_type="annual_pentest",
                    report_date=date(2026, 9, 9), tester="QA Tester", tested_environments=["production"], tested_channels=["web", "api"],
                    test_windows={"production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))},
                ),
                scope_targets=[
                    ScopeTarget(target_id="t_web", environment="production", channel="web", value=web_target),
                    ScopeTarget(target_id="t_api", environment="production", channel="api", value=api_target),
                ],
                evidence={"ev_wrap": EvidenceItem(file="evidence/ev_wrap.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)},
            )
            report.vulnerabilities = [self._finding("v_wrap", "Authorization bypass", "high", "001", ["t_web", "t_api"], [
                ImageFragment(frag_id="f_img", type="image", environment="production", evidence_id="ev_wrap", caption="Production response"),
            ])]
            rendered = Document(BytesIO(render_report_docx(report, Path("resources/MAIN_TEST.docx"), report_folder)))

            locations = next(
                cell
                for table in rendered.tables if table.cell(0, 0).text not in {"URL(s) in Scope", "API Routes"}
                for row in table.rows for cell in row.cells
                if "prod.example.test/accounts" in cell.text
            )
            bullets = [paragraph for paragraph in locations.paragraphs if paragraph.style.name == "List Paragraph"]
            self.assertEqual(len(bullets), 2)
            for paragraph in bullets:
                properties = paragraph._p.find(qn("w:pPr"))
                self.assertIsNotNone(properties.find(qn("w:numPr")), "affected locations must be a real bullet list")
                self.assertEqual(properties.find(qn("w:jc")).get(qn("w:val")), "left")
                self.assertEqual(len(paragraph._p.findall(".//" + qn("w:br"))), 1, "a long location should break once")
            self.assertNotIn("\u2022", locations.text, "the bullet glyph must come from the list style, not the text")
            self.assertTrue(bullets[0].text.startswith("https://prod.example.test/accounts/"))
            self.assertTrue(all(len(line) <= LOCATION_WRAP_CHARACTERS for line in bullets[0].text.split("\n")))

            for name, target in (("URL(s) in Scope", web_target), ("API Routes", api_target)):
                table = next(candidate for candidate in rendered.tables if candidate.cell(0, 0).text == name)
                paragraph = next(item for item in table.cell(2, 0).paragraphs if item.text.strip())
                self.assertEqual(len(paragraph._p.findall(".//" + qn("w:br"))), 1)
                self.assertEqual(paragraph.text.replace("\n", ""), target)
                self.assertTrue(all(len(line) <= SCOPE_WRAP_CHARACTERS for line in paragraph.text.split("\n")))

    def test_a_value_with_no_separator_inside_the_limit_still_breaks(self) -> None:
        """Breaking runs back to the nearest special character; a value offering none is cut
        at the limit, because letting the line run widens the table."""
        # A special character inside the limit is preferred over cutting mid-token.
        self.assertEqual(
            _wrap_long_value("https://prod.example.test/accounts/123/details/extra", 36),
            ["https://prod.example.test/accounts/", "123/details/extra"],
        )
        self.assertEqual(_wrap_long_value("x" * 80, 36), ["x" * 36, "x" * 36, "x" * 8])
        for limit in (LOCATION_WRAP_CHARACTERS, SCOPE_WRAP_CHARACTERS):
            for value in (
                "https://internal-banking-portal-uat.northstar.example.test/accounts/settings/notifications/preferences/email",
                "com.northstar.mobile.banking.application.android.enterprise.edition.release.candidate",
                "https://prod.example.test/reports/export?format=invalid&scope=all&page=2&size=100&sort=desc",
                "x" * 200,
            ):
                with self.subTest(limit=limit, value=value):
                    lines = _wrap_long_value(value, limit)
                    self.assertGreater(len(lines), 1, "fixture must be long enough to wrap")
                    self.assertEqual("".join(lines), value, "wrapping must not lose characters")
                    self.assertTrue(all(len(line) <= limit for line in lines), f"{lines} exceeds {limit}")
                    for line in lines[:-1]:
                        self.assertTrue(
                            not line[-1].isalnum() or len(line) == limit,
                            f"{line!r} should end on a special character or fill the line",
                        )

    def test_a_query_string_breaks_on_its_own_separators(self) -> None:
        # Fixed limit: this pins where the algorithm breaks, not the shipped column widths.
        # Counting back from the 36th character lands on "=" rather than the earlier "?".
        self.assertEqual(
            _wrap_long_value("https://api.example.test/search?q=session+fixation&environment=production", 36),
            ["https://api.example.test/search?q=", "session+fixation&environment=", "production"],
        )

    def test_a_finding_without_a_number_leaves_the_id_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            (report_folder / "evidence").mkdir()
            buffer = BytesIO()
            Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
            (report_folder / "evidence" / "ev_blank.png").write_bytes(buffer.getvalue())
            now = datetime.now().astimezone()
            report = Report(
                report_id="r_blank", app_id="CI-DOCX", saved_at=now,
                engagement=Engagement(
                    app_name="Northstar Banking", ci_number="CI-DOCX", segment="JH", report_type="annual_pentest",
                    report_date=date(2026, 9, 9), tester="QA Tester", tested_environments=["production"], tested_channels=["web"],
                    test_windows={"production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))},
                ),
                scope_targets=[ScopeTarget(target_id="t_web", environment="production", channel="web", value="https://prod.example.test")],
                evidence={"ev_blank": EvidenceItem(file="evidence/ev_blank.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)},
            )
            image = lambda index: [ImageFragment(frag_id=f"f_img_{index}", type="image", environment="production", evidence_id="ev_blank", caption="Production response")]
            report.vulnerabilities = [
                self._finding("v_numbered", "Numbered finding", "high", "042", ["t_web"], image(1)),
                self._finding("v_unnumbered", "Unnumbered finding", "low", None, ["t_web"], image(2)),
            ]
            rendered = Document(BytesIO(render_report_docx(report, Path("resources/MAIN_TEST.docx"), report_folder)))

            summary = next(table for table in rendered.tables if table.cell(0, 0).text == "Findings")
            numbers = {row.cells[0].text: row.cells[4].text for row in summary.rows[1:]}
            self.assertEqual(numbers, {"Numbered finding": "042", "Unnumbered finding": ""})

            details = {
                table.cell(0, 1).text: table.cell(1, 1).text
                for table in rendered.tables
                if table.cell(0, 0).text == "Severity" and len(table.rows) >= 5
            }
            self.assertEqual(details.get("High"), "042")
            self.assertEqual(details.get("Low"), "", "an unnumbered finding must not fall back to its internal uid")

            everything = "\n".join([*(p.text for p in rendered.paragraphs), *(c.text for t in rendered.tables for r in t.rows for c in r.cells)])
            self.assertNotIn("v_unnumbered", everything)

    @staticmethod
    def _numbering_details(document, paragraph) -> tuple[str, str | None, int | None]:
        """The numId, nsid and level-0 startOverride behind one list paragraph."""
        numbering = document.part.numbering_part.element
        numbering_id = str(paragraph._p.pPr.numPr.numId.val)
        number = next(element for element in numbering.iterchildren(qn("w:num")) if element.get(qn("w:numId")) == numbering_id)
        abstract_id = number.find(qn("w:abstractNumId")).get(qn("w:val"))
        abstract = next(element for element in numbering.iterchildren(qn("w:abstractNum")) if element.get(qn("w:abstractNumId")) == abstract_id)
        nsid = abstract.find(qn("w:nsid"))
        override = next(
            (level.find(qn("w:startOverride")) for level in number.iterchildren(qn("w:lvlOverride")) if level.get(qn("w:ilvl")) == "0"),
            None,
        )
        return (
            numbering_id,
            nsid.get(qn("w:val")) if nsid is not None else None,
            int(override.get(qn("w:val"))) if override is not None else None,
        )

    def _numbered_sections(self, report_folder: Path, *, continue_second: bool):
        """A proof of concept holding two numbered lists either side of an image, plus one in the
        description, so a continued chain can be told apart from a section boundary."""
        contents = [
            Content(type="description", fragments=[
                ListFragment(frag_id="f_desc_list", type="numbered_list", items=[ListItem(runs=[Run(text="Description step")])]),
            ]),
            Content(type="recommended_remediation", fragments=[
                ParagraphFragment(frag_id="f_rem", type="paragraph", runs=[Run(text="Remediate it")]),
            ]),
            Content(type="proof_of_concept", fragments=[
                ListFragment(frag_id="f_poc_one", type="numbered_list", items=[
                    ListItem(runs=[Run(text="First step")]), ListItem(runs=[Run(text="Second step")]),
                ]),
                ImageFragment(frag_id="f_poc_img", type="image", environment="production", evidence_id="ev_layout", caption="Proof"),
                ListFragment(frag_id="f_poc_two", type="numbered_list", continue_numbering=continue_second, items=[
                    ListItem(runs=[Run(text="Third step")]), ListItem(runs=[Run(text="Fourth step")]),
                ]),
            ]),
        ]
        document = self._layout_document(report_folder, contents)
        listed = [paragraph for paragraph in document.paragraphs if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None]
        by_text = {paragraph.text: self._numbering_details(document, paragraph) for paragraph in listed}
        return by_text

    def test_a_continued_numbered_list_shares_one_numbering_with_the_list_above_it(self) -> None:
        """Word reads one numId as one list, so a chain shares it and writes a single startOverride.
        The chain shares its nsid too, which is why the control case below checks both."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            details = self._numbered_sections(Path(temporary_directory), continue_second=True)

            steps = [details[text] for text in ("First step", "Second step", "Third step", "Fourth step")]
            self.assertEqual(len({numbering_id for numbering_id, _, _ in steps}), 1, "a continued list did not join the list above it")
            self.assertEqual(len({nsid for _, nsid, _ in steps}), 1)
            # One numId means one w:num, so there is one startOverride behind all four paragraphs --
            # the count is restarted once, at the top of the chain, and never again inside it.
            self.assertEqual({override for _, _, override in steps}, {1}, "a continued list restarted the count")

            self.assertNotEqual(
                details["Description step"][0], steps[0][0],
                "description shares numbering with the proof of concept, so a chain could cross sections",
            )

    def test_two_numbered_lists_in_one_section_restart_independently_by_default(self) -> None:
        """New coverage, not a re-assertion: nothing else pins this. The component test that looks
        similar drives compose_docx_template, which render_report_docx never calls, and its two lists
        differ only because they sit at separate anchors. This is what stands between a future edit
        and silently renumbering every report on disk."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            details = self._numbered_sections(Path(temporary_directory), continue_second=False)

            first, second = details["First step"], details["Third step"]
            self.assertNotEqual(first[0], second[0], "two independent lists shared a numId")
            self.assertNotEqual(first[1], second[1], "two independent lists shared an nsid")
            self.assertEqual((first[2], second[2]), (1, 1), "each independent list needs its own restart")

    def test_an_instance_label_is_numbered_once_even_when_the_tester_typed_it(self) -> None:
        """Three of the instance titles already saved carry the label in their text, from before the
        generator wrote it. Rendering both would read 'Instance 1: Instance 1: Production'."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            document = self._layout_document(report_folder, [
                Content(type="proof_of_concept", fragments=[
                    InstanceTitleFragment(frag_id="f_typed", type="instance_title", text="Instance 7: Production"),
                    InstanceTitleFragment(frag_id="f_plain", type="instance_title", text="Non-Production"),
                ]),
            ])
            text_of = lambda element: "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()
            titles = [
                text_of(item) for item in document.element.body.iterchildren()
                if item.tag == qn("w:p") and "Production" in text_of(item)
            ]
            # The tester's own number goes too: the position in the section is the truth, not the typing.
            self.assertEqual(titles, ["Instance 1: Production", "Instance 2: Non-Production"])

    def _layout_document(self, report_folder: Path, contents: list, *, status: str = "open_new"):
        """Render one finding through the shipped template, for page-layout assertions."""
        evidence_folder = report_folder / "evidence"
        evidence_folder.mkdir(exist_ok=True)
        buffer = BytesIO()
        Image.new("RGB", (40, 20), "white").save(buffer, format="PNG")
        (evidence_folder / "ev_layout.png").write_bytes(buffer.getvalue())
        now = datetime.now().astimezone()
        report = Report(
            report_id="r_layout", app_id="CI-DOCX", saved_at=now,
            engagement=Engagement(
                app_name="Northstar Banking", ci_number="CI-DOCX", segment="JH", report_type="annual_pentest",
                report_date=date(2026, 9, 9), tester="QA Tester", tested_environments=["production"], tested_channels=["web"],
                test_windows={"production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))},
            ),
            scope_targets=[ScopeTarget(target_id="t_web", environment="production", channel="web", value="https://prod.example.test")],
            evidence={"ev_layout": EvidenceItem(file="evidence/ev_layout.png", width_px=40, height_px=20, sha256="0" * 64, uploaded_at=now)},
        )
        report.vulnerabilities = [Vulnerability(
            uid="v_layout", display_id="001", title="Layout finding",
            likelihood="high", impact="high", severity="high", status=status,
            scope=Scope(mode="custom", target_ids=["t_web"]), contents=contents,
        )]
        return Document(BytesIO(render_report_docx(report, Path("resources/MAIN_TEST.docx"), report_folder, allow_incomplete=True)))

    @staticmethod
    def _table(suffix: str) -> TableFragment:
        return TableFragment(
            frag_id=f"f_table_{suffix}", type="table",
            header=[ListItem(runs=[Run(text="Header")])],
            rows=[[ListItem(runs=[Run(text=f"Row {suffix}")])]],
        )

    def test_a_table_is_followed_by_one_spacer_so_two_tables_never_merge(self) -> None:
        """A table fragment contributes only its w:tbl, and Word silently merges adjacent tables."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            document = self._layout_document(report_folder, [
                Content(type="description", fragments=[self._table("a"), self._table("b")]),
                Content(type="recommended_remediation", fragments=[ParagraphFragment(frag_id="f_fix", type="paragraph", runs=[Run(text="Apply the fix.")])]),
                Content(type="proof_of_concept", fragments=[
                    ListFragment(frag_id="f_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request.")])]),
                    ImageFragment(frag_id="f_img", type="image", environment="production", evidence_id="ev_layout", caption="Production response"),
                ]),
            ])
            body = list(document.element.body.iterchildren())
            for left, right in zip(body, body[1:]):
                self.assertFalse(left.tag == qn("w:tbl") and right.tag == qn("w:tbl"), "adjacent tables merge into one in Word")

            first = next(index for index, element in enumerate(body) if element.tag == qn("w:tbl") and "Row a" in "".join(node.text or "" for node in element.iter(qn("w:t"))))
            spacer = body[first + 1]
            self.assertTrue(_is_blank_paragraph(spacer), "a mid-section table needs a spacer below it")
            self.assertEqual(body[first + 2].tag, qn("w:tbl"), "exactly one spacer, not two")
            properties = spacer.find(qn("w:pPr"))
            # An empty paragraph carrying either of these is read back as a fragment by docx_import.
            self.assertIsNone(properties.find(qn("w:numPr")), "a numbered spacer imports as a phantom list")
            self.assertIsNone(properties.find(qn("w:pStyle")), "a caption-styled spacer erases the previous image caption")

            last_table = body[first + 2]
            blanks = 0
            following = last_table.getnext()
            while following is not None and _is_blank_paragraph(following):
                blanks += 1
                following = following.getnext()
            self.assertEqual(blanks, 1, "a table ending a section keeps only the template blank; its spacer is trimmed")

    def test_section_headings_are_kept_on_the_page_with_the_content_below_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            paragraph = lambda name: [ParagraphFragment(frag_id=f"f_{name}", type="paragraph", runs=[Run(text=f"The {name} text.")])]
            document = self._layout_document(report_folder, [
                Content(type="description", fragments=paragraph("description")),
                Content(type="recommended_remediation", fragments=paragraph("remediation")),
                Content(type="previous_proof_of_concept", fragments=[ListFragment(frag_id="f_prev", type="numbered_list", items=[ListItem(runs=[Run(text="Reproduce it.")])])]),
                Content(type="proof_of_concept", fragments=[
                    ListFragment(frag_id="f_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request.")])]),
                    ImageFragment(frag_id="f_img", type="image", environment="production", evidence_id="ev_layout", caption="Production response"),
                ]),
                Content(type="in_conclusion", fragments=paragraph("conclusion")),
            ], status="open_previously_discovered")

            for title in ("Description:", "Recommended Remediation:", "Previous Proof of Concept:", "Proof of Concept:", "In Conclusion:", "The following demonstrates the vulnerability:"):
                heading = next(item for item in document.paragraphs if item.text.strip() == title)
                self.assertTrue(_keeps_next(heading._p), f"{title!r} must be kept with its content")
                previous = heading._p.getprevious()
                if previous is not None and _is_blank_paragraph(previous):
                    self.assertFalse(_keeps_next(previous), f"the walk above {title!r} must stop at the blank")

            # Filled by token replacement rather than an anchor, so the walk cannot reach it. Pinned
            # so the gap stays visible instead of being mistaken for coverage.
            ticket = next(item for item in document.paragraphs if item.text.strip() == "Severity Review Ticket (if applicable):")
            self.assertFalse(_keeps_next(ticket._p))
            title = next(item for item in document.paragraphs if item.text.strip() == "Layout finding")
            self.assertFalse(_keeps_next(title._p), "a finding title already carries its own page break")

    def test_labels_titles_and_lead_ins_are_kept_with_what_they_introduce(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            document = self._layout_document(report_folder, [
                Content(type="description", fragments=[
                    ParagraphFragment(frag_id="f_lead", type="paragraph", runs=[Run(text="Use these values:")]),
                    self._table("a"),
                    CodeFragment(frag_id="f_code", type="code_block", caption="Request", text="GET /accounts/123"),
                    CodeFragment(frag_id="f_bare", type="code_block", caption=None, text="GET /health"),
                ]),
                Content(type="recommended_remediation", fragments=[ParagraphFragment(frag_id="f_fix", type="paragraph", runs=[Run(text="Apply the fix.")])]),
                Content(type="proof_of_concept", fragments=[
                    ListFragment(frag_id="f_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request.")])]),
                    InstanceTitleFragment(frag_id="f_instance", type="instance_title", text="Instance 1: Production"),
                    ImageFragment(frag_id="f_img", type="image", environment="production", evidence_id="ev_layout", caption="Production response"),
                ]),
            ])
            body = list(document.element.body.iterchildren())
            text_of = lambda element: "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()

            for label in ("PROD:", "Instance 1: Production", "Request"):
                element = next(item for item in body if item.tag == qn("w:p") and text_of(item) == label)
                self.assertTrue(_keeps_next(element), f"{label!r} must be kept with what follows it")

            lead_in = next(item for item in body if item.tag == qn("w:p") and text_of(item) == "Use these values:")
            self.assertTrue(_keeps_next(lead_in), "a table lead-in must not be stranded above its table")
            self.assertTrue(_keeps_next(lead_in.getnext()), "the blank between a lead-in and its table must not break the chain")

            # Located from the caption, because the template's own cover art is the first drawing.
            caption = next(item for item in body if item.tag == qn("w:p") and text_of(item).endswith("Production response"))
            image = caption.getprevious()
            self.assertTrue(image.xpath(".//w:drawing"), "the caption must sit directly below its image")
            self.assertTrue(_keeps_next(image), "an image must stay with its caption")
            self.assertFalse(_keeps_next(caption), "a caption ends a chain and must not start another")

            bare_code = next(item for item in body if item.tag == qn("w:p") and text_of(item) == "GET /health")
            self.assertFalse(_keeps_next(bare_code.getprevious()), "an uncaptioned code block has no heading to keep")

    def _assert_image_fragment_format(self, document) -> None:
        for index in range(len(document.inline_shapes)):
            shape = document.inline_shapes[index]
            line = shape._inline.graphic.graphicData.pic.spPr.find(qn("a:ln"))
            self.assertIsNone(line)
            relationship_id = shape._inline.graphic.graphicData.pic.blipFill.blip.get(qn("r:embed"))
            image = Image.open(BytesIO(document.part.related_parts[relationship_id].blob)).convert("RGB")
            width, height = image.size
            self.assertTrue(all(image.getpixel((x, 0)) == (0, 0, 0) for x in range(width)))
            self.assertTrue(all(image.getpixel((x, height - 1)) == (0, 0, 0) for x in range(width)))
            self.assertTrue(all(image.getpixel((0, y)) == (0, 0, 0) for y in range(height)))
            self.assertTrue(all(image.getpixel((width - 1, y)) == (0, 0, 0) for y in range(height)))
            paragraph = next(shape._inline.iterancestors(qn("w:p")))
            alignment = paragraph.find(qn("w:pPr") + "/" + qn("w:jc"))
            self.assertIsNotNone(alignment)
            self.assertEqual(alignment.get(qn("w:val")), "center")

    @staticmethod
    def _finding(
        uid: str,
        title: str,
        severity: str,
        display_id: str,
        target_ids: list[str],
        images: list[ImageFragment],
        *,
        likelihood: str = "high",
        impact: str = "high",
    ) -> Vulnerability:
        return Vulnerability(
            uid=uid,
            display_id=display_id,
            title=title,
            likelihood=likelihood,
            impact=impact,
            severity=severity,
            status="open_new",
            scope=Scope(mode="custom", target_ids=target_ids),
            contents=[
                Content(type="description", fragments=[ParagraphFragment(frag_id=f"{uid}_description", type="paragraph", runs=[Run(text="A complete "), Run(text="description.", bold=True)]), NoteFragment(frag_id=f"{uid}_note", type="note", runs=[Run(text="Validate the result independently.")])]),
                Content(type="recommended_remediation", fragments=[ListFragment(frag_id=f"{uid}_remediation", type="bulleted_list", items=[ListItem(runs=[Run(text="Apply authorization controls.")])])]),
                Content(type="proof_of_concept", fragments=[ListFragment(frag_id=f"{uid}_steps", type="numbered_list", items=[ListItem(runs=[Run(text="Send the request.")]), ListItem(runs=[Run(text="Observe the response.")])]), CodeFragment(frag_id=f"{uid}_code", type="code_block", caption="Request", text="GET /accounts/123"), TableFragment(frag_id=f"{uid}_table", type="table", caption="Generated table", header=[ListItem(runs=[Run(text="Generated Header")]), ListItem(runs=[Run(text="Result")])], rows=[[ListItem(runs=[Run(text="Request")]), ListItem(runs=[Run(text="Allowed")])]]), *images]),
            ],
        )


if __name__ == "__main__":
    unittest.main()