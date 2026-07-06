"""Shared exception hierarchy + response envelopes (SaaS Constitution Article V).

The single source of truth for how every service reports success and failure. Handlers raise a
:class:`PlugsHubError` (or a subclass) instead of returning bespoke JSON; a single global handler
(see :mod:`plugshub_common.http_middleware`) renders the error envelope. Two envelopes exist and
exactly one appears per response (Article V §3):

* success — ``{"data": ...}`` with an optional ``meta`` (pagination / top-level info).
* error   — ``{"error": {"code", "message", "request_id", "details?}}``.

``code`` is a stable, namespaced machine string (``domain.reason``, Article V §5). Clients branch on
``code``, never on ``message``. The library owns the ``common.*`` namespace; services add their own.
"""

from typing import Any, Dict, Optional

__all__ = [
    "PlugsHubError",
    "InvalidBodyError",
    "ValidationFailedError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "ConflictError",
    "PreconditionFailedError",
    "RateLimitedError",
    "DependencyUnavailableError",
    "InternalError",
    "error_envelope",
    "success_envelope",
    "error_from_exception",
]


class PlugsHubError(Exception):
    """Base of the shared exception hierarchy (Article V §1).

    Carries the machine ``code`` (namespaced ``domain.reason``), a developer/log-facing ``message``,
    the authoritative ``http_status``, and optional structured ``details``. Never expose raw
    exception strings or stack traces to clients (Article V §2) — render via :func:`error_envelope`.
    """

    code: str = "common.error"
    http_status: int = 500

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.message = message or self.__class__.__doc__ or self.__class__.__name__
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details
        super().__init__(self.message)

    def to_envelope(self, request_id: str) -> Dict[str, Any]:
        """Render this error as the standard error envelope (Article V §5)."""
        return error_envelope(self.code, self.message, request_id, self.details)


class InvalidBodyError(PlugsHubError):
    """A missing or malformed request body — never a server fault (Article XVI §1)."""

    code = "common.invalid_body"
    http_status = 400


class ValidationFailedError(PlugsHubError):
    """Boundary validation rejected typed input (Article VI §5)."""

    code = "common.validation_error"
    http_status = 422


class UnauthorizedError(PlugsHubError):
    """Missing or invalid authentication credential (Article XVI §7)."""

    code = "common.unauthorized"
    http_status = 401


class ForbiddenError(PlugsHubError):
    """Authenticated but not permitted — deny-by-default (Article XIX §2)."""

    code = "common.forbidden"
    http_status = 403


class NotFoundError(PlugsHubError):
    """Requested resource does not exist (or is not visible to the principal)."""

    code = "common.not_found"
    http_status = 404


class ConflictError(PlugsHubError):
    """State conflict — e.g. a stale optimistic-lock write (Article VI §9)."""

    code = "common.conflict"
    http_status = 409


class PreconditionFailedError(PlugsHubError):
    """An ``If-Match``/version precondition failed (Article VI §9)."""

    code = "common.precondition_failed"
    http_status = 412


class RateLimitedError(PlugsHubError):
    """Throttled — pairs with a ``Retry-After`` header and 429 (Article XVI §3d)."""

    code = "common.rate_limited"
    http_status = 429

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        retry_after: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class DependencyUnavailableError(PlugsHubError):
    """A downstream dependency is unavailable — degrade this feature only (Article XXVI §3)."""

    code = "common.dependency_unavailable"
    http_status = 503


class InternalError(PlugsHubError):
    """An unexpected server fault (Article XVI §5) — the only class that logs at ERROR/5xx."""

    code = "common.internal"
    http_status = 500


def error_envelope(
    code: str,
    message: str,
    request_id: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the standard error envelope (Article V §5). ``details`` is omitted when absent."""
    error: Dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        error["details"] = details
    return {"error": error}


def success_envelope(
    data: Any,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the standard success envelope (Article V §4). ``meta`` is omitted when absent.

    There is no ``success`` boolean — the HTTP status conveys success (Article V §3/§4).
    """
    body: Dict[str, Any] = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def error_from_exception(exc: BaseException, request_id: str) -> Dict[str, Any]:
    """Map any exception to an error envelope, never leaking internals (Article V §2).

    A :class:`PlugsHubError` is rendered with its own code/message; anything else collapses to an
    opaque ``common.internal`` — the raw exception string is *not* forwarded to the client.
    """
    if isinstance(exc, PlugsHubError):
        return exc.to_envelope(request_id)
    return error_envelope("common.internal", "Internal server error", request_id)
