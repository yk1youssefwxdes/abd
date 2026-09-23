#!/usr/bin/env python3
"""
renew_client_license.py  –  On-Site License Renewal & Extension Tool
====================================================================
Quickly renew or extend a client's license on their PC:
  • Automatically reads the client PC's hardware fingerprint
  • Generates and installs a freshly encrypted license.enc
  • Can extend by N days or set a specific expiry date
  • Immediately runs validation to guarantee the app will start

Usage:
------
  # Extend by 1 year (365 days from today):
  python tools/renew_client_license.py --days 365

  # Extend by 1 month trial (30 days):
  python tools/renew_client_license.py --days 30

  # Set specific end date:
  python tools/renew_client_license.py --end-date 2028-12-31
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.hardware import get_fingerprint_hash
from core.license_utils import encrypt_license_payload, get_license_secret
from core.paths import get_licenses_dir, get_base_dir, get_data_dir


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _info(msg: str) -> None:
    print(f"        {msg}")


def _fail(msg: str) -> None:
    print(f"  [ERR] {msg}", file=sys.stderr)


def renew_license(days: int | None = None, start_date_str: str | None = None, end_date_str: str | None = None) -> bool:
    _banner("LICENSE RENEWAL / EXTENSION")

    today = datetime.date.today()
    start_date = start_date_str or today.isoformat()

    if end_date_str:
        end_date = end_date_str
    elif days:
        end_date = (today + datetime.timedelta(days=days)).isoformat()
    else:
        end_date = (today + datetime.timedelta(days=365)).isoformat()

    # Hardware fingerprint
    try:
        fp = get_fingerprint_hash()
        _info(f"Target PC Fingerprint: {fp[:8]}...{fp[-8:]}")
    except Exception as exc:
        _fail(f"Could not compute hardware fingerprint: {exc}")
        return False

    _info(f"New License Period   : {start_date}  -->  {end_date}")

    payload = {
        "LICENSED_FINGERPRINT": fp,
        "START_DATE": start_date,
        "END_DATE": end_date,
    }

    secret_key = get_license_secret()
    extra_secret = os.getenv("LICENSE_EXTRA_SECRET", "")
    if extra_secret:
        secret_key += extra_secret

    encrypted = encrypt_license_payload(payload, secret_key, "license.enc")
    content = json.dumps(encrypted, indent=2)

    # Write to all standard license locations
    target_dirs = [get_licenses_dir(), get_data_dir(), get_base_dir()]
    for target_dir in target_dirs:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            lic_file = target_dir / "license.enc"
            lic_file.write_text(content, encoding="utf-8")
            _ok(f"Installed license to: {lic_file}")
        except Exception as exc:
            _info(f"Could not write to {target_dir}: {exc}")

    # Immediate self-validation test
    try:
        from core.license import validate_or_exit
        validate_or_exit()
        _ok("VALIDATION SUCCESSFUL! License is active and verified for this PC.")
        return True
    except SystemExit as exc:
        _fail(f"Validation failed: {exc}")
        return False
    except Exception as exc:
        _fail(f"Validation error: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="School ERP On-Site License Renewal Tool")
    parser.add_argument("--days", type=int, default=None, help="Number of days from today (e.g. 30, 365)")
    parser.add_argument("--end-date", type=str, default=None, help="Specific expiry date (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, default=None, help="Specific start date (YYYY-MM-DD)")
    args = parser.parse_args()

    success = renew_license(days=args.days, start_date_str=args.start_date, end_date_str=args.end_date)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
