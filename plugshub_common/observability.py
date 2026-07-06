"""Optional error tracking / observability initializer (SaaS Constitution Article IV §6).

Article IV §6 requires every service to be wired for **error tracking**. This module provides the
fleet-standard, **vendor-neutral** wiring for it. The current backend is Sentry, but the public API
names nothing vendor-specific, so the Constitution stays vendor-neutral and the backend can be
swapped by a future amendment without changing call sites.

Design guarantees:

* **Safe no-op when unconfigured.** :func:`init_error_tracking` reads the DSN from its argument or
  ``SENTRY_DSN`` (Article III); with no DSN it initializes nothing and returns ``False``. A service
  with error tracking switched off runs unchanged.
* **Lazy optional dependency.** ``sentry-sdk`` is imported only inside :func:`init_error_tracking`
  (the ``sentry`` extra), so core ``import plugshub_common`` stays light and works without it
  installed.
* **Error-signal integrity (Article XVI §5).** Only genuine **server faults (5xx)** are reported;
  expected **client errors (4xx)** — the whole :class:`~plugshub_common.errors.PlugsHubError`
  hierarchy with a ``http_status < 500`` — are never sent, so the error tracker stays a signal of
  real defects, not hostile/expected noise.
* **No secrets / PII (Article IV §4, XVI §4).** A ``before_send`` hook scrubs sensitive fields via
  the shared masking helpers, and ``send_default_pii`` is disabled.

Scope note: **Better Stack (uptime/synthetic monitoring) and log shipping are external
infrastructure, not code** (Articles XXVIII §3, IV §1) — this module only covers the in-process
error-tracking SDK initialization and capture path.
"""

import os
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


class _State:
    """Module-level error-tracking state (a service initializes tracking once at startup)."""

    enabled: bool = False
    sdk: Any = None
    extra_sensitive_keys: frozenset = frozenset()


_state = _State()


def _scrub_event(
    event: Optional[Dict[str, Any]],
    extra_keys: Iterable[str],
) -> Optional[Dict[str, Any]]:
    """``before_send`` hook: mask sensitive fields and attach correlation tags (Article XVI §4).

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
    return scrubbed


def init_error_tracking(
    dsn: Optional[str] = None,
    *,
    environment: Optional[str] = None,
    release: Optional[str] = None,
    service: Optional[str] = None,
    traces_sample_rate: float = 0.0,
    extra_sensitive_keys: Optional[Iterable[str]] = None,
    sdk: Any = None,
) -> bool:
    """Initialize error tracking if a DSN is configured; otherwise a safe no-op (Article IV §6).

    Resolves the DSN from ``dsn`` or the ``SENTRY_DSN`` environment variable (Article III). With no
    DSN, returns ``False`` and initializes nothing — the standard "tracking disabled" path, which
    works even without ``sentry-sdk`` installed. With a DSN, lazily imports the SDK (raising a clear
    install hint if the ``sentry`` extra is missing), installs the scrubbing ``before_send`` hook,
    disables default PII, and returns ``True``. ``sdk`` may be injected for tests.
    """
    dsn = dsn or os.getenv("SENTRY_DSN")
    if not dsn:
        _state.enabled = False
        _state.sdk = None
        return False

    if sdk is None:
        try:
            import sentry_sdk as sdk  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via error path only
            raise RuntimeError(
                "SENTRY_DSN is set but sentry-sdk is not installed; "
                "install plugshub-common[sentry]"
            ) from exc

    keys = frozenset(extra_sensitive_keys) if extra_sensitive_keys else frozenset()
    _state.extra_sensitive_keys = (SENSITIVE_KEYS | _EXTRA_SENSITIVE | keys)
    scrub_keys = _state.extra_sensitive_keys

    def before_send(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Any:
        return _scrub_event(event, scrub_keys)

    sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        before_send=before_send,
    )
    if service is not None and hasattr(sdk, "set_tag"):
        sdk.set_tag("service", service)

    _state.sdk = sdk
    _state.enabled = True
    return True


def should_report(exc: BaseException) -> bool:
    """Whether ``exc`` is a genuine server fault worth reporting (Article XVI §5).

    Anything that is not a :class:`PlugsHubError` is treated as an unexpected 5xx and reported. A
    :class:`PlugsHubError` is reported only when its ``http_status >= 500`` — expected 4xx client
    errors are never sent.
    """
    if isinstance(exc, PlugsHubError):
        return exc.http_status >= 500
    return True


def capture_exception(exc: BaseException) -> bool:
    """Report a server fault to the tracker, filtering out 4xx and no-op when disabled.

    Returns ``True`` if the exception was sent. A no-op (returns ``False``) when tracking is not
    initialized or when ``exc`` is an expected client error (Article XVI §5). Safe to call from the
    global HTTP error handler for every exception.
    """
    if not _state.enabled or _state.sdk is None:
        return False
    if not should_report(exc):
        return False
    _state.sdk.capture_exception(exc)
    return True


def is_error_tracking_enabled() -> bool:
    """Whether error tracking has been initialized with a DSN."""
    return _state.enabled


def reset_error_tracking() -> None:
    """Reset module state (primarily for tests)."""
    _state.enabled = False
    _state.sdk = None
    _state.extra_sensitive_keys = frozenset()
