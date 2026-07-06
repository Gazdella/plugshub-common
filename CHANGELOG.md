# Changelog

All notable changes to `plugshub-common` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (SaaS Constitution Article XIV §3,
Article XVII §5).

## [0.3.0] - 2026-07-06

### Added

The full remaining **Appendix A** module inventory landed, so a conformant service can now obtain
every cross-cutting capability from the shared library (Article XVII §1):

- `config` — typed, fail-fast configuration loader on pydantic-settings; aborts startup on a missing
  or insecure required value, with no insecure defaults (Article III).
- `logging` — structured JSON logging, one event per line, with `timestamp/level/service/message`,
  contextvar-bound `request_id`/`tenant_id`, and sensitive-field masking helpers (Article IV,
  Article XVI §4).
- `errors` — shared exception hierarchy plus the standard error `{error:{code,message,request_id,
  details?}}` and success `{data, meta?}` envelope builders, with the namespaced `common.*` code
  convention (Article V).
- `http_middleware` — FastAPI/Starlette request-context middleware (`X-Request-ID`/`X-Tenant-ID`),
  a single global exception handler that renders the error envelope, and RED-metrics hooks
  (Articles IV §6, V, VIII §1).
- `service_auth` — service-to-service auth: constant-time `X-Internal-Service-Token` verification,
  fail-closed on non-public endpoints, health/ready/metrics exempt (Article VIII §2, D-2).
- `db` — shared async `aiomysql` pool with parameterized-query helpers and an auto-discovering,
  fail-closed tenant resolver over the shared validator (Article IX).
- `clients` — pooled async `aiohttp` client with timeouts, retries, and a circuit breaker, auto-
  attaching `X-Request-ID`/`X-Tenant-ID`/`X-Internal-Service-Token` (Articles VIII §1, XXVI §3).
- `resilience` — standard retry/timeout/circuit-breaker policy primitives (Article XXVI §3).
- `messaging` — standard event envelope, transactional outbox + relay, idempotent consumer, and
  dead-letter-queue helpers (Article VIII §3).
- `validation` — boundary input validation on typed models; malformed input maps to the error
  envelope (Article VI §5).
- `authz` — deny-by-default authorization from verified claims plus an object-level ownership check
  (Article XIX).
- `audit` — append-only audit-trail writer (actor/action/target/tenant/UTC timestamp/request_id/
  outcome) with logging and in-memory sinks (Article XX).
- `featureflags` — feature-flag / kill-switch provider interface with in-memory, environment, and
  Redis-backed implementations (Article XXVI §4).
- `canonical` — UTC RFC-3339 timestamp helpers and integer-minor-unit `Money` with ISO-4217 codes
  (Article XXIV).

### Changed

- `pyproject.toml` — added core dependencies (`pydantic`, `pydantic-settings`) and optional extras
  (`http`, `db`, `redis`, `messaging`, `all`, `dev`); configured ruff, mypy, and pytest.
- `README.md` — documented every module and refreshed the roadmap.

## [0.2.0] - 2026-07-02

### Added

- `tenant` — the standard fail-closed tenant-id validator (Article IX §2/§6).

## [0.1.0] - 2026-07-02

### Added

- `health` — standard `/health` (liveness) and `/ready` (readiness) response shapes (Article VII).
- Initial package scaffolding.

[0.3.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.3.0
[0.2.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.2.0
[0.1.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.1.0
