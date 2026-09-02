"""plugshub-common — shared fleet helpers (SaaS Constitution Appendix A).

The single toolbox (Article XVII) every PlugsHub service imports so cross-cutting standards are
byte-identical everywhere and cannot drift. Modules map 1:1 to Appendix A capabilities; heavier
backends (FastAPI, aiomysql, aiohttp, redis) are optional extras and imported lazily so the core
``import plugshub_common`` stays light.
"""

# Audit trail (Article XX)
from plugshub_common.audit import AuditRecord, AuditWriter, InMemoryAuditSink, LoggingAuditSink

# Authorization (Article XIX)
from plugshub_common.authz import (
    PermissionChecker,
    Principal,
    check_object_ownership,
    principal_from_claims,
    require_permission,
)

# Canonical representation (Article XXIV)
from plugshub_common.canonical import Money, parse_rfc3339, to_rfc3339, utc_now

# Configuration (Article III)
from plugshub_common.config import BaseServiceSettings, ConfigError, load_settings

# Errors & envelopes (Article V)
from plugshub_common.errors import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    InternalError,
    InvalidBodyError,
    NotFoundError,
    PlugsHubError,
    PreconditionFailedError,
    RateLimitedError,
    UnauthorizedError,
    ValidationFailedError,
    error_envelope,
    error_from_exception,
    success_envelope,
)

# Feature flags (Article XXVI §4)
from plugshub_common.featureflags import (
    EnvFeatureFlags,
    FeatureFlagProvider,
    InMemoryFeatureFlags,
)

# Health (Article VII)
from plugshub_common.health import liveness, readiness

# Structured logging (Article IV)
from plugshub_common.logging import (
    configure_logging,
    get_logger,
    mask,
    mask_mapping,
    set_request_context,
)

# Messaging: outbox / idempotent consumer / DLQ (Article VIII §3)
from plugshub_common.messaging import (
    IdempotentConsumer,
    InMemoryDeadLetterQueue,
    InMemoryOutbox,
    OutboxRelay,
    event_envelope,
)

# Error tracking / observability (Article IV §6)
from plugshub_common.observability import (
    capture_exception,
    init_error_tracking,
    is_error_tracking_enabled,
)

# The terminal pre-auth park (Article VIII §4 — a cross-service contract)
from plugshub_common.preauth import PREAUTH_KEY_TEMPLATE, preauth_key

# Resilience (Articles VIII §1, XXVI §3)
from plugshub_common.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RetryPolicy,
    TimeoutPolicy,
    retry_async,
)

# Service-to-service auth (Article VIII §2)
from plugshub_common.service_auth import (
    INTERNAL_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    TENANT_ID_HEADER,
    require_service_token,
    verify_service_token,
)

# Tenancy (Article IX)
from plugshub_common.tenant import validate_tenant

# Validation (Article VI §5)
from plugshub_common.validation import parse_json_body, validate_model

__all__ = [
    # audit
    # authz
    # canonical
    # config
    # error tracking / observability
    # errors
    # feature flags
    # health & tenancy
    # logging
    # messaging
    # resilience
    # service auth
    # validation
    "AuditRecord",
    "AuditWriter",
    "BaseServiceSettings",
    "capture_exception",
    "check_object_ownership",
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "ConfigError",
    "configure_logging",
    "ConflictError",
    "DependencyUnavailableError",
    "EnvFeatureFlags",
    "error_envelope",
    "error_from_exception",
    "event_envelope",
    "FeatureFlagProvider",
    "ForbiddenError",
    "get_logger",
    "IdempotentConsumer",
    "init_error_tracking",
    "InMemoryAuditSink",
    "InMemoryDeadLetterQueue",
    "InMemoryFeatureFlags",
    "InMemoryOutbox",
    "INTERNAL_TOKEN_HEADER",
    "InternalError",
    "InvalidBodyError",
    "is_error_tracking_enabled",
    "liveness",
    "load_settings",
    "LoggingAuditSink",
    "mask",
    "mask_mapping",
    "Money",
    "NotFoundError",
    "OutboxRelay",
    "parse_json_body",
    "parse_rfc3339",
    "PermissionChecker",
    "PlugsHubError",
    "preauth_key",
    "PREAUTH_KEY_TEMPLATE",
    "PreconditionFailedError",
    "Principal",
    "principal_from_claims",
    "RateLimitedError",
    "readiness",
    "REQUEST_ID_HEADER",
    "require_permission",
    "require_service_token",
    "retry_async",
    "RetryPolicy",
    "set_request_context",
    "success_envelope",
    "TENANT_ID_HEADER",
    "TimeoutPolicy",
    "to_rfc3339",
    "UnauthorizedError",
    "utc_now",
    "validate_model",
    "validate_tenant",
    "ValidationFailedError",
    "verify_service_token",
]

# Read from the INSTALLED package metadata, i.e. from pyproject.toml — never
# hardcoded here.
#
# It was hardcoded, and it drifted: pyproject went 0.4.1 -> 0.4.2 -> 0.4.3 -> 0.5.0
# while this string stayed at "0.4.1" through every one of those releases. Anyone
# checking `plugshub_common.__version__` to find out what a service was running got
# 0.4.1 no matter what was installed — which is exactly how a fleet-wide version
# audit reached the wrong conclusion on 2026-09-02, mid-incident.
#
# One source of truth. A release bumps pyproject.toml and this follows.
#
# The fallback is for a source tree that was never pip-installed (running tests
# straight out of a checkout); "0.0.0.dev0" is deliberately not a plausible release
# number, so an environment reporting it is telling you it has no metadata rather
# than quietly naming a version that might be wrong.
try:  # pragma: no cover - trivial, and the except needs an uninstalled tree to hit
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("plugshub-common")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"
