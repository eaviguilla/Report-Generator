from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import urlopen

from app import init as run
from scripts import burp_release, default_release

import run as default_launcher

REPO = Path(__file__).resolve().parent.parent
HOLDER = (
    "import sys; sys.path.insert(0, sys.argv[2]); from app import init as run; from pathlib import Path\n"
    "handle = run.take_server_lock(Path(sys.argv[1]), wait=1)\n"
    "print('locked' if handle else 'refused', flush=True)\n"
    "sys.stdin.read()\n"
)
# What `python app/init.py` does, with the browser stubbed out so a test never opens a real one.
SERVE_WRAPPER = "import webbrowser; webbrowser.open = lambda *a, **k: True; from app import init as run; raise SystemExit(run.main())"


class Lines:
    """A child's merged output, read on a thread, so a test can wait for a line without ever hanging."""

    def __init__(self, process: subprocess.Popen) -> None:
        self.seen: list[str] = []
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, args=(process.stdout,), daemon=True).start()

    def _read(self, stream) -> None:
        for line in iter(stream.readline, ""):
            self.seen.append(line.rstrip("\n"))
            self._queue.put(line.rstrip("\n"))
        stream.close()
        self._queue.put(None)

    def output(self, timeout: float = 15) -> str:
        """Everything the child printed, once it has closed its output (so the last lines are not missed)."""
        self.wait_for("\0", timeout)
        return "\n".join(self.seen)

    def wait_for(self, prefix: str, timeout: float = 90) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                return None
            if line.startswith(prefix):
                return line
        return None


def start_child(args: list[str], env: dict | None = None, cwd: Path = REPO, **kwargs) -> tuple[subprocess.Popen, Lines]:
    process = subprocess.Popen(
        args, cwd=cwd, env=env or os.environ.copy(), text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs
    )
    return process, Lines(process)


def finish(process: subprocess.Popen, timeout: float = 20) -> int:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()
    finally:
        if process.stdin:
            process.stdin.close()


def hold_lock(folder: Path) -> subprocess.Popen:
    """A separate process holding `folder`/server.lock; an in-process lock would not conflict on macOS and Linux."""
    process, lines = start_child([sys.executable, "-c", HOLDER, str(folder), str(REPO)], stdin=subprocess.PIPE)
    if lines.wait_for("locked", timeout=30) is None:
        process.kill()
        raise AssertionError("the lock holder did not get its lock")
    return process


def release(process: subprocess.Popen) -> None:
    process.stdin.close()
    finish(process)


def port_answers(url: str) -> bool:
    port = int(url.rsplit(":", 1)[1])
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


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


class DataFolderTests(unittest.TestCase):
    def test_data_dir_follows_the_apps_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            absolute = str(Path(directory) / "elsewhere")
            os.environ.pop(run.DATA_ENV, None)
            self.assertEqual(run.data_dir(), run.ROOT / "data")
            os.environ[run.DATA_ENV] = ""
            self.assertEqual(run.data_dir(), run.ROOT / "data", "an empty value means unset, as in app.main")
            os.environ[run.DATA_ENV] = absolute
            self.assertEqual(run.data_dir(), Path(absolute))

            # A relative value is read against where app/init.py was started, then written back absolute, so the
            # relaunched child (which runs from the app folder) serves the folder the parent locked.
            start = os.getcwd()
            os.chdir(directory)
            try:
                os.environ[run.DATA_ENV] = "here"
                expected = Path(os.getcwd()) / "here"
                self.assertEqual(run.data_dir(), expected)
                run.pin_data_dir()
                self.assertEqual(os.environ[run.DATA_ENV], str(expected))
            finally:
                os.chdir(start)

    def test_default_data_folder_is_the_servers_default_data_folder(self) -> None:
        """The launcher sits in app/, so a ROOT one level short would put data/, the lock and .venv under app/."""
        env = {key: value for key, value in os.environ.items() if key != run.DATA_ENV}
        served = subprocess.run(
            [sys.executable, "-c", "import app.main as m; print(m.DATA)"], cwd=REPO, env=env, capture_output=True, text=True, timeout=120
        )
        self.assertEqual(served.returncode, 0, served.stderr)
        with patch.dict(os.environ):
            os.environ.pop(run.DATA_ENV, None)
            self.assertEqual(run.data_dir(), REPO / "data")
            self.assertEqual(Path(served.stdout.strip().splitlines()[-1]), run.data_dir(), "the launcher must lock the folder the server serves")
        self.assertEqual(run.ROOT, REPO)
        self.assertEqual(run.VENV_DIR, REPO / ".venv")
        self.assertEqual(run.REQUIREMENTS, REPO / "requirements.txt")
        self.assertTrue(run.REQUIREMENTS.is_file(), "ROOT must be the folder that holds requirements.txt")

    def test_data_dir_matches_what_app_main_serves(self) -> None:
        """app.main is the other half of this rule, so pin the text of its half and run it once for real."""
        source = (REPO / "app" / "main.py").read_text(encoding="utf-8")
        self.assertRegex(source, r'Path\(os\.environ\.get\("VULNREPORT_DATA_DIR"\) or ROOT / "data"\)')
        self.assertEqual(run.DATA_ENV, "VULNREPORT_DATA_DIR")
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, run.DATA_ENV: directory}
            served = subprocess.run(
                [sys.executable, "-c", "import app.main as m; print(m.DATA)"], cwd=REPO, env=env, capture_output=True, text=True, timeout=120
            )
            with patch.dict(os.environ, {run.DATA_ENV: directory}):
                self.assertEqual(served.stdout.strip().splitlines()[-1], str(run.data_dir()), served.stderr)


class LockTests(unittest.TestCase):
    def guard(self, folder: Path) -> subprocess.CompletedProcess:
        code = "from app import init as run; run.LOCK_WAIT = 0.3; run.guard_start()"
        return subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, env={**os.environ, run.DATA_ENV: str(folder)}, capture_output=True, text=True, timeout=60
        )

    def test_a_second_start_on_the_same_data_folder_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            holder = hold_lock(Path(directory))
            try:
                refused = self.guard(Path(directory))
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(f"already running on {directory}", refused.stderr)
            finally:
                release(holder)
            self.assertEqual(self.guard(Path(directory)).returncode, 0, "the folder is free again once the holder let go")

    def test_the_lock_is_released_when_its_process_dies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            holder = hold_lock(Path(directory))
            holder.kill()
            holder.wait()
            handle = run.take_server_lock(Path(directory), wait=5)
            self.assertIsNotNone(handle, "a killed server must not block the next start")
            handle.close()

    def test_lock_state_creates_nothing_and_sees_a_holder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "data"
            self.assertFalse(run.lock_is_held(folder))
            self.assertFalse(folder.exists(), "looking must not create the data folder")
            holder = hold_lock(folder)
            try:
                self.assertTrue(run.lock_is_held(folder))
            finally:
                release(holder)
            self.assertFalse(run.lock_is_held(folder))

    def test_a_folder_whose_data_moved_refuses_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), patch.object(run, "_server_lock", None):
            app = Path(directory)
            (app / run.MOVED_NOTE).write_text("Data moved to /somewhere/else.\n", encoding="utf-8")
            os.environ.pop(run.DATA_ENV, None)
            os.environ.pop(run.RELAUNCH_FLAG, None)
            with patch.object(run, "ROOT", app):
                with self.assertRaises(SystemExit) as refused:
                    run.guard_start()
            self.assertEqual(refused.exception.code, "Data moved to /somewhere/else.")
            self.assertFalse((app / "data").exists(), "refusing must happen before anything creates data/")

            # An explicit data folder is a deliberate choice, so the note no longer applies.
            os.environ[run.DATA_ENV] = str(app / "chosen")
            with patch.object(run, "ROOT", app):
                run.guard_start()
            run._server_lock.close()


class DataStatusTests(unittest.TestCase):
    def test_status_counts_reports_the_way_the_workspace_finds_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "data"
            self.assertEqual(run.count_reports(folder), 0)
            for name, body in (("Northstar/2026-09_Annual_a1", "{}"), ("unnamed/2026-09_Report_b2", "not json at all")):
                draft = folder / "apps" / name / "draft.json"
                draft.parent.mkdir(parents=True)
                draft.write_text(body, encoding="utf-8")
            (folder / "apps" / "Northstar" / "2026-09_Annual_a1" / "draft.bak.json").write_text("{}", encoding="utf-8")
            from app.workspace import Workspace

            scanned = list(Workspace(folder, "QA").apps_root.glob("*/*/draft.json"))
            self.assertEqual(run.count_reports(folder), len(scanned))
            self.assertEqual(run.count_reports(folder), 2, "an unreadable draft still counts: bringing data over must not skip it")

    def test_status_prints_one_json_line_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {run.DATA_ENV: str(Path(directory) / "data")}):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.main(["--data-status"]), 0)
            status = json.loads(out.getvalue())
            self.assertEqual(status["data"], str(Path(directory) / "data"))
            self.assertEqual((status["reports"], status["locked"]), (0, False))
            self.assertEqual(set(status), {"data", "reports", "locked", "venv"})
            self.assertEqual(list(Path(directory).iterdir()), [], "--data-status must never create anything")


def make_release(folder: Path, *markers: str) -> None:
    """A release folder: `run.py` is how a release from before the launcher moved marks itself, `app/init.py` a current one."""
    folder.mkdir(parents=True, exist_ok=True)
    for marker in markers:
        (folder / marker).parent.mkdir(parents=True, exist_ok=True)
        (folder / marker).write_text("", encoding="utf-8")


def tree(folder: Path) -> dict:
    return {str(path.relative_to(folder)): (path.read_bytes() if path.is_file() else None) for path in sorted(folder.rglob("*"))}


class BringOverTests(unittest.TestCase):
    """A previous release's data must arrive whole, once, and never overwrite or delete anything."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        base = Path(self.folder.name).resolve()  # run.ROOT is resolved, and macOS temp folders are symlinks
        self.old, self.new = base / "old", base / "new"
        make_release(self.old, "run.py")  # a release from before the launcher moved
        make_release(self.new, "app/init.py")
        for name, body in (("Northstar/2026-09_Annual_a1", b'{"a": 1}'), ("Other/2026-09_Retest_b2", b'{"b": 2}')):
            draft = self.old / "data" / "apps" / name / "draft.json"
            draft.parent.mkdir(parents=True)
            draft.write_bytes(body)
            (draft.parent / "evidence").mkdir()
            (draft.parent / "evidence" / "ev_1.png").write_bytes(b"png:" + body)
        (self.old / "data" / "prefs.json").write_text('{"tester": "QA"}', encoding="utf-8")
        (self.old / "generated").mkdir()
        (self.old / "generated" / "JH - Report.docx").write_bytes(b"docx")
        patches = [patch.object(run, "ROOT", self.new), patch.object(run, "VENV_DIR", self.new / ".venv")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(run.DATA_ENV, None)

    def bring(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.bring_over(*args)
        return code, out.getvalue(), err.getvalue()

    def test_bring_over_moves_every_report_and_marks_the_old_folder(self) -> None:
        before = tree(self.old / "data")
        code, out, err = self.bring(str(self.old))
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.new / "data"), before, "every file arrives exactly as it was")
        self.assertFalse((self.old / "data").exists(), "renamed, not copied: there must be one store")
        self.assertEqual((self.new / "generated" / "JH - Report.docx").read_bytes(), b"docx")
        self.assertFalse((self.old / "generated").exists())
        note = (self.old / run.MOVED_NOTE).read_text(encoding="utf-8")
        self.assertIn(str(self.new), note)
        self.assertEqual(run.count_reports(self.new / "data"), 2)

    def test_bring_over_sets_aside_an_empty_data_folder(self) -> None:
        (self.new / "data" / ".locks").mkdir(parents=True)
        (self.new / "data" / "prefs.json").write_text("made by an early Start", encoding="utf-8")
        code, _, err = self.bring(str(self.old))
        self.assertEqual(code, 0, err)
        aside = [path for path in self.new.iterdir() if path.name.startswith("data.before-move-")]
        self.assertEqual(len(aside), 1)
        self.assertEqual((aside[0] / "prefs.json").read_text(encoding="utf-8"), "made by an early Start", "set aside, never deleted")

    def test_bring_over_accepts_a_release_of_either_layout(self) -> None:
        """Releases already with testers have run.py at the top; a current one has app/init.py. Neither may be refused."""
        for name, markers in (("before the move", ("run.py",)), ("current", ("app/init.py",)), ("both", ("run.py", "app/init.py"))):
            with self.subTest(release=name):
                base = Path(self.folder.name).resolve() / name.replace(" ", "-")
                old, new = base / "old", base / "new"
                make_release(old, *markers)
                make_release(new, "app/init.py")
                draft = old / "data" / "apps" / "Northstar" / "2026-09_Annual_a1" / "draft.json"
                draft.parent.mkdir(parents=True)
                draft.write_bytes(b'{"a": 1}')
                (old / "generated").mkdir()
                (old / "generated" / "JH - Report.docx").write_bytes(b"docx")
                with patch.object(run, "ROOT", new), patch.object(run, "VENV_DIR", new / ".venv"):
                    code, _, err = self.bring(str(old))
                self.assertEqual(code, 0, err)
                self.assertEqual((new / "data" / "apps" / "Northstar" / "2026-09_Annual_a1" / "draft.json").read_bytes(), b'{"a": 1}')
                self.assertEqual((new / "generated" / "JH - Report.docx").read_bytes(), b"docx")
                self.assertFalse((new / "app" / "data").exists(), "data must land beside app/, not inside it")
                self.assertFalse((new / "app" / "generated").exists())

    def test_bring_over_refuses_a_folder_that_already_holds_reports(self) -> None:
        draft = self.new / "data" / "apps" / "Mine" / "2026-09_Annual_c3" / "draft.json"
        draft.parent.mkdir(parents=True)
        draft.write_text("{}", encoding="utf-8")
        before = (tree(self.old), tree(self.new))
        code, _, err = self.bring(str(self.old))
        self.assertEqual(code, 1)
        self.assertIn("already holds reports", err)
        self.assertEqual((tree(self.old), tree(self.new)), before, "a refusal changes nothing")

    def test_bring_over_refuses_while_either_folder_is_locked(self) -> None:
        for name, folder in (("previous release", self.old / "data"), ("this folder", self.new / "data")):
            with self.subTest(locked=name):
                baseline = (tree(self.old), tree(self.new))
                holder = hold_lock(folder)
                try:
                    code, _, err = self.bring(str(self.old))
                finally:
                    release(holder)
                self.assertEqual(code, 1)
                self.assertIn("Stop it first", err)
                # The holder's own lock file is the only thing that may differ.
                (folder / run.LOCK_NAME).unlink()
                if folder == self.new / "data":
                    folder.rmdir()
                self.assertEqual((tree(self.old), tree(self.new)), baseline, "a refusal changes nothing")

    def test_bring_over_refusals_change_nothing(self) -> None:
        (self.old / run.MOVED_NOTE).write_text("moved", encoding="utf-8")
        marked = self.old
        plain = self.old.parent / "plain"
        plain.mkdir()
        empty = self.old.parent / "empty"
        make_release(empty, "app/init.py")
        (empty / "data" / "apps").mkdir(parents=True)
        rows = [
            ("no folder given", "", {}),
            ("this very folder", str(self.new), {}),
            ("a folder holding this one", str(self.new.parent), {}),
            ("neither run.py nor app/init.py", str(plain), {}),
            ("already moved", str(marked), {}),
            ("no reports", str(empty), {}),
            ("the data folder is set elsewhere", str(self.old), {run.DATA_ENV: str(self.new.parent / "custom")}),
        ]
        for name, argument, extra in rows:
            with self.subTest(refused=name), patch.dict(os.environ, extra):
                before = tree(self.new.parent)
                code, out, err = self.bring(argument)
                self.assertEqual(code, 1, out)
                self.assertIn("Nothing was moved", err)
                self.assertEqual(tree(self.new.parent), before)

    def test_bring_over_keeps_a_working_venv_and_removes_a_broken_copy(self) -> None:
        (self.old / ".venv" / "bin").mkdir(parents=True)
        (self.old / ".venv" / "bin" / "python").write_text("interpreter", encoding="utf-8")
        (self.old / ".venv" / ".requirements-sha256").write_text("abc\n", encoding="utf-8")
        with patch.object(run, "_venv_imports_cleanly", return_value=True):
            code, out, err = self.bring(str(self.old))
        self.assertEqual(code, 0, err)
        self.assertTrue((self.new / ".venv" / ".requirements-sha256").is_file(), "the stamp comes along with the copy")
        self.assertTrue((self.old / ".venv").is_dir(), "the previous .venv is copied, not moved")

    def test_a_broken_venv_copy_is_removed_and_the_data_still_arrives(self) -> None:
        (self.old / ".venv" / "bin").mkdir(parents=True)
        (self.old / ".venv" / "bin" / "python").write_text("interpreter", encoding="utf-8")
        with patch.object(run, "_venv_imports_cleanly", return_value=False):
            code, out, err = self.bring(str(self.old))
        self.assertEqual(code, 0, err)
        self.assertFalse((self.new / ".venv").exists(), "a copy that fails its check is deleted, so Start rebuilds it")
        self.assertEqual(run.count_reports(self.new / "data"), 2)
        self.assertIn("rebuild", out)

    def test_an_existing_venv_here_is_never_replaced(self) -> None:
        (self.old / ".venv").mkdir()
        (self.old / ".venv" / "marker").write_text("old", encoding="utf-8")
        (self.new / ".venv").mkdir()
        (self.new / ".venv" / "marker").write_text("new", encoding="utf-8")
        code, _, err = self.bring(str(self.old))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.new / ".venv" / "marker").read_text(encoding="utf-8"), "new")


class VenvProbeTests(unittest.TestCase):
    def test_the_probe_passes_for_a_working_environment_and_fails_for_a_missing_one(self) -> None:
        self.assertTrue(run._venv_imports_cleanly(Path(sys.executable)), "the tests run in an environment that can start the app")
        self.assertFalse(run._venv_imports_cleanly(Path(tempfile.gettempdir()) / "no-such-interpreter"))

    def test_the_probe_names_what_app_main_loads_at_import(self) -> None:
        """Compiled and lazily-imported parts are where a copied environment breaks first."""
        self.assertIn("PIL._imaging", run.VENV_PROBE_MODULES)
        self.assertIn("jinja2", run.VENV_PROBE_MODULES)


class StreamTests(unittest.TestCase):
    def test_children_receive_the_launchers_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / ".venv"
            venv.mkdir()
            for name, extra, expected in (("under Burp", {run.BURP_FLAG: "1"}, True), ("from a console", {}, False)):
                with self.subTest(start=name), patch.dict(os.environ, extra), patch.object(run, "VENV_DIR", venv), patch.object(
                    run, "STAMP", venv / ".stamp"
                ), patch.object(run.subprocess, "run", return_value=MagicMock(returncode=0)) as spawn:
                    if not extra:
                        os.environ.pop(run.BURP_FLAG, None)
                    with patch.object(run, "needs_install", return_value=True), patch("builtins.print"):
                        run.bootstrap()
                    run.relaunch()
                    self.assertGreaterEqual(spawn.call_count, 3)
                    for call in spawn.call_args_list:
                        streams = {key: call.kwargs.get(key) for key in ("stdin", "stdout", "stderr")}
                        if expected:
                            self.assertEqual(streams, {"stdin": sys.stdin, "stdout": sys.stdout, "stderr": sys.stderr})
                        else:
                            self.assertEqual(streams, {"stdin": None, "stdout": None, "stderr": None})


class ScriptPathTests(unittest.TestCase):
    """`python app/init.py` puts app/ first on the module path, not the release root, and only a script path shows it.

    Every other launcher test starts the code with `python -c`, which puts the working directory on the path and
    would pass even if the app could not be imported. These run the file itself, from a folder that is not the
    repository, so the working directory cannot be what makes the import work.
    """

    def script(self, *arguments: str) -> list[str]:
        return [sys.executable, str(REPO / "app" / "init.py"), *arguments]

    def test_data_status_runs_from_any_folder_with_only_the_standard_library(self) -> None:
        with tempfile.TemporaryDirectory() as elsewhere, tempfile.TemporaryDirectory() as data:
            env = {**os.environ, run.DATA_ENV: data}
            env.pop(run.RELAUNCH_FLAG, None)
            done = subprocess.run(self.script("--data-status"), cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            status = json.loads(done.stdout)
            self.assertEqual((status["data"], status["reports"], status["locked"]), (data, 0, False))
            self.assertEqual(list(Path(data).iterdir()), [], "--data-status must create nothing")

    def test_the_server_starts_and_stops_when_run_as_a_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as elsewhere, tempfile.TemporaryDirectory() as data:
            env = {**os.environ, run.RELAUNCH_FLAG: "1", run.BURP_FLAG: "1", run.DATA_ENV: data}
            process, lines = start_child(self.script(), env=env, cwd=Path(elsewhere), stdin=subprocess.PIPE)
            self.addCleanup(finish, process, 0.1)
            line = lines.wait_for(run.ADDRESS_LINE)
            self.assertIsNotNone(line, "the server did not start:\n" + "\n".join(lines.seen))
            self.assertTrue(port_answers(line[len(run.ADDRESS_LINE):]))
            process.stdin.close()
            self.assertEqual(finish(process, 20), 0, lines.output())


class ServeTests(unittest.TestCase):
    """Each test starts `app/init.py` for real, serving from this interpreter, with the browser stubbed out."""

    def start(self, *, burp: bool, stdin) -> tuple[subprocess.Popen, Lines]:
        env = {**os.environ, run.RELAUNCH_FLAG: "1"}
        env.pop(run.BURP_FLAG, None)
        if burp:
            env[run.BURP_FLAG] = "1"
        process, lines = start_child([sys.executable, "-c", SERVE_WRAPPER], env=env, stdin=stdin, start_new_session=os.name == "posix")
        self.addCleanup(finish, process, 0.1)
        return process, lines

    def address(self, lines: Lines) -> str:
        line = lines.wait_for(run.ADDRESS_LINE)
        self.assertIsNotNone(line, "no address line was printed:\n" + "\n".join(lines.seen))
        return line[len(run.ADDRESS_LINE):]

    def test_address_line_is_printed_only_once_the_server_answers(self) -> None:
        process, lines = self.start(burp=False, stdin=subprocess.DEVNULL)
        url = self.address(lines)
        with urlopen(url, timeout=5) as response:  # one request, no retry: the line must mean "ready"
            self.assertEqual(response.status, 200)

    def test_end_of_input_stops_only_a_server_started_by_burp(self) -> None:
        with self.subTest(case="started by Burp, input closed after the line"):
            process, lines = self.start(burp=True, stdin=subprocess.PIPE)
            url = self.address(lines)
            self.assertTrue(port_answers(url))
            process.stdin.close()
            self.assertEqual(finish(process, 15), 0, "\n".join(lines.seen))
            self.assertFalse(port_answers(url), "the port must be closed after Stop")

        with self.subTest(case="started by Burp, input closed before it starts (Stop during setup)"):
            process, lines = self.start(burp=True, stdin=subprocess.DEVNULL)
            self.assertEqual(finish(process, 90), 0, "\n".join(lines.seen))
            self.assertNotIn("Close this window", lines.output(), "a Burp start prints no console advice")

        with self.subTest(case="console start, input empty from the beginning"):
            process, lines = self.start(burp=False, stdin=subprocess.DEVNULL)
            url = self.address(lines)
            with urlopen(url, timeout=5) as response:
                self.assertEqual(response.status, 200, "only a Burp start treats end of input as Stop")
            self.assertIsNone(process.poll())
            self.assertIsNotNone(lines.wait_for("Close this window", 5), "a console start still prints its advice")

    @unittest.skipUnless(os.name == "posix", "Windows cannot send Ctrl+C to one child without also sending it to the test runner")
    def test_ctrl_c_in_a_console_start_exits_cleanly(self) -> None:
        process, lines = self.start(burp=False, stdin=subprocess.DEVNULL)
        self.address(lines)
        process.send_signal(signal.SIGINT)
        code = finish(process, 20)
        output = lines.output()
        self.assertEqual(code, 0, output)
        self.assertNotIn("Traceback", output)


BURP_FILE = REPO / "report_generator_burp.py"
DEFAULT_LAUNCHER = REPO / "run.py"
# Words that must never appear in the default build's launcher (docs/plans/split-release-into-burp-and-default.md, Q3/Q8).
# Checked case-insensitively: "burp" alone also catches BURP_FLAG, started_by_burp and report_generator_burp.py.
BURP_WORDS = ("burp", "--data-status", "--bring-over", "init.py")


def python2_only_problems(tree: ast.AST) -> list[str]:
    """Constructs Jython 2.7 cannot load (or that this file promises not to use), by name and line."""
    forbidden = {
        "f-string": ast.JoinedStr, "annotated assignment": ast.AnnAssign, "walrus": ast.NamedExpr, "nonlocal": ast.Nonlocal,
        "yield from": ast.YieldFrom, "await": ast.Await, "async def": ast.AsyncFunctionDef, "async for": ast.AsyncFor,
        "async with": ast.AsyncWith, "match statement": ast.Match, "except*": ast.TryStar,
    }
    problems = []
    for node in ast.walk(tree):
        for name, kind in forbidden.items():
            if isinstance(node, kind):
                problems.append(f"{name} at line {node.lineno}")
        if isinstance(node, ast.Raise) and node.cause is not None:
            problems.append(f"raise ... from at line {node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            problems.append(f"print at line {node.lineno}: use the tab's buffer or callbacks.printOutput")
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            arguments = node.args
            if arguments.kwonlyargs or arguments.posonlyargs:
                problems.append(f"keyword-only or positional-only arguments at line {node.lineno}")
            if isinstance(node, ast.FunctionDef):
                if node.returns is not None or any(arg.annotation for arg in [*arguments.args, *arguments.kwonlyargs]):
                    problems.append(f"annotation at line {node.lineno}")
        if isinstance(node, ast.Starred) and isinstance(node.ctx, ast.Store):
            problems.append(f"starred assignment at line {node.lineno}")
        if isinstance(node, ast.Dict) and None in node.keys:
            problems.append(f"dict unpacking at line {node.lineno}")
    return problems


def jython_or_reason(needs_venv: bool) -> tuple[str | None, str | None]:
    """(jython jar, None) when the Jython self-checks can run here, else (None, why not)."""
    try:
        java = subprocess.run(["java", "-version"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None, "no Java runtime (running java failed)"
    if java.returncode != 0:  # the macOS /usr/bin/java stub exists without a runtime, so run it rather than search PATH
        return None, "no Java runtime (java -version failed)"
    jar = os.environ.get("VULNREPORT_JYTHON_JAR", "")
    if not jar or not Path(jar).is_file():
        return None, "VULNREPORT_JYTHON_JAR does not name a Jython standalone jar"
    if needs_venv and run.needs_install(hashlib.sha256(run.REQUIREMENTS.read_bytes()).hexdigest()):
        return None, ".venv is not current, and a test must not install packages"
    return jar, None


class BurpFileTests(unittest.TestCase):
    """The extension is one Jython 2.7 file that no compiler checks, so these are what stands between a typo and a tester."""

    def test_burp_file_uses_only_python_2_7_syntax(self) -> None:
        probes = {
            "f-string": 'x = f"{1}"', "annotation": "def f(a: int): pass", "nonlocal": "def f():\n    a = 1\n    def g():\n        nonlocal a",
            "keyword-only": "def f(*, a): pass", "raise from": "raise ValueError() from None", "print": "print('x')",
            "yield from": "def f():\n    yield from x", "walrus": "(a := 1)", "starred": "a, *b = c",
            "async": "async def f(): pass", "match": "match x:\n    case 1: pass",
        }
        for name, snippet in probes.items():
            with self.subTest(probe=name):
                self.assertTrue(python2_only_problems(ast.parse(snippet)), f"the checker missed {name}, so it would pass a file using it")
        self.assertEqual(python2_only_problems(ast.parse(BURP_FILE.read_text(encoding="utf-8"))), [])

    def test_burp_file_shares_only_two_names_with_the_launcher(self) -> None:
        source = BURP_FILE.read_text(encoding="utf-8")
        self.assertIn(f'ADDRESS_LINE = u"{run.ADDRESS_LINE}"', source)
        self.assertIn(f'BURP_FLAG = u"{run.BURP_FLAG}"', source)
        for name in ("VULNREPORT_DATA_DIR", "VULNREPORT_PORT", "VULNREPORT_JYTHON_JAR", run.DATA_ENV):
            self.assertNotIn(name, source, f"{name} must stay out of the extension: the data folder and port are app/init.py's alone")
        self.assertEqual(set(re.findall(r"VULNREPORT_\w+", source)), {run.BURP_FLAG})

    def test_burp_file_only_runs_launcher_commands_that_exist(self) -> None:
        """The extension calls app/init.py with these flags, so app/init.py must still understand them."""
        source = BURP_FILE.read_text(encoding="utf-8")
        launcher_source = (REPO / "app" / "init.py").read_text(encoding="utf-8")
        found = re.findall(r'launcher_file\([^)]*\)\.getPath\(\), u"(--[a-z-]+)"', source)
        self.assertGreaterEqual(len(found), 2, "the pattern matched nothing: the way the extension calls the launcher changed")
        self.assertEqual(set(found), {"--data-status", "--bring-over"}, "the extension's calls into the launcher changed; update this pin")
        for flag in sorted(set(found)):
            self.assertIn(f'"{flag}"', launcher_source, f"the extension passes {flag} to the launcher, which does not read it")

    def test_burp_file_names_the_launcher_once_and_by_its_current_path(self) -> None:
        source = BURP_FILE.read_text(encoding="utf-8")
        self.assertEqual(source.count('File(File(app_folder, u"app"), u"init.py")'), 1, "the path is written in one helper")
        self.assertEqual(len(re.findall(r"launcher_file\(", source)), 5, "the helper, plus its four users")
        self.assertNotIn("run.py", source, "the Burp file must never need to know the default build's launcher exists")
        self.assertTrue((REPO / "app" / "init.py").is_file(), "the file the extension starts exists where it says")


class DefaultLauncherTests(unittest.TestCase):
    """run.py carries its own copy of app/init.py's shared logic (Q3/Q8): these prove the copy is sound."""

    def test_run_py_has_no_fragment_of_the_burp_build(self) -> None:
        source = DEFAULT_LAUNCHER.read_text(encoding="utf-8").lower()
        for word in BURP_WORDS:
            self.assertNotIn(word, source, f"run.py must not hint that a Burp build exists ({word})")
        # Positive case: the probe words really do appear in the file this build leaves out, so the
        # checks above are not vacuous.
        launcher_source = (REPO / "app" / "init.py").read_text(encoding="utf-8").lower()
        self.assertTrue(any(word in launcher_source for word in BURP_WORDS), "the probe words must exist somewhere")

    def test_run_py_is_the_release_root_launcher(self) -> None:
        """Unlike app/init.py, which sits one level inside app/, run.py sits at the release root itself."""
        self.assertEqual(default_launcher.ROOT, REPO)
        self.assertEqual(default_launcher.VENV_DIR, REPO / ".venv")
        self.assertEqual(default_launcher.REQUIREMENTS, REPO / "requirements.txt")
        self.assertTrue(default_launcher.REQUIREMENTS.is_file(), "ROOT must be the folder that holds requirements.txt")

    def guard_root(self, folder: Path) -> subprocess.CompletedProcess:
        code = "import run; run.LOCK_WAIT = 0.3; run.guard_start()"
        return subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, env={**os.environ, run.DATA_ENV: str(folder)}, capture_output=True, text=True, timeout=60
        )

    def test_run_py_also_refuses_a_second_start_on_the_same_data_folder(self) -> None:
        """The locking code is copied, not shared (Q3/Q8): prove the copy still enforces one server per folder."""
        with tempfile.TemporaryDirectory() as directory:
            holder = hold_lock(Path(directory))
            try:
                refused = self.guard_root(Path(directory))
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(f"already running on {directory}", refused.stderr)
            finally:
                release(holder)


class ReleaseTests(unittest.TestCase):
    def test_default_release_zip_has_run_py_at_the_root_and_nothing_burp(self) -> None:
        with tempfile.TemporaryDirectory() as dist, patch.object(default_release, "DIST", Path(dist)):
            archive = default_release.build_release("Report-Generator-test")
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                launcher = bundle.read("Report-Generator-test/run.py")
        self.assertIn("Report-Generator-test/run.py", names)
        self.assertNotIn("Report-Generator-test/app/init.py", names, "the Burp build's launcher must not ship here")
        self.assertNotIn("Report-Generator-test/report_generator_burp.py", names)
        self.assertEqual(launcher, DEFAULT_LAUNCHER.read_bytes(), "the shipped launcher is the repository's file, byte for byte")
        for name in names:
            top = name.split("/", 2)[1] if name.count("/") >= 1 else ""
            self.assertNotIn(top, {"data", "generated", "burp", "tests"}, f"{name} must not ship")
            self.assertFalse(name.endswith((".jar", ".class")), f"{name}: nothing compiled or downloaded ships")

    def test_burp_release_zip_has_app_init_and_the_burp_file_and_a_renamed_readme(self) -> None:
        with tempfile.TemporaryDirectory() as dist, patch.object(burp_release, "DIST", Path(dist)):
            archive = burp_release.build_release("Report-Generator-Burp-test")
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                burp = bundle.read("Report-Generator-Burp-test/report_generator_burp.py")
                launcher = bundle.read("Report-Generator-Burp-test/app/init.py")
                readme = bundle.read("Report-Generator-Burp-test/README.md")
        self.assertIn("Report-Generator-Burp-test/app/init.py", names)
        self.assertIn("Report-Generator-Burp-test/report_generator_burp.py", names)
        self.assertNotIn("Report-Generator-Burp-test/run.py", names, "one launcher only, where testers are told to find it")
        self.assertNotIn("Report-Generator-Burp-test/README-burp.md", names, "it ships renamed, not under its repository name")
        self.assertEqual(burp, BURP_FILE.read_bytes(), "the shipped extension is the repository's file, byte for byte")
        self.assertEqual(launcher, (REPO / "app" / "init.py").read_bytes())
        self.assertEqual(readme, (REPO / "README-burp.md").read_bytes(), "README-burp.md ships renamed to README.md")
        for name in names:
            top = name.split("/", 2)[1] if name.count("/") >= 1 else ""
            self.assertNotIn(top, {"data", "generated", "burp", "tests"}, f"{name} must not ship")
            self.assertFalse(name.endswith((".jar", ".class")), f"{name}: nothing compiled or downloaded ships")


class JythonSelfCheckTests(unittest.TestCase):
    def run_jython(self, mode: str, data_folder: str, jar: str, timeout: int = 300) -> subprocess.CompletedProcess:
        env = {**os.environ, run.DATA_ENV: data_folder}
        env.pop(run.RELAUNCH_FLAG, None)
        env.pop(run.BURP_FLAG, None)
        command = ["java", "-Djava.awt.headless=true", "-jar", jar, str(BURP_FILE), mode, str(REPO), sys._base_executable]
        return subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout)

    def test_jython_launcher_self_check(self) -> None:
        jar, why = jython_or_reason(needs_venv=True)
        if jar is None:
            self.skipTest(why)
        with tempfile.TemporaryDirectory() as data_folder:
            result = self.run_jython("--self-check", data_folder, jar)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_jython_tab_starts_stops_and_opens_the_browser_once(self) -> None:
        jar, why = jython_or_reason(needs_venv=True)
        if jar is None:
            self.skipTest(why)
        with tempfile.TemporaryDirectory() as data_folder:
            result = self.run_jython("--self-check-panel", data_folder, jar, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_self_check_refuses_a_data_folder_that_has_reports(self) -> None:
        jar, why = jython_or_reason(needs_venv=False)
        if jar is None:
            self.skipTest(why)
        with tempfile.TemporaryDirectory() as data_folder:
            draft = Path(data_folder) / "apps" / "Real" / "2026-09_Annual_x1" / "draft.json"
            draft.parent.mkdir(parents=True)
            draft.write_bytes(b'{"planted": true}')
            before = tree(Path(data_folder))
            result = self.run_jython("--self-check", data_folder, jar, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("holds 1 report", result.stdout)
            self.assertNotIn(run.ADDRESS_LINE, result.stdout, "no server may have been started")
            self.assertEqual(tree(Path(data_folder)), before, "the planted report and its folder must be byte-for-byte as they were")


if __name__ == "__main__":
    unittest.main()
