#!/usr/bin/env bash
# ==============================================================================
# School ERP - Automated Setup for Linux / macOS
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo " School ERP - Automated System Setup (Linux / macOS)"
echo "=============================================================================="
echo

# 1. Detect Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3.10+ is required but was not found on this system."
    echo "Please install python3 and python3-venv (e.g. sudo apt install python3 python3-venv)"
    exit 1
fi

PY_OK=$("$PYTHON_CMD" -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>/dev/null || echo 0)
if [ "$PY_OK" != "1" ]; then
    echo "[ERROR] School ERP requires Python 3.10 or newer."
    exit 1
fi

echo "[OK] Found System Python: $("$PYTHON_CMD" --version)"

# 2. Check Node
if command -v node >/dev/null 2>&1; then
    echo "[OK] Found Node.js: $(node -v)"
else
    echo "[WARN] Node.js not found on PATH. WhatsApp microservice requires Node.js."
fi

# 3. Create venv if missing
VENV_DIR="$SCRIPT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[*] Creating virtual environment in venv..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created."
fi

# 4. Run setup_client.py
"$VENV_PYTHON" "$SCRIPT_DIR/setup_client.py" "$@"
