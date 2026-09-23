#!/usr/bin/env python3
"""
Production Deployment & Client Release Builder Tool for School ERP.

Features:
- Isolated client build in build/clients/<client_slug>/
- Automatic or manual machine fingerprint collection
- License payload generation & encryption (encrypt_license.py)
- Pyarmor / Fernet obfuscation of application code & templates
- Scrubbing of development source files, tools/, and plaintext license sources
- Build manifest generation
- Pre-packaging security & completeness verification
- Optional runtime smoke testing (--smoke-test)
- ZIP release artifact generation

Safety Rule:
- NEVER touch, modify, obfuscate, or delete the developer source tree (PROJECT_ROOT).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Project root calculation
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_client_release")


def mask_fingerprint(fp: str) -> str:
    """Return a masked representation of a fingerprint for safe logging."""
    if len(fp) <= 12:
        return "****"
    return f"{fp[:6]}...{fp[-6:]}"


def slugify(text: str) -> str:
    """Convert string to safe directory/file slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_") or "client"


def get_default_fingerprint() -> str:
    """Retrieve fingerprint using tools/fingerprint_generator.py logic."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.fingerprint_generator import get_fingerprint_hash
        return get_fingerprint_hash()
    except Exception as exc:
        logger.error(f"Failed to generate hardware fingerprint: {exc}")
        sys.exit(1)


def validate_dates(start_str: str, end_str: str) -> Tuple[datetime.date, datetime.date]:
    """Validate ISO start and end dates."""
    try:
        start_date = datetime.date.fromisoformat(start_str)
    except ValueError:
        raise ValueError(f"Invalid start date format '{start_str}'. Use YYYY-MM-DD.")

    try:
        end_date = datetime.date.fromisoformat(end_str)
    except ValueError:
        raise ValueError(f"Invalid end date format '{end_str}'. Use YYYY-MM-DD.")

    if start_date > end_date:
        raise ValueError(f"Start date ({start_str}) cannot be later than end date ({end_str}).")

    today = datetime.date.today()
    if end_date < today:
        raise ValueError(f"End date ({end_str}) is in the past. License would be immediately expired.")

    return start_date, end_date


def prompt_user_input(args: argparse.Namespace) -> Dict[str, Any]:
    """Interactively collect missing client release options."""
    print("==================================================")
    print("School ERP Client Release Builder (Interactive)")
    print("==================================================")

    client_name = args.client
    while not client_name:
        client_name = input("Client Name: ").strip()

    fingerprint = args.fingerprint
    if not fingerprint:
        auto_fp = get_default_fingerprint()
        choice = input(f"Use current machine fingerprint ({mask_fingerprint(auto_fp)})? [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            fingerprint = auto_fp
        else:
            while not fingerprint:
                fingerprint = input("Enter License Fingerprint (SHA-256): ").strip()

    today_str = datetime.date.today().isoformat()
    default_end_str = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()

    start_date_str = args.start_date
    end_date_str = args.end_date

    while True:
        if not start_date_str:
            inp = input(f"Start Date [{today_str}]: ").strip()
            start_date_str = inp if inp else today_str

        if not end_date_str:
            inp = input(f"End Date [{default_end_str}]: ").strip()
            end_date_str = inp if inp else default_end_str

        try:
            validate_dates(start_date_str, end_date_str)
            break
        except ValueError as err:
            print(f"Date Error: {err}")
            start_date_str = None
            end_date_str = None

    if not args.yes:
        confirm = input(f"\nBuild release for '{client_name}' ({start_date_str} -> {end_date_str})? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Build cancelled by user.")
            sys.exit(0)

    return {
        "client": client_name,
        "fingerprint": fingerprint,
        "start_date": start_date_str,
        "end_date": end_date_str,
    }


def copy_source_to_release(source_root: Path, release_root: Path) -> None:
    """Copy project source to isolated release folder while excluding dev artifacts."""
    logger.info(f"Copying project files to isolated release directory: {release_root}")

    # Explicit exclusions
    exclude_dirs = {
        ".git",
        ".github",
        "venv",
        ".venv",
        "build",
        "dist",
        "dist_tmp",
        "_obf_stage",
        "tests",
        "__pycache__",
        ".claude",
        "node_modules",
        "whatsapp_session",
        ".wwebjs_cache",
        ".wwebjs_auth",
        "data",
        "logs",
        "backups",
    }
    exclude_files = {
        "run_server.py.bak",
        "run_server_config.json",
        ".gitignore",
    }
    exclude_extensions = {".pyc", ".pyo", ".pyd", ".log"}

    def ignore_filter(dirpath: str, filenames: list[str]) -> list[str]:
        rel_dir = os.path.relpath(dirpath, str(source_root))
        ignored = []

        for name in filenames:
            full_p = Path(dirpath) / name
            if full_p.is_dir():
                if name in exclude_dirs or name.startswith("."):
                    ignored.append(name)
            else:
                if (
                    name in exclude_files
                    or Path(name).suffix.lower() in exclude_extensions
                    or name.startswith("tests_")
                ):
                    ignored.append(name)
        return ignored

    if release_root.exists():
        shutil.rmtree(release_root)

    shutil.copytree(source_root, release_root, ignore=ignore_filter)
    logger.info("[OK] Isolated release copy created.")


def generate_and_encrypt_license(
    release_root: Path, fingerprint: str, start_date: str, end_date: str
) -> None:
    """Generate tools/license_source.json in release and run encrypt_license.py."""
    logger.info("Generating license definition and encrypting payload...")

    release_tools = release_root / "tools"
    release_tools.mkdir(parents=True, exist_ok=True)
    license_source = release_tools / "license_source.json"

    license_data = {
        "LICENSED_FINGERPRINT": fingerprint,
        "START_DATE": start_date,
        "END_DATE": end_date,
    }
    license_source.write_text(json.dumps(license_data, indent=2), encoding="utf-8")

    encrypt_script = release_tools / "encrypt_license.py"
    output_enc = release_root / "license.enc"

    if not encrypt_script.exists():
        raise RuntimeError(f"encrypt_license.py missing from {release_tools}")

    cmd = [
        sys.executable,
        str(encrypt_script),
        "--input",
        str(license_source),
        "--output",
        str(output_enc),
        "--force",
    ]

    res = subprocess.run(
        cmd,
        cwd=str(release_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    if res.returncode != 0:
        logger.error(f"License encryption failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        raise RuntimeError("encrypt_license.py execution failed.")

    if not output_enc.exists() or output_enc.stat().st_size == 0:
        raise RuntimeError("license.enc was not created or is empty.")

    logger.info("[OK] Encrypted license (license.enc) generated successfully.")


def run_obfuscation(release_root: Path, non_interactive: bool) -> None:
    """Run obfuscate_project.py on release copy."""
    logger.info("Obfuscating application Python code, JavaScript, and templates...")

    obf_script = release_root / "tools" / "obfuscate_project.py"
    if not obf_script.exists():
        raise RuntimeError(f"obfuscate_project.py missing at {obf_script}")

    obf_output_dir = release_root.parent / f"{release_root.name}_obfuscated"
    if obf_output_dir.exists():
        shutil.rmtree(obf_output_dir)

    cmd = [
        sys.executable,
        str(obf_script),
        "--project-root",
        str(release_root),
        "--output-dir",
        str(obf_output_dir),
    ]

    res = subprocess.run(
        cmd,
        cwd=str(release_root),
        capture_output=True,
        text=True,
        timeout=300,
    )

    if res.returncode != 0:
        logger.error(f"Obfuscation failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        raise RuntimeError("obfuscate_project.py execution failed.")

    logger.info("[OK] Obfuscation engine finished.")

    # List obfuscated/modified files to confirm with user before replacement
    obfuscated_files = list(obf_output_dir.rglob("*"))
    logger.info(f"Generated {len(obfuscated_files)} obfuscated/packaged artifacts in staging.")

    if not non_interactive:
        print("\nObfuscation completed successfully.")
        print(f"The release directory ({release_root}) will now be updated with the obfuscated code.")
        confirm = input("Continue with release packaging? [Y/n]: ").strip().lower()
        if confirm not in ("", "y", "yes"):
            raise RuntimeError("Build aborted by user before applying obfuscated code.")

    # Swap obfuscated output into release_root
    shutil.rmtree(release_root)
    shutil.move(obf_output_dir, release_root)
    logger.info("[OK] Obfuscated application applied to release directory.")


def clean_release_directory(release_root: Path) -> None:
    """Remove tools/, license_source.json, and unnecessary source remnants from release."""
    logger.info("Scrubbing development tools and temporary files from release...")

    # 1. Ensure run_server.py launcher shim exists if run_server.pyc was generated
    run_server_py = release_root / "run_server.py"
    run_server_pyc = release_root / "run_server.pyc"
    if run_server_pyc.exists() and not run_server_py.exists():
        shim_code = (
            "#!/usr/bin/env python3\n"
            "import os, runpy\n"
            "_dir = os.path.dirname(os.path.abspath(__file__))\n"
            "runpy.run_path(os.path.join(_dir, 'run_server.pyc'), run_name='__main__')\n"
        )
        run_server_py.write_text(shim_code, encoding="utf-8")
        logger.info("[OK] Created run_server.py launcher shim for run_server.pyc.")

    # 2. Remove tools/ directory
    release_tools = release_root / "tools"
    if release_tools.exists():
        shutil.rmtree(release_tools)
        logger.info("[OK] Removed tools/ directory from release.")

    # 3. Remove license_source.json if anywhere in release
    for source_file in release_root.rglob("license_source.json"):
        try:
            source_file.unlink()
            logger.info(f"[OK] Removed plaintext license source: {source_file}")
        except Exception:
            pass

    # 4. Scrub __pycache__ directories
    for pycache in release_root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)

    logger.info("[OK] Scrubbing complete.")


def generate_build_manifest(
    manifest_path: Path,
    client: str,
    fingerprint: str,
    start_date: str,
    end_date: str,
    status: str = "success",
) -> None:
    """Generate safe build_manifest.json outside client runtime package."""
    manifest_data = {
        "product": "School ERP",
        "client": client,
        "fingerprint": mask_fingerprint(fingerprint),
        "start_date": start_date,
        "end_date": end_date,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": sys.platform,
        "status": status,
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    logger.info(f"[OK] Build manifest generated at {manifest_path}")


def verify_release(release_root: Path, fingerprint: str, start_date: str, end_date: str) -> List[str]:
    """Perform pre-packaging sanity and security verification checks."""
    logger.info("Executing release verification audit...")
    errors = []

    # Required items
    required_paths = [
        release_root,
        release_root / "license.enc",
        release_root / "core",
        release_root / "school_erp",
        release_root / "templates",
        release_root / "static",
        release_root / "whatsapp_service",
    ]

    for req in required_paths:
        if not req.exists():
            errors.append(f"Missing required path: {req.relative_to(release_root)}")

    if not (release_root / "run_server.py").exists() and not (release_root / "run_server.pyc").exists():
        errors.append("Missing required launcher: run_server.py or run_server.pyc")

    if not (release_root / "manage.py").exists() and not (release_root / "manage.pyc").exists():
        errors.append("Missing required entry script: manage.py or manage.pyc")

    # Forbidden items
    forbidden_paths = [
        release_root / "tools",
        release_root / "license_source.json",
        release_root / ".git",
        release_root / "venv",
        release_root / ".venv",
    ]

    for forb in forbidden_paths:
        if forb.exists():
            errors.append(f"Forbidden path exists in release: {forb.name}")

    # Check for pycache files
    pycaches = list(release_root.rglob("__pycache__"))
    if pycaches:
        errors.append(f"Found {len(pycaches)} __pycache__ directories in release.")

    # Secret scanner checks
    sensitive_keys = ["WA_API_KEY", fingerprint, start_date, end_date]
    text_extensions = {".py", ".json", ".js", ".html", ".txt", ".md", ".yml", ".yaml"}

    suspicious = []
    for filepath in release_root.rglob("*"):
        if filepath.is_file() and filepath.suffix.lower() in text_extensions:
            # Skip encrypted templates or binary blobs
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                for key in sensitive_keys:
                    if key and len(key) > 5 and key in content:
                        # Distinguish parameter name definitions from actual values
                        if key == "WA_API_KEY" and "WA_API_KEY =" in content and "secrets.token_hex" in content:
                            continue
                        suspicious.append(f"Potential sensitive key found in {filepath.relative_to(release_root)}")
            except Exception:
                pass

    if suspicious:
        logger.warning(f"Secret scanner warning: {len(suspicious)} suspicious occurrences found.")
        for s in suspicious[:5]:
            logger.warning(f"  - {s}")

    return errors


def run_smoke_test(release_root: Path) -> None:
    """Optional smoke test to verify release package can initialize Django & license."""
    logger.info("Executing runtime smoke test on release package...")

    smoke_code = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')\n"
        "django.setup()\n"
        "from core.license import validate_or_exit\n"
        "print('SMOKE_TEST_LICENSE_VALID:', validate_or_exit())\n"
    )

    cmd = [sys.executable, "-c", smoke_code]
    res = subprocess.run(
        cmd,
        cwd=str(release_root),
        capture_output=True,
        text=True,
        timeout=30,
    )

    if res.returncode != 0:
        logger.error(f"Smoke test failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        raise RuntimeError("Runtime smoke test failed!")

    if "SMOKE_TEST_LICENSE_VALID: True" not in res.stdout:
        logger.error(f"Smoke test unexpected output:\n{res.stdout}")
        raise RuntimeError("Smoke test license validation did not return True.")

    logger.info("[OK] Runtime smoke test passed cleanly (Django setup + license validation OK).")


def create_zip_package(release_root: Path, zip_path: Path) -> None:
    """Create ZIP archive of final production release directory."""
    logger.info(f"Creating final release ZIP package: {zip_path}")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(release_root):
            for file in files:
                abs_path = Path(root) / file
                rel_path = Path("SchoolERP") / abs_path.relative_to(release_root)
                zf.write(abs_path, rel_path)

    logger.info(f"[OK] ZIP release package created ({zip_path.stat().st_size / (1024*1024):.2f} MB).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="School ERP Client Release Builder Tool")
    parser.add_argument("--client", help="Client name (e.g. 'Example School')")
    parser.add_argument("--fingerprint", help="Target client machine hardware fingerprint (SHA-256)")
    parser.add_argument("--start-date", help="License start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="License end date (YYYY-MM-DD)")
    parser.add_argument("--output", help="Custom output directory for release build")
    parser.add_argument("--smoke-test", action="store_true", help="Run runtime smoke test after packaging")
    parser.add_argument("--keep-build", action="store_true", help="Keep uncompressed release build directory")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--yes", action="store_true", help="Bypass interactive prompts (non-interactive / CI mode)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # 1. Gather client info
    if args.client and args.start_date and args.end_date:
        fingerprint = args.fingerprint or get_default_fingerprint()
        validate_dates(args.start_date, args.end_date)
        info = {
            "client": args.client,
            "fingerprint": fingerprint,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    else:
        info = prompt_user_input(args)

    client_name = info["client"]
    client_slug = slugify(client_name)
    fingerprint = info["fingerprint"]
    start_date = info["start_date"]
    end_date = info["end_date"]

    # 2. Safety path resolution
    if args.output:
        base_build_dir = Path(args.output).resolve()
    else:
        base_build_dir = PROJECT_ROOT / "build" / "clients" / client_slug

    release_dir = base_build_dir / "release"
    manifest_file = base_build_dir / "build_manifest.json"
    zip_file = base_build_dir / f"SchoolERP-{slugify(client_name)}.zip"

    # Strict Safety Checks
    if release_dir.resolve() == PROJECT_ROOT.resolve():
        logger.error("CRITICAL SAFETY ERROR: Release directory cannot be PROJECT_ROOT!")
        return 1

    if PROJECT_ROOT.resolve() in release_dir.resolve().parents and not (
        release_dir.resolve().is_relative_to(PROJECT_ROOT / "build")
        or release_dir.resolve().is_relative_to(PROJECT_ROOT / "dist")
    ):
        logger.error(f"CRITICAL SAFETY ERROR: Invalid release target path {release_dir}")
        return 1

    logger.info("==================================================")
    logger.info("School ERP Client Release Builder")
    logger.info("==================================================")
    logger.info(f"Client     : {client_name}")
    logger.info(f"Fingerprint: {mask_fingerprint(fingerprint)}")
    logger.info(f"License    : {start_date} -> {end_date}")
    logger.info(f"Target Dir : {release_dir}")
    logger.info("==================================================")

    try:
        # Step 1: Create isolated release copy
        copy_source_to_release(PROJECT_ROOT, release_dir)

        # Step 2: License definition & encryption
        generate_and_encrypt_license(release_dir, fingerprint, start_date, end_date)

        # Step 3: Obfuscation
        run_obfuscation(release_dir, non_interactive=args.yes)

        # Step 4: Scrub development source & tools
        clean_release_directory(release_dir)

        # Step 5: Pre-packaging verification audit
        errors = verify_release(release_dir, fingerprint, start_date, end_date)
        if errors:
            logger.error("RELEASE VERIFICATION FAILED:")
            for err in errors:
                logger.error(f"  - {err}")
            generate_build_manifest(manifest_file, client_name, fingerprint, start_date, end_date, status="failed")
            return 1
        logger.info("[OK] Verification audit passed.")

        # Step 6: Smoke test (optional)
        if args.smoke_test:
            run_smoke_test(release_dir)

        # Step 7: Build manifest
        generate_build_manifest(manifest_file, client_name, fingerprint, start_date, end_date, status="success")

        # Step 8: Final ZIP package
        create_zip_package(release_dir, zip_file)

        if not args.keep_build:
            # Leave release_dir intact per requirements or client build structure
            pass

        print("\n==================================================")
        print("BUILD SUCCESSFUL")
        print("==================================================")
        print(f"Client    : {client_name}")
        print(f"License   : {start_date} → {end_date}")
        print(f"Release   : {release_dir}")
        print(f"Package   : {zip_file}")
        print("==================================================\n")
        return 0

    except Exception as exc:
        logger.error(f"\nBUILD FAILED: {exc}")
        generate_build_manifest(manifest_file, client_name, fingerprint, start_date, end_date, status="failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
