"""Shared async DB pool + fail-closed tenant resolver (SaaS Constitution Article IX).

Database access goes through the **shared connection pool** (per-call connections are forbidden,
§1), queries are **parameterized** (§1), and no ORM is introduced (§1). Multi-tenancy is one
database per tenant; the tenant is resolved per request and **validated by the shared validator**
(:func:`plugshub_common.tenant.validate_tenant`) against an **auto-discovered** authoritative set
before it ever forms a schema name (§2, §6). Validation **fails closed** with no fallback to a
shared schema.

``aiomysql`` is imported lazily (the ``db`` extra), and the tenant resolver's discovery function is
injectable, so this module imports and unit-tests without a live database.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Set, Tuple

from plugshub_common.errors import DependencyUnavailableError
from plugshub_common.tenant import validate_tenant

__all__ = ["DBConfig", "DBPool", "TenantResolver"]


@dataclass
class DBConfig:
    """Connection settings for the shared pool (Article III — no hardcoded credentials)."""

    host: str
    port: int = 3306
    user: str = ""
    password: str = ""
    db: Optional[str] = None
    minsize: int = 1
    maxsize: int = 10
    autocommit: bool = True
    pool_recycle: int = 3600


class DBPool:
    """A shared async MySQL pool with parameterized-query helpers (Article IX §1).

    Lifecycle is tied to the framework (``start``/``stop``, Article II §4). Every helper takes a
    parameter sequence and passes it to the driver — string-formatted SQL is never built here. An
    already-constructed ``pool`` may be injected (for tests); otherwise :meth:`start` creates an
    ``aiomysql`` pool.
    """

    def __init__(self, config: Optional[DBConfig] = None, pool: Any = None) -> None:
        self._config = config
        self._pool = pool

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

    async def execute(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> int:
        """Run a write/DDL-free statement with parameters; return affected row count (§1)."""
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if schema:
                    await cur.execute("USE `{}`".format(schema))
                await cur.execute(query, tuple(params or ()))
                return cur.rowcount

    async def fetch_all(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> List[Tuple[Any, ...]]:
        """Run a parameterized query and return all rows (§1)."""
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if schema:
                    await cur.execute("USE `{}`".format(schema))
                await cur.execute(query, tuple(params or ()))
                return list(await cur.fetchall())

    async def fetch_one(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        schema: Optional[str] = None,
    ) -> Optional[Tuple[Any, ...]]:
        """Run a parameterized query and return the first row or ``None`` (§1)."""
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if schema:
                    await cur.execute("USE `{}`".format(schema))
                await cur.execute(query, tuple(params or ()))
                return await cur.fetchone()


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
