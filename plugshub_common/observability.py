"""Error tracking on the Better Stack log path (SaaS Constitution Article IV §6).

Article IV §6 requires every service to be wired for **error tracking**. The fleet's error
destination is **Better Stack**: a service's structured `ERROR` log lines are shipped off-host by a
Vector agent into that service's dedicated Better Stack Source (Article XXVIII §7), where the alert
inventory turns them into pages. This module is the in-process half of that path — the thing a
service calls when it catches a server fault so the fault reliably becomes one of those lines.

Design guarantees:

* **No SDK, no DSN, nothing to arm.** The sink is the service's own log stream, which every service
  already configures via :mod:`plugshub_common.logging`. There is no vendor client to initialize and
  no credential that can be missing, so error tracking cannot silently be "wired but dormant" —
  :func:`capture_exception` works whether or not :func:`init_error_tracking` was ever called.
* **Error-signal integrity (Article XVI §5).** Only genuine **server faults (5xx)** are reported;
  expected **client errors (4xx)** — the whole :class:`~plugshub_common.errors.PlugsHubError`
  hierarchy with a ``http_status < 500`` — are never reported, so `ERROR` stays a signal of real
  defects rather than hostile/expected noise (Article IV §8, log-noise hygiene).
* **Correlated.** Every report carries the current ``request_id``/``tenant_id`` so a fault in Better
  Stack is traceable back to its request (Article IV §2/§5), plus ``service``/``environment``/
  ``release`` when :func:`init_error_tracking` supplied them.
* **No secrets / PII (Article IV §4, XVI §4).** Structured fields are masked with the shared masking
  helpers before they are emitted.
* **Traces stay with OpenTelemetry.** A reported fault is also recorded on the current OTLP span
  (``record_exception`` + ``ERROR`` status) when a tracer is active, which is what drives the
  Tracing → Errors view and the error-rate alert. Metrics and traces reach Better Stack over OTLP;
  this module never exports them itself.
"""

import logging
from typing import Any, Dict, Iterable, Mapping, Optional

from plugshub_common.errors import PlugsHubError
from plugshub_common.logging import (
    SENSITIVE_KEYS,
    current_request_id,
    current_tenant_id,
    mask_mapping,
)

__all__ = [
    "init_error_tracking",
    "capture_exception",
    "is_error_tracking_enabled",
    "reset_error_tracking",
    "should_report",
]

# Extra header/cookie keys worth scrubbing beyond the shared logging defaults (Article XVI §4).
_EXTRA_SENSITIVE = frozenset({"cookie", "set-cookie", "x-api-key", "x-auth-token", "session"})

# Server faults are reported on a dedicated logger so a Vector source or a Better Stack alert can
# select them by name without having to pattern-match every service's own logger.
_FAULT_LOGGER = "plugshub.server_fault"

# `logging` raises KeyError if an `extra` key shadows a built-in LogRecord attribute. Caller context
# must never turn a fault report into a second, different exception, so colliding keys are prefixed
# rather than passed through.
_RESERVED_LOG_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _State:
    """Static tags a service registers once at startup, attached to every report."""

    tags: Dict[str, str] = {}
    extra_sensitive_keys: frozenset = frozenset()


_state = _State()


def _scrub_event(
    event: Optional[Dict[str, Any]],
    extra_keys: Iterable[str],
) -> Optional[Dict[str, Any]]:
    """Mask sensitive fields and attach correlation tags to a report's structured fields.

    Recursively masks known-sensitive keys (credentials, tokens, phone, email, cookies, ...) across
    the whole event, then tags it with the current ``request_id``/``tenant_id`` so a reported fault
    is traceable back to its request (Article IV §2/§5).
    """
    if not isinstance(event, Mapping):
        return event
    scrubbed = mask_mapping(event, extra_keys)
    tags = scrubbed.get("tags")
    if not isinstance(tags, dict):
        tags = {}
        scrubbed["tags"] = tags
    request_id = current_request_id()
    if request_id is not None:
        tags.setdefault("request_id", request_id)
    tenant_id = current_tenant_id()
    if tenant_id is not None:
        tags.setdefault("tenant_id", tenant_id)
    for key, value in _state.tags.items():
        tags.setdefault(key, value)
    return scrubbed


def init_error_tracking(
    *,
    environment: Optional[str] = None,
    release: Optional[str] = None,
    service: Optional[str] = None,
    extra_sensitive_keys: Optional[Iterable[str]] = None,
) -> bool:
    """Register the static tags carried by every reported fault (Article IV §6).

    Optional: :func:`capture_exception` reports faults with or without this call, because the sink
    is the service's log stream rather than a vendor client that has to be constructed. Calling it
    at startup is still worth doing — it stamps ``service``/``environment``/``release`` onto every
    report, which is how Better Stack groups a fault by deployment. Always returns ``True``: with no
    DSN to supply there is no configuration under which error tracking is off.
    """
    tags: Dict[str, str] = {}
    if service is not None:
        tags["service"] = service
    if environment is not None:
        tags["environment"] = environment
    if release is not None:
        tags["release"] = release
    _state.tags = tags
    keys = frozenset(extra_sensitive_keys) if extra_sensitive_keys else frozenset()
    _state.extra_sensitive_keys = SENSITIVE_KEYS | _EXTRA_SENSITIVE | keys
    return True


def should_report(exc: BaseException) -> bool:
    """Whether ``exc`` is a genuine server fault worth reporting (Article XVI §5).

    Anything that is not a :class:`PlugsHubError` is treated as an unexpected 5xx and reported. A
    :class:`PlugsHubError` is reported only when its ``http_status >= 500`` — expected 4xx client
    errors are never reported.
    """
    if isinstance(exc, PlugsHubError):
        return exc.http_status >= 500
    return True


def capture_exception(exc: BaseException, context: Optional[Mapping[str, Any]] = None) -> bool:
    """Report a server fault to Better Stack, filtering out expected 4xx.

    Emits a scrubbed, correlated ``ERROR`` log record with the traceback attached — which the host
    Vector agent ships to the service's Better Stack Source — and records the exception on the
    current OTLP span when one is active. Returns ``True`` if the fault was reported, ``False`` for
    an expected client error (Article XVI §5). Safe to call from the global HTTP error handler for
    every exception.

    ``context`` adds structured fields to the record (route, upstream, identifiers, ...). It is
    masked with the shared helpers before emission, so a caller cannot leak a credential or PII into
    the log stream by attaching a request payload (Article IV §4, XVI §4).
    """
    if not should_report(exc):
        return False

    event: Dict[str, Any] = dict(context or {})
    event["exception_type"] = type(exc).__name__
    event["fault"] = "server"
    fields = _scrub_event(
        event, _state.extra_sensitive_keys or (SENSITIVE_KEYS | _EXTRA_SENSITIVE)
    )
    safe = {
        (f"context_{k}" if k in _RESERVED_LOG_KEYS else k): v for k, v in (fields or {}).items()
    }
    logging.getLogger(_FAULT_LOGGER).error(
        "server fault: %s", type(exc).__name__, exc_info=exc, extra=safe
    )
    _record_on_span(exc)
    return True


def _record_on_span(exc: BaseException) -> None:
    """Mark the active OTLP span as failed, so the fault also shows in Tracing → Errors."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode
    except ImportError:  # OpenTelemetry is a service-level dependency, not a library one.
        return
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def is_error_tracking_enabled() -> bool:
    """Whether faults reach an error destination — always ``True`` (Article IV §6).

    Kept so a service can report the state of §6 wiring on ``/ready``. The answer is unconditional
    because the destination is the log stream: there is no DSN to arm and therefore no "wired but
    dormant" state to distinguish.
    """
    return True


def reset_error_tracking() -> None:
    """Clear the registered static tags (primarily for tests)."""
    _state.tags = {}
    _state.extra_sensitive_keys = frozenset()
