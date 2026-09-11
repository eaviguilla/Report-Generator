from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV_DIR / ".requirements-sha256"
RELAUNCH_FLAG = "VULNREPORT_BOOTSTRAPPED"


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


def serve() -> None:
    import uvicorn

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Report Generator is running at {url}")
    print("Close this window to stop the application.")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    if inside_venv() or os.environ.get(RELAUNCH_FLAG):
        serve()
    else:
        bootstrap()
        raise SystemExit(relaunch())
