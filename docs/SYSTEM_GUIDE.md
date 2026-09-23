# School ERP — Complete System Architecture & Operations Guide

Welcome to the comprehensive technical and operational manual for **School ERP**. This guide covers system architecture, local Windows client deployment, cloud/online deployment, licensing, and operational workflows.

---

## Table of Contents
1. [System Overview & Architecture](#1-system-overview--architecture)
2. [Local Windows On-Premises Deployment](#2-local-windows-on-premises-deployment)
3. [Licensing System (Local & Cloud)](#3-licensing-system-local--cloud)
4. [Cloud & Online Deployment (Railway, Render, VPS)](#4-cloud--online-deployment)
5. [WhatsApp Automation Service](#5-whatsapp-automation-service)
6. [Data Storage, Backups & Upgrades](#6-data-storage-backups--upgrades)
7. [Day-to-Day Administration & Troubleshooting](#7-day-to-day-administration--troubleshooting)

---

## 1. System Overview & Architecture

### Technology Stack
- **Web Framework**: Django 5.2 / 6.0 with Python 3.11–3.14
- **Admin & UI**: Django Unfold (modern, responsive Tailwind-based dashboard), Django HTMX
- **Static File Engine**: WhiteNoise (`CompressedManifestStaticFilesStorage`) with asset hashing & Gzip/Brotli compression
- **WhatsApp Engine**: Node.js microservice (`whatsapp-web.js` + Puppeteer controlling headless Chromium)
- **Database**:
  - **Local (Windows 10/11)**: SQLite in **WAL mode** (Write-Ahead Logging) for safe concurrent LAN multi-user access
  - **Cloud Deployment**: PostgreSQL via `dj-database-url` and `psycopg2-binary`

### Repository Layout
```
├── core/                   # Main Django app: models, views, analytics, licensing, paths
├── school_erp/             # Django project settings, URLs, WSGI/ASGI configurations
├── static/                 # Static assets (CSS, JS, Fonts, Icons, Images)
├── staticfiles/            # Compiled static root produced by collectstatic
├── templates/              # HTML templates for dashboards & cockpit
├── whatsapp_service/       # Node.js background service for WhatsApp automation
├── tools/                  # Vendor tools (licensing, obfuscation, fingerprint collection)
├── scripts/                # Packaging and release build scripts (PowerShell, Bash, Batch)
├── docs/                   # Additional operational and testing documentation
├── installer.iss           # Inno Setup script for building Windows installer .exe
├── nixpacks.toml           # Railway / Nixpacks build configuration (Chromium, Node, Python)
├── Procfile                # Process definitions for cloud deployment (web, worker, release)
└── run_server.py           # GUI & tray server launcher for local Windows deployments
```

---

## 2. Local Windows On-Premises Deployment

For private tutoring centers and schools running locally on Windows 10/11:

### 2.1 Clean Separation of Code vs Customer Data
To ensure updates and uninstallation never delete client data:
- **Application Code** (Immutable): `C:\Program Files\School ERP\`
- **Customer Data** (Mutable & Preserved): `C:\ProgramData\SchoolERP\`
  - `database/`: Active SQLite database (`database.sqlite3` with `-wal` and `-shm` files)
  - `media/`: Uploaded photos, documents, and student attachments
  - `backups/`: Automated and manual database snapshots
  - `whatsapp_session/`: WhatsApp Web credentials & QR authentication cache
  - `logs/`: Application logs (`django.log`, `whatsapp.log`)
  - `licenses/`: Client license file (`license.enc`)

### 2.2 Running Locally
Launch the application via:
```powershell
python run_server.py
```
This launcher starts Django on Waitress, checks prerequisites, launches the WhatsApp background service, and displays a system tray icon.

### 2.3 Creating the Standalone Windows Installer (`.exe`)
1. On a Windows build machine, run:
   ```powershell
   .\scripts\build_windows_release.ps1
   ```
2. Compile the installer with **Inno Setup 6**:
   ```cmd
   ISCC.exe installer.iss
   ```
3. The standalone setup `.exe` will be generated in `dist/SchoolERP_Setup_v1.0.0.exe`.

---

## 3. Licensing System (Local & Cloud)

The licensing system protects the software against unauthorized copying and enforces trial or subscription expiration dates.

### 3.1 License Structure
A license payload contains:
```json
{
  "LICENSED_FINGERPRINT": "<Hardware SHA-256 Hash or *>",
  "START_DATE": "YYYY-MM-DD",
  "END_DATE": "YYYY-MM-DD"
}
```

### 3.2 Distributing a Free Trial or Paid Version to a Client
1. **Collect Client Fingerprint**:
   On the client machine, run:
   ```powershell
   python tools/fingerprint_generator.py
   ```
   *(Or run the one-line PowerShell command without Python installed:)*
   ```powershell
   $u = (Get-CimInstance Win32_ComputerSystemProduct).UUID; $b = (Get-CimInstance Win32_BaseBoard).SerialNumber; $str = "$u|$b"; $sha = [System.Security.Cryptography.SHA256]::Create(); $hash = [System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($str))).Replace("-","").ToLower(); Write-Host "Fingerprint: $hash"
   ```

2. **Generate the Encrypted `license.enc`**:
   Edit `tools/license_source.json`:
   ```json
   {
     "LICENSED_FINGERPRINT": "PASTE_CLIENT_FINGERPRINT_HERE",
     "START_DATE": "2026-08-24",
     "END_DATE": "2026-09-24"
   }
   ```
   Run:
   ```bash
   python tools/encrypt_license.py --force
   ```

3. **Install the License**:
   Place the generated `license.enc` into:
   ```
   C:\ProgramData\SchoolERP\licenses\license.enc
   ```

### 3.3 Renewing / Extending a License
When a center pays to renew:
- Simply generate a new `license.enc` with a new `END_DATE` (e.g. `2036-12-31`).
- Send the `license.enc` file to the client to replace the old one in `C:\ProgramData\SchoolERP\licenses\`.
- **No data is lost and no reinstallation is required.**

### 3.4 Cloud Deployment Licensing
For cloud servers (where hardware is ephemeral), the default bundled `license.enc` uses the wildcard fingerprint `*`, allowing it to run smoothly on any container.

---

## 4. Cloud & Online Deployment

The application is fully container-ready and configured for platforms like **Railway**, **Render**, **Fly.io**, or standard **Linux VPS**.

### 4.1 Deployment Configuration Files
- **`Procfile`**:
  - `web`: `gunicorn school_erp.wsgi --workers 2 --log-file -`
  - `worker`: `cd whatsapp_service && node server.js`
  - `release`: `python manage.py collectstatic --noinput && python manage.py migrate --noinput && cd whatsapp_service && npm install --omit=dev`
- **`nixpacks.toml`**: Automatically provisions Python, Node.js 22, and **Chromium** (for WhatsApp automation) with system font libraries.
- **`railway.json`**: Configures Railway deployment properties and restart policies.

### 4.2 Required Environment Variables
Configure these in your cloud provider's dashboard (see `.env.example`):

| Variable | Description | Example |
|---|---|---|
| `DJANGO_SECRET_KEY` | Unique random secret key | `django-insecure-xyz...` |
| `DJANGO_DEBUG` | Production debug toggle | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated domains | `school.yourdomain.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS origins for CSRF | `https://school.yourdomain.com` |
| `DATABASE_URL` | PostgreSQL connection string | `postgres://user:pass@host:5432/db` |
| `WA_PORT` | Port for the Node WhatsApp service | `3000` |
| `WA_API_KEY` | Optional shared secret for WA API | `secure-api-key-here` |

---

## 5. WhatsApp Automation Service

The WhatsApp background service handles automated communications (absences, receipts, announcements):

- **Technology**: Node.js with `whatsapp-web.js` + Puppeteer.
- **QR Code Scanning**:
  - Direct scanning via the School ERP web dashboard (**Cockpit > WhatsApp**).
  - Credentials and session tokens are preserved in `data/whatsapp_session/` (local) or `whatsapp_session/` (cloud).
- **Chromium Discovery**:
  - Auto-detects Chromium path via `which chromium` / `which google-chrome-stable`.
  - Can be manually overridden using `CHROME_PATH`.
- **Endpoints**:
  - `GET /status`: Checks connection state (`QR_RECEIVED`, `AUTHENTICATED`, `READY`, `OFFLINE`).
  - `POST /send`: Sends individual/bulk messages and PDF attachments.
  - `POST /logout`: Clears session data for re-linking.

---

## 6. Data Storage, Backups & Upgrades

### 6.1 Database Concurrency (SQLite WAL Mode)
When running locally with multiple staff computers over a Local Area Network (LAN):
- SQLite is configured with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=30000`.
- Readers do not block writers, preventing `"database is locked"` exceptions during peak check-in hours.

### 6.2 Backups
- Automatic snapshots are saved to `C:\ProgramData\SchoolERP\backups\` (local) or `data/backups/`.
- To perform a manual backup, copy the `database/database.sqlite3` file (and its `-wal` file if running).

### 6.3 Safe Application Upgrades
Upgrading software on a client machine:
1. Run the new installer `.exe`.
2. It overwrites only files in `C:\Program Files\School ERP\`.
3. Customer databases, media uploads, and message logs in `C:\ProgramData\SchoolERP\` remain 100% untouched.

---

## 7. Day-to-Day Administration & Troubleshooting

### Common Diagnostics

#### 1. "Static files / CSS not loading in production"
- Run: `python manage.py collectstatic --noinput`
- Verify that `whitenoise.middleware.WhiteNoiseMiddleware` is positioned directly after `SecurityMiddleware` in `school_erp/settings.py`.

#### 2. "WhatsApp service offline"
- Check that Node.js dependencies are installed (`cd whatsapp_service && npm install`).
- Check `whatsapp.log` for browser launch issues.
- Verify Chromium is installed (`which chromium`).

#### 3. "This copy of the application is not licensed for this device"
- Verify that `license.enc` exists in `C:\ProgramData\SchoolERP\licenses\` or the project root.
- Verify that the machine fingerprint matches the one used to generate the license.
- Check that the system clock on the PC is set correctly and within the `START_DATE` and `END_DATE` range.
