# School ERP — Release Preparation & Build Process

This document describes the step-by-step reproducible process for building and validating a release of **School ERP** for commercial distribution.

---

## 1. Release Architecture Overview

A commercial release package contains:
1. **Application Source Code**: `school_erp/`, `core/`, `templates/`, `static/`, `manage.py`, `version.json`.
2. **Compiled Static Assets**: `staticfiles/` (pre-collected via `collectstatic`).
3. **WhatsApp Microservice**: `whatsapp_service/` with locked production `node_modules/` (built via `npm ci --omit=dev`).
4. **Desktop Launcher**: `run_server.py`.
5. **Private Runtimes** (for Windows packaging):
   * `runtime/python/` (Standalone Python + site-packages)
   * `runtime/node/` (Standalone `node.exe`)
   * `runtime/chromium/` (Tested `chrome.exe`)

---

## 2. Automated Pre-Release Validation on Linux/Ubuntu

Before packaging for Windows, run the automated validation script:

```bash
./scripts/prepare_release.sh
```

### What `prepare_release.sh` Verifies:
1. **Python Environment**: Checks interpreter version (3.10+).
2. **File Integrity**: Ensures required core files (`manage.py`, `core/paths.py`, `core/version.py`, `version.json`, `run_server.py`, `requirements.txt`, `whatsapp_service/package-lock.json`) exist.
3. **Deterministic Node Dependencies**: Runs `npm ci` inside `whatsapp_service/`.
4. **JavaScript Syntax**: Validates `whatsapp_service/server.js` syntax.
5. **Django System Checks**: Executes `manage.py check`.
6. **Migrations Consistency**: Executes `manage.py makemigrations --check --dry-run` to ensure no ungenerated migrations.
7. **Automated Tests**: Runs the Django test suite (`manage.py test`).
8. **Static Files Collection**: Validates that all static assets can be collected without conflicts.

---

## 3. Assembling the Release Directory for Windows Packaging

On the build machine:

```bash
# 1. Clean previous builds
rm -rf release/SchoolERP

# 2. Create release folder structure
mkdir -p release/SchoolERP/runtime/python
mkdir -p release/SchoolERP/runtime/node
mkdir -p release/SchoolERP/runtime/chromium

# 3. Copy application files (excluding development and customer data)
rsync -av --exclude='data' \
          --exclude='logs' \
          --exclude='backups' \
          --exclude='venv' \
          --exclude='.venv' \
          --exclude='.git' \
          --exclude='*.sqlite3*' \
          --exclude='__pycache__' \
          --exclude='whatsapp_session' \
          --exclude='.wwebjs_cache' \
          ./ release/SchoolERP/

# 4. Prepare production Node modules
(cd release/SchoolERP/whatsapp_service && npm ci --omit=dev)

# 5. Collect static assets
(cd release/SchoolERP && ./venv/bin/python manage.py collectstatic --noinput)
```

---

## 4. Forbidden Items in Release Package

The following items **must never** be packaged into a customer release:
* `data/` directory (customer database, uploads, local logs)
* `*.sqlite3`, `*.sqlite3-wal`, `*.sqlite3-shm`
* `.env` or local secret files
* `whatsapp_service/whatsapp_session/` or personal WhatsApp tokens
* `venv/` or `.venv/` (Linux virtual environment)
* `.git/` metadata and IDE settings
