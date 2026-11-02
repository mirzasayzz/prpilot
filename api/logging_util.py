"""Structured JSON logging for PRPilot API modules.

Usage:

    from api.logging_util import get_logger, log_event

    logger = get_logger(__name__)
    log_event(logger, "info", "webhook received",
              delivery_id="123", event="pull_request")

Rules built into this module:

* Log names, ids, and short status values, never secret values.
  Any mapping key that looks like a key, token, secret, password,
  credential, or bearer value is replaced with "[REDACTED]".
* The same redaction applies to text shaped like
  "api_key=abc123" in a free-form message.
* Exception type names may be logged. Full exception text and
  tracebacks are not logged here, because they can carry values
  that were in the failing call.

Prompt delimiting and private code sent to LLMs:

* When code is sent to an LLM, put it inside a clearly delimited
  block (for example a fenced code block with the file path in a
  header line) and keep the instruction text outside that block,
  so model output cannot be mistaken for an instruction and code
  cannot be mistaken for a system prompt.
* Never send secrets, tokens, private keys, or encrypted values
  to an LLM. Only the code under review goes in the prompt.
* Per-repository opt-out of LLM review is a documented follow-up
  item. It is not a feature in this codebase, and this module does
  not claim otherwise. Do not log a per-repo opt-out as if it had
  been honoured until that feature exists.
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "private_key",
    "encryption_key",
    "credential",
    "bearer",
    "auth",
)

_TEXT_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key"
    r"|authorization|bearer)\s*[:=]\s*[^\s,;\"']+"
)


def _is_sensitive_key(key):
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact_value(key, value):
    """Return REDACTED for sensitive keys, otherwise the value."""
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    return value


def redact_mapping(value):
    """Recursively redact sensitive keys in dicts and lists."""
    if isinstance(value, dict):
        return {
            key: redact_mapping(redact_value(key, item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item) for item in value]
    return value


def redact_text(text):
    """Redact key-like assignments inside a free-form message."""
    if not isinstance(text, str):
        return text
    return _TEXT_PATTERN.sub(lambda match: match.group(1) + "=" + REDACTED, text)


class JsonFormatter(logging.Formatter):
    """Format a log record as one JSON object per line."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for field in ("delivery_id", "request_id", "event", "installation_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        if record.exc_info and record.exc_info[0] is not None:
            # Type name only. No exception text, no traceback.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def get_logger(name):
    """Return a logger writing JSON lines to stdout, once only."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


def log_event(logger, level, message, delivery_id=None, request_id=None, **fields):
    """Log one structured event without secret values."""
    extra = {"fields": redact_mapping(fields)}
    if delivery_id is not None:
        extra["delivery_id"] = delivery_id
    if request_id is not None:
        extra["request_id"] = request_id
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(redact_text(message), extra=extra)
