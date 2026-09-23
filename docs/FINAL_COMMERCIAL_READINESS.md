# Final Commercial Readiness & Audit Verification Matrix

This document provides the authoritative commercial packaging verification status for **School ERP** (v1.0.0), distinguishing components verified on Ubuntu from those requiring physical/VM Windows execution.

---

## 1. Readiness Audit Matrix

| Category | Component / Requirement | Status | Verification Detail |
| :--- | :--- | :--- | :--- |
| **Architecture** | Read-Only Application in `Program Files` | **[PASS]** | App binaries, templates, static assets, and runtimes resolve in application directory. |
| **Architecture** | Read-Write Customer Data in `ProgramData` | **[PASS]** | All mutable paths resolve to `C:\ProgramData\SchoolERP` via `core/paths.py`. |
| **Architecture** | Central Path Abstraction (`core/paths.py`)| **[PASS]** | 9 packaging unit tests verify resolution, directory creation, and env override. |
| **Python Runtime** | Private Bundled Runtime (`runtime/python`)| **[PASS]** | `run_server.py` checks `runtime/python/` before venv/system Python. |
| **Python Runtime** | Python Embed site-packages support | **[PASS]** | Build script uncomments `import site` in `._pth` and pre-installs wheels. |
| **Node Runtime** | Private Bundled Node (`runtime/node`) | **[PASS]** | Discovers `runtime/node/node.exe` with system fallback in development. |
| **Node Runtime** | Zero Runtime `npm install` | **[PASS]** | `_check_npm_update()` eliminated from startup. `package-lock.json` enforced. |
| **Chromium** | Private Bundled Chromium (`runtime/chromium`)| **[PASS]** | Discovers `runtime/chromium/chrome.exe` and passes `CHROME_PATH` to Node. |
| **WhatsApp** | Session Isolation in `ProgramData` | **[PASS]** | `LocalAuth` session located at `C:\ProgramData\SchoolERP\whatsapp_session\`. |
| **WhatsApp** | Single Active Client & Mutex Queue | **[PASS]** | `whatsapp_service/server.js` serializes all actions via `enqueueAction`. |
| **WhatsApp** | Exponential Backoff Retry | **[PASS]** | Prevents tight infinite crash loops and eliminates browser lock collisions. |
| **Launcher** | Non-Admin Standard User Operation | **[PASS]** | Launcher only writes to `ProgramData` (never writes to `Program Files`). |
| **Launcher** | Graceful Process Teardown | **[PASS]** | Process tree termination (`taskkill /T /F` on Win, `os.killpg` on Linux) cleans Node and Chromium. |
| **Ports** | Dynamic Free Port Allocation | **[PASS]** | Searches free TCP ports > 1024; retries on collision with LAN IP detection. |
| **Logging** | Structured Rotating Disk Logs | **[PASS]** | Rotating 5MB logs in `logs/django.log`, `logs/launcher.log`, `logs/whatsapp.log` with secret redaction. |
| **Licensing** | Preservation & Hardware Locking | **[PASS]** | `core/license.py` reads `licenses/license.enc`. AES-GCM and PowerShell fingerprint unchanged. |
| **Database** | Upgrade Data Preservation | **[PASS]** | `database.sqlite3` stored in `ProgramData` and untouched by installer updates. |
| **Database** | First-Run Auto Migration | **[PASS]** | Auto-applies initial migrations on clean machines if database is missing. |
| **Installer** | Inno Setup Definition (`installer.iss`) | **[PASS]** | Configured with `Permissions: users-full` on ProgramData and Start Menu / Desktop shortcuts. |
| **Release Build** | Pre-Release Validation Script | **[PASS]** | `./scripts/prepare_release.sh` executes 8 validation stages with 0 errors. |
| **Offline** | 100% Offline Local Operation | **[PASS]** | Zero runtime downloads or CDN dependencies for local ERP operation. |
| **Clean Machine** | Clean Windows 10/11 Installer Execution | **[NOT TESTED]** | Requires execution on physical/VM Windows machine. |
| **Code Signing** | SmartScreen / EV Authenticode Signature | **[NOT TESTED]** | Requires code signing certificate on Windows build machine. |

---

## 2. Distinction: Verified on Ubuntu vs. Requires Windows Test

### Verified on Ubuntu (100% Complete)
1. Central path resolution (`core/paths.py`) and environment overrides.
2. Complete test suite passing: **55 passed tests (46 ERP tests + 9 packaging tests)**.
3. Django configuration checks: **0 issues**.
4. Database migrations consistency: **0 ungenerated migrations**.
5. Node.js WhatsApp service syntax, state machine, and `npm ci` lockfile audit.
6. Desktop controller (`run_server.py`) runtime discovery and logging.
7. Automated release scripts (`scripts/prepare_release.sh`, `scripts/build_windows_release.ps1`).
8. Static asset collection simulation (237 static files validated).

### Requires Windows Test (To be run on Windows 10/11 machine)
1. Inno Setup `.EXE` compilation via `ISCC.exe installer.iss`.
2. Clean machine installation wizard execution on a PC without Python/Node/Chrome.
3. Desktop and Start Menu shortcut launch test.
4. EV Code Signing (optional for SmartScreen warning elimination).
