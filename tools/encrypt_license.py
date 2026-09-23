#!/usr/bin/env python3
"""Encrypt a license source file into the runtime license file used by the app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.license_utils import (
    encrypt_license_payload,
    get_project_root,
    get_settings_path,
    get_license_secret,
)


def main() -> int:
    project_root = get_project_root()
    default_source = project_root / "tools" / "license_source.json"
    default_output = project_root / "license.enc"
    default_settings = get_settings_path(project_root)

    parser = argparse.ArgumentParser(
        description="Encrypt a plain-text license definition into the runtime license file.",
    )
    parser.add_argument(
        "--input",
        default=str(default_source),
        help="Plain JSON license file to encrypt. Default: tools/license_source.json",
    )
    parser.add_argument(
        "--output",
        default=str(default_output),
        help="Encrypted output file. Default: license.enc",
    )
    parser.add_argument(
        "--settings",
        default=str(default_settings),
        help="Django settings.py path used to derive the encryption key.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the encrypted output file if it already exists.",
    )
    parser.add_argument(
        "--extra",
        default="",
        help="Optional extra secret fragment to combine with SECRET_KEY for stronger derivation.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    settings_path = Path(args.settings)

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    if output_path.exists() and not args.force:
        print(
            f"Output file already exists: {output_path} (use --force to overwrite)",
            file=sys.stderr,
        )
        return 3

    license_source = json.loads(input_path.read_text(encoding="utf-8"))
    secret_key = get_license_secret()
    if args.extra:
        secret_key = secret_key + args.extra

    encrypted = encrypt_license_payload(license_source, secret_key, output_path.name)
    output_path.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")
    print(f"Encrypted license written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
