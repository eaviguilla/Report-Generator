from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# This file lives at the release root, where data/, .venv and requirements.txt sit.
ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV_DIR / ".requirements-sha256"
RELAUNCH_FLAG = "VULNREPORT_BOOTSTRAPPED"

ADDRESS_LINE = "Report Generator is running at "
# The data folder rule is app/main.py's: the variable when set and not empty, else data/ in the app folder.
DATA_ENV = "VULNREPORT_DATA_DIR"
LOCK_NAME = "server.lock"
MOVED_NOTE = "DATA-MOVED.txt"

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


def bootstrap() -> None:
    """Create .venv and install requirements. Does nothing when already current."""
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not needs_install(digest):
        return
    try:
        if not venv_python().is_file():
            print(f"Creating virtual environment in {VENV_DIR}", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        print("Installing dependencies. The first run takes about a minute.", flush=True)
        subprocess.run([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Setup failed ({error.returncode}). Check your network or proxy and run the command again."
        ) from error
    STAMP.write_text(digest + "\n", encoding="utf-8")


def relaunch() -> int:
    """Re-run this script with the virtual environment interpreter."""
    environment = {**os.environ, RELAUNCH_FLAG: "1"}
    try:
        return subprocess.run([str(venv_python()), str(Path(__file__).resolve())], cwd=ROOT, env=environment).returncode
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

def serve() -> None:
    import uvicorn

    port = free_port()
    url = f"http://127.0.0.1:{port}"

    class AnnouncingServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets=sockets)
            if not self.started:
                return
            # Only now is the port bound and the app imported, so this line is a real "ready".
            print(f"{ADDRESS_LINE}{url}", flush=True)
            print("Close this window to stop the application.", flush=True)
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    # Defensive: this already matches where python puts ROOT on sys.path when run as a script, but
    # being explicit costs nothing.
    sys.path.insert(0, str(ROOT))
    server = AnnouncingServer(uvicorn.Config("app.main:app", host="127.0.0.1", port=port))
    try:
        server.run()
    except KeyboardInterrupt:
        # Server.run re-raises the Ctrl+C it captured, after shutting down; uvicorn.run used to swallow it.
        pass


def main() -> int:
    guard_start()
    if inside_venv() or os.environ.get(RELAUNCH_FLAG):
        serve()
        return 0
    bootstrap()
    return relaunch()


if __name__ == "__main__":
    raise SystemExit(main())
