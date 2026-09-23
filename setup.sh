#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo " School ERP - Automated Client Setup (Linux)"
echo "=============================================================================="
echo

PYTHON_EXE=""
if [ -f "$SCRIPT_DIR/runtime/python/bin/python" ]; then
    PYTHON_EXE="$SCRIPT_DIR/runtime/python/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON_EXE="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_EXE="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
fi

if [ -z "$PYTHON_EXE" ]; then
    echo "[ERROR] Python 3.10+ was not found on this system."
    exit 1
fi

echo "Found Python: $PYTHON_EXE"
"$PYTHON_EXE" "$SCRIPT_DIR/setup_client.py" "$@"
