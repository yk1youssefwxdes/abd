
const express = require('express');

const app = express();

const port = Number(process.env.WA_PORT || 3000);
const host = process.env.WA_HOST || '0.0.0.0';
const API_KEY = process.env.WA_API_KEY || null;

const SERVICE_VERSION = 'dev-1.0.0';

app.use(express.json({ limit: '100mb' }));

// ─────────────────────────────────────────────────────────────────────────────
// Logger
// ─────────────────────────────────────────────────────────────────────────────

function log(level, message, meta = null) {
    const timestamp = new Date().toISOString();

    const logLine =
        `[${timestamp}][${level.toUpperCase()}][WhatsApp DEV]: ${message} ` +
        (meta ? ` ${JSON.stringify(meta)} ` : '');

    if (level === 'error') {
        console.error(logLine);
    } else if (level === 'warn') {
        console.warn(logLine);
    } else {
        console.log(logLine);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// API Key Middleware
// ─────────────────────────────────────────────────────────────────────────────

function requireApiKey(req, res, next) {
    if (!API_KEY) {
        return next();
    }

    const key = req.headers['x-api-key'];

    if (key === API_KEY) {
        return next();
    }

    return res.status(401).json({
        success: false,
        error: 'Unauthorized'
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Fake WhatsApp State
// ─────────────────────────────────────────────────────────────────────────────

const clientStatus = 'READY';

const clientInfo = {
    pushname: 'DEV WhatsApp',
    wid: {
        user: '212600000000'
    },
    platform: 'development'
};

// ─────────────────────────────────────────────────────────────────────────────
// GET /status
// ─────────────────────────────────────────────────────────────────────────────

app.get('/status', (req, res) => {
    res.json({
        service: 'running',
        status: clientStatus,

        // No real QR code in development
        qr: null,

        info: clientInfo,

        version: SERVICE_VERSION,

        uptime: process.uptime(),

        restartCount: 0,

        development: true
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// POST /send
// ─────────────────────────────────────────────────────────────────────────────

app.post('/send', requireApiKey, async (req, res) => {
    const {
        phone,
        message = '',
        attachments
    } = req.body;

    const hasAttachments =
        Array.isArray(attachments) &&
        attachments.length > 0;

    if (!phone || (!message && !hasAttachments)) {
        return res.status(400).json({
            success: false,
            error: 'Phone and message or attachments are required'
        });
    }

    // Normalize phone exactly like the real service
    let cleanedPhone = String(phone).replace(/\D/g, '');

    // Morocco standard format conversion
    if (/^(06|07|05)/.test(cleanedPhone) && cleanedPhone.length === 10) {
        cleanedPhone = '212' + cleanedPhone.substring(1);
    } else if (
        /^(6|7|5)/.test(cleanedPhone) &&
        cleanedPhone.length === 9
    ) {
        cleanedPhone = '212' + cleanedPhone;
    } else if (cleanedPhone.startsWith('00212')) {
        cleanedPhone = cleanedPhone.substring(2);
    }

    const chatId = `${cleanedPhone} @c.us`;

    // ─────────────────────────────────────────────────────────────────────
    // DEV LOG ONLY
    // ─────────────────────────────────────────────────────────────────────

    log('info', '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    log('info', 'DEV MESSAGE — NOTHING WILL BE SENT');
    log('info', `Phone: ${phone} `);
    log('info', `Chat ID: ${chatId} `);

    if (message) {
        log('info', `Message: ${message} `);
    }

    if (hasAttachments) {
        log('info', `Attachments: ${attachments.length} `);

        attachments.forEach((attachment, index) => {
            log('info', `Attachment #${index + 1} `, {
                name: attachment.name || null,
                mime_type: attachment.mime_type || null,

                // Don't print the potentially huge base64 data
                data: attachment.data
                    ? `[base64 data: ${attachment.data.length} chars]`
                    : null
            });
        });
    }

    log('info', '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

    // Fake message ID
    const fakeMessageId =
        `DEV_${Date.now()}_${Math.random().toString(36).substring(2, 10)} `;

    return res.json({
        success: true,
        messageId: fakeMessageId,

        // Useful for your Django application
        development: true,

        message: 'Message logged successfully. Nothing was sent.'
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// POST /logout
// ─────────────────────────────────────────────────────────────────────────────

app.post('/logout', requireApiKey, async (req, res) => {
    log('info', 'DEV logout requested — no real WhatsApp session exists.');

    return res.json({
        success: true,
        message: 'DEV logout simulated successfully',
        development: true
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// POST /restart
// ─────────────────────────────────────────────────────────────────────────────

app.post('/restart', requireApiKey, async (req, res) => {
    log('info', 'DEV restart requested — nothing to restart.');

    return res.json({
        success: true,
        message: 'DEV restart simulated successfully',
        development: true
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// 404
// ─────────────────────────────────────────────────────────────────────────────

app.use((req, res) => {
    res.status(404).json({
        success: false,
        error: `Route ${req.method} ${req.path} not found`
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// Error Handler
// ─────────────────────────────────────────────────────────────────────────────

app.use((err, req, res, next) => {
    log('error', `Unhandled error: ${err.message} `, {
        stack: err.stack
    });

    res.status(500).json({
        success: false,
        error: 'Internal server error'
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// Start
// ─────────────────────────────────────────────────────────────────────────────

app.listen(port, host, () => {
    log(
        'info',
        `DEV WhatsApp server listening at http://${host}:${port}`
    );

    log(
        'info',
        '⚠️ DEVELOPMENT MODE — messages are ONLY logged and NEVER sent.'
    );

    if (API_KEY) {
        log('info', 'API key authentication is ENABLED.');
    } else {
        log('info', 'API key authentication is DISABLED.');
    }
});

