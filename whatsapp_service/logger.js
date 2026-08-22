const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const MAX_LOG_BYTES = 5 * 1024 * 1024;
const MAX_LOG_FILES = 5;
const hashSecret = process.env.WA_LOG_HASH_SECRET || process.env.WA_API_KEY || 'whatsapp-log-secret';
const logDirectory = process.env.WA_LOG_DIR || path.join(__dirname, 'logs');
const logFile = path.join(logDirectory, 'whatsapp.log');

function hashIdentifier(value, prefix) {
    if (value === undefined || value === null || value === '') return null;
    const digest = crypto.createHmac('sha256', hashSecret).update(String(value)).digest('hex');
    return `${prefix}:${digest.slice(0, 12)}`;
}

function maskPhone(value) {
    if (value === undefined || value === null || value === '') return null;
    const digits = String(value).replace(/\D/g, '');
    if (digits.length < 6) return 'masked';
    return `+${digits.slice(0, 3)}********${digits.slice(-3)}`;
}

function safeError(error) {
    if (!error) return { error_code: null, error_type: null, error_message: null };
    let message = String(error.message || error).replace(/[\r\n]+/g, ' ');
    if (process.env.WA_API_KEY) message = message.split(process.env.WA_API_KEY).join('[REDACTED]');
    message = message.replace(/\b\d{8,}\b/g, '[REDACTED_ID]');
    message = message.slice(0, 500);
    return {
        error_code: error.code || error.statusCode || null,
        error_type: error.name || typeof error,
        error_message: message
    };
}

function rotateLogs() {
    try {
        if (!fs.existsSync(logFile) || fs.statSync(logFile).size < MAX_LOG_BYTES) return;
        for (let index = MAX_LOG_FILES - 1; index >= 1; index -= 1) {
            const source = `${logFile}.${index}`;
            const destination = `${logFile}.${index + 1}`;
            if (fs.existsSync(source)) fs.renameSync(source, destination);
        }
        fs.renameSync(logFile, `${logFile}.1`);
    } catch (error) {
        process.stderr.write(`WhatsApp log rotation failed: ${safeError(error).error_message}\n`);
    }
}

function log(level, fields = {}) {
    const entry = {
        timestamp: new Date().toISOString(),
        level,
        service: 'whatsapp',
        component: fields.component || 'service',
        event: fields.event || 'unknown',
        operation: fields.operation || null,
        correlation_id: fields.correlation_id || null,
        request_id: fields.request_id || fields.correlation_id || null,
        state: fields.state || null,
        duration_ms: fields.duration_ms ?? null,
        result: fields.result || null,
        error_code: fields.error_code || null,
        error_type: fields.error_type || null,
        ...fields
    };
    delete entry.message;
    delete entry.body;
    delete entry.headers;
    delete entry.authorization;
    delete entry.api_key;
    delete entry.qr;
    delete entry.qr_code;
    delete entry.cookies;
    delete entry.storage;
    delete entry.session;
    delete entry.phone;
    delete entry.participants;
    delete entry.message_text;
    delete entry.media_data;

    const line = JSON.stringify(entry);
    process.stdout.write(`${line}\n`);
    try {
        fs.mkdirSync(logDirectory, { recursive: true });
        rotateLogs();
        fs.appendFileSync(logFile, `${line}\n`, { encoding: 'utf8' });
    } catch (error) {
        process.stderr.write(`WhatsApp log write failed: ${safeError(error).error_message}\n`);
    }
}

function errorFields(error) {
    return safeError(error);
}

module.exports = {
    log,
    errorFields,
    hashIdentifier,
    maskPhone,
    host: os.hostname()
};
