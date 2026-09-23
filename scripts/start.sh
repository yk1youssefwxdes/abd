#!/bin/bash
set -e

echo "=================================================="
echo "  Starting School ERP Production Services"
echo "=================================================="

# 1. Auto-detect Chromium path if not already provided
if [ -z "$CHROME_PATH" ]; then
    DETECTED_CHROME=$(which chromium 2>/dev/null || which chromium-browser 2>/dev/null || which google-chrome-stable 2>/dev/null || which google-chrome 2>/dev/null || true)
    if [ -n "$DETECTED_CHROME" ]; then
        export CHROME_PATH="$DETECTED_CHROME"
        echo "[*] Auto-detected Chromium at: $CHROME_PATH"
    fi
fi

# 2. Start Node.js WhatsApp automation service in background
if [ -d "whatsapp_service" ]; then
    echo "[*] Launching WhatsApp automation background service..."
    (cd whatsapp_service && node server.js) &
    WA_PID=$!
    echo "[✔] WhatsApp service started with PID $WA_PID"
fi

# 2. Start Gunicorn web server for Django in foreground
echo "[*] Starting Gunicorn web server on port ${PORT:-8000}..."
exec gunicorn school_erp.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --log-file -
