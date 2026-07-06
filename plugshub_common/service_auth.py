"""Service-to-service authentication (SaaS Constitution Article VIII §2, D-2).

Internal east-west calls must prove they come from a fleet service. The caller attaches the shared
``INTERNAL_SERVICE_TOKEN`` in its own **``X-Internal-Service-Token``** header (kept distinct from
``Authorization``, which carries the end-user JWT); the receiver **verifies** it with a
**constant-time** compare and **fails closed** on every non-public endpoint. Only liveness /
readiness / metrics are exempt (§2, D-2).

The pure verification logic is dependency-free and unit-testable. A Starlette/FastAPI middleware
(:func:`build_service_auth_middleware`) applies it fleet-wide; import it only when the ``http``
extra is installed.
"""

import hmac
from typing import Any, Callable, Iterable, Optional

from plugshub_common.errors import UnauthorizedError

__all__ = [
    "INTERNAL_TOKEN_HEADER",
    "REQUEST_ID_HEADER",
    "TENANT_ID_HEADER",
    "DEFAULT_PUBLIC_PATHS",
    "verify_service_token",
    "is_public_path",
    "require_service_token",
    "build_service_auth_middleware",
]

INTERNAL_TOKEN_HEADER = "X-Internal-Service-Token"
REQUEST_ID_HEADER = "X-Request-ID"
TENANT_ID_HEADER = "X-Tenant-ID"

# Only liveness/readiness/metrics are exempt from the service credential (Article VIII §2).
DEFAULT_PUBLIC_PATHS = frozenset({"/health", "/ready", "/metrics"})


def verify_service_token(provided: Optional[str], expected: str) -> bool:
    """Constant-time compare of the presented token against the shared secret (Article VIII §2).

    Fails closed: an empty/absent ``provided`` or an unset ``expected`` returns ``False``. Uses
    :func:`hmac.compare_digest` so timing does not leak the secret (Article XVI §8).
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def is_public_path(path: str, public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS) -> bool:
    """Whether ``path`` is exempt from the service credential (health/ready/metrics)."""
    return path.rstrip("/") in {p.rstrip("/") for p in public_paths} or path in public_paths


def require_service_token(
    provided: Optional[str],
    expected: str,
    path: str,
    public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS,
) -> None:
    """Enforce the service credential on a non-public path, or raise (Article VIII §2).

    Public paths pass through untouched. On a non-public path an invalid/absent token raises
    :class:`~plugshub_common.errors.UnauthorizedError` (401 ``common.unauthorized``) — fail-closed.
    """
    if is_public_path(path, public_paths):
        return
    if not verify_service_token(provided, expected):
        raise UnauthorizedError(
            "missing or invalid internal service token",
            code="common.service_unauthorized",
        )


def build_service_auth_middleware(
    expected_token: str,
    public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS,
) -> Callable[..., Any]:
    """Build a Starlette/FastAPI middleware that enforces the service credential (Article VIII §2).

    Verifies ``X-Internal-Service-Token`` (fail-closed) on every non-public request and reads
    ``X-Tenant-ID`` + ``X-Request-ID`` into the logging context. Requires the ``http`` extra
    (starlette). On rejection it returns the standard error envelope with a 401 status.
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore
    from starlette.requests import Request  # type: ignore
    from starlette.responses import JSONResponse  # type: ignore

    from plugshub_common.errors import error_envelope
    from plugshub_common.logging import set_request_context

    public = frozenset(public_paths)

    class ServiceAuthMiddleware(BaseHTTPMiddleware):  # type: ignore[misc, valid-type]
        async def dispatch(self, request: "Request", call_next: Callable[..., Any]) -> Any:
            request_id = request.headers.get(REQUEST_ID_HEADER)
            tenant_id = request.headers.get(TENANT_ID_HEADER)
            set_request_context(request_id=request_id, tenant_id=tenant_id)

            if not is_public_path(request.url.path, public):
                token = request.headers.get(INTERNAL_TOKEN_HEADER)
                if not verify_service_token(token, expected_token):
                    body = error_envelope(
                        "common.service_unauthorized",
                        "missing or invalid internal service token",
                        request_id or "",
                    )
                    return JSONResponse(body, status_code=401)
            return await call_next(request)

    return ServiceAuthMiddleware
