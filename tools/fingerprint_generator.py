#!/usr/bin/env python3
"""
Standalone fingerprint generator for clients.

- No Django or project imports
- Uses PowerShell Get-CimInstance on Windows to collect Machine UUID
  and BaseBoard SerialNumber
- Prints only the SHA-256 fingerprint (one line)
- Never prints raw hardware identifiers
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from typing import Tuple


def _run_powershell(cmd: str) -> str:
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
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                return ln
        return ""
    except Exception:
        return ""


def _collect_windows_uuid_and_baseboard() -> Tuple[str, str]:
    uuid_cmd = "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"
    mb_cmd = "(Get-CimInstance -ClassName Win32_BaseBoard).SerialNumber"

    uuid = _run_powershell(uuid_cmd)
    mb = _run_powershell(mb_cmd)
    return uuid, mb


def get_fingerprint_hash() -> str:
    if platform.system().lower() == "windows":
        uuid_val, mb_val = _collect_windows_uuid_and_baseboard()
    else:
        uuid_val = platform.node() or ""
        mb_val = ""

    combined = "|".join([uuid_val, mb_val])
    digest = hashlib.sha256(combined.encode('utf-8')).hexdigest()

    # Cleanup
    uuid_val = mb_val = combined = None

    return digest


def main() -> None:
    print(get_fingerprint_hash())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
