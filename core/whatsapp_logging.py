"""Privacy-safe structured logging helpers for WhatsApp operations."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import uuid
from typing import Any

LOGGER = logging.getLogger("whatsapp")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(x-api-key|authorization|wa_api_key|secret_key|token)=?[^\s,;]+"),
)

_log_directory = Path(os.environ.get("WA_LOG_DIR", Path(__file__).resolve().parents[1] / "logs"))
try:
    _log_directory.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(handler, RotatingFileHandler) for handler in LOGGER.handlers):
        _handler = RotatingFileHandler(
            _log_directory / "whatsapp-django.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _handler.setLevel(logging.INFO)
        LOGGER.addHandler(_handler)
except OSError:
    pass


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def hash_identifier(value: Any, prefix: str) -> str | None:
    if value in (None, ""):
        return None
    secret = os.environ.get("WA_LOG_HASH_SECRET") or os.environ.get("WA_API_KEY") or "whatsapp-log-secret"
    digest = hmac.new(secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()
    return f"{prefix}:{digest[:12]}"


def mask_phone(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 6:
        return "masked"
    return f"+{digits[:3]}********{digits[-3:]}"


def safe_error(error: BaseException | None) -> dict[str, str | None]:
    if error is None:
        return {"error_code": None, "error_type": None, "error_message": None}
    message = re.sub(r"[\r\n]+", " ", str(error))
    for secret_name in ("WA_API_KEY", "SECRET_KEY", "LICENSE_EXTRA_SECRET"):
        secret = os.environ.get(secret_name)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"\b\d{8,}\b", "[REDACTED_ID]", message)
    message = message[:500]
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return {
        "error_code": getattr(error, "code", None),
        "error_type": type(error).__name__,
        "error_message": message,
    }


def log_event(level: int = logging.INFO, **fields: Any) -> None:
    entry = {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "level": logging.getLevelName(level),
        "service": "whatsapp",
        "component": fields.pop("component", "django"),
        "event": fields.pop("event", "unknown"),
        "operation": fields.pop("operation", None),
        "correlation_id": fields.pop("correlation_id", None),
        "request_id": fields.pop("request_id", None),
        "state": fields.pop("state", None),
        "duration_ms": fields.pop("duration_ms", None),
        "result": fields.pop("result", None),
        "error_code": fields.pop("error_code", None),
        "error_type": fields.pop("error_type", None),
        **fields,
    }
    for key in ("api_key", "authorization", "headers", "body", "message", "message_text", "phone", "participants", "session", "qr"):
        entry.pop(key, None)
    LOGGER.log(level, json.dumps(entry, ensure_ascii=True, default=str))
