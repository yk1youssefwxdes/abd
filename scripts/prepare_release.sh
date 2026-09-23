#!/usr/bin/env bash
# ==============================================================================
# School ERP - Commercial Release Preparation & Validation Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "======================================================================"
echo " Starting School ERP Release Validation & Preparation"
echo " Project Root: ${PROJECT_ROOT}"
echo "======================================================================"

cd "${PROJECT_ROOT}"

# 1. Determine Python Interpreter
PYTHON_BIN="python3"
if [ -f "${PROJECT_ROOT}/venv/bin/python" ]; then
    PYTHON_BIN="${PROJECT_ROOT}/venv/bin/python"
elif [ -f "${PROJECT_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

echo "[1/8] Verifying Python Environment using: $(${PYTHON_BIN} --version)..."

# 2. Verify Required Files
echo "[2/8] Checking required project files and manifests..."
REQUIRED_FILES=(
    "manage.py"
    "school_erp/settings.py"
    "school_erp/wsgi.py"
    "core/paths.py"
    "core/version.py"
    "version.json"
    "requirements.txt"
    "run_server.py"
    "whatsapp_service/server.js"
    "whatsapp_service/package.json"
    "whatsapp_service/package-lock.json"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "${PROJECT_ROOT}/${file}" ]; then
        echo "ERROR: Required file missing: ${file}" >&2
        exit 1
    fi
done
echo "  -> All required files are present."

# 3. Validate Node.js & npm dependencies via npm ci
echo "[3/8] Validating Node.js dependencies via 'npm ci' in whatsapp_service..."
if command -v npm >/dev/null 2>&1; then
    (
        cd "${PROJECT_ROOT}/whatsapp_service"
        npm ci --ignore-scripts --prefer-offline || npm ci
    )
    echo "  -> whatsapp_service dependencies locked and verified."
else
    echo "WARNING: npm not found on PATH. Skipping npm ci verification."
fi

# 4. Check Node.js syntax
echo "[4/8] Validating Node.js WhatsApp service syntax..."
if command -v node >/dev/null 2>&1; then
    node -c "${PROJECT_ROOT}/whatsapp_service/server.js"
    echo "  -> server.js syntax verified."
else
    echo "WARNING: node not found on PATH. Skipping syntax check."
fi

# 5. Django System Checks
echo "[5/8] Running Django system configuration checks..."
${PYTHON_BIN} manage.py check
echo "  -> Django system checks passed."

# 6. Django Migrations Check
echo "[6/8] Verifying database migrations consistency..."
${PYTHON_BIN} manage.py makemigrations --check --dry-run
echo "  -> No ungenerated migrations found."

# 7. Django Test Suite
echo "[7/8] Running automated test suite..."
${PYTHON_BIN} manage.py test
echo "  -> All tests passed successfully."

# 8. Verify Static Assets
echo "[8/8] Testing static asset collection..."
${PYTHON_BIN} manage.py collectstatic --noinput --dry-run
echo "  -> Static files collection validated."

echo "======================================================================"
echo " RELEASE PREPARATION & VALIDATION SUCCESSFUL"
echo " School ERP is clean, validated, and ready for packaging."
echo "======================================================================"
