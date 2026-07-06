# plugshub-common

Shared fleet helpers — the **SaaS Constitution Appendix A** package. A single source of truth for
cross-service standards so they are byte-identical everywhere and cannot drift (Article XVII). A
conformant service obtains these capabilities here and **MUST NOT** re-implement them.

## Modules

| Module | Purpose | Constitution |
|---|---|---|
| `config` | Typed, fail-fast configuration loader; no insecure defaults | Article III |
| `logging` | Structured JSON logs with `request_id`/`tenant_id` context + masking | Article IV, XVI §4 |
| `errors` | Exception hierarchy + `{data}` / `{error}` envelope builders | Article V |
| `http_middleware` | Request-context middleware, global error handler, RED metrics | Articles IV §6, V, VIII §1 |
| `service_auth` | Constant-time `X-Internal-Service-Token` verification (fail-closed) | Article VIII §2 (D-2) |
| `db` | Shared async pool + auto-discovering fail-closed tenant resolver | Article IX |
| `clients` | Pooled async HTTP client with retries + circuit breaker | Articles VIII §1, XXVI §3 |
| `resilience` | Retry / timeout / circuit-breaker policy primitives | Article XXVI §3 |
| `messaging` | Event envelope, transactional outbox, idempotent consumer, DLQ | Article VIII §3 |
| `validation` | Boundary input validation on typed models | Article VI §5 |
| `authz` | Deny-by-default permissions + object-level ownership checks | Article XIX |
| `audit` | Append-only audit-trail writer | Article XX |
| `featureflags` | Feature-flag / kill-switch client (in-memory, env, redis) | Article XXVI §4 |
| `observability` | Optional, vendor-neutral error tracking (Sentry) — 5xx only, PII-scrubbed | Article IV §6 |
| `canonical` | UTC RFC-3339 time + integer-minor-unit `Money` (ISO-4217) | Article XXIV |
| `health` | Standard `/health` + `/ready` response shapes | Article VII |
| `tenant` | Fail-closed tenant-id validator | Article IX §2/§6 |

## Install

Services depend on a **pinned, tagged release** (Article XVII §4), never a moving branch:

```
plugshub-common @ git+https://github.com/Gazdella/plugshub-common.git@v0.4.0
```

The core install is light. Pull optional backends only where needed:

```
# HTTP edge + inter-service client (FastAPI/Starlette + aiohttp)
plugshub-common[http]   @ git+https://github.com/Gazdella/plugshub-common.git@v0.4.0
# Shared async DB pool (aiomysql)
plugshub-common[db]     @ git+https://github.com/Gazdella/plugshub-common.git@v0.4.0
# Error tracking SDK (sentry-sdk) — only needed when a DSN is configured
plugshub-common[sentry] @ git+https://github.com/Gazdella/plugshub-common.git@v0.4.0
# Everything
plugshub-common[all]    @ git+https://github.com/Gazdella/plugshub-common.git@v0.4.0
```

## Usage

```python
from plugshub_common import (
    liveness, readiness,                       # health (Article VII)
    success_envelope, error_envelope,          # envelopes (Article V)
    InvalidBodyError, NotFoundError,           # exception hierarchy (Article V)
    configure_logging, set_request_context,    # logging (Article IV)
    to_rfc3339, Money,                         # canonical (Article XXIV)
)

# GET /health
return JSONResponse(liveness(SERVICE_NAME, VERSION))

# GET /ready  (service builds its own `checks` + `ready`)
body, status = readiness(ready, checks)
return JSONResponse(body, status_code=status)

# A successful response
return JSONResponse(success_envelope({"id": "inv_123"}))

# A failed operation raises a shared error; the global handler renders the envelope
raise NotFoundError("invoice not found")
```

Wire the HTTP edge (with the `http` extra) in one call:

```python
from fastapi import FastAPI
from plugshub_common.http_middleware import setup_http
from plugshub_common.service_auth import build_service_auth_middleware

app = FastAPI(docs_url=None, redoc_url=None)  # disable docs in prod (Article XVI §2)
metrics = setup_http(app)                     # request context + global error handler + RED metrics
app.add_middleware(build_service_auth_middleware(INTERNAL_SERVICE_TOKEN))
```

Initialize error tracking once at startup (safe no-op when `SENTRY_DSN` is unset):

```python
from plugshub_common import init_error_tracking

# Reads SENTRY_DSN from the environment; no-op (returns False) when unset.
init_error_tracking(environment="production", service=SERVICE_NAME)
# Thereafter the global HTTP handler reports 5xx server faults only; 4xx are filtered (Article XVI §5).
```

## Development

```
pip install -e ".[all,dev]"
pytest          # test suite (Article X)
ruff check .    # lint (Article XI)
mypy plugshub_common
```

## Notes on default implementations

A few capabilities that require external infrastructure ship as a **fully-typed interface plus a
correct in-memory/default implementation** (unit-tested), with the production backend noted in the
module docstring:

- `messaging` — outbox, processed-id, and dead-letter stores are interfaces with in-memory defaults;
  the broker publish is a callable the service supplies (Kafka/RabbitMQ/SQS in production).
- `audit` — ships a `LoggingAuditSink` (dedicated append-only logger) and an `InMemoryAuditSink`;
  point the audit logger at durable append-only storage in production.
- `featureflags` — `RedisFeatureFlags` works against any Redis-like client; `InMemoryFeatureFlags`
  and `EnvFeatureFlags` need nothing.
- `http_middleware` — `RedMetrics` is an in-memory RED recorder; swap in a Prometheus/OTel recorder
  with the same `record` signature in production.
- `observability` — vendor-neutral error-tracking wiring; the current backend is Sentry via the
  lazy optional `sentry` extra. Uptime/synthetic monitoring (e.g. Better Stack) and log shipping are
  external infrastructure, not code (Articles XXVIII §3, IV §1).

This Constitution: see [`SAAS_CONSTITUTION.md`](../SAAS_CONSTITUTION.md) (Article XVII, Appendix A).
