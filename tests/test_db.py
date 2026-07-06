import pytest

from plugshub_common.db import DBPool, TenantResolver
from plugshub_common.resilience import RetryPolicy

_UUID = "239cca94-9c80-4bcd-915e-445f35b6a260"


class _FakeCursor:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log
        self.rowcount = len(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, query, params=None):
        self._log.append((query, params))

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def cursor(self):
        return _FakeCursor(self._rows, self._log)


class _FakePool:
    def __init__(self, rows):
        self.rows = rows
        self.log = []

    def acquire(self):
        return _FakeConn(self.rows, self.log)


async def test_fetch_all_is_parameterized():
    pool_backend = _FakePool([(1, "a"), (2, "b")])
    db = DBPool(pool=pool_backend)
    rows = await db.fetch_all("SELECT id, name FROM t WHERE x = %s", (5,))
    assert rows == [(1, "a"), (2, "b")]
    assert pool_backend.log[-1] == ("SELECT id, name FROM t WHERE x = %s", (5,))


async def test_execute_returns_rowcount():
    pool_backend = _FakePool([(1,)])
    db = DBPool(pool=pool_backend)
    n = await db.execute("UPDATE t SET x = %s WHERE id = %s", (1, 2))
    assert n == 1


async def test_fetch_one():
    db = DBPool(pool=_FakePool([(42,)]))
    assert await db.fetch_one("SELECT 1") == (42,)


async def test_pool_not_started_raises():
    from plugshub_common.errors import DependencyUnavailableError

    db = DBPool()
    with pytest.raises(DependencyUnavailableError):
        await db.fetch_all("SELECT 1")


async def test_tenant_resolver_discovers_and_validates():
    calls = {"n": 0}

    async def discover():
        calls["n"] += 1
        return {_UUID}

    resolver = TenantResolver(discover=discover, refresh_interval=1000)
    schema = await resolver.resolve(_UUID)
    assert schema == "tenant" + _UUID
    # cached: no second discovery
    await resolver.resolve(_UUID)
    assert calls["n"] == 1


async def test_tenant_resolver_fail_closed_on_unknown():
    async def discover():
        return {_UUID}

    resolver = TenantResolver(discover=discover)
    with pytest.raises(ValueError):
        await resolver.resolve("11111111-1111-1111-1111-111111111111")


async def test_tenant_resolver_refreshes():
    class Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

    clock = Clock()
    state = {"set": {_UUID}}

    async def discover():
        return set(state["set"])

    resolver = TenantResolver(discover=discover, refresh_interval=100, _clock=clock)
    await resolver.get_tenants()
    new = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state["set"] = {new}
    clock.t = 101
    tenants = await resolver.get_tenants()
    assert new in tenants


async def test_tenant_resolver_discover_from_pool():
    pool_backend = _FakePool([("tenant" + _UUID,), ("mysql",)])
    db = DBPool(pool=pool_backend)
    resolver = TenantResolver(pool=db)
    schema = await resolver.resolve(_UUID)
    assert schema == "tenant" + _UUID


# --- Failover resilience (Article IX §7) -----------------------------------------------------
#
# A no-wait retry policy keeps these tests fast and deterministic (no real MySQL server needed).
_NO_WAIT = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0, jitter=False)


class _SeqCursor:
    """A cursor whose ``execute`` optionally raises once, then returns fixed rows."""

    def __init__(self, rows, exec_error=None):
        self._rows = rows
        self._exec_error = exec_error
        self.rowcount = len(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, query, params=None):
        if self._exec_error is not None:
            raise self._exec_error

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _SeqConn:
    """A fake connection with an optional failing ``ping`` and/or failing query execution."""

    def __init__(self, *, rows=None, ping_error=None, exec_error=None):
        self._rows = rows if rows is not None else [(1,)]
        self._ping_error = ping_error
        self._exec_error = exec_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def ping(self, reconnect=True):
        if self._ping_error is not None:
            raise self._ping_error

    def cursor(self):
        return _SeqCursor(self._rows, self._exec_error)


class _CtxWrap:
    """Wraps a plain object so ``pool.acquire()`` looks like an async context manager."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _SeqPool:
    """A fake pool that hands out connections from a fixed sequence, one per ``acquire()`` call."""

    def __init__(self, conns):
        self._conns = list(conns)
        self.acquire_count = 0

    def acquire(self):
        self.acquire_count += 1
        index = min(self.acquire_count - 1, len(self._conns) - 1)
        return _CtxWrap(self._conns[index])


async def test_stale_connection_is_discarded_and_replaced():
    """A dead connection fails its liveness ping and is discarded; a fresh one serves the query."""
    dead = _SeqConn(ping_error=ConnectionResetError("gone away"))
    fresh = _SeqConn(rows=[(1,)])
    pool_backend = _SeqPool([dead, fresh])
    db = DBPool(pool=pool_backend, retry_policy=_NO_WAIT)

    result = await db.fetch_one("SELECT 1")

    assert result == (1,)
    assert pool_backend.acquire_count == 2


async def test_transient_query_error_is_retried_on_fresh_connection():
    """A connection that drops mid-query is retried transparently on a fresh connection."""
    broken = _SeqConn(exec_error=ConnectionResetError("server has gone away"))
    fresh = _SeqConn(rows=[(42,)])
    pool_backend = _SeqPool([broken, fresh])
    db = DBPool(pool=pool_backend, retry_policy=_NO_WAIT)

    result = await db.fetch_one("SELECT 1")

    assert result == (42,)
    assert pool_backend.acquire_count == 2


async def test_non_transient_error_is_not_retried():
    """A non-transient error (e.g. a syntax error) propagates immediately, with no retry."""
    broken = _SeqConn(exec_error=ValueError("you have an error in your SQL syntax"))
    pool_backend = _SeqPool([broken, _SeqConn()])
    db = DBPool(pool=pool_backend, retry_policy=_NO_WAIT)

    with pytest.raises(ValueError):
        await db.fetch_one("SELECT bad syntax")

    assert pool_backend.acquire_count == 1


async def test_execute_and_fetch_all_also_retry_transient_errors():
    """The retry-on-transient-error behavior applies to every query helper, not just fetch_one."""
    broken_exec = _SeqConn(exec_error=ConnectionResetError("gone away"))
    fresh_exec = _SeqConn(rows=[])
    exec_pool = _SeqPool([broken_exec, fresh_exec])
    db_exec = DBPool(pool=exec_pool, retry_policy=_NO_WAIT)
    assert await db_exec.execute("UPDATE t SET x = 1") == 0
    assert exec_pool.acquire_count == 2

    broken_fetch = _SeqConn(exec_error=ConnectionResetError("gone away"))
    fresh_fetch = _SeqConn(rows=[(1, "a"), (2, "b")])
    fetch_pool = _SeqPool([broken_fetch, fresh_fetch])
    db_fetch = DBPool(pool=fetch_pool, retry_policy=_NO_WAIT)
    assert await db_fetch.fetch_all("SELECT * FROM t") == [(1, "a"), (2, "b")]
    assert fetch_pool.acquire_count == 2


async def test_retries_are_bounded_then_propagate():
    """Retries are bounded — persistent transient failures eventually propagate, not loop forever.
    """
    always_broken = _SeqConn(exec_error=ConnectionResetError("gone away"))
    pool_backend = _SeqPool([always_broken])
    policy = RetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0, jitter=False)
    db = DBPool(pool=pool_backend, retry_policy=policy)

    with pytest.raises(ConnectionResetError):
        await db.fetch_one("SELECT 1")

    assert pool_backend.acquire_count == 2


async def test_ping_before_use_can_be_disabled():
    """When ``ping_before_use`` is off, a dead-ping connection is used anyway (no liveness check).
    """
    from plugshub_common.db import DBConfig

    conn = _SeqConn(ping_error=ConnectionResetError("would be dead if checked"), rows=[(7,)])
    pool_backend = _SeqPool([conn])
    config = DBConfig(host="localhost", ping_before_use=False)
    db = DBPool(config=config, pool=pool_backend, retry_policy=_NO_WAIT)

    result = await db.fetch_one("SELECT 1")

    assert result == (7,)
    assert pool_backend.acquire_count == 1
