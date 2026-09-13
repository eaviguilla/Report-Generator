"""
VulnReport -- tester identity bootstrap.

Resolves the tester's display name ONCE on first launch and stores it in
data/prefs.json. It then prefills engagement.tester on every new report, so the
tester never types their own name again.

Based on secur32.GetUserNameExW with EXTENDED_NAME_FORMAT.NameDisplay (= 3),
which returns the Active Directory display name, e.g. "Viguilla, Elias Angelo".

WHY THIS IS LONGER THAN THE 15-LINE REFERENCE SCRIPT
----------------------------------------------------
The reference version works on a domain-joined Windows machine and fails
silently everywhere else. Four things are handled here that it does not:

  1. NOT DOMAIN-JOINED.  NameDisplay fails with ERROR_NONE_MAPPED (1332) on a
     local/workgroup account. The reference script ignores the return value and
     prints an empty string. We check it and fall through.

  2. NON-WINDOWS.  ctypes.windll does not exist off Windows -- AttributeError
     at import time. Guarded by sys.platform.

  3. RETURN VALUES.  GetUserNameExW returns 0 on failure. The size-probe call
     is EXPECTED to fail with ERROR_MORE_DATA (234); any other error means the
     format is unavailable and we must not allocate from a garbage size.

  4. NAME ORDER.  AD may hold "Surname, Given" or "Given Surname". We store
     both the raw value and a normalised one, and the tester can always edit it.

Auto-detection is a convenience, never an authority. An AD display name is
frequently not what belongs on a client deliverable.

Standalone:
    python tester_identity.py
    python tester_identity.py --json
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

# EXTENDED_NAME_FORMAT -- winbase.h
NAME_UNKNOWN = 0
NAME_FULLY_QUALIFIED_DN = 1
NAME_SAM_COMPATIBLE = 2      # "DOMAIN\\username"  -- works off-domain too
NAME_DISPLAY = 3             # "Viguilla, Elias Angelo"  -- what we want

ERROR_MORE_DATA = 234        # expected from the size-probe call
ERROR_NONE_MAPPED = 1332     # format unavailable (not domain-joined)


@dataclass
class Identity:
    resolved_name: str       # exactly what the OS returned
    display_name: str        # what goes into reports (normalised, editable)
    source: str              # which method succeeded
    confirmed: bool = False  # has the tester approved it?


# =============================================================================
# WINDOWS
# =============================================================================

def _get_user_name_ex(fmt: int) -> str | None:
    """Two-call GetUserNameExW. Returns None if the format is unavailable."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        secur32 = ctypes.WinDLL("secur32", use_last_error=True)
        secur32.GetUserNameExW.argtypes = [
            ctypes.c_int, wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG)]
        secur32.GetUserNameExW.restype = wintypes.BOOLEAN

        size = wintypes.ULONG(0)

        # Probe. Expected to FAIL with ERROR_MORE_DATA and set `size`.
        if secur32.GetUserNameExW(fmt, None, ctypes.byref(size)):
            return None                                  # unexpected success
        err = ctypes.get_last_error()
        if err != ERROR_MORE_DATA or size.value == 0:
            return None                                  # e.g. ERROR_NONE_MAPPED

        buf = ctypes.create_unicode_buffer(size.value)
        if not secur32.GetUserNameExW(fmt, buf, ctypes.byref(size)):
            return None

        return buf.value.strip() or None
    except (OSError, AttributeError, ImportError):
        return None


# =============================================================================
# NORMALISATION
# =============================================================================

def normalise(raw: str) -> str:
    """'Viguilla, Elias Angelo' -> 'Elias Angelo Viguilla'.
    Only flips on a single comma; anything else is returned untouched."""
    if raw.count(",") == 1:
        surname, given = (p.strip() for p in raw.split(","))
        if surname and given:
            return f"{given} {surname}"
    return raw.strip()


def _strip_domain(sam: str) -> str:
    """Remove an optional Windows DOMAIN\\ prefix from a login name."""
    return sam.split("\\", 1)[1] if "\\" in sam else sam


# =============================================================================
# RESOLUTION
# =============================================================================

def resolve_identity() -> Identity:
    """Fallback chain. Always returns an Identity; display_name may be ''."""

    if (raw := _get_user_name_ex(NAME_DISPLAY)):
        return Identity(raw, normalise(raw), "NameDisplay")

    if (raw := _get_user_name_ex(NAME_SAM_COMPATIBLE)):
        return Identity(raw, _strip_domain(raw), "NameSamCompatible")

    try:
        if (raw := getpass.getuser().strip()):
            return Identity(raw, raw, "getpass")
    except Exception:
        pass

    for var in ("USERNAME", "USER", "LOGNAME"):
        if (raw := (os.environ.get(var) or "").strip()):
            return Identity(raw, raw, f"env:{var}")

    return Identity("", "", "unresolved")


# =============================================================================
# PREFS
# =============================================================================

PREFS_SCHEMA = "1.4"
# The only library the app reads or writes. vuln_library.json at the root is an untracked local backup.
LIBRARY_PATH = "resources/vuln_library.json"


class TesterPreferences(BaseModel):
    resolved_name: str = ""
    display_name: str = ""
    source: str = "unresolved"
    confirmed: bool = False


class ReportDefaults(BaseModel):
    classification: str = "Confidential"
    template_set: str = "default-v1"


class Preferences(BaseModel):
    schema_version: Literal["1.4"] = PREFS_SCHEMA
    tester: TesterPreferences | None = None
    defaults: ReportDefaults = Field(default_factory=ReportDefaults)
    library_path: str = LIBRARY_PATH

    @field_validator("library_path")
    @classmethod
    def validate_library_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("library_path cannot be empty")
        # The root copy is a local backup only; point any prefs file still naming it at the real library.
        return LIBRARY_PATH if value.strip() == "vuln_library.json" else value.strip()


def load_or_bootstrap(prefs_path: Path) -> dict:
    """Called by run.py at startup. Resolves identity only on first launch;
    never overwrites a name the tester has confirmed."""
    prefs = Preferences()
    should_write = not prefs_path.exists()
    if prefs_path.exists():
        try:
            prefs = Preferences.model_validate_json(prefs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValidationError):
            backup = prefs_path.with_suffix(".corrupt.json")
            backup.unlink(missing_ok=True)
            prefs_path.replace(backup)
            print(f"  prefs.json was unreadable; moved to {backup.name}")
            prefs = Preferences()
            should_write = True

    if prefs.tester is None:
        ident = resolve_identity()
        prefs.tester = TesterPreferences.model_validate(asdict(ident))
        should_write = True

    if should_write:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = prefs_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs.model_dump(mode="json"), indent=2), encoding="utf-8")
        os.replace(tmp, prefs_path)

    return prefs.model_dump(mode="json")


if __name__ == "__main__":
    ident = resolve_identity()
    if "--json" in sys.argv:
        print(json.dumps(asdict(ident), indent=2))
    else:
        print(f"platform      {sys.platform}")
        print(f"source        {ident.source}")
        print(f"resolved_name {ident.resolved_name!r}")
        print(f"display_name  {ident.display_name!r}")
        if ident.source == "unresolved":
            print("\n  Could not resolve a name. The tester must enter it manually.")
        elif ident.source != "NameDisplay":
            print("\n  NameDisplay unavailable (machine is likely not domain-joined).")
            print("  Fell back -- the tester should confirm this name in Settings.")
