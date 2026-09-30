from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# This file lives in app/, so the release root, where data/, .venv and requirements.txt sit, is one level up.
# It is the same expression app/main.py uses.
ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV_DIR / ".requirements-sha256"
RELAUNCH_FLAG = "VULNREPORT_BOOTSTRAPPED"

# The three names below are shared with the Burp extension (report_generator_burp.py, at the release root), which starts
# this script and reads its output. A test pins them on both sides.
BURP_FLAG = "VULNREPORT_STARTED_BY_BURP"
ADDRESS_LINE = "Report Generator is running at "
# The data folder rule is app/main.py's: the variable when set and not empty, else data/ in the app folder.
DATA_ENV = "VULNREPORT_DATA_DIR"
LOCK_NAME = "server.lock"
MOVED_NOTE = "DATA-MOVED.txt"

# Modules app.main loads when it is imported, compiled parts included: a copied .venv that passes this
# import can start the app. jinja2 and PIL._imaging are the two a plain `import PIL` would not exercise.
VENV_PROBE_MODULES = ["fastapi", "uvicorn", "pydantic", "jinja2", "python_multipart", "docx", "PIL._imaging"]

LOCK_WAIT = 5.0  # seconds a start waits for a stopping server to let go of the lock
_server_lock = None  # held for the life of the process; the operating system releases it on any death


def venv_python() -> Path:
    """Interpreter inside the project virtual environment."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def inside_venv() -> bool:
    """True when this interpreter is the project virtual environment.

    Compares prefixes rather than executables: on macOS and Linux the venv
    interpreter is a symlink to the system one, so resolved paths are equal.
    """
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def needs_install(digest: str) -> bool:
    """True unless the virtual environment already holds these exact requirements."""
    if not venv_python().is_file():
        return True
    if not STAMP.is_file():
        return True
    return STAMP.read_text(encoding="utf-8").strip() != digest


def started_by_burp() -> bool:
    return os.environ.get(BURP_FLAG) == "1"


def child_streams() -> dict:
    """Under Burp, hand the launcher's own pipes to every child.

    On Windows a child gets no standard handles unless they are passed, so without this the server
    would neither show its output in the tab nor see the tab close its input.
    """
    if started_by_burp():
        return {"stdin": sys.stdin, "stdout": sys.stdout, "stderr": sys.stderr}
    return {}


def bootstrap() -> None:
    """Create .venv and install requirements. Does nothing when already current."""
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not needs_install(digest):
        return
    try:
        if not venv_python().is_file():
            print(f"Creating virtual environment in {VENV_DIR}", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True, **child_streams())
        print("Installing dependencies. The first run takes about a minute.", flush=True)
        subprocess.run([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True, **child_streams())
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Setup failed ({error.returncode}). Check your network or proxy and run the command again."
        ) from error
    STAMP.write_text(digest + "\n", encoding="utf-8")


def relaunch() -> int:
    """Re-run this script with the virtual environment interpreter."""
    environment = {**os.environ, RELAUNCH_FLAG: "1"}
    try:
        return subprocess.run(
            [str(venv_python()), str(Path(__file__).resolve())], cwd=ROOT, env=environment, **child_streams()
        ).returncode
    except KeyboardInterrupt:
        return 0


def free_port() -> int:
    """Find the first unused loopback port in the local application range."""
    for port in range(8765, 8800):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found")


# --- the data folder, and one server per folder ------------------------------------------------------

def data_dir() -> Path:
    """The folder app.main will serve, by app.main's own rule.

    A relative value is read against the directory this process was started in. app.main would read it
    against its own working directory, which differs for the relaunched child, so pin_data_dir() writes
    the absolute form back to the environment before the child exists.
    """
    value = os.environ.get(DATA_ENV)
    return Path(os.path.abspath(value)) if value else ROOT / "data"


def pin_data_dir() -> None:
    if os.environ.get(DATA_ENV):
        os.environ[DATA_ENV] = str(data_dir())


def count_reports(folder: Path) -> int:
    """Reports the workspace would find in a data folder: every apps/*/*/draft.json, readable or not."""
    return sum(1 for _ in (folder / "apps").glob("*/*/draft.json"))


def _try_lock(handle) -> bool:
    """One non-blocking attempt at an exclusive lock on the first byte."""
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, 0)
        return True
    except OSError:
        return False


def take_server_lock(folder: Path, wait: float | None = None):
    """Lock `folder`/server.lock for as long as the returned handle stays open, or return None.

    Waits a few seconds, so a Start right after a Stop is not refused while the old process is still
    letting go. A record lock is used because Java's FileChannel.tryLock takes the same kind.
    """
    wait = LOCK_WAIT if wait is None else wait
    folder.mkdir(parents=True, exist_ok=True)
    handle = (folder / LOCK_NAME).open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + wait
    while not _try_lock(handle):
        if time.monotonic() >= deadline:
            handle.close()
            return None
        time.sleep(0.2)
    return handle


def lock_is_held(folder: Path) -> bool:
    """Whether a server holds this folder's lock. Creates nothing: no lock file means no server."""
    lock_file = folder / LOCK_NAME
    if not lock_file.is_file():
        return False
    try:
        handle = lock_file.open("r+b")
    except OSError:
        return False
    with handle:
        return not _try_lock(handle)


def guard_start() -> None:
    """Refuse to start a second server on one data folder, or on a folder whose data has moved away.

    The relaunched child skips this: its parent, which stays alive while it serves, already holds the lock.
    """
    global _server_lock
    if os.environ.get(RELAUNCH_FLAG):
        return
    pin_data_dir()
    note = ROOT / MOVED_NOTE
    if note.is_file() and not os.environ.get(DATA_ENV):
        raise SystemExit(note.read_text(encoding="utf-8").strip())
    folder = data_dir()
    _server_lock = take_server_lock(folder)
    if _server_lock is None:
        raise SystemExit(f"Report Generator is already running on {folder}. Use that one, or stop it first.")


# --- serving -----------------------------------------------------------------------------------------

def _stop_at_end_of_input(server) -> None:
    """Under Burp, the tab closing our input is the request to stop: same flag uvicorn's signal handler sets."""
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return
    try:
        while stream.read(4096):
            pass
    except (OSError, ValueError):
        pass
    server.should_exit = True


def serve() -> None:
    import uvicorn

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    from_burp = started_by_burp()

    class AnnouncingServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets=sockets)
            if not self.started:
                return
            # Only now is the port bound and the app imported, so this line is a real "ready".
            print(f"{ADDRESS_LINE}{url}", flush=True)
            if not from_burp:
                print("Close this window to stop the application.", flush=True)
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    # Run as a script path (python app/init.py), Python searches app/ for modules, not the release root, and
    # uvicorn.Config adds no directory of its own, so "app.main" would not import. Here rather than at the top
    # of the file so importing this module (tests, --data-status) has no side effect.
    sys.path.insert(0, str(ROOT))
    server = AnnouncingServer(uvicorn.Config("app.main:app", host="127.0.0.1", port=port))
    if from_burp:
        threading.Thread(target=_stop_at_end_of_input, args=(server,), daemon=True).start()
    try:
        server.run()
    except KeyboardInterrupt:
        # Server.run re-raises the Ctrl+C it captured, after shutting down; uvicorn.run used to swallow it.
        pass


# --- commands for the Burp extension (standard library only: they run before .venv exists) -----------

def data_status() -> int:
    """One JSON line about the data folder. Reads only: it must never create or change anything."""
    folder = data_dir()
    print(json.dumps({
        "data": str(folder),
        "reports": count_reports(folder),
        "locked": lock_is_held(folder),
        "venv": venv_python().is_file(),
    }), flush=True)
    return 0


def _refuse(message: str) -> int:
    print(f"Nothing was moved. {message}", file=sys.stderr, flush=True)
    return 1


def _is_inside(inner: Path, outer: Path) -> bool:
    return outer == inner or outer in inner.parents


def _venv_imports_cleanly(interpreter: Path) -> bool:
    modules = list(VENV_PROBE_MODULES) + (["win32com.client"] if os.name == "nt" else [])
    code = "import " + ", ".join(modules)
    try:
        return subprocess.run([str(interpreter), "-c", code], capture_output=True, timeout=180).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def bring_over(old_argument: str) -> int:
    """Move a previous release's data (and finished documents) here, then copy its .venv.

    Every check comes first and changes nothing. The data folder is renamed, never copied, so there is
    one store, and nothing is deleted: an empty data folder a Start already made here is set aside.
    """
    if not old_argument:
        return _refuse("Give the previous release folder: app/init.py --bring-over <folder>.")
    if os.environ.get(DATA_ENV):
        return _refuse(f"{DATA_ENV} is set, so the data folder is not inside this release. Move it by hand (see README.md).")
    old = Path(old_argument).resolve()
    if _is_inside(old, ROOT) or _is_inside(ROOT, old):
        return _refuse("That is this folder, or contains it or sits inside it. Choose the previous release folder.")
    # A release from before the launcher moved has run.py at its root; a current one has app/init.py.
    if not ((old / "run.py").is_file() or (old / "app" / "init.py").is_file()):
        return _refuse(f"{old} has neither run.py nor app/init.py, so it is not a Report Generator folder.")
    if (old / MOVED_NOTE).is_file():
        return _refuse(f"{old} was already moved: {(old / MOVED_NOTE).read_text(encoding='utf-8').strip()}")
    old_data, new_data = old / "data", ROOT / "data"
    if count_reports(old_data) == 0:
        return _refuse(f"{old_data} holds no reports.")
    if count_reports(new_data) != 0:
        return _refuse(f"{new_data} already holds reports. Bringing more in would need merging by hand (see README.md).")
    if lock_is_held(old_data):
        return _refuse("The previous release is still running. Stop it first.")
    if lock_is_held(new_data):
        return _refuse("A server is already running in this folder. Stop it first.")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = None
    try:
        if new_data.exists():
            aside = ROOT / f"data.before-move-{stamp}"
            os.rename(new_data, aside)
            print(f"Set aside the empty data folder as {aside.name}.", flush=True)
        os.rename(old_data, new_data)
    except OSError as error:
        if aside is not None and not new_data.exists():
            os.rename(aside, new_data)
        if error.errno == errno.EXDEV:
            return _refuse("The previous folder is on another drive, which a rename cannot cross. Move data by hand (see README.md).")
        return _refuse(f"{error}. If the previous release is still running, stop it first.")
    print(f"Moved {old_data} to {new_data}.", flush=True)

    old_generated, new_generated = old / "generated", ROOT / "generated"
    if old_generated.is_dir():
        leftovers = [child for child in new_generated.iterdir() if child.name != ".gitkeep"] if new_generated.is_dir() else []
        if leftovers:
            print("This folder's generated/ is not empty, so the previous finished documents stay where they are.", flush=True)
        else:
            try:
                if new_generated.exists():
                    os.rename(new_generated, ROOT / f"generated.before-move-{stamp}")
                os.rename(old_generated, new_generated)
                print(f"Moved {old_generated} to {new_generated}.", flush=True)
            except OSError as error:
                print(f"Finished documents were not moved: {error}", flush=True)

    try:
        (old / MOVED_NOTE).write_text(
            f"Report Generator data moved to {ROOT} on {datetime.now():%Y-%m-%d}. Start the copy there.\n", encoding="utf-8"
        )
    except OSError as error:
        print(f"Could not leave a note in {old}: {error}", flush=True)

    if not VENV_DIR.exists() and (old / ".venv").is_dir():
        print("Copying the previous .venv so dependencies are not downloaded again...", flush=True)
        try:
            shutil.copytree(old / ".venv", VENV_DIR, symlinks=True)
            copied = _venv_imports_cleanly(venv_python())
        except (OSError, shutil.Error):
            copied = False
        if copied:
            print("The copied .venv works.", flush=True)
        else:
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            print("The copied .venv did not pass its check and was removed; the first Start will rebuild it.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--data-status"]:
        return data_status()
    if argv[:1] == ["--bring-over"]:
        return bring_over(argv[1] if len(argv) > 1 else "")
    guard_start()
    if inside_venv() or os.environ.get(RELAUNCH_FLAG):
        serve()
        return 0
    bootstrap()
    return relaunch()


if __name__ == "__main__":
    raise SystemExit(main())
