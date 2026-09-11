from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1)


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Back up an existing JSON file and replace it atomically with new content."""
    if path.exists():
        _atomic_write(path.with_suffix(".bak.json"), path.read_bytes())
    _atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def atomic_write_bytes(path: Path, value: bytes) -> None:
    """Atomically replace a binary file without leaving a partial result."""
    _atomic_write(path, value)


def _atomic_write(path: Path, value: bytes) -> None:
    """Write bytes through a unique sibling file and retry transient replacement locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
        for attempt in range(len(REPLACE_RETRY_DELAYS) + 1):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == len(REPLACE_RETRY_DELAYS):
                    raise
                time.sleep(REPLACE_RETRY_DELAYS[attempt])
    finally:
        temporary.unlink(missing_ok=True)
