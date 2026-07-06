from plugshub_common.featureflags import (
    EnvFeatureFlags,
    InMemoryFeatureFlags,
    RedisFeatureFlags,
)


def test_in_memory_default_and_set():
    flags = InMemoryFeatureFlags({"a": True})
    assert flags.is_enabled("a") is True
    assert flags.is_enabled("missing") is False
    assert flags.is_enabled("missing", default=True) is True
    flags.enable("b")
    assert flags.is_enabled("b") is True
    flags.disable("b")
    assert flags.is_enabled("b") is False


def test_per_tenant_override():
    flags = InMemoryFeatureFlags({"x": False})
    flags.set("x", True, tenant_id="t1")
    assert flags.is_enabled("x", tenant_id="t1") is True
    assert flags.is_enabled("x", tenant_id="t2") is False
    assert flags.is_enabled("x") is False


def test_env_flags(monkeypatch):
    flags = EnvFeatureFlags()
    monkeypatch.setenv("PLUGSHUB_FLAG_FEATURE_NEW_BILLING", "true")
    assert flags.is_enabled("feature.new_billing") is True
    monkeypatch.setenv("PLUGSHUB_FLAG_FEATURE_NEW_BILLING", "off")
    assert flags.is_enabled("feature.new_billing") is False
    assert flags.is_enabled("feature.absent", default=True) is True


class _FakeRedis:
    def __init__(self, data):
        self.data = data

    def get(self, key):
        return self.data.get(key)


def test_redis_flags_precedence_and_failsafe():
    client = _FakeRedis({"flag:on": "1", "flag:t1:on": "0"})
    flags = RedisFeatureFlags(client)
    assert flags.is_enabled("on") is True
    assert flags.is_enabled("on", tenant_id="t1") is False  # per-tenant wins
    assert flags.is_enabled("absent", default=True) is True


def test_redis_flags_never_raise():
    class Boom:
        def get(self, key):
            raise RuntimeError("down")

    flags = RedisFeatureFlags(Boom())
    assert flags.is_enabled("x", default=False) is False
    assert flags.is_enabled("x", default=True) is True
