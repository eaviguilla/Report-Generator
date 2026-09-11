from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.html_to_fragments import build, html_to_fragments


class HtmlToFragmentsTests(unittest.TestCase):
    def test_preserves_inline_formatting_and_recognizes_notes(self) -> None:
        fragments, warnings = html_to_fragments(
            "<p>Plain <strong>bold</strong> and <u>underlined</u>.</p>"
            "<p><b><i>Note:</i></b> replace the placeholder.</p>",
            "f_",
        )

        self.assertEqual(warnings, [])
        self.assertEqual([fragment["type"] for fragment in fragments], ["paragraph", "note"])
        self.assertTrue(any(run.get("bold") for run in fragments[0]["runs"]))
        self.assertTrue(any(run.get("underline") for run in fragments[0]["runs"]))
        self.assertEqual("".join(run["text"] for run in fragments[1]["runs"]), "replace the placeholder.")

    def test_recovers_unclosed_lists_and_missing_table_rows(self) -> None:
        list_fragments, list_warnings = html_to_fragments("<ul><li>One<li>Two", "l_")
        table_fragments, table_warnings = html_to_fragments("<table><td>A</td><td>B</td></table>", "t_")

        self.assertEqual(list_fragments[0]["type"], "bulleted_list")
        self.assertEqual(len(list_fragments[0]["items"]), 2)
        self.assertTrue(any("unclosed" in warning for warning in list_warnings))
        self.assertEqual(table_fragments[0]["type"], "table")
        self.assertEqual(len(table_fragments[0]["rows"][0]), 2)
        self.assertTrue(any("missing <tr>" in warning for warning in table_warnings))

    def test_build_marks_placeholders_and_maps_severity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.json"
            output = root / "library.json"
            source.write_text(json.dumps({"findings": [{
                "id": 7,
                "vulnerability_name": "SQL Injection",
                "description": "<p>(insert version here)</p>",
                "remediation": "<p>Use parameters.</p>",
                "severity": "Moderate",
                "likelihood": "High",
                "impact": "Low",
            }]}), encoding="utf-8")

            result = build(source, output)
            entry = result["lib"]["entries"][0]
            self.assertEqual(entry["default_severity"], "medium")
            self.assertTrue(entry["requires_tester_input"])
            self.assertIn("injection", entry["tags"])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["entry_count"], 1)


if __name__ == "__main__":
    unittest.main()