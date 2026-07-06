"""Pooled async HTTP client with circuit breaker (SaaS Constitution Article VIII §1, XXVI §3).

All synchronous inter-service calls go through this shared, pooled client with **timeouts, retries,
and a circuit breaker** (Article VIII §1). Every internal call auto-attaches the three fleet headers
— **``X-Request-ID``** (correlation), **``X-Tenant-ID``** (tenant context), and
**``X-Internal-Service-Token``** (the D-2 service credential) — pulling ``request_id``/``tenant_id``
from the logging context when the caller does not pass them. Resilience is delegated to
:mod:`plugshub_common.resilience` so retry/timeout/breaker behavior is identical fleet-wide.

``aiohttp`` is imported lazily (the ``http`` extra) and the session is injectable, so this module
imports and unit-tests without a network.
"""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from plugshub_common.logging import current_request_id, current_tenant_id, new_request_id
from plugshub_common.resilience import (
    CircuitBreaker,
    RetryPolicy,
    TimeoutPolicy,
    retry_async,
)
from plugshub_common.service_auth import (
    INTERNAL_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    TENANT_ID_HEADER,
)

__all__ = ["HttpResponse", "TransientHTTPError", "ServiceClient", "build_internal_headers"]


class TransientHTTPError(RuntimeError):
    """A retryable HTTP failure (5xx / network) — feeds the breaker (Article XXVI §3)."""


@dataclass
class HttpResponse:
    """A fully-read HTTP response (body consumed inside the pooled connection)."""

    status: int
    headers: Dict[str, str]
    body: str

    def json(self) -> Any:
        """Parse the body as JSON."""
        import json as _json

        return _json.loads(self.body)


def build_internal_headers(
    internal_token: str,
    *,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    extra: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Assemble the three mandatory internal headers (+ any extra) (Article VIII §1).

    ``request_id``/``tenant_id`` default to the current logging context; a correlation id is
    generated when none exists so the call is always traceable. ``Authorization`` is intentionally
    *not* set here — that slot is the forwarded end-user JWT (D-2).
    """
    req_id = request_id or current_request_id() or new_request_id()
    tenant = tenant_id if tenant_id is not None else current_tenant_id()
    headers: Dict[str, str] = {
        REQUEST_ID_HEADER: req_id,
        INTERNAL_TOKEN_HEADER: internal_token,
    }
    if tenant is not None:
        headers[TENANT_ID_HEADER] = tenant
    if extra:
        headers.update(extra)
    return headers


class ServiceClient:
    """A pooled async HTTP client for internal calls (Article VIII §1, XXVI §3).

    One instance per downstream service (holds one connection pool + one circuit breaker). Lifecycle
    is tied to the framework (``start``/``stop``, Article II §4). A session may be injected for
    tests; otherwise :meth:`start` opens an ``aiohttp`` session with the configured timeouts.
    """

    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_policy: Optional[TimeoutPolicy] = None,
        breaker: Optional[CircuitBreaker] = None,
        session: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = internal_token
        self._retry = retry_policy or RetryPolicy()
        self._timeout = timeout_policy or TimeoutPolicy()
        self._breaker = breaker or CircuitBreaker(name=self.base_url or "service")
        self._session = session

    async def start(self) -> None:
        """Open the pooled ``aiohttp`` session (idempotent). Requires the ``http`` extra."""
        if self._session is not None:
            return
        try:
            import aiohttp  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via error path only
            raise RuntimeError(
                "aiohttp is required for plugshub_common.clients; install plugshub-common[http]"
            ) from exc
        timeout = aiohttp.ClientTimeout(
            total=self._timeout.total, connect=self._timeout.connect
        )
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def stop(self) -> None:
        """Close the session cleanly on shutdown (Article XII §6)."""
        if self._session is not None and hasattr(self._session, "close"):
            await self._session.close()
            self._session = None

    async def _do_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json: Optional[Any],
        params: Optional[Mapping[str, Any]],
    ) -> HttpResponse:
        if self._session is None:
            raise RuntimeError("ServiceClient session is not started")
        async with self._session.request(
            method, url, headers=headers, json=json, params=params
        ) as resp:
            body = await resp.text()
            status = int(resp.status)
            if status >= 500:
                raise TransientHTTPError("{} returned {}".format(url, status))
            return HttpResponse(status=status, headers=dict(resp.headers), body=body)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Any] = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        tenant_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> HttpResponse:
        """Perform an internal request with headers, retries, and the breaker (Article VIII §1)."""
        url = path if path.startswith("http") else self.base_url + "/" + path.lstrip("/")
        final_headers = build_internal_headers(
            self._token, tenant_id=tenant_id, request_id=request_id, extra=headers
        )

        async def _attempt() -> HttpResponse:
            return await self._do_request(method, url, final_headers, json, params)

        return await retry_async(_attempt, self._retry, self._breaker)

    async def get(self, path: str, **kwargs: Any) -> HttpResponse:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> HttpResponse:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> HttpResponse:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> HttpResponse:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> HttpResponse:
        return await self.request("DELETE", path, **kwargs)
