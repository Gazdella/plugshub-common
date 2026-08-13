"""plugshub-common — shared fleet helpers (SaaS Constitution Appendix A).

The single toolbox (Article XVII) every PlugsHub service imports so cross-cutting standards are
byte-identical everywhere and cannot drift. Modules map 1:1 to Appendix A capabilities; heavier
backends (FastAPI, aiomysql, aiohttp, redis) are optional extras and imported lazily so the core
``import plugshub_common`` stays light.
"""

# Audit trail (Article XX)
from plugshub_common.audit import AuditRecord, AuditWriter, InMemoryAuditSink, LoggingAuditSink

# The terminal pre-auth park (Article VIII §4 — a cross-service contract)
from plugshub_common.preauth import PREAUTH_KEY_TEMPLATE, preauth_key

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

__version__ = "0.4.1"
