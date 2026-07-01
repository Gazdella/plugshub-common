from plugshub_common.health import liveness, readiness


def test_liveness_standard_shape():
    b = liveness("svc", "1.0.0")
    assert b["status"] == "alive"
    assert set(b) == {"status", "service", "version", "uptime_seconds"}
    assert b["service"] == "svc" and b["version"] == "1.0.0"


def test_readiness_status_semantics():
    body, status = readiness(True, {"db": "connected"})
    assert status == 200 and body == {"ready": True, "checks": {"db": "connected"}}
    body, status = readiness(False, {"db": "disconnected"})
    assert status == 503 and body["ready"] is False
