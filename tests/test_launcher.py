from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run


class BootstrapDecisionTests(unittest.TestCase):
    """The launcher must install on a first run and stay quiet on every run after."""

    def test_install_decisions_follow_the_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / ".venv"
            interpreter = venv / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            stamp = venv / ".requirements-sha256"

            with patch.object(run, "VENV_DIR", venv), patch.object(run, "STAMP", stamp):
                with patch.object(run, "venv_python", return_value=interpreter):
                    self.assertTrue(run.needs_install("abc"), "missing interpreter must install")

                    interpreter.write_text("", encoding="utf-8")
                    self.assertTrue(run.needs_install("abc"), "missing stamp must install")

                    stamp.write_text("abc\n", encoding="utf-8")
                    self.assertFalse(run.needs_install("abc"), "matching stamp must skip install")

                    self.assertTrue(run.needs_install("def"), "changed requirements must reinstall")

    def test_symlinked_venv_interpreter_is_not_mistaken_for_the_venv(self) -> None:
        """A venv python is a symlink to the system python on macOS and Linux."""
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / ".venv"
            venv.mkdir()

            with patch.object(run, "VENV_DIR", venv):
                with patch.object(run.sys, "prefix", str(venv)):
                    self.assertTrue(run.inside_venv())
                with patch.object(run.sys, "prefix", directory):
                    self.assertFalse(run.inside_venv(), "system python must bootstrap, not serve")


if __name__ == "__main__":
    unittest.main()
