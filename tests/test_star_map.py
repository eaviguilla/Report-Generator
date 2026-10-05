from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
_PATH = Path(__file__).resolve().parent.parent / "tools" / "star_map" / "star_map.py"
_SPEC = importlib.util.spec_from_file_location("star_map", _PATH)
star_map = importlib.util.module_from_spec(_SPEC)
sys.modules["star_map"] = star_map
_SPEC.loader.exec_module(star_map)


class StarMapTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def items(self, existing: set[str] | None = None) -> dict[str, dict]:
        return {i["path"]: i for i in star_map.build(self.repo, existing or set())["items"]}

    def test_status_words_become_the_official_statuses(self) -> None:
        cases = [
            ("shipped · 2026-10-02 · `af37291`", None, False, "done"),
            ("in progress · 2026-10-02 · built and tested on macOS", None, False, "in-progress"),
            ("planning", None, False, "needs-info"),
            ("agreed", None, False, "ready-for-agent"),
            ("superseded", None, False, "wontfix"),
            ("abandoned", None, False, "wontfix"),
            ("open", "grilling", False, "ready-for-human"),
            ("open", "research", False, "ready-for-agent"),
            ("claimed", "prototype", False, "in-progress"),
            ("resolved", "grilling", False, "done"),
            ("resolved", "grilling", True, "wontfix"),
            ("needs-triage", None, False, "needs-triage"),
            ("ready-for-agent", None, False, "ready-for-agent"),
        ]
        for raw, ticket_type, merged, expected in cases:
            with self.subTest(raw=raw, ticket_type=ticket_type, merged=merged):
                status, warning = star_map.official_status(star_map.status_word(raw), ticket_type, merged)
                self.assertEqual(status, expected)
                self.assertIsNone(warning)

    def test_an_unknown_or_missing_status_shows_as_needs_triage_with_a_warning(self) -> None:
        for word, fragment in (("someday", '"someday"'), (None, "no Status: line")):
            with self.subTest(word=word):
                status, warning = star_map.official_status(word, None, False)
                self.assertEqual(status, "needs-triage")
                self.assertIn(fragment, warning)

    def test_link_lines_are_read_in_plain_bold_and_blockquote_forms(self) -> None:
        self.write("docs/plans/feature.md", "# Feature\n\n> **Status:** in progress\n")
        forms = {
            "docs/adr/0001-plain.md": "---\nstatus: accepted\n---\n\n# Plain\n\nFrom: [Feature](../plans/feature.md)\n\nBody.\n",
            "docs/adr/0002-bold.md": "# Bold\n\n**From:** [Feature](../plans/feature.md)\n",
            "docs/plans/quoted.md": "# Quoted\n\n> **Status:** agreed\n>\n> **From:** [Feature](feature.md)\n",
        }
        for rel, text in forms.items():
            self.write(rel, text)
        items = self.items()
        for rel in forms:
            with self.subTest(rel=rel):
                self.assertEqual(items[rel]["from"], ["docs/plans/feature.md"])
                self.assertEqual(items[rel]["context"][0]["why"], "It came from this, by a From: line.")

    def test_an_out_of_scope_file_shows_only_while_an_open_item_came_from_it(self) -> None:
        self.write(".out-of-scope/idea.md", "# Turned-down idea\n\nThe reasons it was rejected.\n")
        path = ".out-of-scope/idea.md"
        self.write(".scratch/feature/issues/01-request.md", "# Request\n\nStatus: ready-for-agent\n")
        self.assertNotIn(path, self.items())
        self.write(
            ".scratch/feature/issues/01-request.md",
            "# Request\n\nStatus: ready-for-agent\n\nFrom: [Earlier idea](../../../.out-of-scope/idea.md)\n",
        )
        self.assertIn(path, self.items())

        for status in ("done", "wontfix"):
            with self.subTest(status=status):
                self.write(
                    ".scratch/feature/issues/01-request.md",
                    f"# Request\n\nStatus: {status}\n\nFrom: [Earlier idea](../../../.out-of-scope/idea.md)\n",
                )
                items = self.items()
                self.assertNotIn(path, items)
                self.assertFalse(items[".scratch/feature/issues/01-request.md"]["context"][0]["shown"])
                self.assertEqual(items[".scratch/feature/issues/01-request.md"]["context"][0]["why"], "This idea was turned down before.")

    def test_an_out_of_scope_file_cannot_be_a_blocker(self) -> None:
        self.write(".out-of-scope/idea.md", "# Turned-down idea\n")
        self.write(
            ".scratch/feature/issues/01-request.md",
            "# Request\n\nStatus: ready-for-agent\n\nBlocked by: [Earlier idea](../../../.out-of-scope/idea.md)\n",
        )
        item = self.items()[".scratch/feature/issues/01-request.md"]
        self.assertEqual(item["blockedBy"], [])
        self.assertEqual(item["warnings"], ["Blocked by: names .out-of-scope/idea.md, which is not a work item or decision record."])

    def test_an_out_of_scope_from_link_is_context_without_a_warning(self) -> None:
        self.write(".out-of-scope/idea.md", "# Turned-down idea\n\nThe reasons it was rejected.\n")
        self.write(
            ".scratch/feature/issues/01-request.md",
            "# Request\n\nStatus: ready-for-agent\n\nFrom: [Earlier idea](../../../.out-of-scope/idea.md)\n",
        )
        item = self.items()[".scratch/feature/issues/01-request.md"]
        self.assertEqual(item["warnings"], [])
        self.assertEqual([entry["path"] for entry in item["context"]], [".out-of-scope/idea.md"])
        self.assertEqual(item["context"][0]["why"], "This idea was turned down before.")

    def test_blocked_by_takes_ticket_numbers_from_the_same_folder(self) -> None:
        self.write(".scratch/effort/map.md", "# Effort\n\nStatus: in-progress\n")
        self.write(".scratch/effort/issues/01-first.md", "# First\n\nType: grilling\nStatus: resolved\n")
        self.write(".scratch/effort/issues/02-second.md", "# Second\n\nType: research\nStatus: open\n")
        self.write(".scratch/effort/issues/03-third.md", "# Third\n\nType: grilling\nStatus: open\nBlocked by: 01, 02\n")
        third = self.items()[".scratch/effort/issues/03-third.md"]
        self.assertEqual(third["blockedBy"], [".scratch/effort/issues/01-first.md", ".scratch/effort/issues/02-second.md"])
        self.assertEqual([w["ref"] for w in third["waitsFor"]], ["ticket 02"])

    def test_blocked_by_reads_titles_and_reads_none_as_no_blocker(self) -> None:
        self.write(".scratch/feature/issues/01-first.md", "# 01: First\n\n**Status:** ready-for-agent\n")
        self.write(".scratch/feature/issues/02-second.md", "# 02: Second\n\n**Blocked by:** First\n\n**Status:** ready-for-agent\n")
        self.write(".scratch/feature/issues/03-third.md", "# 03: Third\n\n**Blocked by:** None (can start immediately)\n\n**Status:** ready-for-agent\n")
        items = self.items()
        self.assertEqual(items[".scratch/feature/issues/02-second.md"]["blockedBy"], [".scratch/feature/issues/01-first.md"])
        self.assertEqual(items[".scratch/feature/issues/03-third.md"]["blockedBy"], [])
        self.assertEqual(items[".scratch/feature/issues/03-third.md"]["warnings"], [])

    def test_an_issue_comes_from_its_folders_map_or_else_the_plan_with_its_name(self) -> None:
        self.write(".scratch/mapped/map.md", "# Mapped\n\nStatus: in-progress\n")
        self.write(".scratch/mapped/issues/01-a.md", "# A\n\nType: grilling\nStatus: open\n")
        self.write("docs/plans/planned.md", "# Planned\n\n> **Status:** shipped\n")
        self.write(".scratch/planned/issues/01-b.md", "# B\n\nStatus: needs-triage\n")
        items = self.items()
        for rel, parent in ((".scratch/mapped/issues/01-a.md", ".scratch/mapped/map.md"), (".scratch/planned/issues/01-b.md", "docs/plans/planned.md")):
            with self.subTest(rel=rel):
                self.assertEqual(items[rel]["from"], [parent])
                self.assertEqual(items[rel]["context"][0]["why"], "It came from this, by its folder.")

    def test_a_link_line_naming_a_missing_file_is_a_warning(self) -> None:
        self.write("docs/adr/0001-record.md", "# Record\n\nFrom: [Gone](../plans/gone.md)\n")
        item = self.items()["docs/adr/0001-record.md"]
        self.assertEqual(item["warnings"], ["From: names docs/plans/gone.md, which does not exist."])
        self.assertEqual(item["context"], [])

    def test_a_merged_ticket_is_wontfix_and_names_the_one_that_took_it_over(self) -> None:
        self.write(".scratch/e/map.md", "# E\n\nStatus: in-progress\n")
        self.write(".scratch/e/issues/01-keeper.md", "# Keeper\n\nType: grilling\nStatus: resolved\n")
        self.write(".scratch/e/issues/02-merged.md", "# Merged\n\nType: grilling\nStatus: resolved\nMerged into: [Keeper](01-keeper.md)\n")
        items = self.items()
        merged = items[".scratch/e/issues/02-merged.md"]
        self.assertEqual(merged["status"], "wontfix")
        self.assertEqual(merged["mergedRef"]["ref"], "ticket 01")
        self.assertIn(
            {"path": ".scratch/e/issues/02-merged.md", "title": "Merged", "why": "Merged into this item.", "shown": True},
            items[".scratch/e/issues/01-keeper.md"]["context"],
        )

    def test_next_steps_are_read_in_order_with_their_reasons(self) -> None:
        self.write(
            ".scratch/x/issues/01-a.md",
            "# A\n\nStatus: needs-triage\n\n## Next steps\n\n1. `/triage`: Nobody has looked yet.\n"
            "2. `/implement`: Small once agreed,\n   so build it.\n",
        )
        self.assertEqual(
            self.items()[".scratch/x/issues/01-a.md"]["next"],
            [{"skill": "triage", "reason": "Nobody has looked yet."}, {"skill": "implement", "reason": "Small once agreed, so build it."}],
        )

    def test_the_description_comes_from_where_each_kind_writes_it(self) -> None:
        rows = {
            ".scratch/e/map.md": ("# E\n\n## Destination\n\nA spec for:\n\n- one page;\n- one skill.\n", "A spec for: one page; one skill."),
            ".scratch/e/issues/01-t.md": ("# T\n\nType: grilling\nStatus: open\n\n## Question\n\nWhich layout?\n", "Which layout?"),
            "docs/plans/p.md": ("# P\n\n> **Status:** agreed\n\n## Request\n\nMake it so.\n", "Make it so."),
            ".scratch/x/issues/01-i.md": ("# I\n\nStatus: needs-triage\n\nThe import only validates the model.\n", "The import only validates the model."),
            "docs/adr/0001-r.md": ("---\nstatus: accepted\n---\n\n# R\n\nFrom: [P](../plans/p.md)\n\nA rule with `code`.\n", "A rule with code."),
        }
        for rel, (text, _expected) in rows.items():
            self.write(rel, text)
        items = self.items()
        for rel, (_text, expected) in rows.items():
            with self.subTest(rel=rel):
                self.assertEqual(items[rel]["desc"], expected)

    def test_an_item_older_than_the_cutoff_has_no_star_but_stays_in_context(self) -> None:
        self.write("docs/plans/old.md", "# Old\n\n> **Status:** shipped\n")
        self.write("docs/adr/0001-new.md", "# New\n\nFrom: [Old](../plans/old.md)\n")
        items = self.items(existing={"docs/plans/old.md"})
        self.assertNotIn("docs/plans/old.md", items)
        new = items["docs/adr/0001-new.md"]
        self.assertEqual(new["from"], [])
        self.assertEqual([c["path"] for c in new["context"]], ["docs/plans/old.md"])
        self.assertFalse(new["context"][0]["shown"])

    def test_a_snapshot_changes_when_a_watched_file_is_saved_added_or_removed(self) -> None:
        self.write(".scratch/x/issues/01-a.md", "# A\n")
        script = self.repo / "tool.py"
        script.write_text("", encoding="utf-8")
        first = star_map.snapshot(self.repo, (script,))
        self.assertEqual(len(first), 2)
        edits = {
            "saved": lambda: os.utime(self.repo / ".scratch/x/issues/01-a.md", ns=(1, 1)),
            "tool saved": lambda: os.utime(script, ns=(1, 1)),
            "added": lambda: self.write(".out-of-scope/idea.md", "# Idea\n"),
            "removed": lambda: (self.repo / ".scratch/x/issues/01-a.md").unlink(),
        }
        for name, edit in edits.items():
            with self.subTest(name=name):
                before = star_map.snapshot(self.repo, (script,))
                edit()
                self.assertNotEqual(star_map.snapshot(self.repo, (script,)), before)

    def test_watch_rebuilds_once_after_the_files_stop_changing(self) -> None:
        cases = {
            "no change": (["a", "a", "a"], 0),
            "burst of saves": (["a", "b", "c", "d", "d", "d"], 1),
            "two separate saves": (["a", "b", "b", "b", "c", "c"], 2),
            "still changing": (["a", "b", "c", "d"], 0),
        }
        for name, (states, expected) in cases.items():
            with self.subTest(name=name):
                feed = iter(states)
                rebuilds = []
                star_map.watch(lambda: next(feed), lambda: rebuilds.append(1), lambda: None, rounds=len(states) - 1)
                self.assertEqual(len(rebuilds), expected)

    def test_a_page_is_written_whole_and_leaves_no_temporary_file(self) -> None:
        page = self.repo / "page.html"
        page.write_text("old", encoding="utf-8")
        star_map.write_page(page, "new")
        self.assertEqual(page.read_text(encoding="utf-8"), "new")
        self.assertEqual([p.name for p in self.repo.iterdir()], ["page.html"])
        with patch.object(star_map.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaisesRegex(PermissionError, "locked"):
                star_map.write_page(page, "newer")
        self.assertEqual(page.read_text(encoding="utf-8"), "new")
        self.assertEqual([p.name for p in self.repo.iterdir()], ["page.html"])

    def test_no_text_in_an_item_can_close_the_page_script(self) -> None:
        page = star_map.render(
            "<script>const DATA = /*STAR_MAP_DATA*/null;</script>",
            {"items": [{"title": "</script><script>alert(1)</script>"}]},
        )
        self.assertEqual(page.count("</script>"), 1)
        self.assertIn("\\u003c/script>", page)


if __name__ == "__main__":
    unittest.main()
