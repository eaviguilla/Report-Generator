from __future__ import annotations

import socket
import threading
import webbrowser

import uvicorn


def free_port() -> int:
    """Find the first unused loopback port in the local application range."""
    for port in range(8765, 8800):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found")


if __name__ == "__main__":
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"VulnReport is running at {url}")
    print("Close this window to stop the application.")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
