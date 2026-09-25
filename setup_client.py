#!/usr/bin/env python3
"""
School ERP - Automated Client PC Setup & Deployment Tool
=========================================================
Automated setup tool for School ERP:
1. Environment & Python/Node verification (Python 3.10+ required)
2. Virtual environment (venv) self-bootstrap & dependency management
3. WhatsApp microservice (Node.js) dependency management
4. Hardware fingerprint detection & license activation (Trial / Permanent / Custom / Custom File)
5. Production configuration & customer storage setup (%PROGRAMDATA% / SchoolERP)
6. SQLite database initialization & migrations
7. Static assets collection
8. Desktop, Start Menu & autostart shortcut generation (pythonw silent background launch)
9. Smoke test and automatic server launch

Usage:
    python setup_client.py
    python setup_client.py --non-interactive --trial --launch
    python setup_client.py --lock-here --launch
"""

from __future__ import annotations

import argparse
import datetime
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
IS_WIN = platform.system().lower() == "windows"

CRITICAL_MODULES = [
    "django",
    "cryptography",
    "waitress",
    "whitenoise",
    "PIL",
    "reportlab",
    "openpyxl",
]


# ==============================================================================
# Logging Helpers
# ==============================================================================

def log_header(title: str) -> None:
    print("\n" + "=" * 68)
    print(f"  {title}")
    print("=" * 68)


def log_step(step: int, total: int, title: str) -> None:
    print(f"\n[{step}/{total}] {title}...")


def log_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def log_info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def log_error(msg: str) -> None:
    print(f"  [ERROR] {msg}", file=sys.stderr)


# ==============================================================================
# Virtual Environment Resolution & Self-Bootstrapping
# ==============================================================================

def get_venv_dir() -> Path:
    """Return the primary virtual environment directory."""
    return PROJECT_ROOT / "venv"


def get_venv_python() -> Path:
    """Locate the Python executable inside the virtual environment."""
    v_dir = get_venv_dir()
    if IS_WIN:
        return v_dir / "Scripts" / "python.exe"
    return v_dir / "bin" / "python"


def get_venv_pythonw() -> Path:
    """Locate pythonw.exe inside the virtual environment for windowless execution."""
    v_dir = get_venv_dir()
    if IS_WIN:
        pw = v_dir / "Scripts" / "pythonw.exe"
        if pw.is_file():
            return pw
    return get_venv_python()


def is_running_in_project_venv() -> bool:
    """Check if the current process is running inside the project's venv."""
    try:
        current_py = Path(sys.executable).resolve()
        target_py = get_venv_python().resolve()
        return current_py == target_py
    except Exception:
        return False


def ensure_venv_created(host_python: str) -> bool:
    """Create a virtual environment if it does not already exist."""
    py_exe = get_venv_python()
    if py_exe.is_file():
        return True

    print(f"  Creating isolated virtual environment (venv) using {host_python}...")
    try:
        res = subprocess.run([host_python, "-m", "venv", str(get_venv_dir())], capture_output=True, text=True)
        if res.returncode != 0:
            log_error(f"Failed to create virtual environment: {res.stderr.strip()}")
            return False
        log_ok(f"Virtual environment created at {get_venv_dir()}")
        return True
    except Exception as exc:
        log_error(f"Virtual environment creation error: {exc}")
        return False


def check_python_dependencies(python_exe: str) -> bool:
    """Check whether all critical Python packages are installed in the target interpreter."""
    check_code = f"import {', '.join(CRITICAL_MODULES)}"
    try:
        res = subprocess.run([python_exe, "-c", check_code], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


def install_python_dependencies(python_exe: str) -> bool:
    """Install or update packages from requirements.txt into the virtual environment."""
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        log_warn("requirements.txt not found. Skipping pip install.")
        return True

    print("  Installing/verifying required packages via pip (this may take a moment)...")
    cmd = [python_exe, "-m", "pip", "install", "--no-warn-script-location", "-r", str(req_file)]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        # Fallback for environments requiring --break-system-packages
        cmd_fallback = cmd + ["--break-system-packages"]
        res = subprocess.run(cmd_fallback)

    if res.returncode == 0:
        log_ok("Python dependencies installed successfully.")
        return True
    else:
        log_error("Failed to install Python dependencies via pip.")
        return False


def bootstrap_into_venv() -> None:
    """
    Ensure the script executes inside the project virtual environment (venv).
    If currently running under system Python, this creates the venv, installs requirements,
    and re-executes inside venv/Scripts/python.exe.
    """
    if is_running_in_project_venv():
        return

    # Check minimum Python version of the caller
    if sys.version_info < (3, 10):
        log_error(f"Python 3.10+ is required. Found Python {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    host_py = sys.executable
    if not ensure_venv_created(host_py):
        sys.exit(1)

    venv_py = str(get_venv_python())

    # Check and install dependencies into venv if not already present
    if not check_python_dependencies(venv_py):
        print("  Bootstrapping dependencies into virtual environment...")
        if not install_python_dependencies(venv_py):
            sys.exit(1)

    # Re-exec inside the virtual environment
    re_exec_cmd = [venv_py, str(PROJECT_ROOT / "setup_client.py")] + sys.argv[1:]
    try:
        res = subprocess.run(re_exec_cmd)
        sys.exit(res.returncode)
    except KeyboardInterrupt:
        print("\n  Setup cancelled by user.")
        sys.exit(1)
    except Exception as exc:
        log_error(f"Failed to delegate to virtual environment: {exc}")
        sys.exit(1)


# ==============================================================================
# Hardware Fingerprint & Licensing
# ==============================================================================

def get_hardware_fingerprint() -> str:
    """Return SHA-256 hash of the stable machine identifiers using core.hardware."""
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
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.paths import get_license_file_path, ensure_data_directories
        ensure_data_directories()

        license_path = get_license_file_path()
        if not license_path.is_file():
            return False, f"License file not found (looked in {license_path})"

        from core.license import validate_or_exit, _reset_validation_cache
        _reset_validation_cache()
        is_valid = validate_or_exit()
        return is_valid, f"Valid license active at {license_path}"
    except SystemExit as se:
        msg = str(se) if str(se) else "License is expired or not locked to this hardware fingerprint."
        return False, msg
    except Exception as exc:
        return False, f"License validation error: {exc}"


def activate_license_file(license_src: str) -> bool:
    """Copy user-provided license.enc file to data/licenses directory and project root."""
    src = Path(license_src).resolve()
    if not src.is_file():
        log_error(f"License file not found: {src}")
        return False

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.paths import get_licenses_dir, get_base_dir, ensure_data_directories
        ensure_data_directories()

        dest_data = get_licenses_dir() / "license.enc"
        dest_base = get_base_dir() / "license.enc"
        dest_data.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src, dest_data)
        shutil.copy2(src, dest_base)
        log_ok(f"License file installed successfully to {dest_data}")
        return True
    except Exception as exc:
        log_error(f"Failed to install license: {exc}")
        return False


def generate_locked_license_for_this_machine(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trial_days: Optional[int] = None,
) -> bool:
    """Generate and install an encrypted license.enc locked strictly to this PC's hardware fingerprint."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.license_utils import encrypt_license_payload, get_license_secret
        from core.paths import get_licenses_dir, get_base_dir, ensure_data_directories
        ensure_data_directories()

        today = datetime.date.today()
        if start_date is None:
            start_date = today.isoformat()

        if trial_days is not None:
            end_date = (today + datetime.timedelta(days=trial_days)).isoformat()
        elif end_date is None:
            # Default permanent: 10 years
            end_date = (today + datetime.timedelta(days=3650)).isoformat()

        fp = get_hardware_fingerprint()
        payload = {
            "LICENSED_FINGERPRINT": fp,
            "START_DATE": start_date,
            "END_DATE": end_date,
        }
        secret_key = get_license_secret()
        encrypted = encrypt_license_payload(payload, secret_key, "license.enc")

        dest_data = get_licenses_dir() / "license.enc"
        dest_base = get_base_dir() / "license.enc"
        dest_data.parent.mkdir(parents=True, exist_ok=True)

        content = json.dumps(encrypted, indent=2)
        dest_data.write_text(content, encoding="utf-8")
        dest_base.write_text(content, encoding="utf-8")

        duration_desc = f"{trial_days}-Day Trial" if trial_days else f"{start_date} -> {end_date}"
        log_ok(f"Hardware-locked license generated ({duration_desc}) for Fingerprint: {fp[:8]}...{fp[-6:]}")
        return True
    except Exception as exc:
        log_error(f"Failed to generate locked license: {exc}")
        return False


# ==============================================================================
# WhatsApp Service Dependencies (Node.js)
# ==============================================================================

def setup_node_dependencies() -> bool:
    """Ensure whatsapp_service node_modules are present using installed Node.js/npm."""
    wa_dir = PROJECT_ROOT / "whatsapp_service"
    if not wa_dir.is_dir():
        return True

    node_modules = wa_dir / "node_modules"
    if node_modules.is_dir() and any(node_modules.iterdir()):
        log_ok("WhatsApp service node_modules already present.")
        return True

    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    node_cmd = shutil.which("node") or shutil.which("node.exe")

    if not npm_cmd or not node_cmd:
        log_warn("Node.js or npm is not installed on system PATH.")
        log_info("WhatsApp automation will be paused until Node.js is installed.")
        log_info("You can download Node.js from https://nodejs.org/ and run 'npm install' in whatsapp_service.")
        return True

    print("  Installing WhatsApp service Node dependencies via npm...")
    try:
        res = subprocess.run([npm_cmd, "install", "--omit=dev"], cwd=str(wa_dir), capture_output=True, text=True)
        if res.returncode == 0:
            log_ok("WhatsApp service Node dependencies installed successfully.")
            return True
        else:
            log_warn(f"npm install completed with warnings: {res.stderr.strip()[:200]}")
            return True
    except Exception as exc:
        log_warn(f"Could not run npm install: {exc}")
        return True


# ==============================================================================
# Environment Configuration & Database Initialization
# ==============================================================================

def configure_environment(base_dir: Path) -> None:
    """Generate and configure a secure production .env file for the client system."""
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

        log_ok("Production environment (.env) configured with secure keys.")
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

    # Run database migrations
    manage_py = PROJECT_ROOT / "manage.py"
    if manage_py.exists():
        print("  Applying database migrations (manage.py migrate)...")
        sub_env = os.environ.copy()
        sub_env["SCHOOL_ERP_BASE_DIR"] = str(PROJECT_ROOT)
        sub_env["DJANGO_SETTINGS_MODULE"] = "school_erp.settings"
        sub_env["AUTO_LICENSE"] = "true"
        res = subprocess.run(
            [python_exe, str(manage_py), "migrate", "--noinput"],
            cwd=str(PROJECT_ROOT),
            env=sub_env,
        )
        if res.returncode != 0:
            log_error("Database migration failed.")
            return False
        log_ok("Database initialized and migrated successfully.")

        # Collect static files
        staticfiles_dir = PROJECT_ROOT / "staticfiles"
        if not staticfiles_dir.exists() or not any(staticfiles_dir.iterdir()):
            print("  Collecting static assets (manage.py collectstatic)...")
            subprocess.run(
                [python_exe, str(manage_py), "collectstatic", "--noinput"],
                cwd=str(PROJECT_ROOT),
                env=sub_env,
                capture_output=True,
            )
            log_ok("Static assets collected successfully.")

    return True


# ==============================================================================
# Shortcuts & Quick Launchers Creation
# ==============================================================================

def create_desktop_shortcuts(pythonw_exe: str, enable_autostart: bool = False) -> None:
    """Create Windows / Linux Desktop, Start Menu, Startup shortcuts, and start_server.bat."""
    run_server = PROJECT_ROOT / "run_server.py"
    icon_file = PROJECT_ROOT / "static" / "images" / "app_icon.ico"
    icon_path_str = str(icon_file) if icon_file.exists() else ""

    # Always generate/update start_server.bat in project root for convenience
    start_bat = PROJECT_ROOT / "start_server.bat"
    start_bat_content = f"""@echo off
title School ERP Server
setlocal
cd /d "%~dp0"

if exist "venv\\Scripts\\python.exe" (
    "venv\\Scripts\\python.exe" run_server.py %*
) else (
    python run_server.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server exited with error code %ERRORLEVEL%.
    pause
)
"""
    try:
        start_bat.write_text(start_bat_content, encoding="utf-8")
        log_ok("Local launcher created: start_server.bat")
    except Exception:
        pass

    if IS_WIN:
        try:
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
    """Optional developer scrubbing tool for producing clean customer distribution packages."""
    dirs_to_remove = [
        "tools",
        "playwright_test",
        "docs",
        "tests",
    ]
    files_to_remove = [
        "license_source.json",
        "license_local.enc.bak",
        "installer.iss",
        "nixpacks.toml",
        "railway.json",
        "Procfile",
        ".env.example",
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

    log_ok("Sensitive developer tools and artifacts scrubbed.")


# ==============================================================================
# Main Orchestration Flow
# ==============================================================================

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="School ERP Client PC Automated Setup")
    parser.add_argument("--install-programs", action="store_true", help="Build client release with encrypted code and install in Programs folder")
    parser.add_argument("--programs-dir", help="Custom Programs folder installation directory")
    parser.add_argument("--client-name", default="School ERP", help="Client name")
    parser.add_argument("--license", help="Path to license.enc to install")
    parser.add_argument("--lock-here", action="store_true", help="Generate & activate a license locked strictly to THIS computer")
    parser.add_argument("--trial", action="store_true", help="Activate 14-day free trial license locked to THIS computer")
    parser.add_argument("--trial-days", type=int, default=14, help="Number of trial days (default 14)")
    parser.add_argument("--permanent", action="store_true", help="Activate 10-year permanent license")
    parser.add_argument("--start-date", default=None, help="License start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="License end date (YYYY-MM-DD)")
    parser.add_argument("--autostart", action="store_true", default=None, help="Start School ERP automatically on Windows boot")
    parser.add_argument("--no-autostart", dest="autostart", action="store_false", help="Disable Windows boot autostart")
    parser.add_argument("--non-interactive", action="store_true", help="Run without interactive prompts")
    parser.add_argument("--launch", action="store_true", help="Launch the server automatically after setup")
    parser.add_argument("--fingerprint-only", action="store_true", help="Display hardware fingerprint and exit")
    parser.add_argument("--scrub-dev-files", action="store_true", help="Scrub development files for packaging")
    return parser.parse_args()


def run_programs_encrypted_release(args: argparse.Namespace, venv_py: str, fp: str) -> int:
    """Use tools/build_client_release.py to build an obfuscated release and install it to Programs folder."""
    log_header(f"{APP_NAME} - Client Release Builder (Programs Folder)")

    client_name = args.client_name
    if not args.non_interactive and not args.install_programs:
        inp = input(f"  Enter Client / School Name [{client_name}]: ").strip()
        if inp:
            client_name = inp

    # License selection
    start_date = args.start_date
    end_date = args.end_date
    trial_days = args.trial_days

    is_trial = args.trial
    is_perm = args.permanent or args.lock_here

    if not is_trial and not is_perm and not (start_date and end_date):
        if not args.non_interactive:
            print("\n  Select License Option for this client:")
            print("    [1] 14-Day Free Trial (Hardware-locked to THIS PC) [Default]")
            print("    [2] Full Permanent License (10 Years, locked to THIS PC)")
            print("    [3] Custom Trial / Days")
            lic_choice = input("\n  Enter choice [1/2/3] (default 1): ").strip()
            if lic_choice in ("", "1"):
                is_trial = True
                trial_days = 14
            elif lic_choice == "2":
                is_perm = True
            elif lic_choice == "3":
                custom_str = input("  Enter number of trial days [e.g. 14, 30]: ").strip()
                try:
                    trial_days = int(custom_str) if custom_str else 14
                except ValueError:
                    trial_days = 14
                is_trial = True
        else:
            is_trial = True

    # Programs directory
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        default_prog = Path(local_app_data) / "Programs" / APP_NAME
    else:
        default_prog = Path.home() / "AppData" / "Local" / "Programs" / APP_NAME

    if args.programs_dir:
        programs_dir = Path(args.programs_dir).resolve()
    elif not args.non_interactive:
        inp_prog = input(f"\n  Installation Directory [{default_prog}]: ").strip()
        programs_dir = Path(inp_prog).resolve() if inp_prog else default_prog
    else:
        programs_dir = default_prog

    # Autostart
    enable_autostart = args.autostart
    if enable_autostart is None:
        if not args.non_interactive:
            inp_auto = input("\n  Start School ERP automatically when Windows boots? [y/N]: ").strip().lower()
            enable_autostart = inp_auto in ("y", "yes")
        else:
            enable_autostart = False

    # Launch after setup
    should_launch = args.launch
    if not should_launch and not args.non_interactive:
        inp_launch = input("\n  Launch School ERP immediately after setup? [Y/n]: ").strip().lower()
        should_launch = inp_launch in ("", "y", "yes")

    print("\n  Starting encrypted release compilation & deployment...")
    build_script = PROJECT_ROOT / "tools" / "build_client_release.py"

    cmd = [
        venv_py,
        str(build_script),
        "--client", client_name,
        "--fingerprint", fp,
        "--install-programs",
        "--install-dir", str(programs_dir),
        "--yes",
    ]

    if is_trial:
        cmd.extend(["--trial", "--trial-days", str(trial_days)])
    elif is_perm:
        cmd.append("--permanent")
    elif start_date and end_date:
        cmd.extend(["--start-date", start_date, "--end-date", end_date])

    if enable_autostart:
        cmd.append("--autostart")
    if should_launch:
        cmd.append("--launch")

    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if res.returncode == 0:
        log_header("CLIENT RELEASE DEPLOYED SUCCESSFULLY!")
        print(f"  Installation Directory : {programs_dir}")
        print(f"  Code Protection        : Encrypted & Obfuscated (Pyarmor + Fernet)")
        print(f"  Web Interface URL      : http://127.0.0.1:8000")
        print(f"  Desktop Shortcut       : Created on Desktop & Start Menu")
        print(f"  Quick Launcher         : {programs_dir / 'start_server.bat'}")
        print(f"  Hardware Fingerprint   : {fp}")
        print(f"  Windows Boot Startup   : {'Enabled' if enable_autostart else 'Disabled'}")
        print("=" * 68 + "\n")
        return 0
    else:
        log_error("Release builder failed to deploy client release.")
        return res.returncode


def main() -> int:
    # First: Ensure execution inside the project virtual environment (venv)
    bootstrap_into_venv()

    args = parse_arguments()

    log_header(f"{APP_NAME} - Automated System Setup")

    # Step 1: Hardware Fingerprint
    fp = get_hardware_fingerprint()
    print(f"  Target PC Hardware Fingerprint:\n  >>> {fp} <<<\n")

    if args.fingerprint_only:
        return 0

    venv_py = str(get_venv_python())
    venv_pyw = str(get_venv_pythonw())

    # Check setup mode
    if args.install_programs:
        return run_programs_encrypted_release(args, venv_py, fp)

    if not args.non_interactive:
        print("  Select Setup Mode:")
        print("    [1] Make Client Release in Programs Folder (Encrypted Code) [Recommended]")
        print("    [2] Quick Local Development Setup (Current Folder, In-Place)")
        mode_choice = input("\n  Enter choice [1/2] (default 1): ").strip()
        if mode_choice in ("", "1"):
            return run_programs_encrypted_release(args, venv_py, fp)

    TOTAL_STEPS = 6

    # Step 1: Environment & Python Runtime
    log_step(1, TOTAL_STEPS, "Environment & Python Runtime Verification")
    venv_py = str(get_venv_python())
    venv_pyw = str(get_venv_pythonw())
    print(f"  Active Python Interpreter : {venv_py}")
    if check_python_dependencies(venv_py):
        log_ok("Python virtual environment verified and all core dependencies present.")
    else:
        print("  Installing missing dependencies from requirements.txt...")
        if not install_python_dependencies(venv_py):
            log_error("Setup cannot proceed without required dependencies.")
            return 1

    # Step 2: WhatsApp Microservice Dependencies
    log_step(2, TOTAL_STEPS, "WhatsApp Microservice (Node.js)")
    setup_node_dependencies()

    # Step 3: License Verification & Activation
    log_step(3, TOTAL_STEPS, "License Verification & Activation")
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
            print("\n  License required to run School ERP on this PC.")
            print(f"  Target Fingerprint: {fp}")
            print("\n  Select License Option:")
            print("    [1] 14-Day Free Trial (Hardware-locked to THIS PC) [Default]")
            print("    [2] Full Permanent License (10 Years, locked to THIS PC)")
            print("    [3] Custom Trial / Days")
            print("    [4] Install custom license.enc file")
            print("    [5] Continue without activating license now")

            try:
                choice = input("\n  Enter choice [1/2/3/4/5] (default 1): ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "1"

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
                log_info("Continuing setup without active license. Place license.enc before running.")
        else:
            # In non-interactive mode with no explicit license, default to 14-day trial
            print("  Non-interactive mode: generating 14-Day Free Trial license...")
            generate_locked_license_for_this_machine(trial_days=args.trial_days or 14)
            valid, lic_msg = verify_license()
            if valid:
                log_ok("14-Day Free Trial license activated successfully.")

    # Step 4: Database & Customer Storage Setup
    log_step(4, TOTAL_STEPS, "Database & Customer Storage Setup")
    if not initialize_application(venv_py):
        log_error("Application initialization failed.")
        return 1

    # Step 5: Shortcuts & Desktop Creation
    log_step(5, TOTAL_STEPS, "Desktop & Startup Shortcuts")
    enable_autostart = args.autostart
    if enable_autostart is None:
        if not args.non_interactive:
            try:
                autostart_choice = input("\n  Start School ERP automatically when Windows boots? [Y/n]: ").strip().lower()
                enable_autostart = autostart_choice in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt):
                enable_autostart = False
        else:
            enable_autostart = False

    create_desktop_shortcuts(venv_pyw, enable_autostart=enable_autostart)

    # Step 6: Security & Completion
    log_step(6, TOTAL_STEPS, "Final Verification & Completion")
    if args.scrub_dev_files:
        scrub_sensitive_dev_files(PROJECT_ROOT)

    log_header("SETUP COMPLETED SUCCESSFULLY!")
    print(f"  Application Location : {PROJECT_ROOT}")
    print(f"  Web Interface URL    : http://127.0.0.1:8000")
    print(f"  Desktop Shortcut     : Created on Desktop & Start Menu")
    print(f"  Quick Launcher       : {PROJECT_ROOT / 'start_server.bat'}")
    print(f"  Hardware Fingerprint : {fp}")
    print(f"  Windows Boot Startup : {'Enabled (auto-starts on boot)' if enable_autostart else 'Disabled'}")
    print("=" * 68 + "\n")

    should_launch = args.launch
    if not should_launch and not args.non_interactive:
        try:
            choice = input("Would you like to launch School ERP now? [Y/n]: ").strip().lower()
            should_launch = choice in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            should_launch = False

    if should_launch:
        print("\n  Launching School ERP in background...")
        subprocess.Popen([venv_pyw, str(PROJECT_ROOT / "run_server.py")], cwd=str(PROJECT_ROOT))
        print("  [OK] Server launched. Opening browser in a few seconds...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
