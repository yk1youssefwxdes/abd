const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const path = require('path');
const fs = require('fs');
const net = require('net');
const readline = require('readline');
const { execSync, execFileSync } = require('child_process');

// ── Configuration & Environment Defaults ──────────────────────────────────────
const SERVICE_VERSION = '2.0.0-optimal';
const port = Number(process.env.WA_PORT || 3000);
const host = process.env.WA_HOST || '127.0.0.1';
const API_KEY = process.env.WA_API_KEY || null;

const sessionDataPath = process.env.WA_SESSION_DIR
    ? path.resolve(process.env.WA_SESSION_DIR)
    : path.join(__dirname, 'whatsapp_session');

const logDir = process.env.WA_LOG_DIR
    ? path.resolve(process.env.WA_LOG_DIR)
    : path.join(__dirname, 'logs');

const INIT_TIMEOUT_MS = Number(process.env.WA_INIT_TIMEOUT_MS || 90000);             // 90 seconds timeout
const STARTUP_DELAY_MS = Number(process.env.WA_STARTUP_DELAY_MS !== undefined ? process.env.WA_STARTUP_DELAY_MS : 50); // Instant start
const DESTROY_TIMEOUT_MS = Number(process.env.WA_DESTROY_TIMEOUT_MS || 12000);       // 12 seconds
const RESTART_MAX_DELAY_MS = Number(process.env.WA_RESTART_MAX_DELAY_MS || 30000);   // 30 seconds max backoff
const AUTH_TO_READY_TIMEOUT_MS = Number(process.env.WA_AUTH_TO_READY_TIMEOUT_MS || 60000); // 60 seconds
const MAX_ATTACHMENT_SIZE_MB = Number(process.env.WA_MAX_ATTACHMENT_SIZE_MB || 25);
const QUEUE_TIMEOUT_MS = Number(process.env.WA_QUEUE_TIMEOUT_MS || 300000);         // 5 minutes max in send queue
const SEND_DELAY_MS = Number(process.env.WA_SEND_DELAY_MS || 120);                   // Optimized 120ms pacing
const MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024;                                         // 10MB per log file before rotation

// ── Chrome Path Resolution ───────────────────────────────────────────────────
function resolveChromePath() {
    const specified = process.env.CHROME_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;
    if (specified) {
        const resolved = path.resolve(specified);
        if (fs.existsSync(resolved)) {
            return resolved;
        } else {
            console.warn(`[CONFIG] WARNING: CHROME_PATH "${specified}" does not exist. Falling back to auto-detection.`);
        }
    }

    // Windows standard candidate paths for fast local resolution
    if (process.platform === 'win32') {
        const winCandidates = [
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
            'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'Google\\Chrome\\Application\\chrome.exe') : null,
            process.env.PROGRAMFILES ? path.join(process.env.PROGRAMFILES, 'Google\\Chrome\\Application\\chrome.exe') : null,
        ].filter(Boolean);

        for (const candidate of winCandidates) {
            if (fs.existsSync(candidate)) {
                return candidate;
            }
        }
    }

    // Auto-detect system Chromium/Chrome in Linux / Docker / Cloud environments
    if (process.platform === 'linux') {
        const candidates = [
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            '/usr/bin/google-chrome-stable',
            '/usr/bin/google-chrome',
            'chromium',
            'chromium-browser',
            'google-chrome-stable',
            'google-chrome'
        ];

        for (const candidate of candidates) {
            try {
                if (candidate.startsWith('/')) {
                    if (fs.existsSync(candidate)) {
                        return candidate;
                    }
                } else {
                    const detected = execSync(`which ${candidate} 2>/dev/null`, { encoding: 'utf8' }).trim();
                    if (detected && fs.existsSync(detected)) {
                        return detected;
                    }
                }
            } catch (_) {}
        }
    }

    // Default: allow Puppeteer bundled Chromium
    return null;
}

const customChromePath = resolveChromePath();

// ── In-Memory Registration Cache ─────────────────────────────────────────────
// Greatly speeds up repeated sends and bulk messaging campaigns by caching
// positive number validations in RAM with a 2-hour TTL.
const registrationCache = new Map();
const REG_CACHE_TTL_MS = 2 * 60 * 60 * 1000; // 2 hours
const REG_CACHE_MAX_SIZE = 10000;

function getCachedRegistration(chatId) {
    const item = registrationCache.get(chatId);
    if (!item) return null;
    if (Date.now() - item.ts > REG_CACHE_TTL_MS) {
        registrationCache.delete(chatId);
        return null;
    }
    return item.isRegistered;
}

function setCachedRegistration(chatId, isRegistered) {
    if (registrationCache.size >= REG_CACHE_MAX_SIZE) {
        // Evict oldest 1000 items
        const keys = Array.from(registrationCache.keys()).slice(0, 1000);
        for (const k of keys) registrationCache.delete(k);
    }
    registrationCache.set(chatId, { isRegistered: Boolean(isRegistered), ts: Date.now() });
}

// ── Windows Process Management & Safe Ownership Verification ──────────────────
// Keeps a fast RAM cache of verified PIDs to prevent repeatedly calling external commands.
const verifiedPidsCache = new Map();

/**
 * Safely extracts the ChildProcess object from a Client instance.
 */
function getBrowserProcess(clientInstance) {
    try {
        if (!clientInstance) return null;
        if (clientInstance.pupBrowser && typeof clientInstance.pupBrowser.process === 'function') {
            return clientInstance.pupBrowser.process() || null;
        }
        return null;
    } catch (_) {
        return null;
    }
}

/**
 * Safely extracts the OS Process ID from a Client instance.
 */
function getBrowserPid(clientInstance) {
    try {
        const proc = getBrowserProcess(clientInstance);
        return proc?.pid || null;
    } catch (_) {
        return null;
    }
}

/**
 * Test whether a process ID is currently alive on the operating system.
 */
function isProcessAlive(pid) {
    if (!pid || typeof pid !== 'number' || pid <= 0) return false;
    try {
        process.kill(pid, 0);
        return true;
    } catch (err) {
        return err.code === 'EPERM'; // Process exists but lacks signaling permission
    }
}

/**
 * Fast process info query on Windows without slow PowerShell CLR overhead.
 * Priority:
 * 1. tasklist (~25ms) to verify executable name.
 * 2. wmic (~50ms) to check command line session directory reference.
 * 3. Fallback to PowerShell only if wmic fails.
 */
function getProcessInfoFast(pid) {
    if (!pid || typeof pid !== 'number' || pid <= 0) return null;
    if (process.platform !== 'win32') return null;

    // Check memory cache first (valid for 15 seconds)
    const cached = verifiedPidsCache.get(pid);
    if (cached && Date.now() - cached.ts < 15000) {
        return cached.info;
    }

    try {
        // Fast tasklist call to verify process exists and retrieve binary name
        const tasklistOut = execSync(`tasklist /fi "PID eq ${pid}" /fo csv /nh`, {
            encoding: 'utf8',
            timeout: 1500,
            stdio: ['pipe', 'pipe', 'ignore']
        }).trim();

        if (!tasklistOut || tasklistOut.includes('No tasks are running')) {
            return null;
        }

        const match = tasklistOut.match(/^"([^"]+)"/);
        const name = match ? match[1] : '';

        // Query commandline with wmic (much faster than powershell.exe)
        let commandLine = '';
        try {
            const wmicOut = execSync(`wmic process where (ProcessId=${pid}) get CommandLine /format:list`, {
                encoding: 'utf8',
                timeout: 1500,
                stdio: ['pipe', 'pipe', 'ignore']
            }).trim();
            const clMatch = wmicOut.match(/^CommandLine=(.*)$/m);
            if (clMatch) commandLine = clMatch[1].trim();
        } catch (_) {
            // If wmic fails, fallback to lightweight PowerShell query
            try {
                commandLine = execFileSync('powershell.exe', [
                    '-NoProfile',
                    '-NonInteractive',
                    '-Command',
                    `$p = Get-CimInstance Win32_Process -Filter "ProcessId = ${pid}"; if ($p) { $p.CommandLine }`
                ], { encoding: 'utf8', timeout: 2500 }).trim();
            } catch (_) {}
        }

        const info = { Name: name, CommandLine: commandLine };
        verifiedPidsCache.set(pid, { info, ts: Date.now() });
        return info;
    } catch (_) {
        return null;
    }
}

/**
 * Verify whether a process belongs specifically to THIS WhatsApp service instance.
 */
function isOwnedChromiumProcess(pid) {
    if (!pid || typeof pid !== 'number' || pid <= 0) {
        return { isOwned: false, reason: 'Invalid or missing PID' };
    }
    if (!isProcessAlive(pid)) {
        return { isOwned: false, reason: `Process ${pid} is not alive` };
    }

    // Fast-path: If it is our actively tracked spawned Chromium PID, it is guaranteed owned
    if (activeBrowserPid && activeBrowserPid === pid) {
        return { isOwned: true, reason: 'Active tracked child process' };
    }

    if (process.platform !== 'win32') {
        return { isOwned: true, reason: 'Non-Windows platform check bypass' };
    }

    const info = getProcessInfoFast(pid);
    if (!info || !info.Name) {
        return { isOwned: false, reason: `Could not query process info for PID ${pid}` };
    }

    const name = String(info.Name).toLowerCase();
    const isChromium = name === 'chrome.exe' || name === 'msedge.exe' || name === 'chromium.exe';
    if (!isChromium) {
        return {
            isOwned: false,
            reason: `Process ${pid} executable is "${info.Name}", not a Chromium browser`
        };
    }

    const cmdLine = String(info.CommandLine || '').toLowerCase();
    const sessionDirNormalized = path.resolve(sessionDataPath).toLowerCase();

    // Check if the command line references our session directory or chromium-profile
    if (cmdLine && !cmdLine.includes(sessionDirNormalized) && !cmdLine.includes('chromium-profile')) {
        return {
            isOwned: false,
            reason: `Chromium process ${pid} command line does not reference session path "${sessionDirNormalized}"`
        };
    }

    return { isOwned: true, reason: 'Verified Chromium process owning WhatsApp session profile' };
}

/**
 * Terminate a browser process tree ONLY after ownership verification.
 */
function terminateOwnedBrowser(pid, reason = 'Cleanup') {
    if (!pid || typeof pid !== 'number' || pid <= 0) {
        return false;
    }

    const ownership = isOwnedChromiumProcess(pid);
    if (!ownership.isOwned) {
        log('warn', `Refusing to terminate PID ${pid}: ${ownership.reason}. Unrelated process will NOT be touched.`, { component: 'Process' });
        return false;
    }

    log('warn', `Terminating verified owned browser process tree (PID: ${pid}, Reason: ${reason})...`, { component: 'Process' });
    try {
        if (process.platform === 'win32') {
            execSync(`taskkill /pid ${pid} /T /F`, { stdio: 'ignore', timeout: 4000 });
        } else {
            process.kill(pid, 'SIGKILL');
        }
        verifiedPidsCache.delete(pid);
        if (activeBrowserPid === pid) activeBrowserPid = null;
        log('info', `Verified browser process tree (PID: ${pid}) successfully terminated.`, { component: 'Process' });
        return true;
    } catch (err) {
        log('debug', `Termination note for PID ${pid}: ${err.message}`, { component: 'Process' });
        return false;
    }
}

/**
 * Fast TCP probe to check if a local port is currently listening.
 */
function isPortListening(testPort, timeoutMs = 250) {
    return new Promise((resolve) => {
        if (!testPort || isNaN(testPort)) return resolve(false);
        const socket = new net.Socket();
        let done = false;

        const finish = (result) => {
            if (!done) {
                done = true;
                socket.destroy();
                resolve(result);
            }
        };

        socket.setTimeout(timeoutMs);
        socket.once('connect', () => finish(true));
        socket.once('timeout', () => finish(false));
        socket.once('error', () => finish(false));

        socket.connect(testPort, '127.0.0.1');
    });
}

/**
 * Fast Windows socket PID query using filtered findstr (avoids parsing entire system netstat).
 */
function getPidListeningOnPort(portNum) {
    if (!portNum) return null;
    if (process.platform === 'win32') {
        try {
            const output = execSync(`netstat -ano -p tcp | findstr ":${portNum} "`, {
                stdio: ['pipe', 'pipe', 'ignore'],
                timeout: 1500,
                encoding: 'utf8'
            });
            const lines = output.split('\n');
            for (const line of lines) {
                if (line.includes('LISTENING')) {
                    const parts = line.trim().split(/\s+/);
                    const pid = parseInt(parts[parts.length - 1], 10);
                    if (!isNaN(pid) && pid > 0) return pid;
                }
            }
        } catch (_) {}
    }
    return null;
}

// ── Stale Lock Files Management ───────────────────────────────────────────────
async function cleanStaleBrowserLocks() {
    const pathsToCheck = [
        path.join(sessionDataPath, 'session'),
        path.join(sessionDataPath, 'chromium-profile', 'Default'),
    ];

    for (const sessionPath of pathsToCheck) {
        if (!fs.existsSync(sessionPath)) continue;

        const devToolsPath = path.join(sessionPath, 'DevToolsActivePort');
        if (fs.existsSync(devToolsPath)) {
            try {
                const content = fs.readFileSync(devToolsPath, 'utf8').trim();
                const firstLine = content.split('\n')[0].trim();
                const portNum = Number(firstLine);

                if (portNum > 0) {
                    const listening = await isPortListening(portNum, 200);
                    if (listening) {
                        log('warn', `DevToolsActivePort ${portNum} is currently ACTIVE. Checking process...`, { component: 'Chromium' });

                        const orphanPid = getPidListeningOnPort(portNum);
                        if (orphanPid) {
                            const ownership = isOwnedChromiumProcess(orphanPid);
                            if (ownership.isOwned) {
                                log('warn', `Identified verified orphaned Chromium PID ${orphanPid} on port ${portNum}. Terminating...`, { component: 'Chromium' });
                                terminateOwnedBrowser(orphanPid, `Orphaned DevTools port ${portNum}`);
                                await new Promise((r) => setTimeout(r, 600));
                            } else {
                                log('warn', `Process ${orphanPid} on port ${portNum} is NOT an owned Chromium process (${ownership.reason}). Aborting lock deletion.`, { component: 'Chromium' });
                                return { safe: false, reason: `Port ${portNum} is occupied by an unverified process (PID: ${orphanPid}).` };
                            }
                        }
                    }

                    // Re-check port
                    const stillListening = await isPortListening(portNum, 150);
                    if (!stillListening && fs.existsSync(devToolsPath)) {
                        log('info', `DevToolsActivePort ${portNum} is confirmed dead. Removing stale port file.`, { component: 'Chromium' });
                        try { fs.unlinkSync(devToolsPath); } catch (_) {}
                    }
                }
            } catch (e) {
                log('warn', `Could not inspect DevToolsActivePort: ${e.message}`, { component: 'Chromium' });
            }
        }

        // Remove SingletonLock & SingletonCookie if unlocked
        const lockFiles = ['SingletonLock', 'SingletonCookie', 'SingletonSocket'];
        for (const fileName of lockFiles) {
            const filePath = path.join(sessionPath, fileName);
            if (fs.existsSync(filePath)) {
                try {
                    const fd = fs.openSync(filePath, 'r+');
                    fs.closeSync(fd);
                    fs.unlinkSync(filePath);
                    log('info', `Removed stale lock file: ${fileName}`, { component: 'Chromium' });
                } catch (err) {
                    if (err.code === 'EBUSY' || err.code === 'EPERM') {
                        log('warn', `Cannot remove ${fileName}: handle is locked by an active process.`, { component: 'Chromium' });
                        return { safe: false, reason: `${fileName} is currently locked by a process.` };
                    }
                }
            }
        }
    }

    return { safe: true };
}

// ── Enhanced Logger with Rotation ─────────────────────────────────────────────
let clientStatus = 'STOPPED';
let clientGeneration = 0;
let restartCount = 0;

function log(level, message, meta = {}) {
    const timestamp = new Date().toISOString();
    const component = meta.component || 'WhatsApp';
    const currentGen = meta.generation !== undefined ? meta.generation : clientGeneration;
    const attemptStr = restartCount > 0 ? ` [attempt=${restartCount}]` : '';

    const logLine = `[${timestamp}] [${level.toUpperCase()}] [${component}] [generation=${currentGen}] [${clientStatus}]${attemptStr} ${message}`;

    if (level === 'error') {
        console.error(logLine);
    } else if (level === 'warn') {
        console.warn(logLine);
    } else {
        console.log(logLine);
    }

    if (logDir) {
        try {
            fs.mkdirSync(logDir, { recursive: true });
            const logFile = path.join(logDir, 'whatsapp.log');

            if (fs.existsSync(logFile)) {
                const stats = fs.statSync(logFile);
                if (stats.size > MAX_LOG_SIZE_BYTES) {
                    const backupFile = path.join(logDir, 'whatsapp.log.1');
                    try {
                        if (fs.existsSync(backupFile)) fs.unlinkSync(backupFile);
                        fs.renameSync(logFile, backupFile);
                    } catch (_) {}
                }
            }
            fs.appendFileSync(logFile, logLine + '\n', 'utf8');
        } catch (_) {}
    }
}

// Ensure session and cache directories exist
try {
    fs.mkdirSync(sessionDataPath, { recursive: true });
    fs.mkdirSync(path.join(sessionDataPath, 'wwebjs_cache'), { recursive: true });
} catch (_) {}

// ── In-Memory Send Queue ──────────────────────────────────────────────────────
class SendQueue {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
    }

    enqueue(taskFn) {
        return new Promise((resolve, reject) => {
            this.queue.push({
                taskFn,
                resolve,
                reject,
                enqueuedAt: Date.now()
            });
            this.process();
        });
    }

    getStatus() {
        return {
            length: this.queue.length,
            isProcessing: this.isProcessing
        };
    }

    async process() {
        if (this.isProcessing || this.queue.length === 0) return;
        this.isProcessing = true;

        while (this.queue.length > 0) {
            const item = this.queue.shift();

            if (clientStatus !== 'READY') {
                const err = new Error(`WhatsApp client unavailable (Status: ${clientStatus}). Message rejected.`);
                err.statusCode = 503;
                item.reject(err);
                continue;
            }

            if (Date.now() - item.enqueuedAt > QUEUE_TIMEOUT_MS) {
                const timeoutErr = new Error(`Send operation timed out in queue (exceeded ${Math.round(QUEUE_TIMEOUT_MS / 1000)}s)`);
                timeoutErr.statusCode = 504;
                item.reject(timeoutErr);
                continue;
            }

            try {
                const result = await item.taskFn();
                item.resolve(result);
            } catch (err) {
                item.reject(err);
            }

            // Pacing delay between consecutive sends (protects against rate limits)
            if (SEND_DELAY_MS > 0 && this.queue.length > 0) {
                await new Promise((r) => setTimeout(r, SEND_DELAY_MS));
            }
        }

        this.isProcessing = false;
    }

    clear(reason = 'Send queue cleared') {
        const count = this.queue.length;
        if (count > 0) {
            log('warn', `Clearing ${count} pending queued sends with HTTP 503. Reason: ${reason}`, { component: 'Queue' });
        }
        while (this.queue.length > 0) {
            const item = this.queue.shift();
            const err = new Error(`WhatsApp client recovering: ${reason}`);
            err.statusCode = 503;
            item.reject(err);
        }
    }
}

const sendQueue = new SendQueue();

// ── Phone Number Normalization ────────────────────────────────────────────────
function normalizePhoneNumber(rawPhone) {
    if (!rawPhone || (typeof rawPhone !== 'string' && typeof rawPhone !== 'number')) {
        return { valid: false, error: 'Phone number must be a non-empty string or number.' };
    }
    const original = String(rawPhone).trim();
    if (!original) {
        return { valid: false, error: 'Phone number cannot be empty.' };
    }

    if (/^\d+@c\.us$/.test(original) || /^[a-zA-Z0-9_-]+@g\.us$/.test(original)) {
        return { valid: true, cleanedPhone: original.split('@')[0], chatId: original };
    }

    const firstPart = original.split(/[/,;\n|]/)[0].trim();
    let cleaned = firstPart.replace(/[\s\-\(\)\.]/g, '');

    if (cleaned.startsWith('+')) {
        cleaned = cleaned.substring(1);
    } else if (cleaned.startsWith('00')) {
        cleaned = cleaned.substring(2);
    }

    if (!/^\d+$/.test(cleaned)) {
        return { valid: false, error: `Phone number "${original}" contains invalid characters.` };
    }

    // Moroccan formats
    if (/^0[567]\d{8}$/.test(cleaned)) {
        cleaned = '212' + cleaned.substring(1);
    } else if (/^[567]\d{8}$/.test(cleaned)) {
        cleaned = '212' + cleaned;
    } else if (/^212[567]\d{8}$/.test(cleaned)) {
        // Valid
    } else if (/^[1-9]\d{7,14}$/.test(cleaned)) {
        // Valid international
    } else {
        return {
            valid: false,
            error: `Invalid phone number format "${original}". Must be a valid Moroccan number or international format.`
        };
    }

    const chatId = `${cleaned}@c.us`;
    return { valid: true, cleanedPhone: cleaned, chatId };
}

// ── State Machine & Client Lifecycle Management ──────────────────────────────
let client = null;
let clientInfo = null;
let qrCodeData = null;
let activeBrowserPid = null;

let lastReadyAt = null;
let lastError = null;
let restartTimer = null;
let authToReadyTimer = null;
let isExecutingAction = false;
const actionQueue = [];
const invalidatedGenerations = new Set();

function setStatus(newStatus) {
    const prevStatus = clientStatus;
    clientStatus = newStatus;
    log('info', `State changed: ${prevStatus} -> ${newStatus}`);

    if (prevStatus === 'READY' && newStatus !== 'READY') {
        sendQueue.clear(`Client transitioned to ${newStatus}`);
    }
}

function enqueueAction(actionFn, isInitAction = false) {
    return new Promise((resolve, reject) => {
        if (clientStatus === 'SHUTTING_DOWN') {
            return reject(new Error('Service is shutting down'));
        }

        if (isInitAction) {
            const hasPendingInit = actionQueue.some((item) => item.isInitAction);
            if (hasPendingInit) {
                log('debug', 'An initialization action is already queued. Dropping duplicate request.');
                return resolve({ deduplicated: true });
            }
        }

        actionQueue.push({ actionFn, resolve, reject, isInitAction });
        processNextAction();
    });
}

async function processNextAction() {
    if (isExecutingAction || actionQueue.length === 0) return;
    isExecutingAction = true;
    const { actionFn, resolve, reject } = actionQueue.shift();

    try {
        const result = await actionFn();
        resolve(result);
    } catch (err) {
        log('error', `Action execution error: ${err.message}`, { stack: err.stack });
        reject(err);
    } finally {
        isExecutingAction = false;
        setImmediate(processNextAction);
    }
}

async function destroyCurrentClient(reason = 'Teardown', clientOverride = null, pidOverride = null) {
    if (restartTimer) {
        clearTimeout(restartTimer);
        restartTimer = null;
    }
    if (authToReadyTimer) {
        clearTimeout(authToReadyTimer);
        authToReadyTimer = null;
    }

    const clientToDestroy = clientOverride || client;
    const pidToDestroy = pidOverride || getBrowserPid(clientToDestroy) || activeBrowserPid;

    if (client === clientToDestroy) {
        client = null;
    }
    if (activeBrowserPid === pidToDestroy) {
        activeBrowserPid = null;
    }

    if (!clientToDestroy && !pidToDestroy) {
        return;
    }

    log('info', `Initiating safe client and browser destruction (Reason: ${reason}, Target PID: ${pidToDestroy || 'unknown'})...`);

    if (clientToDestroy) {
        let timeoutHandle = null;

        const destroyPromise = Promise.resolve().then(async () => {
            try {
                clientToDestroy.removeAllListeners();
            } catch (_) {}
            if (typeof clientToDestroy.destroy === 'function') {
                await clientToDestroy.destroy();
            }
        });

        const timeoutPromise = new Promise((_, reject) => {
            timeoutHandle = setTimeout(() => {
                reject(new Error(`client.destroy() timed out after ${DESTROY_TIMEOUT_MS}ms`));
            }, DESTROY_TIMEOUT_MS);
        });

        try {
            await Promise.race([destroyPromise, timeoutPromise]);
            log('info', 'WhatsApp client destroyed cleanly.');
        } catch (err) {
            log('warn', `Graceful client destroy failed: ${err.message}. Enforcing process termination.`);
        } finally {
            if (timeoutHandle) clearTimeout(timeoutHandle);
        }
    }

    if (pidToDestroy) {
        terminateOwnedBrowser(pidToDestroy, reason);
    }

    await new Promise((r) => setTimeout(r, 600));
    await cleanStaleBrowserLocks();
}

/**
 * Initialize a new WhatsApp Client with high-performance flags and local web version cache.
 */
async function initializeNewClient(triggerReason = 'Standard') {
    if (clientStatus === 'SHUTTING_DOWN') return;

    clientGeneration += 1;
    const thisGeneration = clientGeneration;

    log('info', `Starting client initialization (Reason: ${triggerReason})...`, { generation: thisGeneration });

    await destroyCurrentClient(`Re-init [${triggerReason}]`);

    const lockCheck = await cleanStaleBrowserLocks();
    if (!lockCheck.safe) {
        log('warn', `Cannot safely initialize: ${lockCheck.reason}. Scheduling backoff retry.`, { generation: thisGeneration });
        setStatus('ERROR');
        scheduleRestart(4000, 'Lock check failed');
        return;
    }

    setStatus('STARTING');
    qrCodeData = null;
    clientInfo = null;

    // ── High-Performance Puppeteer Flags (Windows & Cloud) ────────────────────
    // Isolated user-data-dir completely prevents colliding with any desktop Chrome.
    // Heavy rendering, audio decoding, extensions, and telemetry are stripped out.
    const puppeteerArgs = [
        `--user-data-dir=${path.join(sessionDataPath, 'chromium-profile')}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-accelerated-2d-canvas',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-breakpad',
        '--disable-component-update',
        '--disable-extensions',
        '--disable-ipc-flooding-protection',
        '--disable-renderer-backgrounding',
        '--disable-dev-shm-usage',
        '--disable-session-crashed-bubble',
        '--disable-infobars',
        '--hide-scrollbars',
        '--window-size=1280,800',
        '--mute-audio',
        '--renderer-process-limit=2',
        '--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,CalculateNativeWinOcclusion,InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater,AutofillServerCommunication,HeavyAdIntervention,BackForwardCache,MediaSessionService',
        '--disable-default-apps',
        '--disable-sync',
        '--disable-speech-api',
        '--disable-wake-on-wifi',
        '--disable-client-side-phishing-detection',
        '--disable-component-extensions-with-background-pages',
        '--metrics-recording-only',
        '--no-pings',
        '--password-store=basic',
        '--use-mock-keychain',
        '--disk-cache-size=104857600',
        '--js-flags=--max-old-space-size=512',
        '--disable-blink-features=AutomationControlled'
    ];

    if (process.platform === 'linux' || process.env.WA_DISABLE_SANDBOX === 'true' || process.env.NO_SANDBOX === '1') {
        if (process.env.WA_DISABLE_SANDBOX !== 'false') {
            puppeteerArgs.push('--no-sandbox', '--disable-setuid-sandbox', '--no-zygote');
        }
    }

    const puppeteerConfig = {
        headless: true, // In Puppeteer 22+ uses the fast modern Chrome headless engine
        args: puppeteerArgs,
        timeout: 60000
    };

    if (customChromePath) {
        log('info', `Using custom Chromium runtime at: ${customChromePath}`, { generation: thisGeneration });
        puppeteerConfig.executablePath = customChromePath;
    } else {
        log('info', 'Using Puppeteer default Chromium browser.', { generation: thisGeneration });
    }

    // Use local disk cache for WhatsApp Web HTML/JS bundles
    const localCachePath = path.join(sessionDataPath, 'wwebjs_cache');

    const newClient = new Client({
        authStrategy: new LocalAuth({
            dataPath: sessionDataPath
        }),
        puppeteer: puppeteerConfig,
        webVersionCache: {
            type: 'local',
            path: localCachePath,
            strict: false
        }
    });

    // ── Generation-guarded Event Listeners ────────────────────────────────────
    newClient.on('qr', async (qr) => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) {
            log('debug', 'Ignored qr event from stale client generation.', { generation: thisGeneration });
            return;
        }
        setStatus('QR_REQUIRED');
        log('info', 'QR Code generated. Scan via School ERP WhatsApp settings.', { generation: thisGeneration });
        try {
            qrCodeData = await qrcode.toDataURL(qr);
        } catch (err) {
            log('error', `Failed to generate QR data URL: ${err.message}`, { generation: thisGeneration });
        }
    });

    newClient.on('authenticated', () => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) {
            log('debug', 'Ignored authenticated event from stale client generation.', { generation: thisGeneration });
            return;
        }
        setStatus('AUTHENTICATED');
        qrCodeData = null;
        log('info', 'Authenticated successfully with WhatsApp. Loading chats...', { generation: thisGeneration });

        if (authToReadyTimer) clearTimeout(authToReadyTimer);
        authToReadyTimer = setTimeout(() => {
            if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
            if (clientStatus === 'AUTHENTICATED') {
                log('error', `Ready event did not arrive within ${AUTH_TO_READY_TIMEOUT_MS}ms after authentication. Recovery initiated.`, { generation: thisGeneration });
                invalidatedGenerations.add(thisGeneration);
                lastError = 'Ready event timeout after authentication';
                setStatus('ERROR');

                enqueueAction(async () => {
                    await destroyCurrentClient(`Auth to ready timeout (gen ${thisGeneration})`, newClient, activeBrowserPid);
                    scheduleRestart(4000, 'Auth-to-ready timeout');
                }).catch((err) => {
                    log('error', `Auth-to-ready recovery action failed: ${err.message}`);
                });
            }
        }, AUTH_TO_READY_TIMEOUT_MS);
    });

    newClient.on('auth_failure', (msg) => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
        log('error', `WhatsApp authentication failed: ${msg}. Session may need re-pairing.`, { generation: thisGeneration });
        invalidatedGenerations.add(thisGeneration);

        if (authToReadyTimer) {
            clearTimeout(authToReadyTimer);
            authToReadyTimer = null;
        }
        setStatus('ERROR');
        lastError = `Authentication failed: ${msg}`;

        try { newClient.removeAllListeners(); } catch (_) {}

        enqueueAction(async () => {
            const authFailPid = getBrowserPid(newClient) || activeBrowserPid;
            await destroyCurrentClient(`Auth failure: ${msg}`, newClient, authFailPid);

            const sessionDir = path.join(sessionDataPath, 'session');
            try {
                if (fs.existsSync(sessionDir)) {
                    fs.rmSync(sessionDir, { recursive: true, force: true });
                    log('info', 'Cleaned expired session directory after auth failure.', { generation: thisGeneration });
                }
            } catch (_) {}

            scheduleRestart(2500, 'Authentication failure recovery');
        }).catch((err) => {
            log('error', `Auth failure cleanup action failed: ${err.message}`);
        });
    });

    newClient.on('ready', () => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
        if (authToReadyTimer) {
            clearTimeout(authToReadyTimer);
            authToReadyTimer = null;
        }
        setStatus('READY');
        clientInfo = newClient.info;
        lastReadyAt = new Date().toISOString();
        restartCount = 0;
        lastError = null;
        log('info', 'WhatsApp Client is fully READY for high-speed messaging.', { generation: thisGeneration });
    });

    newClient.on('disconnected', (reason) => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
        if (clientStatus === 'SHUTTING_DOWN') return;

        invalidatedGenerations.add(thisGeneration);
        if (authToReadyTimer) {
            clearTimeout(authToReadyTimer);
            authToReadyTimer = null;
        }
        setStatus('DISCONNECTED');
        lastError = `Disconnected: ${reason}`;
        log('warn', `WhatsApp client disconnected. Reason: ${reason}`, { generation: thisGeneration });

        if (reason === 'LOGOUT' || reason === 'NAVIGATION') {
            enqueueAction(async () => {
                const discPid = getBrowserPid(newClient) || activeBrowserPid;
                await destroyCurrentClient(`Disconnected: ${reason}`, newClient, discPid);
                const sessionDir = path.join(sessionDataPath, 'session');
                try {
                    if (fs.existsSync(sessionDir)) {
                        fs.rmSync(sessionDir, { recursive: true, force: true });
                        log('info', 'Session folder removed following remote logout.');
                    }
                } catch (_) {}
                scheduleRestart(2000, `Post-logout fresh client (${reason})`);
            }).catch((err) => {
                log('error', `Teardown after disconnect failed: ${err.message}`);
            });
        } else {
            scheduleRestart(2500, `Disconnected: ${reason}`);
        }
    });

    newClient.on('change_state', (state) => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
        log('info', `WhatsApp connection state changed to: ${state}`, { generation: thisGeneration });
    });

    client = newClient;

    // Fast polling captures PID as soon as Chrome process starts
    const pidPollInterval = setInterval(() => {
        if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) {
            clearInterval(pidPollInterval);
            return;
        }
        const detectedPid = getBrowserPid(newClient);
        if (detectedPid && detectedPid !== activeBrowserPid) {
            activeBrowserPid = detectedPid;
            log('info', `Chromium PID identified: ${activeBrowserPid}`, { generation: thisGeneration });

            const proc = getBrowserProcess(newClient);
            if (proc) {
                proc.once('exit', (code, signal) => {
                    if (thisGeneration !== clientGeneration || invalidatedGenerations.has(thisGeneration)) return;
                    if (clientStatus === 'SHUTTING_DOWN') return;

                    log('error', `Chromium process (PID: ${detectedPid}) exited unexpectedly (code: ${code}, signal: ${signal}).`, { generation: thisGeneration });
                    invalidatedGenerations.add(thisGeneration);
                    lastError = `Chromium exited unexpectedly (code: ${code})`;
                    setStatus('ERROR');
                    scheduleRestart(3000, 'Chromium process exit');
                });
            }
            clearInterval(pidPollInterval);
        }
    }, 200);

    // Timeout guard
    let initTimeoutHandle = null;
    const initTimeoutPromise = new Promise((_, reject) => {
        initTimeoutHandle = setTimeout(() => {
            reject(new Error(`Initialization timeout after ${INIT_TIMEOUT_MS}ms`));
        }, INIT_TIMEOUT_MS);
    });

    try {
        log('info', `Initializing client with ${INIT_TIMEOUT_MS}ms timeout guard...`, { generation: thisGeneration });
        await Promise.race([
            newClient.initialize(),
            initTimeoutPromise
        ]);

        const finalPid = getBrowserPid(newClient);
        if (finalPid && !activeBrowserPid) {
            activeBrowserPid = finalPid;
            log('info', `Chromium PID identified: ${activeBrowserPid}`, { generation: thisGeneration });
        }
        log('info', 'WhatsApp Web client loaded.', { generation: thisGeneration });
    } catch (err) {
        clearInterval(pidPollInterval);
        invalidatedGenerations.add(thisGeneration);

        const failedPid = getBrowserPid(newClient) || activeBrowserPid;
        log('error', `Client initialization failed: ${err.message}. Captured PID: ${failedPid || 'unknown'}`, { generation: thisGeneration });
        lastError = err.message;
        setStatus('ERROR');

        try { newClient.removeAllListeners(); } catch (_) {}

        await destroyCurrentClient(`Init failure: ${err.message}`, newClient, failedPid);
        scheduleRestart(4000, 'Initialization failure');
    } finally {
        clearInterval(pidPollInterval);
        if (initTimeoutHandle) clearTimeout(initTimeoutHandle);
    }
}

function scheduleRestart(baseDelayMs = 2500, triggerReason = 'Generic') {
    if (clientStatus === 'SHUTTING_DOWN') return;

    if (restartTimer) {
        log('debug', `Restart already scheduled, skipping duplicate trigger (${triggerReason}).`);
        return;
    }

    const hasPendingInit = actionQueue.some((item) => item.isInitAction);
    if (hasPendingInit) {
        log('debug', `Initialization action already pending in queue, skipping trigger (${triggerReason}).`);
        return;
    }

    restartCount += 1;
    const backoff = Math.min(
        Math.round(baseDelayMs * Math.pow(1.4, Math.max(0, restartCount - 1))),
        RESTART_MAX_DELAY_MS
    );

    setStatus('RESTART_WAIT');
    log('info', `Scheduling client restart in ${backoff}ms (attempt #${restartCount}, max ${RESTART_MAX_DELAY_MS}ms, trigger: ${triggerReason})...`);

    restartTimer = setTimeout(() => {
        restartTimer = null;
        enqueueAction(() => initializeNewClient(`restart_attempt_${restartCount}`), true).catch((err) => {
            log('error', `Scheduled restart failed to enqueue: ${err.message}`);
        });
    }, backoff);
}

// ── Graceful Shutdown ────────────────────────────────────────────────────────
let isShuttingDown = false;

async function handleShutdown(signal) {
    if (isShuttingDown) return;
    isShuttingDown = true;
    setStatus('SHUTTING_DOWN');
    log('info', `Received ${signal || 'shutdown'} signal. Initiating clean exit...`);

    const forceExitTimer = setTimeout(() => {
        log('warn', 'Shutdown watchdog expired (10s). Forcing process exit.');
        process.exit(1);
    }, 10000);
    forceExitTimer.unref();

    sendQueue.clear('Service shutting down');

    if (restartTimer) {
        clearTimeout(restartTimer);
        restartTimer = null;
    }
    if (authToReadyTimer) {
        clearTimeout(authToReadyTimer);
        authToReadyTimer = null;
    }

    try {
        await destroyCurrentClient('Shutdown');
    } catch (_) {}

    log('info', 'WhatsApp service shutdown complete.');
    process.exit(0);
}

process.on('SIGTERM', () => handleShutdown('SIGTERM'));
process.on('SIGINT', () => handleShutdown('SIGINT'));

if (process.platform === 'win32' && process.stdin.isTTY) {
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout
    });
    rl.on('SIGINT', () => {
        process.emit('SIGINT');
    });
}

process.on('uncaughtException', (err) => {
    log('error', `FATAL UNCAUGHT EXCEPTION: ${err.message}`, { stack: err.stack, component: 'System' });
    try {
        if (activeBrowserPid) {
            terminateOwnedBrowser(activeBrowserPid, 'Emergency uncaughtException exit');
        }
    } catch (_) {}

    setTimeout(() => {
        process.exit(1);
    }, 1000).unref();
});

process.on('unhandledRejection', (reason) => {
    const msg = reason instanceof Error ? reason.message : String(reason);
    const stack = reason instanceof Error ? reason.stack : null;
    log('error', `UNHANDLED REJECTION: ${msg}`, { stack, component: 'System' });
});

// ── Express Application & API Setup ──────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '100mb' }));

function requireApiKey(req, res, next) {
    if (!API_KEY) return next();
    const key = req.headers['x-api-key'];
    if (key === API_KEY) return next();
    return res.status(401).json({ success: false, error: 'Unauthorized' });
}

// GET /status — Instant status response (< 5ms response time)
app.get('/status', (req, res) => {
    res.json({
        service: 'running',
        status: clientStatus,
        qr: qrCodeData,
        info: clientInfo,
        version: SERVICE_VERSION,
        uptime: process.uptime(),
        restartCount: restartCount,
        clientExists: Boolean(client),
        isInitializing: clientStatus === 'STARTING' || isExecutingAction,
        lastReadyAt: lastReadyAt,
        lastError: lastError,
        clientGeneration: clientGeneration,
        queue: sendQueue.getStatus(),
        cacheSize: registrationCache.size,
        retryInfo: {
            isWaiting: clientStatus === 'RESTART_WAIT',
            restartCount: restartCount,
            maxBackoffMs: RESTART_MAX_DELAY_MS
        }
    });
});

// POST /check-number — Fast verification with RAM cache
app.post('/check-number', requireApiKey, async (req, res) => {
    const { phone } = req.body;
    if (!phone) {
        return res.status(400).json({ success: false, error: 'Phone number is required' });
    }
    if (clientStatus !== 'READY' || !client) {
        return res.status(503).json({ success: false, error: 'Service is not READY' });
    }
    const phoneResult = normalizePhoneNumber(phone);
    if (!phoneResult.valid) {
        return res.status(400).json({ success: false, error: phoneResult.error });
    }
    try {
        if (phoneResult.chatId.endsWith('@g.us')) {
            return res.json({ success: true, registered: true, chatId: phoneResult.chatId, isGroup: true });
        }

        // Check RAM cache
        const cached = getCachedRegistration(phoneResult.chatId);
        if (cached !== null) {
            return res.json({ success: true, registered: cached, chatId: phoneResult.chatId, isGroup: false, fromCache: true });
        }

        const isRegistered = await client.isRegisteredUser(phoneResult.chatId);
        setCachedRegistration(phoneResult.chatId, isRegistered);
        return res.json({ success: true, registered: Boolean(isRegistered), chatId: phoneResult.chatId, isGroup: false });
    } catch (err) {
        return res.status(500).json({ success: false, error: err.message });
    }
});

// POST /send — High-speed message & attachment sender
app.post('/send', requireApiKey, async (req, res) => {
    const { phone, message = '', attachments, skip_registration_check = false } = req.body;
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;

    if (!phone || (!message && !hasAttachments)) {
        return res.status(400).json({
            success: false,
            error: 'Phone and message or attachments are required'
        });
    }

    if (clientStatus !== 'READY' || !client) {
        return res.status(503).json({
            success: false,
            error: `WhatsApp client is not ready (Current status: ${clientStatus}). Please retry once the service is READY.`
        });
    }

    const phoneResult = normalizePhoneNumber(phone);
    if (!phoneResult.valid) {
        return res.status(400).json({
            success: false,
            error: phoneResult.error
        });
    }
    const { chatId } = phoneResult;

    if (hasAttachments) {
        for (let i = 0; i < attachments.length; i++) {
            const att = attachments[i];
            if (!att.name || !att.data) {
                return res.status(400).json({
                    success: false,
                    error: `Attachment #${i + 1} is missing required 'name' or 'data' fields.`
                });
            }
            const approximateBytes = Math.ceil(att.data.length * 0.75);
            if (approximateBytes > MAX_ATTACHMENT_SIZE_MB * 1024 * 1024) {
                return res.status(400).json({
                    success: false,
                    error: `Attachment "${att.name}" exceeds maximum allowed size of ${MAX_ATTACHMENT_SIZE_MB}MB.`
                });
            }
        }
    }

    try {
        const result = await sendQueue.enqueue(async () => {
            if (clientStatus !== 'READY' || !client) {
                const err = new Error(`Client disconnected before message could be sent (Status: ${clientStatus})`);
                err.statusCode = 503;
                throw err;
            }

            // High-speed verification with RAM cache
            if (chatId.endsWith('@c.us') && !skip_registration_check && process.env.WA_SKIP_REG_CHECK !== 'true') {
                const cached = getCachedRegistration(chatId);
                if (cached === false) {
                    const notRegErr = new Error(`Le numéro ${phone} n'est pas enregistré sur WhatsApp.`);
                    notRegErr.statusCode = 400;
                    throw notRegErr;
                } else if (cached === null) {
                    try {
                        const isRegistered = await client.isRegisteredUser(chatId);
                        setCachedRegistration(chatId, isRegistered);
                        if (isRegistered === false) {
                            const notRegErr = new Error(`Le numéro ${phone} n'est pas enregistré sur WhatsApp.`);
                            notRegErr.statusCode = 400;
                            throw notRegErr;
                        }
                    } catch (regCheckErr) {
                        if (regCheckErr.statusCode === 400) throw regCheckErr;
                    }
                }
            }

            let lastResponse = null;

            if (hasAttachments) {
                for (let i = 0; i < attachments.length; i++) {
                    const attachment = attachments[i];
                    const { name, mime_type, data } = attachment;
                    if (!name || !data) continue;

                    const media = new MessageMedia(mime_type || 'application/octet-stream', data, name);
                    const options = {};
                    if (message && i === 0) {
                        options.caption = message;
                    }

                    lastResponse = await client.sendMessage(chatId, media, options);
                    log('info', `Attachment sent to ${chatId}: ${name}`);
                }
            } else {
                lastResponse = await client.sendMessage(chatId, message);
                log('info', `Message successfully sent to ${chatId}.`);
            }

            // Successful send confirms the number is registered
            setCachedRegistration(chatId, true);

            return { success: true, messageId: lastResponse?.id?.id || null };
        });

        return res.json(result);
    } catch (err) {
        const status = err.statusCode || 500;
        log('error', `Send error to ${phone}: ${err.message}`);
        return res.status(status).json({ success: false, error: err.message });
    }
});

// POST /logout
app.post('/logout', requireApiKey, async (req, res) => {
    try {
        log('info', 'Logging out from WhatsApp session via API...');
        res.json({ success: true, message: 'Logged out successfully' });

        enqueueAction(async () => {
            if (client) {
                try {
                    await client.logout();
                } catch (err) {
                    log('warn', `Logout error on client: ${err.message}`);
                }
            }
            await destroyCurrentClient('API Logout');

            const sessionDir = path.join(sessionDataPath, 'session');
            try {
                if (fs.existsSync(sessionDir)) {
                    fs.rmSync(sessionDir, { recursive: true, force: true });
                    log('info', 'Session files removed after explicit logout.');
                }
            } catch (_) {}

            await initializeNewClient('Post-logout fresh client');
        }, true).catch((err) => {
            log('error', `Re-init after logout failed: ${err.message}`);
        });
    } catch (error) {
        log('error', `Logout endpoint error: ${error.message}`);
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /restart
app.post('/restart', requireApiKey, async (req, res) => {
    log('info', 'Manual restart requested via API...');
    res.json({ success: true, message: 'Restart initiated' });

    enqueueAction(() => initializeNewClient('API Manual Restart'), true).catch((err) => {
        log('error', `Manual restart failed: ${err.message}`);
    });
});

// ── Immediate Server Start ───────────────────────────────────────────────────
// HTTP server starts listening right away at process boot.
// This guarantees that health checks (e.g. Django / Waitress / Python GUI)
// succeed within 5ms without hanging on browser launch.
const server = app.listen(port, host, () => {
    log('info', `WhatsApp automation service listening at http://${host}:${port}`);
    if (API_KEY) {
        log('info', 'API key authentication is ENABLED.');
    } else {
        log('info', 'API key authentication is DISABLED.');
    }

    if (STARTUP_DELAY_MS > 0) {
        setTimeout(() => {
            enqueueAction(() => initializeNewClient('Initial Startup'), true).catch((err) => {
                log('error', `Initial client startup failed: ${err.message}`);
            });
        }, STARTUP_DELAY_MS);
    } else {
        enqueueAction(() => initializeNewClient('Immediate Startup'), true).catch((err) => {
            log('error', `Initial client startup failed: ${err.message}`);
        });
    }
});