#!/usr/bin/env python3
"""
Vendor-side license creation tool for School ERP.

Generates AES-GCM encrypted runtime license files (license.enc) compatible
with core.license and core.license_utils.

Usage examples:
    # 1-year license locked to specific client fingerprint:
    python tools/create_license.py --fingerprint <FP> --days 365 --out license.enc

    # Wildcard license valid for 30-day trial:
    python tools/create_license.py --wildcard --days 30 --out license.enc

    # Specific date range:
    python tools/create_license.py --fingerprint <FP> --start 2026-09-01 --end 2027-09-01 --out license.enc

    # Also save unencrypted JSON definition:
    python tools/create_license.py --wildcard --days 365 --source-json tools/license_source.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.license_utils import encrypt_license_payload, get_license_secret


def build_license_payload(
    fingerprint: str,
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    days: int | None = None,
) -> Dict[str, Any]:
    today = datetime.date.today()

    if start_date_str:
        start_date = datetime.date.fromisoformat(start_date_str)
    else:
        start_date = today

    if end_date_str:
        end_date = datetime.date.fromisoformat(end_date_str)
    elif days is not None:
        end_date = start_date + datetime.timedelta(days=days)
    else:
        end_date = start_date + datetime.timedelta(days=365)

    if start_date > end_date:
        raise ValueError(f"Start date ({start_date}) cannot be after end date ({end_date})")

    return {
        "LICENSED_FINGERPRINT": fingerprint,
        "START_DATE": start_date.isoformat(),
        "END_DATE": end_date.isoformat(),
    }


def create_license(
    fingerprint: str,
    output_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
    source_json_path: Path | None = None,
    extra_secret: str = "",
) -> Dict[str, Any]:
    payload = build_license_payload(fingerprint, start_date, end_date, days)

    secret_key = get_license_secret()
    if extra_secret:
        secret_key += extra_secret

    encrypted = encrypt_license_payload(payload, secret_key, output_name="license.enc")
    content = json.dumps(encrypted, indent=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    if source_json_path:
        source_json_path.parent.mkdir(parents=True, exist_ok=True)
        source_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="School ERP Vendor License Creation Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fingerprint", help="Target client hardware fingerprint (SHA-256)")
    group.add_argument("--wildcard", action="store_true", help="Issue a wildcard license valid on any device (*)")

    parser.add_argument("--days", type=int, default=None, help="License duration in days (default: 365)")
    parser.add_argument("--start", help="License start date (YYYY-MM-DD, default: today)")
    parser.add_argument("--end", help="License end date (YYYY-MM-DD)")
    parser.add_argument("--out", default="license.enc", help="Encrypted output file path (default: license.enc)")
    parser.add_argument("--source-json", default=None, help="Optional path to write plain JSON definition")
    parser.add_argument("--extra-secret", default=os.getenv("LICENSE_EXTRA_SECRET", ""), help="Extra secret fragment")
    args = parser.parse_args()

    fp = "*" if args.wildcard else args.fingerprint
    out_path = Path(args.out).resolve()
    source_path = Path(args.source_json).resolve() if args.source_json else None

    try:
        payload = create_license(
            fingerprint=fp,
            output_path=out_path,
            start_date=args.start,
            end_date=args.end,
            days=args.days,
            source_json_path=source_path,
            extra_secret=args.extra_secret,
        )
        print("=" * 60)
        print("  LICENSE GENERATED SUCCESSFULLY")
        print("=" * 60)
        print(f"  Fingerprint : {payload['LICENSED_FINGERPRINT']}")
        print(f"  Period      : {payload['START_DATE']}  -->  {payload['END_DATE']}")
        print(f"  Output File : {out_path}")
        if source_path:
            print(f"  Source JSON : {source_path}")
        print("=" * 60)
        return 0
    except Exception as exc:
        print(f"Error creating license: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
