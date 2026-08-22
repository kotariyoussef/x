const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const { log, errorFields, hashIdentifier } = require('./logger');

const app = express();
const port = Number(process.env.WA_PORT || 3000);

// ── Simple API-key security ───────────────────────────────────────────────────
// Set WA_API_KEY environment variable before starting (e.g. in run_server.py or .env).
// If not set, the service runs without authentication (local-only, safe for dev).
const API_KEY = process.env.WA_API_KEY || null;

const STATES = new Set([
    'STOPPED', 'STARTING', 'INITIALIZING', 'QR_REQUIRED', 'AUTHENTICATING',
    'AUTHENTICATED', 'READY', 'DISCONNECTED', 'RECONNECTING', 'LOGGING_OUT',
    'RESTARTING', 'ERROR'
]);
let serviceState = 'STOPPED';
let stateChangedAt = Date.now();
let startupAt = Date.now();
let restartCount = 0;

function correlationId() {
    return crypto.randomUUID();
}

function transitionState(nextState, reason, fields = {}) {
    if (!STATES.has(nextState)) nextState = 'ERROR';
    const now = Date.now();
    const previousState = serviceState;
    const stateDuration = now - stateChangedAt;
    serviceState = nextState;
    stateChangedAt = now;
    clientStatus = nextState;
    log('INFO', {
        component: 'state_machine',
        event: 'state_change',
        operation: fields.operation || null,
        previous_state: previousState,
        state: nextState,
        reason,
        state_duration_ms: stateDuration,
        ...fields
    });
}

function operationLog(level, event, operation, startedAt, fields = {}) {
    log(level, {
        component: fields.component || 'client',
        event,
        operation,
        duration_ms: startedAt ? Date.now() - startedAt : null,
        ...fields
    });
}

function requireApiKey(req, res, next) {
    if (!API_KEY) return next(); // No key configured – allow all
    const key = req.headers['x-api-key'];
    if (key === API_KEY) return next();
    return res.status(401).json({ success: false, error: 'Unauthorized' });
}
// ─────────────────────────────────────────────────────────────────────────────


app.use((req, res, next) => {
    const id = req.headers['x-correlation-id'] || req.headers['x-request-id'] || correlationId();
    req.correlationId = String(id).slice(0, 100);
    res.setHeader('X-Correlation-ID', req.correlationId);
    const startedAt = Date.now();
    log('INFO', {
        component: 'http',
        event: 'request_received',
        operation: `${req.method} ${req.path}`,
        correlation_id: req.correlationId,
        request_id: req.correlationId,
        http_method: req.method,
        endpoint: req.path
    });
    res.on('finish', () => log(res.statusCode >= 500 ? 'ERROR' : 'INFO', {
        component: 'http',
        event: 'request_completed',
        operation: `${req.method} ${req.path}`,
        correlation_id: req.correlationId,
        request_id: req.correlationId,
        http_method: req.method,
        endpoint: req.path,
        http_status: res.statusCode,
        duration_ms: Date.now() - startedAt,
        result: res.statusCode < 400 ? 'success' : 'failure'
    }));
    next();
});
app.use(express.json({ limit: '100mb' }));

let qrCodeData = null;
let clientStatus = 'INITIALIZING'; // INITIALIZING, QR_RECEIVED, AUTHENTICATED, READY, DISCONNECTED, ERROR
let clientInfo = null;
let client = null;
let isRestarting = false;

function createClient() {
    console.log('Initializing WhatsApp Client...');
    const operationStartedAt = Date.now();
    startupAt = startupAt || operationStartedAt;
    transitionState('INITIALIZING', 'client_initialize_started', { operation: 'initialize' });
    operationLog('INFO', 'client_created', 'initialize', operationStartedAt, {
        component: 'client',
        node_version: process.version,
        platform: process.platform,
        architecture: process.arch,
        library: 'whatsapp-web.js',
        headless: true,
        port,
        session_directory_exists: fs.existsSync(path.join(__dirname, 'whatsapp_session'))
    });
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
        transitionState('QR_REQUIRED', 'qr_received', { operation: 'authenticate', qr_available: true });
        operationLog('INFO', 'qr_generated', 'authenticate', startupAt, { qr_available: true });
        console.log('QR Code received. Please scan on the dashboard.');
        try {
            qrCodeData = await qrcode.toDataURL(qr);
        } catch (err) {
            log('ERROR', { component: 'qr', event: 'qr_generation_failed', operation: 'authenticate', result: 'failure', ...errorFields(err) });
        }
    });

    newClient.on('authenticated', () => {
        transitionState('AUTHENTICATED', 'authentication_success', { operation: 'authenticate' });
        operationLog('INFO', 'authentication_success', 'authenticate', startupAt, { authenticated: true });
        qrCodeData = null;
        console.log('Authenticated successfully with WhatsApp.');
    });

    newClient.on('auth_failure', (msg) => {
        const fields = errorFields(new Error(String(msg || 'Authentication failed')));
        transitionState('ERROR', 'authentication_failure', { operation: 'authenticate', ...fields });
        operationLog('ERROR', 'authentication_failed', 'authenticate', startupAt, fields);
        console.error('WhatsApp Authentication failure');
        restartClient('authentication_failure');
    });

    newClient.on('ready', () => {
        transitionState('READY', 'client_ready', { operation: 'initialize' });
        operationLog('INFO', 'whatsapp_ready', 'initialize', startupAt, {
            authenticated: true,
            browser_status: 'ready',
            client_version: newClient.info?.platform || null
        });
        clientInfo = newClient.info;
        console.log('WhatsApp Client is fully ready!');
    });

    newClient.on('disconnected', (reason) => {
        transitionState('DISCONNECTED', 'client_disconnected', { operation: 'connection', disconnect_reason: String(reason || 'unknown').slice(0, 200) });
        operationLog('WARN', 'connection_lost', 'connection', startupAt, { disconnect_reason: String(reason || 'unknown').slice(0, 200) });
        console.log('Client was logged out / disconnected');
        restartClient('disconnect');
    });

    client = newClient;

    client.initialize().catch(err => {
        const fields = errorFields(err);
        transitionState('ERROR', 'initialization_error', { operation: 'initialize', ...fields });
        operationLog('ERROR', 'client_initialize_failed', 'initialize', operationStartedAt, fields);
        console.error('Failed to initialize WhatsApp client');
        // Even an init failure usually means the browser/session is wedged.
        restartClient('initialization_error');
    });
}

let isShuttingDown = false;

async function shutdown() {
    if (isShuttingDown) return;
    isShuttingDown = true;

    transitionState('STOPPED', 'process_shutdown', { operation: 'shutdown' });
    log('INFO', { component: 'process', event: 'shutdown_started', operation: 'shutdown', uptime_ms: Date.now() - startupAt });
    console.log('Shutting down WhatsApp service...');

    try {
        if (client) {
            await client.destroy();
            client = null;
            log('INFO', { component: 'client', event: 'client_destroy_completed', operation: 'shutdown', result: 'success' });
            console.log('WhatsApp client destroyed.');
        }
    } catch (error) {
        log('ERROR', { component: 'client', event: 'client_destroy_failed', operation: 'shutdown', result: 'failure', ...errorFields(error) });
        console.error('Error destroying WhatsApp client');
    }

    process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// Tears down the dead client (if possible) and spins up a fresh one.
// This replaces "client.initialize() on the same instance", which is
// what was forcing a manual process restart after logout/disconnect.
async function restartClient(reason = 'unspecified') {
    if (isRestarting || isShuttingDown) return;

    isRestarting = true;
    restartCount += 1;
    const operationStartedAt = Date.now();
    transitionState('RESTARTING', reason, { operation: 'restart', trigger: reason, retry_count: restartCount });
    operationLog('INFO', 'restart_started', 'restart', operationStartedAt, { trigger: reason, retry_count: restartCount });

    try {
        const old = client;

        if (old) {
            operationLog('INFO', 'restart_client_destroy_started', 'restart', operationStartedAt, { trigger: reason });
            try {
                await old.destroy();
                operationLog('INFO', 'restart_client_destroy_completed', 'restart', operationStartedAt, { result: 'success' });
            } catch (err) {
                operationLog('WARN', 'restart_client_destroy_failed', 'restart', operationStartedAt, { result: 'failure', ...errorFields(err) });
                console.warn('Error destroying old client (continuing anyway)');
            }
        }
    } finally {
        isRestarting = false;

        if (!isShuttingDown) {
            transitionState('RECONNECTING', 'restart_initialize_started', { operation: 'restart', trigger: reason });
            createClient();
            operationLog('INFO', 'restart_initialize_started', 'restart', operationStartedAt, { trigger: reason });
        }
    }
}

// Initial boot
transitionState('STARTING', 'process_start', { operation: 'startup', node_version: process.version, platform: process.platform, architecture: process.arch, configured_port: port });
log('INFO', { component: 'process', event: 'process_started', operation: 'startup', node_version: process.version, platform: process.platform, architecture: process.arch, configured_port: port, session_directory_exists: fs.existsSync(path.join(__dirname, 'whatsapp_session')) });
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
    log('INFO', { component: 'health', event: 'health_status_requested', operation: 'health_check', correlation_id: req.correlationId, state: serviceState });
    res.json({
        status: serviceState,
        qr: qrCodeData,
        info: clientInfo,
        service: 'whatsapp',
        process: 'online',
        api: 'online',
        client: serviceState === 'STOPPED' ? 'stopped' : 'initialized',
        authenticated: ['AUTHENTICATED', 'READY'].includes(serviceState),
        ready: serviceState === 'READY'
    });
});

// POST /send — Send message to phone number
app.post('/send', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'send_message';
    const { phone, message = '', attachments } = req.body;
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const destinationHash = hashIdentifier(phone, 'hash');
    log('INFO', { component: 'message', event: 'message_send_requested', operation, correlation_id: req.correlationId, destination_hash: destinationHash, message_type: hasAttachments ? 'media' : 'text', message_length: typeof message === 'string' ? message.length : 0, has_media: hasAttachments, media_count: hasAttachments ? attachments.length : 0 });

    if (!phone || (!message && !hasAttachments)) {
        operationLog('WARN', 'message_validation_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', error_code: 'WA_INVALID_REQUEST' });
        return res.status(400).json({ success: false, error: 'Phone and message or attachments are required' });
    }

    if (clientStatus !== 'READY') {
        operationLog('WARN', 'message_send_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', error_code: 'WA_NOT_READY', state: serviceState });
        return res.status(503).json({
            success: false,
            error: 'WhatsApp client is not ready. Current status: ' + clientStatus
        });
    }

    try {
        const chatId = formatPhoneToChatId(phone);
        if (!chatId) {
            operationLog('WARN', 'message_validation_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', error_code: 'WA_INVALID_REQUEST' });
            return res.status(400).json({ success: false, error: 'Invalid phone number' });
        }
        log('INFO', { component: 'message', event: 'message_send_started', operation, correlation_id: req.correlationId, destination_hash: destinationHash, has_media: hasAttachments });

        const isRegistered = await client.isRegisteredUser(chatId);
        if (!isRegistered) {
            operationLog('WARN', 'message_validation_failed', operation, operationStartedAt, { correlation_id: req.correlationId, destination_hash: destinationHash, result: 'failure', error_code: 'WA_NOT_REGISTERED' });
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
                log('INFO', { component: 'media', event: 'media_send_completed', operation, correlation_id: req.correlationId, destination_hash: destinationHash, file_size: Buffer.byteLength(data, 'base64'), mime_type: mime_type || 'application/octet-stream', result: 'success' });
            }

            if (!message) {
                operationLog('INFO', 'message_send_success', operation, operationStartedAt, { correlation_id: req.correlationId, destination_hash: destinationHash, result: 'success', has_media: true, media_count: attachments.length });
                res.json({ success: true, messageId: lastResponse?.id?.id || null });
            } else {
                operationLog('INFO', 'message_send_success', operation, operationStartedAt, { correlation_id: req.correlationId, destination_hash: destinationHash, result: 'success', has_media: true, media_count: attachments.length });
                res.json({ success: true, messageId: lastResponse?.id?.id || null });
            }
        } else {
            lastResponse = await client.sendMessage(chatId, message);
            console.log('Message successfully sent.');
            operationLog('INFO', 'message_send_success', operation, operationStartedAt, { correlation_id: req.correlationId, destination_hash: destinationHash, result: 'success', has_media: false });
            res.json({ success: true, messageId: lastResponse?.id?.id || null });
        }
    } catch (error) {
        operationLog('ERROR', 'message_send_failed', operation, operationStartedAt, { correlation_id: req.correlationId, destination_hash: destinationHash, result: 'failure', ...errorFields(error) });
        console.error('Failed to send message');
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /send-group - Send a message to one explicitly selected WhatsApp group
app.post('/send-group', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'send_group_message';
    const { groupId, message = '', attachments } = req.body;
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const groupHash = hashIdentifier(groupId, 'group');
    log('INFO', { component: 'group_message', event: 'group_message_send_requested', operation, correlation_id: req.correlationId, group_id_hash: groupHash, message_length: typeof message === 'string' ? message.length : 0, has_media: hasAttachments, media_count: hasAttachments ? attachments.length : 0 });

    if (!groupId || (!message && !hasAttachments)) {
        operationLog('WARN', 'group_message_validation_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: groupHash, result: 'failure', error_code: 'WA_INVALID_REQUEST' });
        return res.status(400).json({ success: false, error: 'groupId and message or attachments are required' });
    }
    if (serviceState !== 'READY') {
        operationLog('WARN', 'group_message_send_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: groupHash, result: 'failure', error_code: 'WA_NOT_READY', state: serviceState });
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        let lastResponse = null;
        if (hasAttachments) {
            for (const attachment of attachments) {
                if (!attachment || !attachment.name || !attachment.data) continue;
                const media = new MessageMedia(attachment.mime_type || 'application/octet-stream', attachment.data, attachment.name);
                lastResponse = await client.sendMessage(groupId, media, message ? { caption: message } : {});
            }
        } else {
            lastResponse = await client.sendMessage(groupId, message);
        }
        operationLog('INFO', 'group_message_send_success', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: groupHash, result: 'success', has_media: hasAttachments, media_count: hasAttachments ? attachments.length : 0 });
        return res.json({ success: true, messageId: lastResponse?.id?.id || null });
    } catch (error) {
        operationLog('ERROR', 'group_message_send_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: groupHash, result: 'failure', ...errorFields(error) });
        return res.status(500).json({ success: false, error: error.message });
    }
});

// POST /create-group — Create a WhatsApp group
app.post('/create-group', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'create_group';
    const { name, participants = [] } = req.body;
    log('INFO', { component: 'group', event: 'group_create_requested', operation, correlation_id: req.correlationId, participant_count: Array.isArray(participants) ? participants.length : 0 });
    if (!name) {
        operationLog('WARN', 'group_create_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', error_code: 'WA_INVALID_REQUEST' });
        return res.status(400).json({ success: false, error: 'Group name is required' });
    }
    if (clientStatus !== 'READY') {
        operationLog('WARN', 'group_create_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', error_code: 'WA_NOT_READY', state: serviceState });
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
                    log('WARN', { component: 'group', event: 'participant_validation_failed', operation: 'create_group', result: 'failure', ...errorFields(err) });
                }
            }
        }

        console.log(`Creating WhatsApp group with ${participantChatIds.length} initial participants`);
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
            log('WARN', { component: 'group', event: 'group_invite_link_failed', operation: 'create_group', result: 'failure', ...errorFields(linkErr) });
        }

        operationLog('INFO', 'group_create_success', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'success', group_id_hash: hashIdentifier(groupId, 'group'), participant_count: participantChatIds.length });
        return res.json({
            success: true,
            groupId: groupId,
            inviteLink: inviteLink
        });
    } catch (error) {
        operationLog('ERROR', 'group_create_failed', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'failure', ...errorFields(error) });
        console.error('Failed to create group');
        return res.status(500).json({ success: false, error: error.message });
    }
});

// POST /group-add-participants — Add participants to an existing group
app.post('/group-add-participants', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'add_group_participants';
    const { groupId, participants = [] } = req.body;
    log('INFO', { component: 'group', event: 'group_add_participants_requested', operation, correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), participant_count: Array.isArray(participants) ? participants.length : 0 });
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
                    log('WARN', { component: 'group', event: 'participant_validation_failed', operation: 'add_group_participants', result: 'failure', ...errorFields(err) });
                }
            }
        }

        if (participantChatIds.length === 0) {
            operationLog('INFO', 'group_add_participants_success', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'success', group_id_hash: hashIdentifier(groupId, 'group'), participant_count: 0, success_count: 0, failure_count: 0 });
            return res.json({ success: true, added: [], message: 'No valid registered participants to add' });
        }

        let addResult = null;
        let addError = null;
        try {
            addResult = await chat.addParticipants(participantChatIds);
        } catch (err) {
            log('ERROR', { component: 'group', event: 'group_add_participants_failed', operation, correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), result: 'failure', ...errorFields(err) });
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

        operationLog('INFO', 'group_add_participants_success', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'success', group_id_hash: hashIdentifier(groupId, 'group'), participant_count: participantChatIds.length });
        return res.json({
            success: true,
            results: results,
            raw: addResult
        });
    } catch (error) {
        operationLog('ERROR', 'group_add_participants_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), result: 'failure', ...errorFields(error) });
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

// POST /group-remove-participants — Remove participants from an existing group
app.post('/group-remove-participants', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'remove_group_participants';
    const { groupId, participants = [] } = req.body;
    log('INFO', { component: 'group', event: 'group_remove_participants_requested', operation, correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), participant_count: Array.isArray(participants) ? participants.length : 0 });
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
            log('ERROR', { component: 'group', event: 'group_remove_participants_failed', operation, correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), result: 'failure', ...errorFields(err) });
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

        operationLog('INFO', 'group_remove_participants_success', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'success', group_id_hash: hashIdentifier(groupId, 'group'), participant_count: participantChatIds.length });
        return res.json({
            success: true,
            results: results,
            raw: removeResult
        });
    } catch (error) {
        operationLog('ERROR', 'group_remove_participants_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), result: 'failure', ...errorFields(error) });
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

// GET /group-info — Get group info including participants
app.get('/group-info', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'group_info';
    const groupId = req.query.groupId;
    log('INFO', { component: 'group', event: 'group_info_requested', operation, correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group') });
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
            log('WARN', { component: 'group', event: 'group_invite_link_failed', operation: 'group_info', result: 'failure', ...errorFields(err) });
        }

        const participants = (chat.participants || []).map(p => ({
            id: p.id._serialized,
            user: p.id.user,
            isAdmin: p.isAdmin,
            isSuperAdmin: p.isSuperAdmin
        }));

        operationLog('INFO', 'group_info_success', operation, operationStartedAt, { correlation_id: req.correlationId, result: 'success', group_id_hash: hashIdentifier(groupId, 'group'), participant_count: participants.length });
        return res.json({
            success: true,
            id: chat.id._serialized,
            name: chat.name,
            inviteLink: inviteLink,
            participants: participants
        });
    } catch (error) {
        operationLog('ERROR', 'group_info_failed', operation, operationStartedAt, { correlation_id: req.correlationId, group_id_hash: hashIdentifier(groupId, 'group'), result: 'failure', ...errorFields(error) });
        return res.status(500).json({ success: false, error: error.message });
    }
});

// GET /groups — List all accessible WhatsApp groups
app.get('/groups', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    const operation = 'list_groups';
    log('INFO', { component: 'group', event: 'group_list_requested', operation, correlation_id: req.correlationId });
    if (clientStatus !== 'READY') {
        return res.status(503).json({ success: false, error: 'WhatsApp client is not ready' });
    }

    try {
        const chats = await client.getChats();
        const groupChats = chats.filter(c => c.isGroup);
        const groups = groupChats.map(g => ({
            id: g.id._serialized,
            name: g.name || 'Unnamed Group',
            isReadOnly: Boolean(g.isReadOnly),
            unreadCount: g.unreadCount || 0,
            timestamp: g.timestamp || null,
            participantCount: Array.isArray(g.participants) ? g.participants.length : (g.groupMetadata?.participants?.length || 0),
        }));

        operationLog('INFO', 'group_list_success', operation, operationStartedAt, {
            correlation_id: req.correlationId,
            result: 'success',
            group_count: groups.length
        });
        return res.json({
            success: true,
            groups: groups,
            count: groups.length
        });
    } catch (error) {
        operationLog('ERROR', 'group_list_failed', operation, operationStartedAt, {
            correlation_id: req.correlationId,
            result: 'failure',
            ...errorFields(error)
        });
        return res.status(500).json({ success: false, error: error.message || String(error) });
    }
});

// POST /logout — Logout session
app.post('/logout', requireApiKey, async (req, res) => {
    const operationStartedAt = Date.now();
    log('INFO', { component: 'client', event: 'logout_requested', operation: 'logout', correlation_id: req.correlationId });
    transitionState('LOGGING_OUT', 'logout_requested', { operation: 'logout' });
    try {
        console.log('Logging out from WhatsApp session...');
        await client.logout();
        operationLog('INFO', 'logout_completed', 'logout', operationStartedAt, { correlation_id: req.correlationId, result: 'success', session_deleted: false });
        restartClient('manual_logout');
        res.json({ success: true });
    } catch (error) {
        operationLog('ERROR', 'logout_failed', 'logout', operationStartedAt, { correlation_id: req.correlationId, result: 'failure', ...errorFields(error) });
        console.error('Logout error');
        res.status(500).json({ success: false, error: error.message });
    }
});

// POST /restart — Restart the WhatsApp client without restarting the server
app.post('/restart', requireApiKey, async (req, res) => {
    log('INFO', { component: 'client', event: 'restart_requested', operation: 'restart', correlation_id: req.correlationId, trigger: 'admin_request' });
    console.log('Manual restart requested via API...');
    res.json({ success: true, message: 'Restart initiated' });
    setTimeout(() => restartClient('admin_request'), 200);
});

process.on('uncaughtException', (error) => {
    log('ERROR', { component: 'process', event: 'uncaught_exception', operation: 'process', result: 'failure', ...errorFields(error) });
});

process.on('unhandledRejection', (error) => {
    log('ERROR', { component: 'process', event: 'unhandled_rejection', operation: 'process', result: 'failure', ...errorFields(error) });
});

process.on('exit', (code) => {
    log(code === 0 ? 'INFO' : 'ERROR', { component: 'process', event: 'process_exit', operation: 'process', result: code === 0 ? 'success' : 'failure', exit_code: code, uptime_ms: Date.now() - startupAt });
});

app.listen(port, '127.0.0.1', () => {
    log('INFO', { component: 'http', event: 'process_ready', operation: 'startup', state: serviceState, configured_port: port, result: 'success' });
    console.log(`WhatsApp automation service listening at http://localhost:${port}`);
    if (API_KEY) {
        console.log('API key authentication is ENABLED.');
    } else {
        console.log('API key authentication is DISABLED (set WA_API_KEY env var to enable).');
    }
});
