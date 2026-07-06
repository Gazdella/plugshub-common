"""HTTP request-context middleware, global error handler, RED metrics (Articles IV §6, V, VIII §1).

The fleet-standard FastAPI/Starlette wiring so every service behaves identically at the HTTP edge:

* **Request context** — read/generate ``X-Request-ID`` and read ``X-Tenant-ID``, bind both to the
  logging context (Article IV §2/§5), and echo ``X-Request-ID`` on every response (Article V §6).
* **Single global error handler** — render the standard error envelope for every raised
  :class:`~plugshub_common.errors.PlugsHubError` and for any unhandled exception, never leaking
  internals (Article V §1/§2). Per-handler ad-hoc try/except is forbidden.
* **RED metrics** — a Rate/Errors/Duration hook per request (Article IV §6), with a dependency-free
  in-memory recorder default.

FastAPI/Starlette are imported lazily (the ``http`` extra); the metrics recorder is pure stdlib.
"""

import time
from typing import Any, Callable, Dict, Optional

from plugshub_common.errors import (
    PlugsHubError,
    RateLimitedError,
    error_from_exception,
)
from plugshub_common.logging import (
    clear_request_context,
    new_request_id,
    set_request_context,
)
from plugshub_common.observability import capture_exception
from plugshub_common.service_auth import REQUEST_ID_HEADER, TENANT_ID_HEADER

__all__ = [
    "RedMetrics",
    "new_request_id",
    "build_request_context_middleware",
    "install_exception_handlers",
    "setup_http",
]


class RedMetrics:
    """A minimal in-memory RED (Rate, Errors, Duration) recorder (Article IV §6).

    A correct, dependency-free default so metrics work in tests and simple deployments. Production
    services swap in a Prometheus/OTel-backed recorder with the same ``record`` signature; the
    middleware only depends on that method.
    """

    def __init__(self) -> None:
        self.requests: int = 0
        self.errors: int = 0
        self.total_duration: float = 0.0
        self.by_route: Dict[str, Dict[str, float]] = {}

    def record(self, method: str, path: str, status: int, duration: float) -> None:
        """Record one completed request (rate, error count, duration)."""
        self.requests += 1
        self.total_duration += duration
        if status >= 500:
            self.errors += 1
        key = "{} {}".format(method, path)
        bucket = self.by_route.setdefault(
            key, {"requests": 0.0, "errors": 0.0, "duration": 0.0}
        )
        bucket["requests"] += 1
        bucket["duration"] += duration
        if status >= 500:
            bucket["errors"] += 1


def build_request_context_middleware(
    metrics: Optional[RedMetrics] = None,
) -> Callable[..., Any]:
    """Build the Starlette request-context + RED-metrics middleware (Articles IV, V §6).

    Binds ``request_id``/``tenant_id`` to the logging context for the request, echoes
    ``X-Request-ID`` on the response, records RED metrics, and always clears the context afterward.
    Requires the ``http`` extra.
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore
    from starlette.requests import Request  # type: ignore

    class RequestContextMiddleware(BaseHTTPMiddleware):  # type: ignore[misc, valid-type]
        async def dispatch(self, request: "Request", call_next: Callable[..., Any]) -> Any:
            request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
            tenant_id = request.headers.get(TENANT_ID_HEADER)
            set_request_context(request_id=request_id, tenant_id=tenant_id)
            # Stash for exception handlers, which run outside this middleware's try/finally.
            request.state.request_id = request_id

            start = time.monotonic()
            status = 500
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers[REQUEST_ID_HEADER] = request_id
                return response
            finally:
                if metrics is not None:
                    metrics.record(
                        request.method,
                        request.url.path,
                        status,
                        time.monotonic() - start,
                    )
                clear_request_context()

    return RequestContextMiddleware


def install_exception_handlers(app: Any) -> None:
    """Register the single global error handler on a FastAPI app (Article V §1/§2).

    Renders every :class:`PlugsHubError` with its authoritative status + error envelope, maps
    unhandled exceptions to an opaque ``common.internal`` 500 (no leaked internals, Article V §2),
    and attaches ``X-Request-ID`` (and ``Retry-After`` for 429s). Requires the ``http`` extra.
    """
    from starlette.requests import Request  # type: ignore
    from starlette.responses import JSONResponse  # type: ignore

    def _request_id(request: "Request") -> str:
        return getattr(request.state, "request_id", "") or request.headers.get(
            REQUEST_ID_HEADER, ""
        )

    async def _handle_plugshub_error(request: "Request", exc: PlugsHubError) -> Any:
        request_id = _request_id(request)
        # Report only genuine server faults (5xx); 4xx client errors are filtered out (XVI §5).
        capture_exception(exc)
        response = JSONResponse(
            exc.to_envelope(request_id), status_code=exc.http_status
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        if isinstance(exc, RateLimitedError) and exc.retry_after is not None:
            response.headers["Retry-After"] = str(exc.retry_after)
        return response

    async def _handle_unexpected(request: "Request", exc: Exception) -> Any:
        request_id = _request_id(request)
        # Unhandled exceptions are 5xx server faults — report to the error tracker (Article IV §6).
        capture_exception(exc)
        response = JSONResponse(
            error_from_exception(exc, request_id), status_code=500
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.add_exception_handler(PlugsHubError, _handle_plugshub_error)
    app.add_exception_handler(Exception, _handle_unexpected)


def setup_http(app: Any, metrics: Optional[RedMetrics] = None) -> RedMetrics:
    """One-call wiring: request-context middleware + global error handlers (Articles IV, V).

    Returns the :class:`RedMetrics` recorder in use so the service can expose it on ``/metrics``.
    Requires the ``http`` extra.
    """
    metrics = metrics or RedMetrics()
    app.add_middleware(build_request_context_middleware(metrics))
    install_exception_handlers(app)
    return metrics
