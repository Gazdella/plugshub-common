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
    # health & tenancy
    "liveness",
    "readiness",
    "validate_tenant",
    # errors
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
    # canonical
    "utc_now",
    "to_rfc3339",
    "parse_rfc3339",
    "Money",
    # logging
    "configure_logging",
    "get_logger",
    "set_request_context",
    "mask",
    "mask_mapping",
    # config
    "BaseServiceSettings",
    "load_settings",
    "ConfigError",
    # resilience
    "RetryPolicy",
    "TimeoutPolicy",
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "retry_async",
    # validation
    "parse_json_body",
    "validate_model",
    # authz
    "Principal",
    "principal_from_claims",
    "require_permission",
    "check_object_ownership",
    "PermissionChecker",
    # audit
    "AuditRecord",
    "AuditWriter",
    "InMemoryAuditSink",
    "LoggingAuditSink",
    # feature flags
    "FeatureFlagProvider",
    "InMemoryFeatureFlags",
    "EnvFeatureFlags",
    # error tracking / observability
    "init_error_tracking",
    "capture_exception",
    "is_error_tracking_enabled",
    # service auth
    "INTERNAL_TOKEN_HEADER",
    "REQUEST_ID_HEADER",
    "TENANT_ID_HEADER",
    "verify_service_token",
    "require_service_token",
    # messaging
    "event_envelope",
    "InMemoryOutbox",
    "OutboxRelay",
    "IdempotentConsumer",
    "InMemoryDeadLetterQueue",
]

__version__ = "0.4.1"
