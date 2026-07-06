"""Structured JSON logging with correlation ids (SaaS Constitution Article IV).

The single source of truth for how the fleet logs. Every line is structured JSON, one event per
line (§1), and always carries ``timestamp`` / ``level`` / ``service`` / ``message`` (§2). Within a
request or event, the contextvar-bound ``request_id`` and ``tenant_id`` (§2, §5) are attached
automatically so a single request is traceable end-to-end in one search.

No emoji, no payload dumps (§1). Sensitive fields (credentials, tokens, phone, email, card) MUST be
masked (§4, Article XVI §4) — use :func:`mask` / :func:`mask_mapping` before logging any such value.
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

__all__ = [
    "configure_logging",
    "get_logger",
    "JsonFormatter",
    "set_request_context",
    "clear_request_context",
    "current_request_id",
    "current_tenant_id",
    "new_request_id",
    "mask",
    "mask_mapping",
    "SENSITIVE_KEYS",
]


def new_request_id() -> str:
    """Generate a fresh correlation id when the caller supplied none (Article V §6)."""
    return uuid.uuid4().hex

# Contextvars carry per-request correlation without threading it through every call (Article IV §2).
_request_id: ContextVar[Optional[str]] = ContextVar("plugshub_request_id", default=None)
_tenant_id: ContextVar[Optional[str]] = ContextVar("plugshub_tenant_id", default=None)

# Fields that must never appear in clear text in a log line (Article IV §4, Article XVI §4).
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "apikey",
        "x-internal-service-token",
        "internal_service_token",
        "otp",
        "otp_code",
        "pin",
        "card",
        "card_number",
        "cvv",
        "phone",
        "phone_number",
        "email",
        "ssn",
    }
)

# The reserved slots on a ``LogRecord`` — anything else the caller passed via ``extra`` is a field.
_RESERVED = frozenset(
    vars(logging.makeLogRecord({})).keys()
) | {"message", "asctime", "taskName"}


def set_request_context(
    request_id: Optional[str] = None, tenant_id: Optional[str] = None
) -> None:
    """Bind the correlation id + tenant for the current context (Article IV §2/§5)."""
    if request_id is not None:
        _request_id.set(request_id)
    if tenant_id is not None:
        _tenant_id.set(tenant_id)


def clear_request_context() -> None:
    """Clear the bound correlation id + tenant (call at the end of a request/event)."""
    _request_id.set(None)
    _tenant_id.set(None)


def current_request_id() -> Optional[str]:
    """The correlation id bound to the current context, if any."""
    return _request_id.get()


def current_tenant_id() -> Optional[str]:
    """The tenant id bound to the current context, if any."""
    return _tenant_id.get()


def mask(value: Any, *, keep: int = 0) -> str:
    """Mask a sensitive scalar to a fixed marker (Article IV §4, Article XVI §4).

    Never leaks a token prefix by default (``keep=0`` → ``"***"``). ``keep`` optionally reveals a
    trailing few characters for a card/phone tail; use sparingly and never for secrets.
    """
    if value is None:
        return "***"
    text = str(value)
    if keep <= 0 or len(text) <= keep:
        return "***"
    return "***" + text[-keep:]


def mask_mapping(
    data: Mapping[str, Any], sensitive_keys: Optional[Iterable[str]] = None
) -> Dict[str, Any]:
    """Return a copy of ``data`` with sensitive keys masked, recursing into nested maps.

    Key matching is case-insensitive against :data:`SENSITIVE_KEYS` (plus any extra keys supplied).
    """
    extra = {k.lower() for k in sensitive_keys} if sensitive_keys else set()
    keys = SENSITIVE_KEYS | extra
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in keys:
            out[key] = "***"
        elif isinstance(value, Mapping):
            out[key] = mask_mapping(value, sensitive_keys)
        else:
            out[key] = value
    return out


class JsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as a single JSON line (Article IV §1/§2).

    Always emits ``timestamp`` (RFC 3339 UTC) / ``level`` / ``service`` / ``message``, plus
    ``request_id`` and ``tenant_id`` from the current context when present. Any ``extra=`` fields
    are merged in; exception info renders as a ``error`` string, never a leaked payload.
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service,
            "message": record.getMessage(),
        }

        req_id = _request_id.get()
        if req_id is not None:
            payload["request_id"] = req_id
        tenant = _tenant_id.get()
        if tenant is not None:
            payload["tenant_id"] = tenant

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    service: str, level: str = "INFO", stream: Any = None
) -> logging.Logger:
    """Install the JSON formatter on the root logger and return the service logger (Article IV §1).

    Idempotent: replaces any existing handler so repeated calls do not double-log. ``level`` follows
    the fixed meanings of Article IV §3 (``DEBUG`` is development-only, off in production).
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    return logging.getLogger(service)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger; use after :func:`configure_logging` has installed the formatter."""
    return logging.getLogger(name)
