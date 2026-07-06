"""Shared async DB pool + fail-closed tenant resolver (SaaS Constitution Article IX).

Database access goes through the **shared connection pool** (per-call connections are forbidden,
§1), queries are **parameterized** (§1), and no ORM is introduced (§1). Multi-tenancy is one
database per tenant; the tenant is resolved per request and **validated by the shared validator**
(:func:`plugshub_common.tenant.validate_tenant`) against an **auto-discovered** authoritative set
before it ever forms a schema name (§2, §6). Validation **fails closed** with no fallback to a
shared schema.

**Failover resilience (§7).** The pool MUST survive a database failover (e.g. an HA/Multi-AZ
standby promotion) without manual intervention. Two mechanisms cover it: a stale connection is
recycled by age (``pool_recycle``) and, more immediately, by a **ping-before-use liveness check**
(``ping_before_use``) that discards a connection killed server-side before it is ever handed to the
caller; and a query that still fails because its connection dropped mid-failover is **transparently
retried on a freshly-acquired connection** with small, bounded backoff. Retries reuse
:mod:`plugshub_common.resilience` rather than reinventing a second retry mechanism (Article XVII
§2, DRY within the library) and only ever retry connection-level/transient errors — syntax errors,
constraint violations, and other non-transient driver errors propagate on the first attempt. A
failover is a brief reconnect blip, never a service restart (this is the DB-side counterpart to the
HTTP resilience of Article VIII §1).

``aiomysql`` is imported lazily (the ``db`` extra), and the tenant resolver's discovery function is
injectable, so this module imports and unit-tests without a live database.
"""

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Set, Tuple, Type

from plugshub_common.errors import DependencyUnavailableError
from plugshub_common.resilience import RetryPolicy, retry_async
from plugshub_common.tenant import validate_tenant

__all__ = ["DBConfig", "DBPool", "TenantResolver"]


def _default_transient_errors() -> Tuple[Type[BaseException], ...]:
    """Connection-level error types that indicate a dropped/dead connection (Article IX §7).

    Always includes the stdlib socket-level errors a mid-failover disconnect can raise (``OSError``
    covers ``ConnectionError``, ``ConnectionResetError``, ``BrokenPipeError``, ``TimeoutError``).
    When ``aiomysql`` is installed, its ``OperationalError``/``InterfaceError`` are added too — the
    DB-API classes covering "server has gone away" / "lost connection" / "can't connect", as
    distinct from ``ProgrammingError``/``IntegrityError`` (syntax errors, constraint violations),
    which are never in this set and are therefore never retried.
    """
    errors: List[Type[BaseException]] = [OSError]
    try:
        import aiomysql  # type: ignore

        errors.append(aiomysql.OperationalError)
        errors.append(aiomysql.InterfaceError)
    except ImportError:
        pass
    return tuple(errors)


@dataclass
class DBConfig:
    """Connection settings for the shared pool (Article III — no hardcoded credentials).

    ``pool_recycle`` discards an idle connection older than this many seconds at acquire time — the
    age-based half of failover resilience (Article IX §7). ``ping_before_use`` adds an explicit
    liveness check so a connection killed server-side (e.g. by a failover) is caught even before its
    recycle age is reached.
    """

    host: str
    port: int = 3306
    user: str = ""
    password: str = ""
    db: Optional[str] = None
    minsize: int = 1
    maxsize: int = 10
    autocommit: bool = True
    pool_recycle: int = 3600
    ping_before_use: bool = True


class DBPool:
    """A shared async MySQL pool with parameterized-query helpers (Article IX §1, §7).

    Lifecycle is tied to the framework (``start``/``stop``, Article II §4). Every helper takes a
    parameter sequence and passes it to the driver — string-formatted SQL is never built here. An
    already-constructed ``pool`` may be injected (for tests); otherwise :meth:`start` creates an
    ``aiomysql`` pool.

    **Failover resilience (§7):** every query runs through
    :func:`~plugshub_common.resilience.retry_async` (reused, not reinvented — Article XVII §2) with
    a small, bounded policy that retries *only* connection-level/transient errors (see
    :func:`_default_transient_errors`) on a freshly-acquired connection. Before each attempt,
    :meth:`_check_liveness` pings the acquired connection (when ``ping_before_use`` is enabled) so a
    connection left dead by a failover is discarded rather than handed to the caller. Non-transient
    errors (syntax, constraint violations, ...) propagate on the first attempt, untouched.
    """

    def __init__(
        self,
        config: Optional[DBConfig] = None,
        pool: Any = None,
        *,
        retry_policy: Optional[RetryPolicy] = None,
        transient_errors: Optional[Tuple[Type[BaseException], ...]] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._pool = pool
        self._ping_before_use = config.ping_before_use if config is not None else True
        self._transient_errors = transient_errors or _default_transient_errors()
        base_policy = retry_policy or RetryPolicy(max_attempts=3, base_delay=0.02, max_delay=0.2)
        # The pool owns which errors are retryable, regardless of what a caller-supplied policy
        # sets, so a tuned retry/backoff shape can never accidentally retry a non-transient error.
        self._retry_policy = replace(base_policy, retry_on=self._transient_errors)
        self._sleep = sleep

    async def start(self) -> None:
        """Create the underlying ``aiomysql`` pool (idempotent). Requires the ``db`` extra."""
        if self._pool is not None:
            return
        if self._config is None:
            raise ValueError("DBPool requires a DBConfig to start")
        try:
            import aiomysql  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via error path only
            raise RuntimeError(
                "aiomysql is required for plugshub_common.db; install plugshub-common[db]"
            ) from exc
        cfg = self._config
        self._pool = await aiomysql.create_pool(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            db=cfg.db,
            minsize=cfg.minsize,
            maxsize=cfg.maxsize,
            autocommit=cfg.autocommit,
            pool_recycle=cfg.pool_recycle,
        )

    async def stop(self) -> None:
        """Close the pool cleanly on shutdown (Article XII §6)."""
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    def _require_pool(self) -> Any:
        if self._pool is None:
            raise DependencyUnavailableError("database pool is not started")
        return self._pool

    async def _check_liveness(self, conn: Any) -> None:
        """Ping-before-use: a failed ping means a stale/dead connection (Article IX §7).

        Only runs when the connection exposes ``ping()`` (``aiomysql`` connections do) and
        ``ping_before_use`` is enabled. A failed ping raises (a transient error) so this connection
        is discarded and :func:`~plugshub_common.resilience.retry_async` retries on a fresh one.
        """
        if not self._ping_before_use:
            return
        ping = getattr(conn, "ping", None)
        if callable(ping):
            await ping(reconnect=True)

    async def execute(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> int:
        """Run a write/DDL-free statement with parameters; return affected row count (§1, §7)."""
        pool = self._require_pool()

        async def _attempt() -> int:
            async with pool.acquire() as conn:
                await self._check_liveness(conn)
                async with conn.cursor() as cur:
                    if schema:
                        await cur.execute("USE `{}`".format(schema))
                    await cur.execute(query, tuple(params or ()))
                    return cur.rowcount

        return await retry_async(_attempt, self._retry_policy, sleep=self._sleep)

    async def fetch_all(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> List[Tuple[Any, ...]]:
        """Run a parameterized query and return all rows (§1, §7)."""
        pool = self._require_pool()

        async def _attempt() -> List[Tuple[Any, ...]]:
            async with pool.acquire() as conn:
                await self._check_liveness(conn)
                async with conn.cursor() as cur:
                    if schema:
                        await cur.execute("USE `{}`".format(schema))
                    await cur.execute(query, tuple(params or ()))
                    return list(await cur.fetchall())

        return await retry_async(_attempt, self._retry_policy, sleep=self._sleep)

    async def fetch_one(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> Optional[Tuple[Any, ...]]:
        """Run a parameterized query and return the first row or ``None`` (§1, §7)."""
        pool = self._require_pool()

        async def _attempt() -> Optional[Tuple[Any, ...]]:
            async with pool.acquire() as conn:
                await self._check_liveness(conn)
                async with conn.cursor() as cur:
                    if schema:
                        await cur.execute("USE `{}`".format(schema))
                    await cur.execute(query, tuple(params or ()))
                    return await cur.fetchone()

        return await retry_async(_attempt, self._retry_policy, sleep=self._sleep)


# The schema-name prefix for a tenant database (Article I §1 — tenant-owned assets keep the prefix).
_TENANT_PREFIX = "tenant"


@dataclass
class TenantResolver:
    """Per-request tenant → schema resolver with auto-discovery (Article IX §2/§6).

    Discovers the authoritative set of live tenant schemas (``SHOW DATABASES LIKE 'tenant%'``),
    caches it, and refreshes on a short interval so a newly-provisioned tenant is picked up without
    a redeploy. :meth:`resolve` validates via the shared validator (fail-closed, no fallback schema)
    and returns the concrete schema name.

    ``discover`` is injectable for tests; by default it queries the supplied :class:`DBPool`.
    """

    pool: Optional[DBPool] = None
    refresh_interval: float = 300.0
    discover: Optional[Callable[[], Awaitable[Set[str]]]] = None
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    _cache: Set[str] = field(default_factory=set, init=False)
    _loaded_at: float = field(default=0.0, init=False)
    _loaded: bool = field(default=False, init=False)

    async def _discover_default(self) -> Set[str]:
        if self.pool is None:
            raise ValueError("TenantResolver needs a pool or a discover callable")
        rows = await self.pool.fetch_all("SHOW DATABASES LIKE %s", (_TENANT_PREFIX + "%",))
        names: Set[str] = set()
        for row in rows:
            name = str(row[0])
            names.add(name[len(_TENANT_PREFIX):] if name.startswith(_TENANT_PREFIX) else name)
        return names

    async def get_tenants(self, force: bool = False) -> Set[str]:
        """Return the cached authoritative set, refreshing when stale (Article IX §6)."""
        now = self._clock()
        if force or not self._loaded or (now - self._loaded_at) >= self.refresh_interval:
            discover = self.discover or self._discover_default
            self._cache = await discover()
            self._loaded_at = now
            self._loaded = True
        return self._cache

    async def resolve(self, tenant_id: str) -> str:
        """Validate ``tenant_id`` against the live set and return its schema name (fail-closed).

        Raises ``ValueError`` (via the shared validator) for an unknown/empty/dangerous tenant —
        there is no fallback to a shared/central schema (Article IX §6).
        """
        tenants = await self.get_tenants()
        validate_tenant(tenant_id, tenants, raise_on_invalid=True)
        prefixed = tenant_id.startswith(_TENANT_PREFIX)
        bare = tenant_id[len(_TENANT_PREFIX):] if prefixed else tenant_id
        return _TENANT_PREFIX + bare
