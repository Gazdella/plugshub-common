import pytest

from plugshub_common.db import DBPool, TenantResolver

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
