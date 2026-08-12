const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const path = require('path');

const app = express();
const port = Number(process.env.WA_PORT || 3000);

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

let isShuttingDown = false;

async function shutdown() {
    if (isShuttingDown) return;
    isShuttingDown = true;

    console.log('Shutting down WhatsApp service...');

    try {
        if (client) {
            await client.destroy();
            client = null;
            console.log('WhatsApp client destroyed.');
        }
    } catch (error) {
        console.error('Error destroying WhatsApp client:', error);
    }

    process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// Tears down the dead client (if possible) and spins up a fresh one.
// This replaces "client.initialize() on the same instance", which is
// what was forcing a manual process restart after logout/disconnect.
async function restartClient() {
    if (isRestarting || isShuttingDown) return;

    isRestarting = true;

    try {
        const old = client;

        if (old) {
            try {
                await old.destroy();
            } catch (err) {
                console.warn(
                    'Error destroying old client (continuing anyway):',
                    err.message
                );
            }
        }
    } finally {
        isRestarting = false;

        if (!isShuttingDown) {
            createClient();
        }
    }
}

// Initial boot
createClient();

// Helper to format Moroccan or international phone number to contact ID (formatted e.g. 2126...@c.us)
function formatPhoneToChatId(phone) {
    if (!phone) return null;
    let cleaned = String(phone).replace(/\D/g, '');
    if (/^(06|07|05)/.test(cleaned) && cleaned.length === 10) {
        cleaned = '212' + cleaned.substring(1);
    } else if (/^(6|7|5)/.test(cleaned) && cleaned.length === 9) {
        cleaned = '212' + cleaned;
    } else if (cleaned.startsWith('00212')) {
        cleaned = cleaned.substring(2);
    }
    return cleaned ? `${cleaned}@c.us` : null;
}

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
        const chatId = formatPhoneToChatId(phone);
        if (!chatId) {
            return res.status(400).json({ success: false, error: 'Invalid phone number' });
        }
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
            console.log(`Message successfully sent to ${chatId}.`);
            res.json({ success: true, messageId: lastResponse?.id?.id || null });
        }
    } catch (error) {
        console.error('Failed to send message:', error);
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /create-group — Create a WhatsApp group
app.post('/create-group', requireApiKey, async (req, res) => {
    const { name, participants = [] } = req.body;
    if (!name) {
        return res.status(400).json({ success: false, error: 'Group name is required' });
    }
    if (clientStatus !== 'READY') {
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        const participantChatIds = [];
        for (const phone of participants) {
            const cId = formatPhoneToChatId(phone);
            if (cId) {
                try {
                    const isReg = await client.isRegisteredUser(cId);
                    if (isReg) {
                        participantChatIds.push(cId);
                    }
                } catch (err) {
                    console.warn(`Error checking registration for ${phone}:`, err.message);
                }
            }
        }

        console.log(`Creating WhatsApp group "${name}" with ${participantChatIds.length} initial participants`);
        const groupResult = await client.createGroup(name, participantChatIds);

        const groupId = typeof groupResult === 'string' ? groupResult : (groupResult.gid?._serialized || groupResult.gid);
        
        let inviteLink = null;
        try {
            const chat = await client.getChatById(groupId);
            if (chat && typeof chat.getInviteCode === 'function') {
                const inviteCode = await chat.getInviteCode();
                if (inviteCode) {
                    inviteLink = `https://chat.whatsapp.com/${inviteCode}`;
                }
            }
        } catch (linkErr) {
            console.warn(`Could not get invite code for group ${groupId}:`, linkErr.message);
        }

        return res.json({
            success: true,
            groupId: groupId,
            inviteLink: inviteLink
        });
    } catch (error) {
        console.error('Failed to create group:', error);
        return res.status(500).json({ success: false, error: error.message });
    }
});

// POST /group-add-participants — Add participants to an existing group
app.post('/group-add-participants', requireApiKey, async (req, res) => {
    const { groupId, participants = [] } = req.body;
    if (!groupId || !participants || participants.length === 0) {
        return res.status(400).json({ success: false, error: 'groupId and participants array are required' });
    }
    if (clientStatus !== 'READY') {
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        const chat = await client.getChatById(groupId);
        if (!chat) {
            return res.status(404).json({ success: false, error: `Group ${groupId} not found` });
        }

        const participantChatIds = [];
        for (const phone of participants) {
            const cId = formatPhoneToChatId(phone);
            if (cId) {
                try {
                    const isReg = await client.isRegisteredUser(cId);
                    if (isReg) participantChatIds.push(cId);
                } catch (err) {
                    console.warn(`Error checking registration for ${phone}:`, err.message);
                }
            }
        }

        if (participantChatIds.length === 0) {
            return res.json({ success: true, added: [], message: 'No valid registered participants to add' });
        }

        let addResult = null;
        let addError = null;
        try {
            addResult = await chat.addParticipants(participantChatIds);
        } catch (err) {
            console.error(`Error in chat.addParticipants for group ${groupId}:`, err);
            addError = err;
        }

        // Format response so backend can inspect per-participant status or fallback
        const results = {};
        for (const cId of participantChatIds) {
            const cleanPhone = cId.replace('@c.us', '');
            if (addError) {
                // Direct addition failed (e.g. WhatsApp privacy setting, not in contacts, or driver error)
                results[cleanPhone] = {
                    status: 403,
                    message: typeof addError === 'string' ? addError : (addError.message || 'Error adding participant directly')
                };
            } else if (addResult && typeof addResult === 'object' && addResult[cId]) {
                const code = addResult[cId].code || 200;
                results[cleanPhone] = {
                    status: code,
                    message: code === 200 ? 'Added' : (addResult[cId].message || 'Failed')
                };
            } else {
                results[cleanPhone] = { status: 200, message: 'Added' };
            }
        }

        return res.json({
            success: true,
            results: results,
            raw: addResult
        });
    } catch (error) {
        console.error(`Failed to add participants to group ${groupId}:`, error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

// POST /group-remove-participants — Remove participants from an existing group
app.post('/group-remove-participants', requireApiKey, async (req, res) => {
    const { groupId, participants = [] } = req.body;
    if (!groupId || !participants || participants.length === 0) {
        return res.status(400).json({ success: false, error: 'groupId and participants array are required' });
    }
    if (clientStatus !== 'READY') {
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        const chat = await client.getChatById(groupId);
        if (!chat) {
            return res.status(404).json({ success: false, error: `Group ${groupId} not found` });
        }

        const participantChatIds = [];
        for (const phone of participants) {
            const cId = formatPhoneToChatId(phone);
            if (cId) participantChatIds.push(cId);
        }

        if (participantChatIds.length === 0) {
            return res.json({ success: true, removed: [] });
        }

        let removeResult = null;
        let removeError = null;
        try {
            removeResult = await chat.removeParticipants(participantChatIds);
        } catch (err) {
            console.error(`Error in chat.removeParticipants for group ${groupId}:`, err);
            removeError = err;
        }

        const results = {};
        for (const cId of participantChatIds) {
            const cleanPhone = cId.replace('@c.us', '');
            if (removeError) {
                results[cleanPhone] = {
                    status: 500,
                    message: typeof removeError === 'string' ? removeError : (removeError.message || 'Error removing participant')
                };
            } else if (removeResult && typeof removeResult === 'object' && removeResult[cId]) {
                const code = removeResult[cId].code || 200;
                results[cleanPhone] = {
                    status: code,
                    message: code === 200 ? 'Removed' : (removeResult[cId].message || 'Failed')
                };
            } else {
                results[cleanPhone] = { status: 200, message: 'Removed' };
            }
        }

        return res.json({
            success: true,
            results: results,
            raw: removeResult
        });
    } catch (error) {
        console.error(`Failed to remove participants from group ${groupId}:`, error);
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

// GET /group-info — Get group info including participants
app.get('/group-info', requireApiKey, async (req, res) => {
    const groupId = req.query.groupId;
    if (!groupId) {
        return res.status(400).json({ success: false, error: 'groupId query parameter is required' });
    }
    if (clientStatus !== 'READY') {
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        const chat = await client.getChatById(groupId);
        if (!chat) {
            return res.status(404).json({ success: false, error: `Group ${groupId} not found` });
        }

        let inviteLink = null;
        try {
            if (typeof chat.getInviteCode === 'function') {
                const inviteCode = await chat.getInviteCode();
                if (inviteCode) {
                    inviteLink = `https://chat.whatsapp.com/${inviteCode}`;
                }
            }
        } catch (err) {
            console.warn(`Could not fetch invite code for ${groupId}:`, err.message);
        }

        const participants = (chat.participants || []).map(p => ({
            id: p.id._serialized,
            user: p.id.user,
            isAdmin: p.isAdmin,
            isSuperAdmin: p.isSuperAdmin
        }));

        return res.json({
            success: true,
            id: chat.id._serialized,
            name: chat.name,
            inviteLink: inviteLink,
            participants: participants
        });
    } catch (error) {
        console.error(`Failed to fetch group info for ${groupId}:`, error);
        return res.status(500).json({ success: false, error: error.message });
    }
});

// POST /logout — Logout session
app.post('/logout', requireApiKey, async (req, res) => {
    try {
        console.log('Logging out from WhatsApp session...');
        await client.logout();
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
    setTimeout(() => restartClient(), 200);
});

app.listen(port, '127.0.0.1', () => {
    console.log(`WhatsApp automation service listening at http://localhost:${port}`);
    if (API_KEY) {
        console.log('API key authentication is ENABLED.');
    } else {
        console.log('API key authentication is DISABLED (set WA_API_KEY env var to enable).');
    }
});
