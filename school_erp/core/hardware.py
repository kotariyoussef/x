"""
Hardware fingerprint collection utilities.

Security notes:
- Raw hardware identifiers are never written to disk or logged.
- Only the SHA-256 hash of the combined identifiers is returned.
- Keep this file minimal and avoid importing Django or other heavy modules.
"""
from __future__ import annotations

import hashlib
import platform
import shlex
import subprocess
from typing import Tuple


def _run_powershell(cmd: str) -> str:
    """Run a PowerShell command and return the trimmed output or empty string.

    Uses `powershell` executable which is present on modern Windows systems.
    We run in non-interactive, no-profile mode to reduce startup overhead.
    """
    try:
        full_cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            cmd,
        ]
        out = subprocess.check_output(full_cmd, stderr=subprocess.DEVNULL)
        text = out.decode(errors='ignore')
        # Return the first non-empty trimmed line
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                return ln
        return ""
    except Exception:
        return ""


def _collect_windows_uuid_and_baseboard() -> Tuple[str, str]:
    """Collect Machine UUID and motherboard serial using Get-CimInstance.

    Returns (uuid, baseboard_serial). If commands fail, empty strings are
    returned for missing values.
    """
    # Use Get-CimInstance which is available in PowerShell on Win10/11
    uuid_cmd = "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"
    mb_cmd = "(Get-CimInstance -ClassName Win32_BaseBoard).SerialNumber"

    uuid = _run_powershell(uuid_cmd)
    mb = _run_powershell(mb_cmd)
    return uuid, mb


def get_fingerprint_hash() -> str:
    """Return SHA-256 hash of the stable machine identifiers.

    Only Machine UUID and Motherboard Serial Number are used to increase
    stability across common hardware changes (disk/CPU replacement).
    The raw identifiers are never returned or logged.
    """
    if platform.system().lower() == "windows":
        uuid_val, mb_val = _collect_windows_uuid_and_baseboard()
    else:
        # Non-windows fallback: use platform.node() as UUID and empty baseboard
        uuid_val = platform.node() or ""
        mb_val = ""

    combined = "|".join([uuid_val, mb_val])
    digest = hashlib.sha256(combined.encode('utf-8')).hexdigest()

    # Short-lived cleanup
    uuid_val = mb_val = combined = None

    return digest
