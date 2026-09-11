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

from app.docx_report import render_report_docx
from app.report_service import provision
from app.models import CodeFragment, Content, Engagement, EvidenceItem, ImageFragment, ListFragment, ListItem, NoteFragment, ParagraphFragment, Report, Run, Scope, ScopeTarget, TableFragment, TestAccount, TestWindow, Vulnerability


class DocxReportTests(unittest.TestCase):
    def test_renders_template_with_repeated_findings_and_no_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_folder = Path(temporary_directory)
            evidence_folder = report_folder / "evidence"
            evidence_folder.mkdir()
            evidence = BytesIO()
            Image.new("RGB", (40, 20), "white").save(evidence, format="PNG")
            for evidence_id in ("ev_prod", "ev_prod_extra", "ev_uat", "ev_prod_second"):
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
                    test_type="web_api",
                    test_windows={
                        "production": TestWindow(start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), test_time="22:00 EST"),
                        "non_production": TestWindow(start_date=date(2026, 7, 28), end_date=date(2026, 7, 30), test_time="Any time"),
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
                    for evidence_id in ("ev_prod", "ev_prod_extra", "ev_uat", "ev_prod_second")
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
            previous = next(content for content in report.vulnerabilities[1].contents if content.type == "previous_proof_of_concept")
            next(fragment for fragment in previous.fragments if isinstance(fragment, ListFragment)).items = [
                ListItem(runs=[Run(text="Reproduce the previously reported behavior.")]),
                ListItem(runs=[Run(text="Record the original vulnerable response.")]),
            ]

            template = Path(__file__).resolve().parent.parent / "resources" / "fixtures" / "report-name.docx"
            generated = render_report_docx(report, template, report_folder)
            rendered = Document(BytesIO(generated))
            text = "\n".join([*(paragraph.text for paragraph in rendered.paragraphs), *(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)])
            self.assertNotIn("{{", text)
            self.assertNotIn("-fragments-here", text.casefold())
            self.assertEqual(text.count("Authorization bypass"), 2)
            self.assertEqual(text.count("Session fixation"), 3)
            self.assertNotIn("CRITICAL FINDINGS", text)
            self.assertIn("HIGH FINDINGS", text)
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
            self.assertEqual(len(rendered.inline_shapes), 4)
            self._assert_image_fragment_format(rendered)
            paragraph_texts = [paragraph.text for paragraph in rendered.paragraphs]
            self.assertEqual(paragraph_texts.count("PROD:"), 2)
            self.assertEqual(paragraph_texts.count("NON-PROD:"), 1)
            code_paragraph = next(paragraph for paragraph in rendered.paragraphs if paragraph.text == "GET /accounts/123")
            self.assertIsNone(code_paragraph._p.pPr.numPr)
            with ZipFile(BytesIO(generated)) as archive:
                self.assertIn("word/document.xml", archive.namelist())

            component_generated = render_report_docx(report, Path("resources/MAIN_TEST.docx"), report_folder)
            component_document = Document(BytesIO(component_generated))
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
            self.assertEqual(len(component_document.inline_shapes), 4)
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
                    "Production Environment:\n• https://prod.example.test\n• https://prod-api.example.test",
                )
                self.assertEqual(len(production_location._tc.findall(".//" + qn("w:br"))), 1)
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
            self.assertEqual(image_caption.text, "Figure 2 Production response")
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