import datetime
import json
import os
import secrets
import socket
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.request import urlopen

# Early customer data directories bootstrap & legacy data migration
from core.paths import (
    get_base_dir as _get_paths_base_dir,
    get_data_dir,
    get_config_dir,
    get_logs_dir,
    get_whatsapp_session_dir,
    ensure_data_directories,
    migrate_legacy_data,
)
from core.version import VERSION, APP_NAME

ensure_data_directories()
migrate_legacy_data()


# ---------------------------------------------------------------------------
# Runtime discovery helpers (Commercial Bundled vs. Local Development)
# ---------------------------------------------------------------------------

def _get_base_dir() -> str:
    """Directory containing this script or the frozen executable."""
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return str(_get_paths_base_dir())


def get_runtime_dir() -> str:
    """Path to the bundled runtime directory."""
    return os.path.join(_get_base_dir(), "runtime")


def get_python_executable() -> str:
    """
    Locate Python executable.

    Windows:
    - Use pythonw.exe when this application is already running without a console.
    - Otherwise use python.exe.

    Priority:
    1. Bundled private runtime
    2. Local venv / .venv
    3. Current Python executable
    """
    runtime_dir = get_runtime_dir()

    if sys.platform == "win32":
        # If run_server.py was started with pythonw.exe,
        # always keep the application on pythonw.exe.
        running_without_console = (
            os.path.basename(sys.executable).lower() == "pythonw.exe"
        )

        if running_without_console:
            bundled = os.path.join(
                runtime_dir,
                "python",
                "pythonw.exe",
            )
        else:
            bundled = os.path.join(
                runtime_dir,
                "python",
                "python.exe",
            )
    else:
        bundled = os.path.join(
            runtime_dir,
            "python",
            "bin",
            "python",
        )

    if os.path.isfile(bundled):
        return bundled

    base_dir = _get_base_dir()

    for candidate in ("venv", ".venv"):
        vpath = os.path.join(base_dir, candidate)

        if not os.path.isdir(vpath):
            continue

        if sys.platform == "win32":
            if os.path.basename(sys.executable).lower() == "pythonw.exe":
                vpy = os.path.join(
                    vpath,
                    "Scripts",
                    "pythonw.exe",
                )
            else:
                vpy = os.path.join(
                    vpath,
                    "Scripts",
                    "python.exe",
                )
        else:
            vpy = os.path.join(
                vpath,
                "bin",
                "python",
            )

        if os.path.isfile(vpy):
            return vpy

    return sys.executable


def get_node_executable() -> str:
    """
    Locate Node.js executable.
    1. Bundled private runtime: runtime/node/node.exe (Win) or runtime/node/bin/node (Linux)
    2. System node.exe (Win) or node (Linux)
    """
    runtime_dir = get_runtime_dir()
    if sys.platform == "win32":
        bundled = os.path.join(runtime_dir, "node", "node.exe")
    else:
        bundled = os.path.join(runtime_dir, "node", "bin", "node")

    if os.path.isfile(bundled):
        return bundled

    return "node.exe" if sys.platform == "win32" else "node"


def get_npm_executable() -> str:
    """
    Locate npm executable.
    1. Bundled private runtime: runtime/node/npm.cmd (Win) or runtime/node/bin/npm (Linux)
    2. System npm.cmd (Win) or npm (Linux)
    """
    runtime_dir = get_runtime_dir()
    if sys.platform == "win32":
        bundled = os.path.join(runtime_dir, "node", "npm.cmd")
    else:
        bundled = os.path.join(runtime_dir, "node", "bin", "npm")

    if os.path.isfile(bundled):
        return bundled

    return "npm.cmd" if sys.platform == "win32" else "npm"


def get_chromium_executable() -> str | None:
    """
    Locate Chromium browser binary for Puppeteer / WhatsApp.
    1. Bundled private runtime: runtime/chromium/chrome.exe (Win) or runtime/chromium/chrome (Linux)
    2. CHROME_PATH environment variable if set and existing
    3. Standard Windows installation paths (Google Chrome, Microsoft Edge, Chromium)
    4. PATH lookups (which / where)
    """
    runtime_dir = get_runtime_dir()
    if sys.platform == "win32":
        bundled = os.path.join(runtime_dir, "chromium", "chrome.exe")
    else:
        bundled = os.path.join(runtime_dir, "chromium", "chrome")

    if os.path.isfile(bundled):
        return bundled

    env_chrome = os.environ.get("CHROME_PATH")
    if env_chrome and os.path.isfile(env_chrome):
        return env_chrome

    if sys.platform == "win32":
        # Check standard Windows paths (Chrome, Edge, Brave, Chromium)
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_appdata = os.environ.get("LOCALAPPDATA", "")

        windows_candidates = [
            os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(local_appdata, "Chromium", "Application", "chrome.exe"),
        ]
        for candidate in windows_candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
    else:
        # Linux PATH lookup
        for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
            resolved = shutil.which(name)
            if resolved and os.path.isfile(resolved):
                return resolved

    return None



# ---------------------------------------------------------------------------
# Network / port helpers
# ---------------------------------------------------------------------------

def is_port_available(port, host="0.0.0.0"):
    """Return True if *port* is available for binding on *host*."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(start_port, host="0.0.0.0", max_port=65535):
    """
    Return the first available TCP port >= start_port on *host*.
    """
    port = start_port
    while port <= max_port:
        if is_port_available(port, host):
            return port
        port += 1
    raise RuntimeError(f"No available TCP port found starting from {start_port}.")


def get_local_ip():
    """Return the local LAN IP address without requiring internet access."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Process management (pure — no Tkinter)
# ---------------------------------------------------------------------------

def _stop_process_tree(process, name, log_fn=None):
    """
    Terminate *process* and its entire process group / tree.
    """
    _log = log_fn if callable(log_fn) else (lambda _msg: None)

    if process is None:
        return

    if process.poll() is not None:
        _log(f"{name} was already stopped.")
        return

    try:
        _log(f"Stopping {name}...")

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _log(f"{name} did not exit after taskkill.")

        else:
            import signal

            pgid = None
            try:
                pgid = os.getpgid(process.pid)
            except OSError:
                _log(f"{name}: process group not found; terminating process directly.")

            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log(f"{name} did not stop gracefully. Force-killing process group...")
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=5)
                    except Exception:
                        pass
                except ProcessLookupError:
                    pass
            else:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log(f"{name} did not stop gracefully. Force-killing process...")
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception:
                        pass

        _log(f"{name} stopped.")

    except ProcessLookupError:
        _log(f"{name} was already stopped.")
    except Exception as exc:
        _log(f"Error stopping {name}: {exc}")


def _run_subprocess(args, **kwargs):
    """
    subprocess.run() wrapper injecting CREATE_NO_WINDOW on Windows only.
    """
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


# ---------------------------------------------------------------------------
# Path / environment / config helpers
# ---------------------------------------------------------------------------

def _get_config_path():
    return os.path.join(str(get_config_dir()), "run_server_config.json")


def _load_local_config():
    try:
        with open(_get_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_local_config(config):
    try:
        with open(_get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError:
        pass


def _relaunch_in_venv_if_needed():
    """
    If running in development as a plain script, re-exec using the
    discovered Python runtime without switching a GUI process to python.exe.
    """
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return

    py_exe = get_python_executable()

    current_exe = os.path.normcase(os.path.abspath(sys.executable))
    target_exe = os.path.normcase(os.path.abspath(py_exe))

    if current_exe == target_exe:
        return

    try:
        if os.path.samefile(sys.executable, py_exe):
            return
    except (OSError, FileNotFoundError):
        pass

    # Preserve the GUI interpreter.
    # If we started with pythonw.exe, never relaunch with python.exe.
    if (
        sys.platform == "win32"
        and os.path.basename(sys.executable).lower() == "pythonw.exe"
        and os.path.basename(py_exe).lower() != "pythonw.exe"
    ):
        return

    subprocess.Popen(
        [py_exe] + sys.argv,
        cwd=_get_base_dir(),
        creationflags=subprocess.CREATE_NO_WINDOW
        if sys.platform == "win32"
        else 0,
    )

    sys.exit(0)


_relaunch_in_venv_if_needed()


# ---------------------------------------------------------------------------
# License check — runs before GUI starts
# ---------------------------------------------------------------------------

try:
    from core.license import validate_or_exit
    validate_or_exit()
except SystemExit as _e:
    _root = tk.Tk()
    _root.withdraw()
    _msg = str(_e) if str(_e) else "This copy of the application is not licensed for this device."
    messagebox.showerror("License Verification", _msg)
    sys.exit(1)
except Exception as _e:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "License Verification Error",
        f"Failed to perform license check:\n{_e}",
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Visual constants (Modern Slate Dark Theme)
# ---------------------------------------------------------------------------

BG          = "#0b0f19"  # Deep slate navy
PANEL       = "#141c2b"  # Elevated card surface
PANEL_ALT   = "#0d1522"  # Recessed log viewer
CARD_BORDER = "#1f2b3e"  # Subtle structural border
ACCENT      = "#38bdf8"  # Sky blue accent
PURPLE      = "#6366f1"  # Indigo for QR code & network tools
GREEN       = "#10b981"  # Emerald green (live)
RED         = "#f43f5e"  # Rose red (stopped)
AMBER       = "#f59e0b"  # Warm amber (starting/stopping)
TEXT_MAIN   = "#f8fafc"  # Bright white text
TEXT_DIM    = "#94a3b8"  # Slate secondary text
FONT        = "Segoe UI"


# ---------------------------------------------------------------------------
# QR Code Matrix Generator (Uses reportlab built-in qrencoder)
# ---------------------------------------------------------------------------

def _generate_qr_matrix(text: str) -> list[list[bool]] | None:
    """Generate a 2D boolean matrix for QR code rendering without extra pip packages."""
    try:
        from reportlab.graphics.barcode.qrencoder import QRCode
        for version in range(1, 15):
            try:
                qr = QRCode(version, 0)
                qr.addData(text)
                qr.make()
                return qr.modules
            except Exception:
                continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Disk Logger (Structured logging to logs/launcher.log)
# ---------------------------------------------------------------------------

_log_lock = threading.Lock()

def _disk_log(message: str, level: str = "INFO"):
    """Thread-safe structured logging to customer logs directory."""
    try:
        log_file = get_logs_dir() / "launcher.log"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] [Launcher]: {message}\n"
        with _log_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Server Session (Encapsulates all session-specific state)
# ---------------------------------------------------------------------------

class ServerSession:
    """
    Container for session-specific state.
    A new instance is created on every Start operation.
    """
    def __init__(self, session_id):
        self.id = session_id

        self.django_port = None
        self.whatsapp_port = None

        self.node_process = None
        self.server_instance = None

        self.server_ready = threading.Event()
        self.cancelled = threading.Event()


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class ServerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION} — Contrôleur de Serveur")
        self.root.geometry("560x600")
        self.root.minsize(520, 540)
        self.root.configure(bg=BG)

        # ── Global application state ─────────────────────────────────────────
        self._session = None          # Active ServerSession instance or None
        self.is_running = False
        self.local_ip = get_local_ip()
        self._stopping = False

        self._startup_lock = threading.Lock()
        self._startup_counter = 0

        # Security
        self.whatsapp_api_key = self._load_or_create_api_key()

        # GUI
        self._build_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        _disk_log(f"Lanceur initialisé ({APP_NAME} v{VERSION}). Répertoire de données : {get_data_dir()}")

    # =========================================================================
    # API key
    # =========================================================================

    def _load_or_create_api_key(self):
        config = _load_local_config()
        api_key = config.get("WA_API_KEY")
        if not isinstance(api_key, str) or len(api_key) < 10:
            api_key = secrets.token_urlsafe(32)
            config["WA_API_KEY"] = api_key
            _save_local_config(config)
        return api_key

    # =========================================================================
    # Session management & Validation
    # =========================================================================

    def _new_startup_id(self):
        with self._startup_lock:
            self._startup_counter += 1
            return self._startup_counter

    def _is_valid_session(self, session):
        """
        Returns True iff *session* is the active session and has not been cancelled.
        Thread-safe check.
        """
        return (
            session is not None
            and session is self._session
            and not self._stopping
            and not session.cancelled.is_set()
        )

    # =========================================================================
    # Tkinter-safe logging & helpers
    # =========================================================================

    def _log(self, message):
        """Append entry to activity log. Main thread only."""
        clean_msg = message
        if self.whatsapp_api_key:
            clean_msg = clean_msg.replace(self.whatsapp_api_key, "[REDACTED]")

        _disk_log(clean_msg)

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {clean_msg}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _thread_log(self, message):
        """Thread-safe log helper using root.after."""
        self.root.after(0, lambda m=message: self._log(m))

    def _make_bg_log(self):
        """Return a logging function safe for background thread calls."""
        return lambda msg: self.root.after(0, lambda m=msg: self._log(m))

    def _clear_log(self):
        """Clear visible log entries."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open_data_folder(self):
        """Open customer data folder in Windows Explorer."""
        data_path = get_data_dir()
        try:
            if sys.platform == "win32":
                os.startfile(str(data_path))
            else:
                subprocess.Popen(["xdg-open", str(data_path)])
        except Exception as exc:
            self._log(f"Impossible d'ouvrir le dossier de données : {exc}")

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Buttons styling
        style.configure(
            "Start.TButton",
            background=GREEN, foreground="#ffffff",
            font=(FONT, 10, "bold"), padding=(10, 8), borderwidth=0,
        )
        style.map(
            "Start.TButton",
            background=[("disabled", "#1c3228"), ("active", "#059669")],
            foreground=[("disabled", "#4b6558")],
        )

        style.configure(
            "Stop.TButton",
            background=RED, foreground="#ffffff",
            font=(FONT, 10, "bold"), padding=(10, 8), borderwidth=0,
        )
        style.map(
            "Stop.TButton",
            background=[("disabled", "#331a22"), ("active", "#e11d48")],
            foreground=[("disabled", "#6e4550")],
        )

        style.configure(
            "Open.TButton",
            background="#0284c7", foreground="#ffffff",
            font=(FONT, 10, "bold"), padding=(10, 8), borderwidth=0,
        )
        style.map(
            "Open.TButton",
            background=[("disabled", "#162b3a"), ("active", "#0369a1")],
            foreground=[("disabled", "#415f75")],
        )

        style.configure(
            "Qr.TButton",
            background=PURPLE, foreground="#ffffff",
            font=(FONT, 10, "bold"), padding=(10, 8), borderwidth=0,
        )
        style.map(
            "Qr.TButton",
            background=[("disabled", "#22213a"), ("active", "#4338ca")],
            foreground=[("disabled", "#55527a")],
        )

    def _build_ui(self):
        root_frame = tk.Frame(self.root, bg=BG)
        root_frame.pack(fill="both", expand=True, padx=20, pady=18)

        # ── 1. Header ────────────────────────────────────────────────────────
        header = tk.Frame(root_frame, bg=BG)
        header.pack(fill="x", pady=(0, 14))

        titles_frame = tk.Frame(header, bg=BG)
        titles_frame.pack(side="left", fill="x", expand=True)

        tk.Label(titles_frame, text=APP_NAME, font=(FONT, 17, "bold"),
                 bg=BG, fg=TEXT_MAIN).pack(anchor="w")
        tk.Label(titles_frame, text=f"Contrôleur de Serveur Local • v{VERSION}", font=(FONT, 9),
                 bg=BG, fg=TEXT_DIM).pack(anchor="w")

        # Quick action: Open Data Folder
        data_btn = tk.Button(
            header, text="📂 Données", font=(FONT, 8, "bold"),
            bg=PANEL, fg=TEXT_DIM, activebackground=CARD_BORDER,
            activeforeground=TEXT_MAIN, bd=0, padx=10, pady=4,
            cursor="hand2", command=self._open_data_folder,
        )
        data_btn.pack(side="right")

        # ── 2. Status Card ───────────────────────────────────────────────────
        status_card = tk.Frame(root_frame, bg=PANEL, padx=16, pady=14,
                               highlightbackground=CARD_BORDER, highlightthickness=1)
        status_card.pack(fill="x", pady=(0, 14))

        # Status row
        status_row = tk.Frame(status_card, bg=PANEL)
        status_row.pack(fill="x")

        self.status_dot = tk.Canvas(status_row, width=16, height=16,
                                    bg=PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 10))
        self._draw_dot(RED)

        status_text_frame = tk.Frame(status_row, bg=PANEL)
        status_text_frame.pack(side="left", fill="x", expand=True)

        self.status_label = tk.Label(status_text_frame, text="Serveur Arrêté",
                                     font=(FONT, 13, "bold"), bg=PANEL, fg=TEXT_MAIN)
        self.status_label.pack(anchor="w")

        self.status_sub = tk.Label(status_text_frame,
                                   text="Cliquez sur 'Démarrer le Serveur' pour lancer l'application",
                                   font=(FONT, 9), bg=PANEL, fg=TEXT_DIM)
        self.status_sub.pack(anchor="w")

        # Service badges row
        badges_row = tk.Frame(status_card, bg=PANEL)
        badges_row.pack(fill="x", pady=(10, 4))

        self.web_badge = tk.Label(badges_row, text="🌐 Web : Arrêté",
                                  font=(FONT, 8, "bold"), bg=PANEL_ALT, fg=TEXT_DIM,
                                  padx=8, pady=3)
        self.web_badge.pack(side="left", padx=(0, 8))

        self.wa_badge = tk.Label(badges_row, text="💬 WhatsApp : Arrêté",
                                 font=(FONT, 8, "bold"), bg=PANEL_ALT, fg=TEXT_DIM,
                                 padx=8, pady=3)
        self.wa_badge.pack(side="left")

        # URLs display
        urls_box = tk.Frame(status_card, bg=PANEL)
        urls_box.pack(fill="x", pady=(8, 0))

        self.url_local_label = tk.Label(urls_box, text="",
                                        font=(FONT, 9, "bold"), bg=PANEL,
                                        fg=ACCENT, cursor="hand2")
        self.url_local_label.pack(anchor="w")
        self.url_local_label.bind("<Button-1>", lambda e: self._open_url("local"))

        self.url_lan_label = tk.Label(urls_box, text="",
                                      font=(FONT, 9), bg=PANEL,
                                      fg=TEXT_DIM, cursor="hand2")
        self.url_lan_label.pack(anchor="w", pady=(2, 0))
        self.url_lan_label.bind("<Button-1>", lambda e: self._open_url("lan"))

        # ── 3. Primary Action Buttons ────────────────────────────────────────
        btn_grid = tk.Frame(root_frame, bg=BG)
        btn_grid.pack(fill="x", pady=(0, 14))

        # Row 1: Start / Stop
        row1 = tk.Frame(btn_grid, bg=BG)
        row1.pack(fill="x", pady=(0, 6))

        self.start_btn = ttk.Button(row1, text="▶  Démarrer le Serveur",
                                    style="Start.TButton",
                                    command=self.start_services)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.stop_btn = ttk.Button(row1, text="■  Arrêter le Serveur",
                                   style="Stop.TButton",
                                   command=self.stop_services,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Row 2: Open browser / QR Code modal
        row2 = tk.Frame(btn_grid, bg=BG)
        row2.pack(fill="x")

        self.open_btn = ttk.Button(row2, text="🌐  Ouvrir l'Application",
                                   style="Open.TButton",
                                   command=lambda: self._open_url("local"),
                                   state=tk.DISABLED)
        self.open_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.qr_btn = ttk.Button(row2, text="📱  Accès Réseau (QR Code)",
                                 style="Qr.TButton",
                                 command=self.show_lan_qr_modal,
                                 state=tk.DISABLED)
        self.qr_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # ── 4. Activity Log ──────────────────────────────────────────────────
        log_header_frame = tk.Frame(root_frame, bg=BG)
        log_header_frame.pack(fill="x", pady=(0, 4))

        tk.Label(log_header_frame, text="JOURNAL D'ACTIVITÉ", font=(FONT, 8, "bold"),
                 bg=BG, fg=TEXT_DIM).pack(side="left")

        clear_btn = tk.Button(
            log_header_frame, text="Effacer", font=(FONT, 8),
            bg=BG, fg=TEXT_DIM, activebackground=BG,
            activeforeground=TEXT_MAIN, bd=0, cursor="hand2",
            command=self._clear_log,
        )
        clear_btn.pack(side="right")

        log_frame = tk.Frame(root_frame, bg=PANEL_ALT,
                             highlightbackground=CARD_BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame, bg=PANEL_ALT, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, font=("Consolas", 9),
            relief="flat", padx=10, pady=8,
            state="disabled", wrap="word",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._log("Prêt. Cliquez sur 'Démarrer le Serveur' pour commencer.")

    def _open_url(self, target="local"):
        if self._session and self._session.django_port:
            port = self._session.django_port
            url = f"http://127.0.0.1:{port}" if target == "local" else f"http://{self.local_ip}:{port}"
            webbrowser.open(url)

    def _draw_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 14, 14, fill=color, outline="")

    def _set_status(self, state, session=None):
        """Update the status card and interactive controls. Main thread only."""
        if state == "starting":
            self._draw_dot(AMBER)
            self.status_label.config(text="Démarrage en cours…")
            self.status_sub.config(text="Initialisation des services et ports réseau")
            self.url_local_label.config(text="")
            self.url_lan_label.config(text="")
            self.open_btn.config(state=tk.DISABLED)
            self.qr_btn.config(state=tk.DISABLED)
        elif state == "running":
            self._draw_dot(GREEN)
            self.status_label.config(text="En ligne & Opérationnel")
            self.status_sub.config(text="Accessible sur cet ordinateur et sur le réseau local")
            port = session.django_port if session else (self._session.django_port if self._session else 8000)
            wa_port = session.whatsapp_port if session else (self._session.whatsapp_port if self._session else 3000)

            self.url_local_label.config(text=f"🌐 Local  :  http://127.0.0.1:{port}  (cliquez pour ouvrir)")
            self.url_lan_label.config(text=f"📱 Réseau :  http://{self.local_ip}:{port}  (Wi-Fi / LAN)")

            self.web_badge.config(text=f"🌐 Web : Port {port}", fg=GREEN)
            self.wa_badge.config(text=f"💬 WhatsApp : Port {wa_port}", fg=GREEN)

            self.open_btn.config(state=tk.NORMAL)
            self.qr_btn.config(state=tk.NORMAL)
        elif state == "stopping":
            self._draw_dot(AMBER)
            self.status_label.config(text="Arrêt en cours…")
            self.status_sub.config(text="Fermeture des services d'arrière-plan")
            self.open_btn.config(state=tk.DISABLED)
            self.qr_btn.config(state=tk.DISABLED)
        elif state == "stopped":
            self._draw_dot(RED)
            self.status_label.config(text="Serveur Arrêté")
            self.status_sub.config(text="Cliquez sur 'Démarrer le Serveur' pour lancer l'application")
            self.url_local_label.config(text="")
            self.url_lan_label.config(text="")
            self.web_badge.config(text="🌐 Web : Arrêté", fg=TEXT_DIM)
            self.wa_badge.config(text="💬 WhatsApp : Arrêté", fg=TEXT_DIM)
            self.open_btn.config(state=tk.DISABLED)
            self.qr_btn.config(state=tk.DISABLED)
        elif state == "error":
            self._draw_dot(RED)
            self.status_label.config(text="Erreur de Démarrage")
            self.status_sub.config(text="Échec du démarrage du serveur — consultez le journal ci-dessous")
            self.open_btn.config(state=tk.DISABLED)
            self.qr_btn.config(state=tk.DISABLED)

    # =========================================================================
    # Modal: LAN QR Code for Mobile / Multi-PC Access
    # =========================================================================

    def show_lan_qr_modal(self):
        """Display dialog with high-contrast QR Code for mobile and LAN connection."""
        if not self._session or not self._session.django_port:
            messagebox.showinfo(
                "Réseau Local",
                "Le serveur doit être démarré pour générer le lien et le QR Code d'accès réseau.",
            )
            return

        port = self._session.django_port
        lan_url = f"http://{self.local_ip}:{port}"

        modal = tk.Toplevel(self.root)
        modal.title(f"{APP_NAME} — Accès Réseau Local (Wi-Fi / LAN)")
        modal.geometry("440x560")
        modal.minsize(420, 520)
        modal.configure(bg=BG)
        modal.transient(self.root)
        modal.grab_set()

        # Center on parent window
        try:
            modal.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 220
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 280
            modal.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        container = tk.Frame(modal, bg=BG, padx=20, pady=16)
        container.pack(fill="both", expand=True)

        tk.Label(
            container, text="📱 Connexion Mobile & Tablettes",
            font=(FONT, 13, "bold"), bg=BG, fg=TEXT_MAIN,
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text="Scannez ce QR Code pour ouvrir l'application sur un autre appareil\n(connecté au même réseau Wi-Fi).",
            font=(FONT, 9), bg=BG, fg=TEXT_DIM, justify="center",
        ).pack(pady=(0, 14))

        # QR Code Canvas
        matrix = _generate_qr_matrix(lan_url)
        canvas_size = 230
        qr_canvas = tk.Canvas(
            container, width=canvas_size, height=canvas_size,
            bg="#ffffff", highlightthickness=0, relief="flat",
        )
        qr_canvas.pack(pady=(0, 14))

        if matrix:
            n = len(matrix)
            margin = 15
            cell = (canvas_size - 2 * margin) / n
            for r in range(n):
                for c in range(n):
                    if matrix[r][c]:
                        x1 = margin + c * cell
                        y1 = margin + r * cell
                        x2 = x1 + cell
                        y2 = y1 + cell
                        qr_canvas.create_rectangle(x1, y1, x2, y2, fill="#000000", outline="")
        else:
            qr_canvas.create_text(
                canvas_size // 2, canvas_size // 2,
                text="QR Code non disponible\n(Module qrcode manquant)",
                fill="#333333", font=(FONT, 10), justify="center",
            )

        # Address Box
        addr_card = tk.Frame(container, bg=PANEL, padx=12, pady=8,
                             highlightbackground=CARD_BORDER, highlightthickness=1)
        addr_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            addr_card, text="Adresse Web sur le réseau :",
            font=(FONT, 8), bg=PANEL, fg=TEXT_DIM,
        ).pack(anchor="w")

        url_entry = tk.Entry(
            addr_card, font=("Consolas", 10, "bold"),
            bg=PANEL_ALT, fg=ACCENT, relief="flat", bd=0, justify="center",
        )
        url_entry.insert(0, lan_url)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x", pady=(4, 0))

        # Buttons row
        btn_frame = tk.Frame(container, bg=BG)
        btn_frame.pack(fill="x", pady=(0, 10))

        def _copy_link(btn):
            self.root.clipboard_clear()
            self.root.clipboard_append(lan_url)
            btn.config(text="✓ Adresse copiée !", bg=GREEN)
            self.root.after(2000, lambda: btn.config(text="📋 Copier le lien", bg=PANEL))

        copy_btn = tk.Button(
            btn_frame, text="📋 Copier le lien", font=(FONT, 9, "bold"),
            bg=PANEL, fg=TEXT_MAIN, activebackground=CARD_BORDER,
            activeforeground=TEXT_MAIN, bd=0, padx=12, pady=6,
            cursor="hand2", command=lambda: _copy_link(copy_btn),
        )
        copy_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        def _setup_firewall():
            try:
                cmd = f'netsh advfirewall firewall add rule name="School ERP Web (Port {port})" dir=in action=allow protocol=TCP localport={port}'
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    messagebox.showinfo(
                        "Pare-feu Windows",
                        f"Port {port} débloqué dans le Pare-feu Windows !\nLes autres ordinateurs et téléphones du réseau Wi-Fi peuvent maintenant se connecter.",
                    )
                else:
                    messagebox.showwarning(
                        "Pare-feu Windows",
                        "Impossible de modifier le pare-feu automatiquement.\nVeuillez exécuter ce lanceur en mode Administrateur.",
                    )
            except Exception as e:
                messagebox.showerror("Erreur", str(e))

        fw_btn = tk.Button(
            btn_frame, text="🛡️ Débloquer Pare-feu", font=(FONT, 9),
            bg=PANEL, fg=TEXT_DIM, activebackground=CARD_BORDER,
            activeforeground=TEXT_MAIN, bd=0, padx=10, pady=6,
            cursor="hand2", command=_setup_firewall,
        )
        fw_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        close_btn = tk.Button(
            container, text="Fermer", font=(FONT, 9),
            bg=BG, fg=TEXT_DIM, activebackground=BG,
            activeforeground=TEXT_MAIN, bd=0, cursor="hand2",
            command=modal.destroy,
        )
        close_btn.pack()

    # =========================================================================
    # WhatsApp health check
    # =========================================================================

    def _whatsapp_health_check(self, port, timeout=25):
        url = f"http://127.0.0.1:{port}/status"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        try:
                            data = json.loads(resp.read(4096))
                            return True, data.get("status")
                        except Exception:
                            return True, None
            except Exception:
                pass
            time.sleep(0.5)
        return False, None

    # =========================================================================
    # WhatsApp background thread
    # =========================================================================

    def prepare_and_launch_whatsapp(self, service_dir, session):
        """
        Background thread for Node.js WhatsApp service.
        Session-owned process management and stream reader threads.
        """
        if not self._is_valid_session(session):
            return

        node_cmd = get_node_executable()

        # Check Node.js runtime availability
        node_available = False
        try:
            r = _run_subprocess([node_cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                node_available = True
                self._thread_log(f"Using Node.js ({node_cmd}): {r.stdout.strip()}")
            else:
                self._thread_log("ERROR: Node.js version check returned non-zero.")
        except FileNotFoundError:
            self._thread_log(f"ERROR: Node.js runtime '{node_cmd}' was not found.")
        except subprocess.TimeoutExpired:
            self._thread_log("ERROR: Node.js version check timed out.")

        server_js_path    = os.path.join(service_dir, "server.js")
        package_json_path = os.path.join(service_dir, "package.json")

        if not node_available:
            self._thread_log("WhatsApp service cannot start without Node.js.")
            return

        if not os.path.isdir(service_dir):
            self._thread_log(f"ERROR: WhatsApp service directory not found: {service_dir}")
            return

        if not os.path.isfile(server_js_path):
            self._thread_log("ERROR: whatsapp_service/server.js not found.")
            return

        if not os.path.isfile(package_json_path):
            self._thread_log("ERROR: whatsapp_service/package.json not found.")
            return

        if not self._is_valid_session(session):
            return

        wa_port = session.whatsapp_port
        if wa_port is None:
            self._thread_log("ERROR: WhatsApp port was not assigned. Cannot start service.")
            return

        self._thread_log(f"Starting WhatsApp automation service on port {wa_port}...")

        popen_kwargs = {
            "cwd": service_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True

        env = os.environ.copy()
        env["WA_PORT"]             = str(wa_port)
        env["WA_API_KEY"]          = self.whatsapp_api_key
        env["WA_SESSION_DIR"]      = str(get_whatsapp_session_dir())
        env["WA_LOG_DIR"]          = str(get_logs_dir())
        env["SCHOOL_ERP_DATA_DIR"] = str(get_data_dir())
        if sys.platform != "win32":
            env["WA_DISABLE_SANDBOX"] = "true"

        chromium_bin = get_chromium_executable()
        if chromium_bin:
            env["CHROME_PATH"] = chromium_bin
            self._thread_log(f"Using Chromium runtime at: {chromium_bin}")

        launched_process = None
        for _attempt in range(1, 4):
            if not self._is_valid_session(session):
                return

            try:
                process = subprocess.Popen(
                    [node_cmd, "server.js"],
                    env=env,
                    **popen_kwargs,
                )
            except FileNotFoundError:
                self._thread_log(f"ERROR: node executable '{node_cmd}' not found during launch.")
                return
            except Exception as exc:
                self._thread_log(f"ERROR: Failed to launch WhatsApp service: {exc}")
                return

            # Atomic session ownership check right after Popen
            if not self._is_valid_session(session):
                _stop_process_tree(process, "WhatsApp service (stale session)", log_fn=None)
                return

            session.node_process = process

            # Dedicated daemon reader threads for stdout/stderr to prevent pipe deadlocks
            def _stream_reader(pipe, stream_name, sess):
                try:
                    for line in iter(pipe.readline, b""):
                        if not line or not self._is_valid_session(sess):
                            break
                        text = line.decode("utf-8", errors="replace").rstrip()
                        if text:
                            if self.whatsapp_api_key:
                                text = text.replace(self.whatsapp_api_key, "[REDACTED]")
                            if any(k in text for k in ("listening", "Error", "INITIALIZING", "READY", "QR", "STARTING")):
                                self._thread_log(f"[{stream_name}] {text}")
                except Exception:
                    pass
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            threading.Thread(
                target=_stream_reader,
                args=(process.stdout, "WhatsApp", session),
                daemon=True,
                name=f"wa-stdout-{session.id}",
            ).start()

            threading.Thread(
                target=_stream_reader,
                args=(process.stderr, "WhatsApp-Err", session),
                daemon=True,
                name=f"wa-stderr-{session.id}",
            ).start()

            time.sleep(1.5)

            exit_code = process.poll()
            if exit_code is None:
                if not self._is_valid_session(session):
                    _stop_process_tree(process, "WhatsApp service (stale session)", log_fn=None)
                    session.node_process = None
                    return
                launched_process = process
                break

            # Exit detected
            if not self._is_valid_session(session):
                session.node_process = None
                return

            try:
                wa_port = find_free_port(wa_port + 1, host="127.0.0.1")
                session.whatsapp_port = wa_port
                env["WA_PORT"] = str(wa_port)
                if self._is_valid_session(session):
                    os.environ["WA_PORT"] = str(wa_port)
                self._thread_log(f"WhatsApp port conflict. Retrying on port {wa_port}...")
                continue
            except RuntimeError as exc2:
                self._thread_log(f"ERROR: No available port for WhatsApp service: {exc2}")
                session.node_process = None
                return
        else:
            self._thread_log("ERROR: WhatsApp service failed to start after multiple port attempts.")
            return

        # Health check
        self._thread_log("Waiting for WhatsApp service to respond...")
        reachable, wa_status = self._whatsapp_health_check(wa_port, timeout=25)

        if not self._is_valid_session(session):
            return

        if reachable:
            self._thread_log(f"Service d'automatisation WhatsApp en écoute sur le port {wa_port}.")
            if wa_status == "READY":
                self._thread_log("Client WhatsApp connecté et opérationnel.")
                self.root.after(0, lambda: self.wa_badge.config(text=f"💬 WhatsApp: Port {wa_port} (Prêt)", fg=GREEN))
            elif wa_status in ("QR_RECEIVED", "INITIALIZING", "AUTHENTICATED", "STARTING"):
                self._thread_log(
                    f"Statut WhatsApp : {wa_status}. "
                    "Ouvrez le tableau de bord pour scanner le code QR si nécessaire."
                )
                self.root.after(0, lambda: self.wa_badge.config(text="💬 WhatsApp: QR Requis", fg=AMBER))
            elif wa_status in ("DISCONNECTED", "ERROR", "AUTHENTICATION_FAILED", "RESTART_WAIT"):
                self._thread_log(f"Statut WhatsApp : {wa_status}. Consultez le tableau de bord pour plus de détails.")
                self.root.after(0, lambda: self.wa_badge.config(text="💬 WhatsApp: Déconnecté", fg=AMBER))
            elif wa_status:
                self._thread_log(f"Statut WhatsApp : {wa_status}.")
        else:
            self._thread_log(
                "Le service WhatsApp a démarré mais le test de connexion a expiré "
                "(Chromium/Puppeteer est peut-être encore en cours d'initialisation)."
            )

    # =========================================================================
    # Django / Waitress background thread
    # =========================================================================

    def run_waitress(self, session):
        """
        Background thread for Waitress/Django server.
        Session-owned server instance and port binding.
        """
        self._thread_log("Chargement de Django & du serveur Waitress...")

        try:
            import os
            import django
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "school_erp.settings")
            django.setup()
            from django.core.management import call_command
            from core.paths import get_database_path

            db_file = get_database_path()
            if not db_file.exists() or db_file.stat().st_size == 0:
                self._thread_log("Initialisation de la base de données pour le premier lancement...")
                call_command("migrate", interactive=False, verbosity=0)
                self._thread_log("Base de données initialisée avec succès.")

            from django.contrib.staticfiles.handlers import StaticFilesHandler
            from school_erp.wsgi import application
            from waitress.server import create_server
        except Exception as exc:
            self._thread_log(f"ERREUR : Échec du chargement de Django/Waitress : {exc}")
            if self._is_valid_session(session):
                self.root.after(0, lambda exc=exc: self._handle_session_failure(session, f"Erreur Django: {exc}"))
            return

        if not self._is_valid_session(session):
            return

        server = None
        for _attempt in range(1, 6):
            if not self._is_valid_session(session):
                return
            try:
                server = create_server(
                    StaticFilesHandler(application),
                    host="0.0.0.0",
                    port=session.django_port,
                    threads=8,
                    channel_timeout=30,
                )
                break
            except OSError as exc:
                msg = str(exc).lower()
                if "address already in use" in msg or "port is already allocated" in msg:
                    self._thread_log(f"Port Django {session.django_port} occupé. Nouvelle tentative...")
                    try:
                        new_port = find_free_port(session.django_port + 1)
                        session.django_port = new_port
                        self._thread_log(f"Nouveau port sélectionné : {session.django_port}")
                        continue
                    except RuntimeError as port_exc:
                        self._thread_log(f"ERREUR : Aucun port disponible pour Django : {port_exc}")
                        if self._is_valid_session(session):
                            self.root.after(0, lambda: self._handle_session_failure(session, str(port_exc)))
                        return
                self._thread_log(f"ERREUR : Échec de liaison Waitress : {exc}")
                if self._is_valid_session(session):
                    self.root.after(0, lambda e=exc: self._handle_session_failure(session, f"Échec liaison Waitress: {e}"))
                return
        else:
            self._thread_log("ERREUR : Échec du démarrage de Django après plusieurs tentatives de port.")
            if self._is_valid_session(session):
                self.root.after(0, lambda: self._handle_session_failure(session, "Épuisement des ports disponibles"))
            return

        if not self._is_valid_session(session):
            try:
                server.close()
            except Exception:
                pass
            return

        session.server_instance = server

        if not self._is_valid_session(session):
            try:
                server.close()
            except Exception:
                pass
            session.server_instance = None
            return

        # Mark session live on main thread
        def _mark_live():
            if self._is_valid_session(session):
                self.is_running = True
                self._set_status("running", session)
                self._log(
                    f"Serveur Django actif sur http://{self.local_ip}:{session.django_port} (accessible sur le réseau local)."
                )

        self.root.after(0, _mark_live)
        session.server_ready.set()

        try:
            server.run()
        except Exception as exc:
            self._thread_log(f"Erreur du serveur Waitress : {exc}")
        finally:
            def _on_django_exit():
                if self._is_valid_session(session):
                    self.is_running = False
                    self._begin_shutdown(destroy_after=False)

            self.root.after(0, _on_django_exit)

    # =========================================================================
    # Session failure handler (main thread)
    # =========================================================================

    def _handle_session_failure(self, session, message):
        """Called on main thread when a session fails to start."""
        if self._is_valid_session(session):
            self._log(f"ERREUR : {message}")
            self._set_status("error")
            self._begin_shutdown(destroy_after=False)

    # =========================================================================
    # Browser opener (background thread)
    # =========================================================================

    def open_browser_delayed(self, session):
        """Waits on session.server_ready and TCP port check, then opens browser."""
        if not session.server_ready.wait(timeout=30):
            if self._is_valid_session(session):
                self._thread_log("Délai d'attente dépassé pour la préparation de Django.")
            return

        if not self._is_valid_session(session):
            return

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not self._is_valid_session(session):
                return
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(("127.0.0.1", session.django_port)) == 0:
                        break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            if self._is_valid_session(session):
                self._thread_log("Délai d'attente dépassé pour l'ouverture du port Django.")
            return

        if not self._is_valid_session(session):
            return

        url = f"http://127.0.0.1:{session.django_port}"
        try:
            webbrowser.open(url)
            self._thread_log(f"Navigateur ouvert avec succès à l'adresse : {url}")
        except Exception as exc:
            self._thread_log(f"Impossible d'ouvrir le navigateur automatiquement : {exc}")

    # =========================================================================
    # Start services
    # =========================================================================

    def start_services(self):
        """Main thread entry point to start services under a new ServerSession."""
        if self.is_running or self._stopping or self._session is not None:
            return

        session_id = self._new_startup_id()
        session = ServerSession(session_id)
        self._session = session
        self._stopping = False

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("starting")
        self._log("Démarrage du serveur en cours…")

        try:
            session.django_port = find_free_port(8000)
            self._log(f"Port Web Django alloué : {session.django_port}")
            session.whatsapp_port = find_free_port(3000, host="127.0.0.1")
            self._log(f"Port service WhatsApp alloué : {session.whatsapp_port}")

            os.environ["WA_PORT"] = str(session.whatsapp_port)
            os.environ["WA_API_KEY"] = self.whatsapp_api_key
        except Exception as exc:
            self._log(f"ERREUR : Impossible de réserver les ports réseau : {exc}")
            self._set_status("error")
            self._session = None
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            return

        base_dir = _get_base_dir()
        service_dir = os.path.join(base_dir, "whatsapp_service")

        threading.Thread(
            target=self.prepare_and_launch_whatsapp,
            args=(service_dir, session),
            daemon=True,
            name=f"wa-{session_id}",
        ).start()

        threading.Thread(
            target=self.run_waitress,
            args=(session,),
            daemon=True,
            name=f"django-{session_id}",
        ).start()

        threading.Thread(
            target=self.open_browser_delayed,
            args=(session,),
            daemon=True,
            name=f"browser-{session_id}",
        ).start()

    # =========================================================================
    # Unified Shutdown
    # =========================================================================

    def _begin_shutdown(self, destroy_after=False):
        """
        Unified shutdown entry point.
        Invalidates active session, captures process/server references, and tears down in worker thread.
        """
        if self._stopping and not destroy_after:
            return

        self._stopping = True
        self.is_running = False

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)

        if not destroy_after:
            self._set_status("stopping")
            self._log("Arrêt des services en cours…")

        # Capture and clear active session
        session = self._session
        self._session = None

        if session:
            session.cancelled.set()
            session.server_ready.set()  # Unblock browser thread

        def _worker():
            bg_log = self._make_bg_log()
            if session:
                if session.node_process:
                    _stop_process_tree(session.node_process, "Service WhatsApp", log_fn=bg_log)
                    session.node_process = None
                if session.server_instance:
                    try:
                        session.server_instance.close()
                        bg_log("Serveur Waitress arrêté.")
                    except Exception as exc:
                        bg_log(f"Erreur lors de la fermeture de Waitress : {exc}")
                    session.server_instance = None

            def _finish():
                self._stopping = False
                if destroy_after:
                    self.root.destroy()
                else:
                    self._set_status("stopped")
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)

            self.root.after(0, _finish)

        threading.Thread(
            target=_worker,
            daemon=True,
            name="shutdown-worker",
        ).start()

    def stop_services(self):
        """Stop button callback."""
        self._begin_shutdown(destroy_after=False)

    def on_closing(self):
        """Window close (X button) handler."""
        server_running = self.is_running
        node_running   = (
            self._session is not None
            and self._session.node_process is not None
            and self._session.node_process.poll() is None
        )

        if server_running or node_running:
            if not messagebox.askokcancel(
                "Quitter l'application",
                f"Les services de {APP_NAME} sont actuellement en cours d'exécution.\n\nVoulez-vous les arrêter et fermer l'application ?",
            ):
                return

        self._begin_shutdown(destroy_after=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerApp(root)
    root.mainloop()
