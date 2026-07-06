const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const path = require('path');

const app = express();
const port = 3000;

// ── Simple API-key security ───────────────────────────────────────────────────
// Set WA_API_KEY environment variable before starting (e.g. in run_server.py or .env).
// If not set, the service runs without authentication (local-only, safe for dev).
const API_KEY = process.env.WA_API_KEY || null;

function requireApiKey(req, res, next) {
    if (!API_KEY) return next(); // No key configured – allow all
    const key = req.headers['x-api-key'];
    if (key === API_KEY) return next();
    return res.status(401).json({ success: false, error: 'Unauthorized' });
}
// ─────────────────────────────────────────────────────────────────────────────

app.use(express.json({ limit: '100mb' }));

let qrCodeData = null;
let clientStatus = 'INITIALIZING'; // INITIALIZING, QR_RECEIVED, AUTHENTICATED, READY, DISCONNECTED, ERROR
let clientInfo = null;
let client = null;
let isRestarting = false;

function createClient() {
    console.log('Initializing WhatsApp Client...');
    clientStatus = 'INITIALIZING';
    qrCodeData = null;
    clientInfo = null;

    const newClient = new Client({
        authStrategy: new LocalAuth({
            dataPath: path.join(__dirname, 'whatsapp_session')
        }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        }
    });

    newClient.on('qr', async (qr) => {
        clientStatus = 'QR_RECEIVED';
        console.log('QR Code received. Please scan on the dashboard.');
        try {
            qrCodeData = await qrcode.toDataURL(qr);
        } catch (err) {
            console.error('Failed to generate QR data URL', err);
        }
    });

    newClient.on('authenticated', () => {
        clientStatus = 'AUTHENTICATED';
        qrCodeData = null;
        console.log('Authenticated successfully with WhatsApp.');
    });

    newClient.on('auth_failure', (msg) => {
        clientStatus = 'AUTHENTICATION_FAILED';
        console.error('WhatsApp Authentication failure:', msg);
        restartClient();
    });

    newClient.on('ready', () => {
        clientStatus = 'READY';
        clientInfo = newClient.info;
        console.log('WhatsApp Client is fully ready!');
    });

    newClient.on('disconnected', (reason) => {
        clientStatus = 'DISCONNECTED';
        console.log('Client was logged out / disconnected:', reason);
        restartClient();
    });

    client = newClient;

    client.initialize().catch(err => {
        clientStatus = 'ERROR';
        console.error('Failed to initialize WhatsApp client:', err);
        // Even an init failure usually means the browser/session is wedged.
        restartClient();
    });
}

// Tears down the dead client (if possible) and spins up a fresh one.
// This replaces "client.initialize() on the same instance", which is
// what was forcing a manual process restart after logout/disconnect.
async function restartClient() {
    if (isRestarting) return;
    isRestarting = true;
    try {
        const old = client;
        if (old) {
            try {
                await old.destroy();
            } catch (err) {
                console.warn('Error destroying old client (continuing anyway):', err.message);
            }
        }
    } finally {
        isRestarting = false;
        createClient();
    }
}

// Initial boot
createClient();

// ── Endpoints ─────────────────────────────────────────────────────────────────

// GET /status — Get status, QR code, and connected info (public, no auth needed)
app.get('/status', (req, res) => {
    res.json({
        status: clientStatus,
        qr: qrCodeData,
        info: clientInfo
    });
});

// POST /send — Send message to phone number
app.post('/send', requireApiKey, async (req, res) => {
    const { phone, message = '', attachments } = req.body;
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;

    if (!phone || (!message && !hasAttachments)) {
        return res.status(400).json({ success: false, error: 'Phone and message or attachments are required' });
    }

    if (clientStatus !== 'READY') {
        return res.status(503).json({
            success: false,
            error: 'WhatsApp client is not ready. Current status: ' + clientStatus
        });
    }

    try {
        let cleanedPhone = phone.replace(/\D/g, '');

        // Morocco: local numbers 06x/07x/05x (10 digits) → international
        if (/^(06|07|05)/.test(cleanedPhone) && cleanedPhone.length === 10) {
            cleanedPhone = '212' + cleanedPhone.substring(1);
        // Morocco: 9-digit without leading 0 → prepend 212
        } else if (/^(6|7|5)/.test(cleanedPhone) && cleanedPhone.length === 9) {
            cleanedPhone = '212' + cleanedPhone;
        // International 00212 → 212
        } else if (cleanedPhone.startsWith('00212')) {
            cleanedPhone = cleanedPhone.substring(2);
        }

        const chatId = `${cleanedPhone}@c.us`;
        console.log(`Attempting to send message to: ${chatId}`);

        const isRegistered = await client.isRegisteredUser(chatId);
        if (!isRegistered) {
            console.log(`Number ${chatId} is not registered on WhatsApp`);
            return res.status(400).json({
                success: false,
                error: `Le numéro ${phone} n'est pas enregistré sur WhatsApp.`
            });
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
                console.log(`Attachment sent to ${chatId}: ${name}`);
            }

            if (!message) {
                res.json({ success: true, messageId: lastResponse?.id?.id || null });
            } else {
                res.json({ success: true, messageId: lastResponse?.id?.id || null });
            }
        } else {
            lastResponse = await client.sendMessage(chatId, message);
            console.log(`Message successfully sent to ${chatId}. Message ID: ${lastResponse.id.id}`);
            res.json({ success: true, messageId: lastResponse.id.id });
        }
    } catch (error) {
        console.error('Failed to send message:', error);
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /logout — Logout session
app.post('/logout', requireApiKey, async (req, res) => {
    try {
        console.log('Logging out from WhatsApp session...');
        await client.logout();
        // 'disconnected' will fire from the logout and trigger restartClient(),
        // but we also kick it off here in case the event doesn't fire.
        restartClient();
        res.json({ success: true });
    } catch (error) {
        console.error('Logout error:', error);
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /restart — Restart the WhatsApp client without restarting the server
app.post('/restart', requireApiKey, async (req, res) => {
    console.log('Manual restart requested via API...');
    res.json({ success: true, message: 'Restart initiated' });
    // Respond first, then restart so the response gets through
    setTimeout(() => restartClient(), 200);
});

app.listen(port, () => {
    console.log(`WhatsApp automation service listening at http://localhost:${port}`);
    if (API_KEY) {
        console.log('API key authentication is ENABLED.');
    } else {
        console.log('API key authentication is DISABLED (set WA_API_KEY env var to enable).');
    }
});