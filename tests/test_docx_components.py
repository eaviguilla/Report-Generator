from __future__ import annotations

import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from lxml import etree

from app.docx_components import DocxComponent, compose_docx_components, compose_docx_template


ROOT = Path(__file__).resolve().parent.parent


class DocxComponentTests(unittest.TestCase):
    RATING_FONT_COLORS = {
        "Critical": RGBColor(192, 0, 0),
        "High": RGBColor(237, 125, 49),
        "Medium": RGBColor(255, 192, 0),
        "Low": RGBColor(112, 173, 71),
        "Informational": RGBColor(81, 81, 81),
    }

    def test_inserts_three_severity_components_with_page_breaks(self) -> None:
        generated = compose_docx_components(
            ROOT / "resources" / "MAIN.docx",
            [
                DocxComponent(ROOT / "resources" / "severity_titles" / "critical_severity.docx", {"finding_title": "Critical SQL Injection"}),
                DocxComponent(ROOT / "resources" / "severity_titles" / "high_severity.docx", {"finding_title": "High Authorization Bypass"}),
                DocxComponent(ROOT / "resources" / "severity_titles" / "medium_severity.docx", {"finding_title": "Medium Concurrent Session Allowed"}),
            ],
        )
        document = Document(BytesIO(generated))
        expected = [
            ("Critical Findings", "Critical SQL Injection"),
            ("High Findings", "High Authorization Bypass"),
            ("Medium Findings", "Medium Concurrent Session Allowed"),
        ]
        texts = [paragraph.text for paragraph in document.paragraphs]
        self.assertNotIn("{{findings}}", texts)
        self.assertNotIn("{{finding_title}}", texts)
        positions = []
        for heading, title in expected:
            heading_paragraph = next(paragraph for paragraph in document.paragraphs if paragraph.text == heading)
            title_paragraph = next(paragraph for paragraph in document.paragraphs if paragraph.text == title)
            self.assertEqual(heading_paragraph.style.name, "Report Heading 1")
            self.assertTrue(heading_paragraph._p.pPr.pageBreakBefore is not None)
            positions.extend([texts.index(heading), texts.index(title)])
        self.assertEqual(positions, sorted(positions))

    def test_composes_retest_finding_from_formatted_fragment_templates(self) -> None:
        fragments = ROOT / "resources" / "fragments"
        generated = compose_docx_template(
            ROOT / "resources" / "finding_types" / "retest_finding.docx",
            values={
                "finding_title": "Authorization Bypass Retest",
                "vuln_severity": "High",
                "vuln_id": "VULN-001",
                "status": "Open (Previously Discovered)",
                "prod_affected_locations": "https://production.example.test",
                "non-prod-affected-locations": "https://uat.example.test",
                "severity-review-tickets": "N/A",
            },
            components={
                "description-fragments-here": [
                    DocxComponent(fragments / "paragraph_fragment.docx", {"paragraph-fragment": "Authorization checks can be bypassed."}),
                    DocxComponent(fragments / "note_fragment.docx", {"note-fragment": "Retest both affected environments."}),
                ],
                "recommended-remediation-fragments-here": [
                    DocxComponent(fragments / "bulleted_fragment.docx", {"bullet-list-fragment": "Enforce authorization on the server."}),
                    DocxComponent(fragments / "bulleted_fragment.docx", {"bullet-list-fragment": "Add regression coverage."}),
                ],
                "prev-poc-fragments-here": [
                    DocxComponent(fragments / "title_fragment.docx", {"instance-fragment": "Instance 1: Production"}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Sign in as a standard user."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Request another user's record."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Change the record identifier."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Submit the modified request."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Confirm the unauthorized response data."}),
                ],
                "poc-fragments-here": [
                    DocxComponent(fragments / "title_fragment.docx", {"instance-fragment": "Instance 1: Production"}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Repeat the original request."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Observe that access is still allowed."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Apply the proposed authorization control."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Resend the unauthorized request."}),
                    DocxComponent(fragments / "numbered_fragment.docx", {"numbered-list-fragment": "Confirm that the request is rejected."}),
                ],
                "conclusion-fragments-here": [
                    DocxComponent(fragments / "paragraph_fragment.docx", {"paragraph-fragment": "The finding remains reproducible."}),
                ],
            },
        )

        document = Document(BytesIO(generated))
        all_text = "\n".join(
            [
                *(paragraph.text for paragraph in document.paragraphs),
                *(cell.text for table in document.tables for row in table.rows for cell in row.cells),
            ]
        )
        self.assertNotIn("{{", all_text)

        finding_template = Document(ROOT / "resources" / "finding_types" / "retest_finding.docx")
        self.assertEqual(
            self._formatting(finding_template.paragraphs[0]),
            self._formatting(next(paragraph for paragraph in document.paragraphs if paragraph.text == "Authorization Bypass Retest")),
        )
        self.assertEqual(
            self._formatting(finding_template.paragraphs[3]),
            self._formatting(next(paragraph for paragraph in document.paragraphs if paragraph.text == "Description:")),
        )

        previous_numbered_texts = (
            "Sign in as a standard user.",
            "Request another user's record.",
            "Change the record identifier.",
            "Submit the modified request.",
            "Confirm the unauthorized response data.",
        )
        current_numbered_texts = (
            "Repeat the original request.",
            "Observe that access is still allowed.",
            "Apply the proposed authorization control.",
            "Resend the unauthorized request.",
            "Confirm that the request is rejected.",
        )
        numbering_groups = [
            [
                self._numbering_details(
                    document,
                    next(paragraph for paragraph in document.paragraphs if paragraph.text == text),
                )
                for text in texts
            ]
            for texts in (previous_numbered_texts, current_numbered_texts)
        ]
        for details in numbering_groups:
            self.assertEqual(len(details), 5)
            self.assertEqual(len({item[0] for item in details}), 1)
            self.assertEqual(len({item[1] for item in details}), 1)
            self.assertTrue(all(item[2] == 1 for item in details))
        self.assertNotEqual(numbering_groups[0][0][0], numbering_groups[1][0][0])
        self.assertNotEqual(numbering_groups[0][0][1], numbering_groups[1][0][1])

        expected_fragments = {
            "paragraph_fragment.docx": "Authorization checks can be bypassed.",
            "note_fragment.docx": "Note: Retest both affected environments.",
            "title_fragment.docx": "Instance 1: Production",
            "numbered_fragment.docx": "Sign in as a standard user.",
            "bulleted_fragment.docx": "Enforce authorization on the server.",
        }
        for filename, rendered_text in expected_fragments.items():
            source_document = Document(fragments / filename)
            rendered_paragraph = next(paragraph for paragraph in document.paragraphs if paragraph.text == rendered_text)
            self.assertEqual(self._formatting(source_document.paragraphs[0]), self._formatting(rendered_paragraph))
            if filename in {"numbered_fragment.docx", "bulleted_fragment.docx"}:
                self.assertEqual(
                    self._numbering_format(source_document, source_document.paragraphs[0]),
                    self._numbering_format(document, rendered_paragraph),
                )

    def test_preserves_tag_styles_and_changes_only_rating_colors(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            template = Path(temporary_directory) / "styled-tags.docx"
            document = Document()
            tags = (
                ("ordinary-tag", "Ordinary value", RGBColor(12, 34, 56)),
                ("likelihood-rating", "Critical", self.RATING_FONT_COLORS["Critical"]),
                ("impact-rating", "Low", self.RATING_FONT_COLORS["Low"]),
                ("severity-rating", "High", self.RATING_FONT_COLORS["High"]),
            )
            for token, _, _ in tags:
                paragraph = document.add_paragraph(style="Quote")
                run = paragraph.add_run(f"{{{{{token}}}}}")
                run.bold = True
                run.italic = True
                run.underline = True
                run.font.name = "Courier New"
                run.font.size = Pt(13)
                run.font.small_caps = True
                run.font.color.rgb = RGBColor(12, 34, 56)
            paragraph_properties = [paragraph._p.pPr.xml for paragraph in document.paragraphs]
            run_properties = [self._run_properties_without_color(paragraph.runs[0]) for paragraph in document.paragraphs]
            document.save(template)

            generated = compose_docx_template(
                template,
                values={token: value for token, value, _ in tags},
                components={},
            )
            rendered = Document(BytesIO(generated))
            for index, (_, value, expected_color) in enumerate(tags):
                with self.subTest(value=value):
                    paragraph = rendered.paragraphs[index]
                    run = paragraph.runs[0]
                    self.assertEqual(paragraph.text, value)
                    self.assertEqual(paragraph._p.pPr.xml, paragraph_properties[index])
                    self.assertEqual(self._run_properties_without_color(run), run_properties[index])
                    self.assertEqual(run.font.color.rgb, expected_color)

    def test_applies_all_rating_font_colors(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            template = Path(temporary_directory) / "rating.docx"
            document = Document()
            document.add_paragraph("{{rating}}")
            document.save(template)
            for rating, expected_color in self.RATING_FONT_COLORS.items():
                with self.subTest(rating=rating):
                    generated = compose_docx_template(template, values={"rating": rating}, components={})
                    rendered = Document(BytesIO(generated))
                    self.assertEqual(rendered.paragraphs[0].runs[0].font.color.rgb, expected_color)

    @staticmethod
    def _formatting(paragraph) -> tuple[str | None, tuple[str | None, ...]]:
        properties = deepcopy(paragraph._p.pPr)
        if properties is not None:
            for numbering_id in properties.iter(qn("w:numId")):
                numbering_id.set(qn("w:val"), "0")
        return (
            properties.xml if properties is not None else None,
            tuple(run._r.rPr.xml if run._r.rPr is not None else None for run in paragraph.runs),
        )

    @staticmethod
    def _run_properties_without_color(run) -> str | None:
        properties = deepcopy(run._r.rPr)
        if properties is None:
            return None
        color = properties.find(qn("w:color"))
        if color is not None:
            properties.remove(color)
        return etree.tostring(properties, method="c14n", exclusive=True).decode()

    @staticmethod
    def _numbering_format(document, paragraph) -> tuple[str, str]:
        numbering = document.part.numbering_part.element
        numbering_id = str(paragraph._p.pPr.numPr.numId.val)
        number = next(element for element in numbering.iterchildren(qn("w:num")) if element.get(qn("w:numId")) == numbering_id)
        abstract_id = number.find(qn("w:abstractNumId")).get(qn("w:val"))
        abstract = next(element for element in numbering.iterchildren(qn("w:abstractNum")) if element.get(qn("w:abstractNumId")) == abstract_id)
        number = deepcopy(number)
        abstract = deepcopy(abstract)
        number.set(qn("w:numId"), "0")
        number.find(qn("w:abstractNumId")).set(qn("w:val"), "0")
        for override in list(number.iterchildren(qn("w:lvlOverride"))):
            start_override = override.find(qn("w:startOverride"))
            if start_override is not None:
                override.remove(start_override)
            if not len(override):
                number.remove(override)
        abstract.set(qn("w:abstractNumId"), "0")
        identity = abstract.find(qn("w:nsid"))
        if identity is not None:
            identity.set(qn("w:val"), "00000000")
        return (
            etree.tostring(number, method="c14n", exclusive=True).decode(),
            etree.tostring(abstract, method="c14n", exclusive=True).decode(),
        )

    @staticmethod
    def _numbering_details(document, paragraph) -> tuple[str, str | None, int | None]:
        numbering = document.part.numbering_part.element
        numbering_id = str(paragraph._p.pPr.numPr.numId.val)
        number = next(element for element in numbering.iterchildren(qn("w:num")) if element.get(qn("w:numId")) == numbering_id)
        abstract_id = number.find(qn("w:abstractNumId")).get(qn("w:val"))
        abstract = next(element for element in numbering.iterchildren(qn("w:abstractNum")) if element.get(qn("w:abstractNumId")) == abstract_id)
        nsid = abstract.find(qn("w:nsid"))
        override = next(
            (
                level.find(qn("w:startOverride"))
                for level in number.iterchildren(qn("w:lvlOverride"))
                if level.get(qn("w:ilvl")) == "0"
            ),
            None,
        )
        return (
            numbering_id,
            nsid.get(qn("w:val")) if nsid is not None else None,
            int(override.get(qn("w:val"))) if override is not None else None,
        )


if __name__ == "__main__":
    unittest.main()