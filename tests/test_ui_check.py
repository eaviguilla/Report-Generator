from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import main
from app.report_service import setup_issues
from scripts import ui_check
from tests.support import use_temp_workspace

ROOT = Path(__file__).resolve().parent.parent


class SeedReportTests(unittest.TestCase):
    def setUp(self) -> None:
        use_temp_workspace(self, "UI Check")

    def test_none_saves_nothing(self) -> None:
        self.assertIsNone(ui_check.seed_report(main.workspace, "none"))
        self.assertEqual(main.workspace.list_reports(), [])

    def test_empty_report_still_fails_setup(self) -> None:
        report = main.workspace.load(ui_check.seed_report(main.workspace, "empty"))
        self.assertTrue(setup_issues(report))
        self.assertEqual(report.vulnerabilities, [])

    def test_setup_report_passes_setup_with_no_findings(self) -> None:
        report = main.workspace.load(ui_check.seed_report(main.workspace, "setup"))
        self.assertEqual(setup_issues(report), [])
        self.assertEqual(report.vulnerabilities, [])

    def test_finding_report_passes_setup_and_has_one_finding_with_content(self) -> None:
        report = main.workspace.load(ui_check.seed_report(main.workspace, "finding"))
        self.assertEqual(setup_issues(report), [])
        [finding] = report.vulnerabilities
        self.assertTrue(finding.contents)


class ServeTests(unittest.TestCase):
    def test_free_port_is_in_the_reserved_range(self) -> None:
        self.assertIn(ui_check.free_port(), ui_check.PORTS)

    def bound_socket(self) -> socket.socket:
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        return held

    def test_free_port_skips_a_port_that_is_bound_but_not_listening(self) -> None:
        port = self.bound_socket().getsockname()[1]
        with patch.object(ui_check, "PORTS", range(port, port + 1)):
            with self.assertRaisesRegex(RuntimeError, "No free port"):
                ui_check.free_port()

    def test_reserve_port_holds_the_port_until_it_is_closed(self) -> None:
        released = self.bound_socket()
        port = released.getsockname()[1]
        released.close()
        with patch.object(ui_check, "PORTS", range(port, port + 1)):
            reserved = ui_check.reserve_port()
            self.addCleanup(reserved.close)
            self.assertEqual(reserved.getsockname()[1], port)
            with self.assertRaisesRegex(RuntimeError, "No free port"):
                ui_check.reserve_port()
            reserved.close()
            with ui_check.reserve_port() as again:
                self.assertEqual(again.getsockname()[1], port)

    @unittest.skipIf(os.name == "nt", "terminate() is a hard kill on Windows, so the folder is not removed there")
    def test_serves_a_seeded_report_and_removes_its_folder_when_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            # TMPDIR steers the script's temporary folder here, so the test can see it go.
            env = {**os.environ, "TMPDIR": scratch, "PYTHONUNBUFFERED": "1"}
            process = subprocess.Popen(
                [sys.executable, "-m", "scripts.ui_check", "--report", "finding"],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True,
            )
            self.addCleanup(process.kill)
            self.addCleanup(process.stdout.close)
            url = process.stdout.readline().strip()
            report_line = process.stdout.readline().strip()
            self.assertTrue(url.startswith("URL http://127.0.0.1:"), url)
            self.assertTrue(report_line.startswith("REPORT r_"), report_line)
            base = url.removeprefix("URL ")
            report_id = report_line.removeprefix("REPORT ")
            with urllib.request.urlopen(f"{base}/reports/{report_id}/findings", timeout=10) as response:
                self.assertEqual(response.status, 200)
            self.assertTrue(any(Path(scratch).glob("vulnreport-ui-check-*")))
            process.terminate()
            process.wait(timeout=15)
            self.assertEqual(list(Path(scratch).glob("vulnreport-ui-check-*")), [])


if __name__ == "__main__":
    unittest.main()
