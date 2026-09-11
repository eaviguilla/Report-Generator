from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage import atomic_write_json


class AtomicStorageTests(unittest.TestCase):
    def test_atomic_write_retries_transient_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "draft.json"
            real_replace = os.replace
            replace_sources: list[Path] = []

            def replace_once_unlocked(source, target) -> None:
                replace_sources.append(Path(source))
                if len(replace_sources) == 1:
                    raise PermissionError("temporary Windows lock")
                real_replace(source, target)

            with patch("app.storage.os.replace", side_effect=replace_once_unlocked), patch("app.storage.time.sleep") as sleep:
                atomic_write_json(destination, {"saved": True})

            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"saved": True})
            self.assertEqual(len(replace_sources), 2)
            self.assertNotEqual(replace_sources[0], destination.with_suffix(".tmp"))
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])
            sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()