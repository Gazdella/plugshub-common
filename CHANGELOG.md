# Changelog

All notable changes to `plugshub-common` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (SaaS Constitution Article XIV §3,
Article XVII §5).

## [0.4.4] - 2026-09-12

### Fixed

- `db` — **a query on a dead-but-ESTABLISHED socket was an unbounded await.** `aiomysql` 0.3.0
  has `connect_timeout` and no read or write timeout, so when a peer vanishes without the client
  learning of it, `await cursor.execute()` never returns and the only bound left is the kernel's
  `tcp_retries2` at ~924 s. On 2026-09-11 that froze the billing SQS consumer for 16 minutes.
  Both of the pool's existing failover mechanisms — ping-before-use and transient-error retry —
  assume the query returns, so neither one ever ran. `DBConfig.tcp_user_timeout` (default 30 s,
  `0` disables) now sets `TCP_USER_TIMEOUT` on each acquired connection's socket, so the kernel
  aborts it and the await raises a connection error the pool already knows how to handle. The
  bound is applied *before* the liveness ping, which is itself an unbounded await on such a
  socket. Linux-only; other platforms keep kernel defaults.

### Added

- `db.bind_socket_timeout(conn, timeout_seconds=30)` — the same bound as a public helper, for the
  four services that build their own `aiomysql` pool rather than using `DBPool`. Exported so the
  fleet has one implementation of this `setsockopt` instead of five (Article XVII §2). Call it on
  each connection after acquiring it and before any ping.

  Deliberately **not** `asyncio.wait_for` around the query: cancelling mid-query returns the
  connection to the pool with a server response still on the wire, poisoning it for the next
  caller.

## [0.4.3] - 2026-08-13

### Security

- `service_auth` — **`verify_service_token` raised `TypeError` on a non-ASCII token instead of
  rejecting it.** `hmac.compare_digest` refuses a `str` containing a non-ASCII character, and
  Starlette latin-1-decodes header values, so a single high byte in `X-Internal-Service-Token`
  became an unhandled exception rather than a failed comparison — a 500 reachable by an
  **unauthenticated** caller on every service using this. `require_service_token` and
  `build_service_auth_middleware` both route through the same line, so the whole fleet was
  exposed. Both operands are now encoded to bytes before comparison, with `surrogatepass`
  because a latin-1 decode of arbitrary bytes can produce lone surrogates that plain UTF-8
  encoding also rejects. A wrong token returns `False`; an identical non-ASCII secret still
  matches, so a deployment whose shared secret contains one keeps authenticating.

### Added

- `preauth` — one park-key builder for the terminal pre-auth contract, replacing two
  independent format strings in terminal-service and session-service (Article XVII §2). If
  those ever diverged nothing would error: the park would simply not be found, the session
  would be classified as ordinary, and the charger would run uncapped against a card hold
  already taken. `connector_id` is stringified inside the builder rather than at each call
  site — terminal-service holds it as an `int`, session-service receives it from ocpp where
  it can arrive as a string, which is exactly the detail two implementations get subtly
  wrong. The key stays positional so a fresh pre-auth overwrites an abandoned one.

## [0.4.2] - 2026-08-12

Released without a changelog entry; recorded here retroactively from the tag (Article XIV §3).

### Added

- `db` — `DBConfig.charset` / `use_unicode`, so a service can select `utf8mb4` and adopt the
  shared pool without silent mb3 truncation.
- `clients` — `ServiceClient(trip_on_5xx=...)`, letting a caller keep the circuit breaker
  closed on HTTP 5xx so only transport failures trip it.

## [0.4.1] - 2026-07-06

### Fixed

- `db` — the shared `DBPool` now implements the **failover resilience** required by Article IX §7:
  the pool MUST survive a database failover (e.g. an HA/Multi-AZ standby promotion) without manual
  intervention. Two mechanisms cover it:
  - **Liveness / recycling.** A new `DBConfig.ping_before_use` (default `True`) pings the acquired
    connection before every query; a failed ping means a connection killed server-side (e.g. by a
    failover) and it is discarded instead of handed to the caller. The existing `pool_recycle`
    setting continues to recycle idle-but-stale connections by age — the two mechanisms complement
    each other.
  - **Transparent retry on a fresh connection.** `execute`/`fetch_all`/`fetch_one` now run through
    `plugshub_common.resilience.retry_async` with a small, bounded backoff policy (reused, not
    reinvented, per Article XVII §2/DRY) that retries **only** connection-level/transient errors —
    `OSError` and, when `aiomysql` is installed, its `OperationalError`/`InterfaceError` — on a
    freshly-acquired connection. Non-transient errors (syntax errors, constraint violations, ...)
    are never in the retryable set and propagate immediately on the first attempt. A failover is a
    brief reconnect blip, never a service restart.
  - `DBPool.__init__` gained optional `retry_policy`, `transient_errors`, and `sleep` parameters so
    services can tune backoff/attempts or fully fake the driver's error types in tests without a
    real MySQL server.

## [0.4.0] - 2026-07-06

### Added

- `observability` — optional, vendor-neutral **error-tracking** initializer satisfying Article IV §6.
  `init_error_tracking()` initializes Sentry when a DSN is configured (arg or `SENTRY_DSN`) and is a
  safe **no-op when unset**; `sentry-sdk` is a **lazy optional** dependency (the `sentry` extra) so
  core `import plugshub_common` stays light and works without it installed. `capture_exception()`
  reports only genuine **server faults (5xx)** — expected **4xx** client errors are filtered out
  (Article XVI §5) — and a `before_send` hook scrubs secrets/PII via the shared masking helpers with
  `send_default_pii` disabled (Article IV §4, XVI §4). Wired into the `http_middleware` global error
  handler so unhandled faults are reported automatically. (Uptime/synthetic monitoring and log
  shipping remain external infrastructure, not code — Articles XXVIII §3, IV §1.)

### Changed

- `http_middleware` — the global exception handler now reports server faults via `observability`.
- `pyproject.toml` — added the `sentry` optional extra (`sentry-sdk`) and folded it into `all`.
- `plugshub_common/__init__.py` / `README.md` — export and document the observability module.

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

[0.4.4]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.4.4
[0.4.3]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.4.3
[0.4.2]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.4.2
[0.4.1]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.4.1
[0.4.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.4.0
[0.3.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.3.0
[0.2.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.2.0
[0.1.0]: https://github.com/Gazdella/plugshub-common/releases/tag/v0.1.0
