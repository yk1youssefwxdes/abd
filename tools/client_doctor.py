#!/usr/bin/env python3
"""
client_doctor.py  –  School ERP On-Site System Diagnostic Tool
===============================================================
Run this tool on the client's machine to diagnose any issues:
  • Python & runtime environment
  • Node.js & WhatsApp microservice
  • License validity, hardware fingerprint match & days remaining
  • Database file location, WAL status & PRAGMA integrity check
  • Port 8000 (Web) & Port 3000 (WhatsApp) status
  • Local Network IP address for LAN access
  • Disk space availability

Usage:
------
  python tools/client_doctor.py
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _color(text: str, code: str) -> str:
    # ANSI color if terminal supports it
    if sys.platform != "win32" or "WT_SESSION" in os.environ or "ANSICON" in os.environ:
        return f"\033[{code}m{text}\033[0m"
    return text


def ok(msg: str) -> None:
    print(f"  [{_color('OK', '32')}]   {msg}")


def warn(msg: str) -> None:
    print(f"  [{_color('WARN', '33')}] {msg}")


def fail(msg: str) -> None:
    print(f"  [{_color('FAIL', '31')}] {msg}")


def info(msg: str) -> None:
    print(f"         {msg}")


def header(title: str) -> None:
    print(f"\n{'=' * 64}\n  {title}\n{'=' * 64}")


# ============================================================
# Checks
# ============================================================

def check_system() -> None:
    header("1. Operating System & Hardware")
    info(f"OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})")
    info(f"Machine Name: {platform.node()}")

    # Disk Space Check
    try:
        drive = Path(PROJECT_ROOT).drive or "/"
        total, used, free = shutil.disk_usage(drive)
        free_gb = free / (1024 ** 3)
        if free_gb < 2:
            warn(f"Low disk space on {drive}: {free_gb:.1f} GB free")
        else:
            ok(f"Disk space on {drive}: {free_gb:.1f} GB free")
    except Exception as exc:
        info(f"Disk space check skipped: {exc}")


def check_python() -> None:
    header("2. Python Environment & Core Modules")
    info(f"Python Executable : {sys.executable}")
    info(f"Python Version    : {platform.python_version()}")

    modules = [
        ("django", "Django Framework"),
        ("cryptography", "Cryptography / Fernet"),
        ("whitenoise", "WhiteNoise Static Server"),
        ("waitress", "Waitress Production WSGI"),
    ]

    for mod, desc in modules:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "available")
            ok(f"{desc} ({mod} {ver})")
        except ImportError:
            fail(f"Missing required package: {mod} ({desc})")


def check_license() -> None:
    header("3. License & Hardware Fingerprint")
    try:
        from core.hardware import get_fingerprint_hash
        current_fp = get_fingerprint_hash()
        info(f"Current PC Fingerprint: {current_fp}")
    except Exception as exc:
        fail(f"Could not compute hardware fingerprint: {exc}")
        return

    try:
        from core.license import _load_license_data, _WILDCARD_FINGERPRINT
        lic = _load_license_data()
        lic_fp = lic.get("LICENSED_FINGERPRINT", "")
        start_str = lic.get("START_DATE", "")
        end_str = lic.get("END_DATE", "")

        info(f"License Fingerprint  : {lic_fp}")
        info(f"Active Period        : {start_str}  -->  {end_str}")

        # Check fingerprint match
        if lic_fp == _WILDCARD_FINGERPRINT or lic_fp == "*":
            ok("License Mode: Wildcard (valid for any device)")
        elif lic_fp == current_fp:
            ok("Fingerprint matches this PC exactly")
        else:
            fail("FINGERPRINT MISMATCH! License is locked to a different PC.")

        # Check dates
        try:
            end_date = datetime.date.fromisoformat(end_str)
            today = datetime.date.today()
            days_left = (end_date - today).days

            if days_left < 0:
                fail(f"LICENSE EXPIRED! Expired {abs(days_left)} days ago on {end_str}")
            elif days_left <= 7:
                warn(f"LICENSE EXPIRING SOON! Only {days_left} days left (expires {end_str})")
            else:
                ok(f"License valid ({days_left} days remaining until {end_str})")
        except Exception as exc:
            fail(f"Invalid date format in license: {exc}")

    except SystemExit as exc:
        fail(f"License validation rejected: {exc}")
    except Exception as exc:
        fail(f"License error: {exc}")


def check_database() -> None:
    header("4. SQLite Database & Storage")
    try:
        from core.paths import get_database_path, get_data_dir
        data_dir = get_data_dir()
        db_path = get_database_path()

        info(f"Data Directory : {data_dir}")
        info(f"Database Path  : {db_path}")

        if not db_path.exists():
            fail(f"Database file not found at: {db_path}")
            return

        size_mb = db_path.stat().st_size / (1024 * 1024)
        ok(f"Database file exists ({size_mb:.2f} MB)")

        # Integrity Check
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            if res and res[0] == "ok":
                ok("Database integrity: OK (no corruption detected)")
            else:
                fail(f"Database integrity issue: {res}")

            # WAL check
            cur.execute("PRAGMA journal_mode;")
            journal_mode = cur.fetchone()
            info(f"SQLite Journal Mode: {journal_mode[0].upper() if journal_mode else 'UNKNOWN'}")
            conn.close()
        except Exception as exc:
            fail(f"Cannot query database: {exc}")

    except Exception as exc:
        fail(f"Database check error: {exc}")


def check_node_and_whatsapp() -> None:
    header("5. Node.js & WhatsApp Service")
    node_exe = shutil.which("node") or shutil.which("node.exe")
    if node_exe:
        try:
            ver = subprocess.check_output([node_exe, "-v"], text=True).strip()
            ok(f"Node.js found: {ver} ({node_exe})")
        except Exception as exc:
            warn(f"Node.js execution failed: {exc}")
    else:
        fail("Node.js is NOT installed or not in PATH! WhatsApp service cannot run.")

    wa_dir = PROJECT_ROOT / "whatsapp_service"
    node_modules = wa_dir / "node_modules"
    if node_modules.is_dir() and any(node_modules.iterdir()):
        ok("whatsapp_service node_modules installed")
    else:
        fail("whatsapp_service/node_modules missing! Run: cd whatsapp_service && npm install --omit=dev")

    # Check if WhatsApp service is responding on port 3000
    try:
        req = urllib.request.Request("http://127.0.0.1:3000/status", headers={"User-Agent": "SchoolERP-Doctor"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ok(f"WhatsApp service is actively RUNNING on port 3000 (status: {data.get('status', 'online')})")
    except Exception:
        info("WhatsApp service is not currently running on port 3000 (will launch with run_server.py).")


def check_network_and_ports() -> None:
    header("6. Network & Ports")

    # Get local LAN IP address
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        ok(f"Local Network (LAN) IP: {local_ip}")
        info(f"Other PCs on school network can access: http://{local_ip}:8000")
    except Exception:
        info(f"Local IP: {local_ip}")

    # Port checks
    for port, name in [(8000, "Django Web Server"), (3000, "WhatsApp Microservice")]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        if result == 0:
            ok(f"Port {port} ({name}) is OPEN / IN USE")
        else:
            info(f"Port {port} ({name}) is currently FREE")


def main() -> int:
    print("=" * 64)
    print("       SCHOOL ERP - CLIENT SYSTEM DIAGNOSTIC (DOCTOR)")
    print("=" * 64)
    print(f"Time : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Root : {PROJECT_ROOT}")

    check_system()
    check_python()
    check_license()
    check_database()
    check_node_and_whatsapp()
    check_network_and_ports()

    print("\n" + "=" * 64)
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 64 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
