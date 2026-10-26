"""Serve a throwaway copy of the app for a browser check, then delete it.

    .venv/bin/python -m scripts.ui_check                    # empty manager page
    .venv/bin/python -m scripts.ui_check --report finding   # one report, Setup done, one finding

It uses a temporary data folder and generated/ folder, so nothing under data/ is read or written. It
prints `URL <address>` (and `REPORT <id>` with --report) once the server answers, and serves until it is
stopped (Ctrl-C or kill), which removes the folder. It picks the first port from 8900 to 8999 that it can
bind and serves on that bound socket, so a parallel check cannot take the port in between. Run it in the
background and drive the page with Playwright, using the printed URL.
"""
from __future__ import annotations

import argparse
import errno
import os
import socket
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

PORTS = range(8900, 9000)  # clear of the app's own 8765-8799
STAGES = ("none", "empty", "setup", "finding")


def reserve_port() -> socket.socket:
    """Bind the first free port in PORTS and return the socket, still held. A connect test would call a
    port that another process has bound but not yet listened on free, so only a real bind counts."""
    for port in PORTS:
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as error:
            sock.close()
            # Windows reports a port held by an exclusive bind as EACCES.
            if error.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            continue
        return sock
    raise RuntimeError(f"No free port in {PORTS.start}-{PORTS.stop - 1}")


def free_port() -> int:
    with reserve_port() as sock:
        return sock.getsockname()[1]


def seed_report(workspace, stage: str) -> str | None:
    """Save a report at `stage` and return its ID: `empty` is a blank draft, `setup` passes Setup, and
    `finding` adds one finding with its content. `none` saves nothing."""
    from app import main
    from app.models import ScopeTarget, TestWindow, Vulnerability

    if stage == "none":
        return None
    report = workspace.create_report()
    if stage != "empty":
        report.app_id = "CI-UICHECK"
        report.engagement.app_name = "UI Check"
        report.engagement.ci_number = "CI-UICHECK"
        report.engagement.segment = "JH"
        report.engagement.report_type = "annual_pentest"
        report.engagement.network = "Internal"
        report.engagement.app_owner = "UI Check Owner"
        report.engagement.report_date = date(2026, 1, 3)
        report.engagement.tested_environments = ["production"]
        report.engagement.test_windows = {"production": TestWindow(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))}
        report.scope_targets = [ScopeTarget(target_id="tgt_uicheck", environment="production", channel="web", value="https://prod.example.test")]
    if stage == "finding":
        finding = Vulnerability(
            uid="v_uicheck", title="UI check finding", likelihood="low", impact="low", severity="low",
            status="open_new", scope={"mode": "custom", "target_ids": ["tgt_uicheck"]},
        )
        main.provision(finding)
        report.vulnerabilities = [finding]
        main.sync_evidence_image_slots(finding, report)
    workspace.save(report)
    return report.report_id


def serve(stage: str) -> None:
    import signal

    import uvicorn

    def stop(signum, frame):
        # uvicorn shuts down, then re-raises the signal; the default action would kill the process
        # before the temporary folder below is deleted.
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix="vulnreport-ui-check-") as folder:
        # app.main reads this when it is imported, so it goes in first.
        os.environ["VULNREPORT_DATA_DIR"] = folder
        from unittest.mock import patch

        from app import main

        with patch.object(main, "GENERATED", Path(folder) / "generated"):
            report_id = seed_report(main.workspace, stage)
            sock = reserve_port()
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(main.app, port=port, log_level="warning"))

            def announce() -> None:
                while not server.started and not server.should_exit:
                    time.sleep(0.05)
                if server.started:
                    print(f"URL http://127.0.0.1:{port}", flush=True)
                    if report_id:
                        print(f"REPORT {report_id}", flush=True)

            threading.Thread(target=announce, daemon=True).start()
            # uvicorn serves on the reserved socket, so no other process can take the port in between.
            try:
                server.run(sockets=[sock])
            finally:
                sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a throwaway copy of the app for a browser check")
    parser.add_argument("--report", choices=STAGES, default="none", help="seed one report at this stage (default: none)")
    args = parser.parse_args()
    try:
        serve(args.report)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
