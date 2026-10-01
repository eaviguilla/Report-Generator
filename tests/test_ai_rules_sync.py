"""The Claude rules in .claude/rules/ are generated from the Copilot instructions, so the two cannot drift."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import sync_ai_rules

SOURCE = '''---
description: "A sample."
applyTo: "app/a.py, tests/**"
---

# Sample

- One rule.
'''


def make_repo(root: Path) -> Path:
    folder = root / ".github" / "instructions"
    folder.mkdir(parents=True)
    path = folder / "sample.instructions.md"
    path.write_text(SOURCE, encoding="utf-8")
    return path


class AiRulesSyncTests(unittest.TestCase):
    def test_the_claude_rules_match_the_copilot_instructions(self) -> None:
        self.assertEqual(sync_ai_rules.drift(), [], "run: py -3 scripts/sync_ai_rules.py")

    def test_the_comparison_has_something_to_compare(self) -> None:
        wanted = sync_ai_rules.expected()
        self.assertGreaterEqual(len(wanted), 4, "a floor: an empty folder would make the check above pass")
        for path in wanted:
            self.assertTrue((sync_ai_rules.ROOT / path).is_file(), path.as_posix())

    def test_apply_to_becomes_paths_and_the_body_is_copied_unchanged(self) -> None:
        rendered = sync_ai_rules.render("sample.instructions.md", SOURCE)
        start = '---\npaths:\n  - "app/a.py"\n  - "tests/**"\n---\n<!-- Generated from .github/instructions/sample.instructions.md.'
        self.assertTrue(rendered.startswith(start), rendered)
        self.assertTrue(rendered.endswith("\n\n# Sample\n\n- One rule.\n"), rendered)
        self.assertNotIn("applyTo", rendered)

    def test_a_missing_edited_or_orphaned_copy_is_reported_and_rewritten(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            source = make_repo(root)
            self.assertEqual(sync_ai_rules.drift(root), ["missing .claude/rules/sample.md"])
            self.assertEqual(sync_ai_rules.write(root), [".claude/rules/sample.md"])
            self.assertEqual(sync_ai_rules.drift(root), [])
            copy = root / ".claude" / "rules" / "sample.md"
            copy.write_text(copy.read_text(encoding="utf-8") + "- a hand edit\n", encoding="utf-8")
            self.assertEqual(sync_ai_rules.drift(root), ["out of date .claude/rules/sample.md"])
            sync_ai_rules.write(root)
            self.assertEqual(sync_ai_rules.drift(root), [])
            source.unlink()
            self.assertEqual(sync_ai_rules.drift(root), ["orphaned .claude/rules/sample.md, its instruction file is gone"])
            sync_ai_rules.write(root)
            self.assertFalse(copy.exists())

    def test_a_hand_written_rule_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            make_repo(root)
            sync_ai_rules.write(root)
            mine = root / ".claude" / "rules" / "mine.md"
            mine.write_text('---\npaths:\n  - "x"\n---\n- a Claude-only rule\n', encoding="utf-8")
            self.assertEqual(sync_ai_rules.drift(root), [])
            sync_ai_rules.write(root)
            self.assertTrue(mine.exists())

    def test_an_instruction_file_without_apply_to_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "sample.instructions.md needs frontmatter with an applyTo list"):
            sync_ai_rules.render("sample.instructions.md", '---\ndescription: "x"\n---\n\n# Body\n')
        with self.assertRaisesRegex(ValueError, "needs frontmatter"):
            sync_ai_rules.render("sample.instructions.md", "# No frontmatter\n")


if __name__ == "__main__":
    unittest.main()
