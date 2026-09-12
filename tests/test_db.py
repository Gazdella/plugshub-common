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
    """Retries are bounded — persistent transient failures eventually propagate,
    rather than looping forever."""
    always_broken = _SeqConn(exec_error=ConnectionResetError("gone away"))
    pool_backend = _SeqPool([always_broken])
    policy = RetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0, jitter=False)
    db = DBPool(pool=pool_backend, retry_policy=policy)

    with pytest.raises(ConnectionResetError):
        await db.fetch_one("SELECT 1")

    assert pool_backend.acquire_count == 2


async def test_ping_before_use_can_be_disabled():
    """When ``ping_before_use`` is off, a dead-ping connection is used anyway
    (no liveness check)."""
    from plugshub_common.db import DBConfig

    conn = _SeqConn(ping_error=ConnectionResetError("would be dead if checked"), rows=[(7,)])
    pool_backend = _SeqPool([conn])
    config = DBConfig(host="localhost", ping_before_use=False)
    db = DBPool(config=config, pool=pool_backend, retry_policy=_NO_WAIT)

    result = await db.fetch_one("SELECT 1")

    assert result == (7,)
    assert pool_backend.acquire_count == 1


def test_dbconfig_defaults_utf8mb4():
    from plugshub_common.db import DBConfig

    cfg = DBConfig(host="h")
    assert cfg.charset == "utf8mb4"
    assert cfg.use_unicode is True


# --- dead-socket bound (Article IX §7) -------------------------------------------------------
#
# The 2026-09-11 billing hang: a dead-but-ESTABLISHED socket turned a query into an unbounded
# await, because aiomysql has no read timeout. These pin the kernel-level bound that replaces it.


class _FakeSocket:
    def __init__(self, raises=None):
        self.calls = []
        self._raises = raises

    def setsockopt(self, level, option, value):
        if self._raises is not None:
            raise self._raises
        self.calls.append((level, option, value))


class _FakeWriter:
    def __init__(self, sock):
        self._sock = sock

    def get_extra_info(self, name):
        return self._sock if name == "socket" else None


def _conn_with_socket(sock):
    conn = _FakeConn([], [])
    conn._writer = _FakeWriter(sock)
    return conn


def test_socket_timeout_is_applied_in_milliseconds(monkeypatch):
    import socket as _socket

    from plugshub_common import db as db_mod

    # Pinned rather than read from the platform: TCP_USER_TIMEOUT is Linux-only, and the test
    # must assert the same thing on a macOS dev box as in CI.
    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    sock = _FakeSocket()
    pool = DBPool(db_mod.DBConfig(host="h", tcp_user_timeout=30))
    pool._bind_socket_timeout(_conn_with_socket(sock))
    assert sock.calls == [(_socket.IPPROTO_TCP, 18, 30_000)]


def test_socket_timeout_zero_disables(monkeypatch):
    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    sock = _FakeSocket()
    pool = DBPool(db_mod.DBConfig(host="h", tcp_user_timeout=0))
    pool._bind_socket_timeout(_conn_with_socket(sock))
    assert sock.calls == []


def test_socket_timeout_skipped_where_unsupported(monkeypatch):
    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", None)
    sock = _FakeSocket()
    pool = DBPool(db_mod.DBConfig(host="h"))
    pool._bind_socket_timeout(_conn_with_socket(sock))
    assert sock.calls == []


def test_socket_timeout_tolerates_a_non_tcp_socket(monkeypatch):
    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    pool = DBPool(db_mod.DBConfig(host="h"))
    # A unix-socket connection raises here; a query must not fail because of it.
    pool._bind_socket_timeout(_conn_with_socket(_FakeSocket(raises=OSError("not TCP"))))


def test_socket_timeout_no_op_without_a_writer():
    from plugshub_common import db as db_mod

    # An injected pool (tests, and the mock connections above) exposes no transport.
    DBPool(db_mod.DBConfig(host="h"))._bind_socket_timeout(_FakeConn([], []))


@pytest.mark.asyncio
async def test_socket_is_bound_before_the_liveness_ping(monkeypatch):
    """Ordering is the point: ping() is itself an unbounded await on a dead socket, so the
    bound has to be in place before it runs, not after."""
    import socket as _socket

    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    order = []
    sock = _FakeSocket()
    conn = _conn_with_socket(sock)

    async def _ping(reconnect=True):
        order.append("ping")

    conn.ping = _ping

    class _Pool:
        def acquire(self):
            return conn

    real_bind = DBPool._bind_socket_timeout

    def _spy(self, c):
        order.append("bind")
        return real_bind(self, c)

    monkeypatch.setattr(DBPool, "_bind_socket_timeout", _spy)
    await DBPool(pool=_Pool()).fetch_one("SELECT 1")
    assert order == ["bind", "ping"]
    assert sock.calls == [(_socket.IPPROTO_TCP, 18, 30_000)]


def test_public_helper_is_usable_without_dbpool(monkeypatch):
    """The four services that build their own aiomysql pool call this directly."""
    import socket as _socket

    from plugshub_common import db as db_mod
    from plugshub_common.db import bind_socket_timeout

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    sock = _FakeSocket()
    bind_socket_timeout(_conn_with_socket(sock), 15)
    assert sock.calls == [(_socket.IPPROTO_TCP, 18, 15_000)]


# --- BoundPool -------------------------------------------------------------------------------
#
# aiomysql's acquire() result is both awaitable and an async context manager, and the fleet uses
# both shapes (31 `async with` and 1 bare `await` in session-service alone). Both must bind.


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn
        self.exited = False

    def __await__(self):
        async def _go():
            return self._conn

        return _go().__await__()

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        self.exited = True
        return False


class _RecordingPool:
    def __init__(self, conn):
        self._conn = conn
        self.last = None
        self.closed = False
        self.freesize = 3

    def acquire(self):
        self.last = _FakeAcquire(self._conn)
        return self.last

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_bound_pool_binds_on_async_with(monkeypatch):
    import socket as _socket

    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    sock = _FakeSocket()
    pool = db_mod.BoundPool(_RecordingPool(_conn_with_socket(sock)), 25)
    async with pool.acquire() as conn:
        assert conn is not None
    assert sock.calls == [(_socket.IPPROTO_TCP, 18, 25_000)]
    assert pool._pool.last.exited is True


@pytest.mark.asyncio
async def test_bound_pool_binds_on_bare_await(monkeypatch):
    import socket as _socket

    from plugshub_common import db as db_mod

    monkeypatch.setattr(db_mod, "_TCP_USER_TIMEOUT", 18)
    sock = _FakeSocket()
    pool = db_mod.BoundPool(_RecordingPool(_conn_with_socket(sock)), 25)
    conn = await pool.acquire()
    assert conn is not None
    assert sock.calls == [(_socket.IPPROTO_TCP, 18, 25_000)]


def test_bound_pool_proxies_everything_else():
    """close/wait_closed/size/freesize must keep working — /ready reads them."""
    from plugshub_common import db as db_mod

    inner = _RecordingPool(_FakeConn([], []))
    pool = db_mod.BoundPool(inner)
    assert pool.freesize == 3
    pool.close()
    assert inner.closed is True


def test_bound_pool_matches_the_real_aiomysql_acquire_shape():
    """BoundPool delegates to three dunders on aiomysql's acquire result. If a driver upgrade
    drops one, every wrapped pool breaks at runtime — catch it here instead."""
    pytest.importorskip("aiomysql", reason="the `db` extra is optional")
    from aiomysql.utils import _PoolAcquireContextManager as Ctx

    for dunder in ("__await__", "__aenter__", "__aexit__"):
        assert hasattr(Ctx, dunder), dunder
