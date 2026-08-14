from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugshub_common.errors import NotFoundError, RateLimitedError
from plugshub_common.http_middleware import RedMetrics, new_request_id, setup_http
from plugshub_common.service_auth import (
    INTERNAL_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    build_service_auth_middleware,
)


def _build_app():
    app = FastAPI()
    metrics = RedMetrics()
    setup_http(app, metrics)

    @app.get("/api/v1/ok")
    def ok():
        from plugshub_common.errors import success_envelope

        return success_envelope({"hello": "world"})

    @app.get("/api/v1/missing")
    def missing():
        raise NotFoundError("no such thing")

    @app.get("/api/v1/limited")
    def limited():
        raise RateLimitedError("slow", retry_after=42)

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("leaked internal detail")

    return app, metrics


def test_success_and_request_id_header():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.get("/api/v1/ok")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"hello": "world"}}
    assert resp.headers[REQUEST_ID_HEADER]


def test_incoming_request_id_is_echoed():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.get("/api/v1/ok", headers={REQUEST_ID_HEADER: "req-abc"})
    assert resp.headers[REQUEST_ID_HEADER] == "req-abc"


def test_error_envelope_rendered():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.get("/api/v1/missing")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "common.not_found"
    assert body["error"]["request_id"] == resp.headers[REQUEST_ID_HEADER]


def test_rate_limited_retry_after():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.get("/api/v1/limited")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "42"


def test_unhandled_exception_hidden():
    app, _ = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "common.internal"
    assert "leaked internal detail" not in resp.text


def test_metrics_recorded():
    app, metrics = _build_app()
    client = TestClient(app)
    client.get("/api/v1/ok")
    client.get("/api/v1/missing")
    assert metrics.requests >= 2


def test_service_auth_middleware_fail_closed():
    app = FastAPI()
    setup_http(app)
    app.add_middleware(build_service_auth_middleware("expected-token"))

    @app.get("/api/v1/private")
    def private():
        from plugshub_common.errors import success_envelope

        return success_envelope({"ok": True})

    @app.get("/health")
    def health():
        return {"status": "alive"}

    client = TestClient(app, raise_server_exceptions=False)
    # no token -> 401
    assert client.get("/api/v1/private").status_code == 401
    # valid token -> 200
    ok = client.get("/api/v1/private", headers={INTERNAL_TOKEN_HEADER: "expected-token"})
    assert ok.status_code == 200
    # health exempt
    assert client.get("/health").status_code == 200


def test_new_request_id_unique():
    assert new_request_id() != new_request_id()


def test_error_tracking_reports_5xx_not_4xx(caplog):
    """The global handler must put a 500's traceback in the log stream Vector ships to Better Stack.

    The envelope it returns is deliberately opaque (Article V §2), so this ERROR record is the only
    server-side trace of the fault — and a 404 must not produce one (Article XVI §5).
    """
    import logging

    from plugshub_common.observability import reset_error_tracking

    reset_error_tracking()
    try:
        app, _ = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.ERROR, logger="plugshub.server_fault"):
            client.get("/api/v1/missing")  # 404 -> not reported
            client.get("/api/v1/boom")     # 500 -> reported

        records = [r for r in caplog.records if r.name == "plugshub.server_fault"]
        assert len(records) == 1
        assert records[0].exc_info is not None
    finally:
        reset_error_tracking()
