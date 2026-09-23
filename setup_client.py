#!/usr/bin/env python3
"""
School ERP - Automated Client PC Setup & Deployment Tool
=========================================================
This script runs on the client's PC to fully automate:
1. System environment & Python/Node runtime verification
2. Hardware fingerprint detection & license activation
3. Python dependencies installation (if not using pre-bundled runtime)
4. WhatsApp service (Node.js) dependencies installation
5. Customer data directory creation (%PROGRAMDATA% / data)
6. SQLite database initialization & migrations
7. Static assets collection
8. Desktop and Start Menu shortcut creation (with pythonw.exe silent launch)
9. Smoke testing and automatic server launch

Usage:
    python setup_client.py
    python setup_client.py --non-interactive --launch
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

APP_NAME = "School ERP"
PROJECT_ROOT = Path(__file__).resolve().parent

# Console colors (if supported)
IS_WIN = platform.system().lower() == "windows"


def log_header(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def log_step(step: int, total: int, title: str) -> None:
    print(f"\n[{step}/{total}] {title}...")


def log_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def log_warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def log_error(msg: str) -> None:
    print(f"  [ERROR] {msg}", file=sys.stderr)


# ==============================================================================
# 1. Hardware Fingerprint & Licensing
# ==============================================================================

def get_hardware_fingerprint() -> str:
    """Return SHA-256 hash of the stable machine identifiers using canonical core.hardware."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.hardware import get_fingerprint_hash
        return get_fingerprint_hash()
    except Exception:
        if IS_WIN:
            def _run_ps(cmd: str) -> str:
                try:
                    full_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
                    out = subprocess.check_output(full_cmd, stderr=subprocess.DEVNULL)
                    for ln in out.decode(errors="ignore").splitlines():
                        ln = ln.strip()
                        if ln:
                            return ln
                    return ""
                except Exception:
                    return ""

            uuid = _run_ps("(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID")
            mb = _run_ps("(Get-CimInstance -ClassName Win32_BaseBoard).SerialNumber")
            combined = f"{uuid}|{mb}"
        else:
            combined = f"{platform.node() or ''}|"

        return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def verify_license() -> Tuple[bool, str]:
    """Check if a valid license file exists and is active for this machine."""
    try:
        # Import core paths & license verification
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.paths import get_license_file_path, ensure_data_directories
        ensure_data_directories()

        license_path = get_license_file_path()
        if not license_path.is_file():
            return False, f"License file not found (looked in {license_path})"

        from core.license import validate_or_exit
        # If validate_or_exit does not raise/exit, license is valid
        is_valid = validate_or_exit()
        return is_valid, f"Valid license active at {license_path}"
    except SystemExit:
        return False, "License is expired or not locked to this hardware fingerprint."
    except Exception as exc:
        return False, f"License validation error: {exc}"


def activate_license_file(license_src: str) -> bool:
    """Copy user provided license file to data/licenses directory."""
    src = Path(license_src).resolve()
    if not src.is_file():
        log_error(f"File not found: {src}")
        return False

    try:
        from core.paths import get_licenses_dir, get_base_dir
        dest = get_licenses_dir() / "license.enc"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        # Also copy to base dir as fallback
        shutil.copy2(src, get_base_dir() / "license.enc")
        log_ok(f"License installed to {dest}")
        return True
    except Exception as exc:
        log_error(f"Failed to install license: {exc}")
        return False


import datetime


def generate_locked_license_for_this_machine(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trial_days: Optional[int] = None,
) -> bool:
    """Generate and install an encrypted license.enc locked strictly to this PC's hardware fingerprint."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.license_utils import encrypt_license_payload, get_license_secret
        from core.paths import get_licenses_dir, get_base_dir

        today = datetime.date.today()
        if start_date is None:
            start_date = today.isoformat()

        if trial_days is not None:
            end_date = (today + datetime.timedelta(days=trial_days)).isoformat()
        elif end_date is None:
            end_date = (today + datetime.timedelta(days=3650)).isoformat()

        fp = get_hardware_fingerprint()
        payload = {
            "LICENSED_FINGERPRINT": fp,
            "START_DATE": start_date,
            "END_DATE": end_date,
        }
        secret_key = get_license_secret()
        encrypted = encrypt_license_payload(payload, secret_key, "license.enc")

        # Write to customer data licenses directory and base dir
        dest_data = get_licenses_dir() / "license.enc"
        dest_base = get_base_dir() / "license.enc"
        dest_data.parent.mkdir(parents=True, exist_ok=True)

        content = json.dumps(encrypted, indent=2)
        dest_data.write_text(content, encoding="utf-8")
        dest_base.write_text(content, encoding="utf-8")

        duration_desc = f"{trial_days}-Day Trial" if trial_days else f"{start_date} -> {end_date}"
        log_ok(f"Hardware-locked license activated ({duration_desc}) for Fingerprint: {fp[:8]}...{fp[-6:]}")
        return True
    except Exception as exc:
        log_error(f"Failed to generate locked license: {exc}")
        return False





# ==============================================================================
# 2. Runtime Discovery (Bundled vs. System)
# ==============================================================================

def get_python_exe() -> str:
    """Locate Python executable (prefers bundled runtime, then virtualenv, then sys.executable)."""
    runtime_py_win = PROJECT_ROOT / "runtime" / "python" / "python.exe"
    runtime_py_lin = PROJECT_ROOT / "runtime" / "python" / "bin" / "python"
    
    if IS_WIN and runtime_py_win.is_file():
        return str(runtime_py_win)
    elif not IS_WIN and runtime_py_lin.is_file():
        return str(runtime_py_lin)

    for venv_dir in ("venv", ".venv"):
        v_win = PROJECT_ROOT / venv_dir / "Scripts" / "python.exe"
        v_lin = PROJECT_ROOT / venv_dir / "bin" / "python"
        if IS_WIN and v_win.is_file():
            return str(v_win)
        elif not IS_WIN and v_lin.is_file():
            return str(v_lin)

    return sys.executable


def get_pythonw_exe() -> str:
    """Locate pythonw.exe for silent background execution without cmd window."""
    py = get_python_exe()
    py_dir = Path(py).parent
    pythonw = py_dir / "pythonw.exe"
    if pythonw.is_file():
        return str(pythonw)
    return py


def get_node_exe() -> Optional[str]:
    """Locate Node.js executable."""
    bundled_win = PROJECT_ROOT / "runtime" / "node" / "node.exe"
    bundled_lin = PROJECT_ROOT / "runtime" / "node" / "bin" / "node"
    if IS_WIN and bundled_win.is_file():
        return str(bundled_win)
    elif not IS_WIN and bundled_lin.is_file():
        return str(bundled_lin)

    which_node = shutil.which("node") or shutil.which("node.exe")
    return which_node


# ==============================================================================
# 3. Environment & Dependencies Setup
# ==============================================================================

def setup_python_dependencies(python_exe: str) -> bool:
    """Install Python packages from requirements.txt if not already installed."""
    # Test if Django is available
    test_cmd = [python_exe, "-c", "import django; print(django.__version__)"]
    res = subprocess.run(test_cmd, capture_output=True, text=True)
    if res.returncode == 0:
        log_ok(f"Python environment verified (Django v{res.stdout.strip()})")
        return True

    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        log_warn("requirements.txt not found. Skipping pip install.")
        return True

    print("  Installing required Python packages via pip...")
    cmd = [python_exe, "-m", "pip", "install", "--no-warn-script-location", "-r", str(req_file)]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        # Fallback: system-managed Python environments (Debian/Ubuntu) need --break-system-packages
        cmd_fallback = cmd + ["--break-system-packages"]
        res = subprocess.run(cmd_fallback)
    return res.returncode == 0


def setup_node_dependencies(node_exe: Optional[str]) -> bool:
    """Ensure whatsapp_service node_modules are present."""
    wa_dir = PROJECT_ROOT / "whatsapp_service"
    if not wa_dir.is_dir():
        return True

    node_modules = wa_dir / "node_modules"
    if node_modules.is_dir() and any(node_modules.iterdir()):
        log_ok("WhatsApp service node_modules already present.")
        return True

    if not node_exe:
        log_warn("Node.js not found. WhatsApp automation will be unavailable until Node.js is installed.")
        return True

    print("  Installing WhatsApp service Node dependencies...")
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        npm_cmd = str(Path(node_exe).parent / ("npm.cmd" if IS_WIN else "npm"))

    if os.path.exists(npm_cmd) or shutil.which(npm_cmd):
        res = subprocess.run([npm_cmd, "ci", "--omit=dev"], cwd=str(wa_dir))
        if res.returncode != 0:
            # Fallback to npm install
            res = subprocess.run([npm_cmd, "install", "--omit=dev"], cwd=str(wa_dir))
        return res.returncode == 0

    log_warn("npm not found to install node_modules.")
    return True


def configure_environment(base_dir: Path) -> None:
    """
    Generate and configure a secure production .env file for the client system.
    """
    env_file = base_dir / ".env"
    if not env_file.exists():
        import secrets
        secret_key = secrets.token_urlsafe(64)
        wa_key = secrets.token_hex(24)

        env_content = f"""# School ERP - Production Environment Configuration
DJANGO_SECRET_KEY={secret_key}
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,0.0.0.0
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
WA_API_KEY={wa_key}
WA_PORT=3000
"""
        env_file.write_text(env_content, encoding="utf-8")

        try:
            from core.paths import get_config_dir
            config_env = get_config_dir() / ".env"
            config_env.parent.mkdir(parents=True, exist_ok=True)
            config_env.write_text(env_content, encoding="utf-8")
        except Exception:
            pass

        log_ok("Production environment (.env) configured with unique secrets.")
    else:
        log_ok("Existing environment (.env) preserved.")


def initialize_application(python_exe: str) -> bool:
    """Ensure directories, configure .env, run database migrations, and collect static files."""
    try:
        from core.paths import ensure_data_directories, migrate_legacy_data
        ensure_data_directories()
        migrate_legacy_data()
        log_ok("Customer data directories initialized.")
    except Exception as exc:
        log_warn(f"Data directories initialization warning: {exc}")

    # Generate / configure environment file
    configure_environment(PROJECT_ROOT)


    # Run migrations — pass PROJECT_ROOT so subprocesses resolve the same license.enc path
    manage_py = PROJECT_ROOT / "manage.py"
    if manage_py.exists():
        print("  Applying database migrations (manage.py migrate)...")
        sub_env = os.environ.copy()
        sub_env["SCHOOL_ERP_BASE_DIR"] = str(PROJECT_ROOT)
        sub_env["DJANGO_SETTINGS_MODULE"] = "school_erp.settings"
        # Allow migration subprocess to bypass hardware fingerprint check —
        # setup_client.py already verified/generated the license above.
        sub_env["AUTO_LICENSE"] = "true"
        res = subprocess.run(
            [python_exe, str(manage_py), "migrate", "--noinput"],
            cwd=str(PROJECT_ROOT),
            env=sub_env,
        )
        if res.returncode != 0:
            log_error("Échec de la migration de la base de données.")
            return False
        log_ok("Base de données initialisée avec succès.")

        # Collect static files if staticfiles/ does not exist
        staticfiles_dir = PROJECT_ROOT / "staticfiles"
        if not staticfiles_dir.exists() or not any(staticfiles_dir.iterdir()):
            print("  Collecting static assets (manage.py collectstatic)...")
            subprocess.run(
                [python_exe, str(manage_py), "collectstatic", "--noinput"],
                cwd=str(PROJECT_ROOT),
                env=sub_env,
            )
            log_ok("Fichiers statiques collectés.")

    return True


# ==============================================================================
# 5. Desktop Shortcuts Creation
# ==============================================================================

def create_desktop_shortcuts(pythonw_exe: str, enable_autostart: bool = False) -> None:
    """Create Windows / Linux Desktop, Start Menu, and optional Startup shortcuts."""
    run_server = PROJECT_ROOT / "run_server.py"
    icon_file = PROJECT_ROOT / "static" / "images" / "app_icon.ico"
    icon_path_str = str(icon_file) if icon_file.exists() else ""

    if IS_WIN:
        try:
            # Generate VBScript to create shell .lnk shortcuts natively (no pip required)
            desktop_dir = Path(os.environ.get("USERPROFILE", "C:")) / "Desktop"
            start_menu_dir = Path(os.environ.get("APPDATA", "C:")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            startup_dir = Path(os.environ.get("APPDATA", "C:")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

            vbs_script = f"""
            Set oWS = WScript.CreateObject("WScript.Shell")
            
            ' 1. Desktop Shortcut
            sLinkFile = "{desktop_dir}\\{APP_NAME}.lnk"
            Set oLink = oWS.CreateShortcut(sLinkFile)
            oLink.TargetPath = "{pythonw_exe}"
            oLink.Arguments = """"{run_server}""""
            oLink.WorkingDirectory = "{PROJECT_ROOT}"
            oLink.Description = "{APP_NAME}"
            """
            if icon_path_str:
                vbs_script += f'\noLink.IconLocation = "{icon_path_str}"'
            vbs_script += """
            oLink.Save

            ' 2. Start Menu Shortcut
            sLinkFile2 = "{start_menu_dir}\\{APP_NAME}.lnk"
            Set oLink2 = oWS.CreateShortcut(sLinkFile2)
            oLink2.TargetPath = "{pythonw_exe}"
            oLink2.Arguments = """"{run_server}""""
            oLink2.WorkingDirectory = "{PROJECT_ROOT}"
            oLink2.Description = "{APP_NAME}"
            """
            if icon_path_str:
                vbs_script += f'\noLink2.IconLocation = "{icon_path_str}"'
            vbs_script += "\noLink2.Save\n"

            if enable_autostart:
                vbs_script += f"""
            ' 3. Windows Boot Startup Shortcut
            sLinkFile3 = "{startup_dir}\\{APP_NAME}.lnk"
            Set oLink3 = oWS.CreateShortcut(sLinkFile3)
            oLink3.TargetPath = "{pythonw_exe}"
            oLink3.Arguments = """"{run_server}""""
            oLink3.WorkingDirectory = "{PROJECT_ROOT}"
            oLink3.Description = "{APP_NAME} Auto-Launcher"
            """
                if icon_path_str:
                    vbs_script += f'\noLink3.IconLocation = "{icon_path_str}"'
                vbs_script += "\noLink3.Save\n"

            temp_vbs = PROJECT_ROOT / "_create_shortcut.vbs"
            temp_vbs.write_text(vbs_script, encoding="utf-8")
            subprocess.run(["cscript", "//Nologo", str(temp_vbs)], capture_output=True)
            if temp_vbs.exists():
                temp_vbs.unlink()

            log_ok("Desktop & Start Menu shortcuts created successfully.")
            if enable_autostart:
                log_ok("Windows boot auto-start enabled (Startup shortcut created).")
        except Exception as exc:
            log_warn(f"Could not create Windows shortcut: {exc}")

    else:
        # Linux .desktop entry
        try:
            desktop_entry = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={pythonw_exe} "{run_server}"
Path={PROJECT_ROOT}
Terminal=false
Categories=Office;Education;
"""
            apps_dir = Path.home() / ".local" / "share" / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            (apps_dir / "school-erp.desktop").write_text(desktop_entry, encoding="utf-8")

            linux_desktop = Path.home() / "Desktop"
            if linux_desktop.is_dir():
                dt_file = linux_desktop / f"{APP_NAME}.desktop"
                dt_file.write_text(desktop_entry, encoding="utf-8")
                dt_file.chmod(0o755)

            if enable_autostart:
                autostart_dir = Path.home() / ".config" / "autostart"
                autostart_dir.mkdir(parents=True, exist_ok=True)
                (autostart_dir / "school-erp.desktop").write_text(desktop_entry, encoding="utf-8")
                log_ok("Linux boot autostart enabled.")

            log_ok("Desktop entry created.")
        except Exception as exc:
            log_warn(f"Could not create Linux shortcut: {exc}")



def scrub_sensitive_dev_files(base_dir: Path) -> None:
    """
    Remove development tooling, license generator tools, test suites, and docs
    from the client installation directory to prevent easy reverse-engineering.
    """
    dirs_to_remove = [
        "tools",
        "playwright_test",
        "docs",
        "tests",
        "scripts",
        ".git",
        ".github",
        ".claude",
        ".gemini",
        ".agents",
    ]
    files_to_remove = [
        "license_source.json",
        "license_local.enc.bak",
        "installer.iss",
        "nixpacks.toml",
        "railway.json",
        "Procfile",
        ".env.example",
        "setup.sh",
        "setup.bat",
    ]

    for d in dirs_to_remove:
        p = base_dir / d
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    for f in files_to_remove:
        p = base_dir / f
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass

    # Remove temporary .vbs
    temp_vbs = base_dir / "_create_shortcut.vbs"
    if temp_vbs.is_file():
        try:
            temp_vbs.unlink()
        except Exception:
            pass

    log_ok("Sensitive developer tools, test suites, and source artifacts scrubbed.")


# ==============================================================================
# Main Orchestration Flow
# ==============================================================================


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="School ERP Client PC Automated Setup")
    parser.add_argument("--license", help="Path to license.enc to install")
    parser.add_argument("--lock-here", action="store_true", help="Generate & activate a license locked strictly to THIS computer")
    parser.add_argument("--trial", action="store_true", help="Activate 14-day free trial license locked to THIS computer")
    parser.add_argument("--trial-days", type=int, default=14, help="Number of trial days (default 14)")
    parser.add_argument("--start-date", default=None, help="License start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="License end date (YYYY-MM-DD)")
    parser.add_argument("--autostart", action="store_true", default=None, help="Start School ERP automatically on Windows boot")
    parser.add_argument("--no-autostart", dest="autostart", action="store_false", help="Disable Windows boot autostart")
    parser.add_argument("--non-interactive", action="store_true", help="Run without interactive prompts")
    parser.add_argument("--launch", action="store_true", help="Launch the server automatically after setup")
    parser.add_argument("--fingerprint-only", action="store_true", help="Display hardware fingerprint and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    log_header(f"{APP_NAME} - Automated Client Setup")

    # Step 1: Hardware Fingerprint
    fp = get_hardware_fingerprint()
    print(f"  Target PC Hardware Fingerprint:\n  >>> {fp} <<<\n")

    if args.fingerprint_only:
        return 0

    TOTAL_STEPS = 6

    # Step 2: License Check / Installation / On-Site Lock
    log_step(1, TOTAL_STEPS, "License Verification & Activation")
    if args.trial:
        generate_locked_license_for_this_machine(trial_days=args.trial_days)
    elif args.lock_here:
        generate_locked_license_for_this_machine(start_date=args.start_date, end_date=args.end_date)
    elif args.license:
        activate_license_file(args.license)

    valid, lic_msg = verify_license()
    if valid:
        log_ok(lic_msg)
    else:
        log_warn(lic_msg)
        if not args.non_interactive:
            print("\n  License required to run this software on this PC.")
            print(f"  Hardware Fingerprint: {fp}")
            print("\n  Select License Option:")
            print("    [1] 14-Day Free Trial (Hardware-locked to THIS PC) [Default]")
            print("    [2] Full Permanent License (10 Years, locked to THIS PC)")
            print("    [3] Custom Trial / Days")
            print("    [4] Install custom license.enc file")
            print("    [5] Continue without activating license now")

            choice = input("\n  Enter choice [1/2/3/4/5] (default 1): ").strip()
            if choice in ("", "1"):
                generate_locked_license_for_this_machine(trial_days=14)
                valid, lic_msg = verify_license()
                if valid:
                    log_ok("14-Day Free Trial license activated successfully for this machine!")
                else:
                    log_error(lic_msg)
            elif choice == "2":
                generate_locked_license_for_this_machine(start_date=args.start_date, end_date=args.end_date)
                valid, lic_msg = verify_license()
                if valid:
                    log_ok("Full license activated successfully for this machine!")
                else:
                    log_error(lic_msg)
            elif choice == "3":
                custom_days_str = input("  Enter number of trial days [e.g. 14, 30]: ").strip()
                try:
                    custom_days = int(custom_days_str) if custom_days_str else 14
                except ValueError:
                    custom_days = 14
                generate_locked_license_for_this_machine(trial_days=custom_days)
                valid, lic_msg = verify_license()
                if valid:
                    log_ok(f"{custom_days}-Day Trial license activated successfully!")
            elif choice == "4":
                user_lic_path = input("  Enter license.enc path (or drag & drop here): ").strip().strip('"').strip("'")
                if user_lic_path:
                    if activate_license_file(user_lic_path):
                        valid, lic_msg = verify_license()
                        if valid:
                            log_ok("License activated successfully!")
                        else:
                            log_error(lic_msg)
            else:
                print("  [INFO] Continuing setup. Place license.enc before running.")



    # Step 3: Runtime Discovery & Python Dependencies
    log_step(2, TOTAL_STEPS, "Runtime & Python Dependencies")
    python_exe = get_python_exe()
    pythonw_exe = get_pythonw_exe()
    print(f"  Using Python interpreter: {python_exe}")
    setup_python_dependencies(python_exe)

    # Step 4: WhatsApp Service & Node.js Dependencies
    log_step(3, TOTAL_STEPS, "WhatsApp Microservice (Node.js)")
    node_exe = get_node_exe()
    if node_exe:
        print(f"  Using Node.js interpreter: {node_exe}")
    setup_node_dependencies(node_exe)

    # Step 5: Database & Static Setup
    log_step(4, TOTAL_STEPS, "Database & Customer Storage Setup")
    initialize_application(python_exe)

    # Step 6: Shortcuts & Startup Creation
    log_step(5, TOTAL_STEPS, "Desktop & Startup Shortcuts")
    enable_autostart = args.autostart
    if enable_autostart is None:
        if not args.non_interactive:
            autostart_choice = input("\n  Start School ERP automatically when Windows boots? [Y/n]: ").strip().lower()
            enable_autostart = autostart_choice in ("", "y", "yes")
        else:
            enable_autostart = True

    create_desktop_shortcuts(pythonw_exe, enable_autostart=enable_autostart)

    # Step 7: Scrub sensitive files & Final Status
    log_step(6, TOTAL_STEPS, "Security Scrubbing & Completion")
    scrub_sensitive_dev_files(PROJECT_ROOT)

    log_header("SETUP COMPLETED SUCCESSFULLY!")
    print(f"  Application Location : {PROJECT_ROOT}")
    print(f"  Launcher             : {PROJECT_ROOT / 'run_server.py'}")
    print(f"  Hardware Fingerprint : {fp}")
    print(f"  Windows Boot Startup : {'Enabled (auto-starts on boot)' if enable_autostart else 'Disabled'}")
    print("================================================================\n")


    should_launch = args.launch
    if not should_launch and not args.non_interactive:
        choice = input("Would you like to launch School ERP now? [Y/n]: ").strip().lower()
        should_launch = choice in ("", "y", "yes")

    if should_launch:
        print("\n  Launching School ERP in background...")
        subprocess.Popen([pythonw_exe, str(PROJECT_ROOT / "run_server.py")], cwd=str(PROJECT_ROOT))
        print("  [OK] Server launched. Opening browser...")

    return 0



if __name__ == "__main__":
    sys.exit(main())
