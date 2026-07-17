import pytest

from plugshub_common.clients import ServiceClient, TransientHTTPError, build_internal_headers
from plugshub_common.logging import clear_request_context, set_request_context
from plugshub_common.resilience import RetryPolicy
from plugshub_common.service_auth import (
    INTERNAL_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    TENANT_ID_HEADER,
)


def test_build_internal_headers_from_context():
    clear_request_context()
    set_request_context(request_id="req-1", tenant_id="t-1")
    headers = build_internal_headers("token-123")
    assert headers[REQUEST_ID_HEADER] == "req-1"
    assert headers[TENANT_ID_HEADER] == "t-1"
    assert headers[INTERNAL_TOKEN_HEADER] == "token-123"
    assert "Authorization" not in headers
    clear_request_context()


def test_build_internal_headers_generates_request_id():
    clear_request_context()
    headers = build_internal_headers("tok")
    assert headers[REQUEST_ID_HEADER]  # generated
    assert TENANT_ID_HEADER not in headers  # no tenant in context


class _FakeResp:
    def __init__(self, status, body="{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self._responses.pop(0)


async def test_request_attaches_headers_and_returns_body():
    session = _FakeSession([_FakeResp(200, '{"data": {"ok": true}}')])
    client = ServiceClient("http://svc", "tok", session=session)
    resp = await client.get("/api/v1/ping", tenant_id="t9", request_id="r9")
    assert resp.status == 200
    assert resp.json() == {"data": {"ok": True}}
    sent = session.calls[0]["headers"]
    assert sent[INTERNAL_TOKEN_HEADER] == "tok"
    assert sent[TENANT_ID_HEADER] == "t9"
    assert sent[REQUEST_ID_HEADER] == "r9"
    assert session.calls[0]["url"] == "http://svc/api/v1/ping"


async def test_5xx_retries_then_succeeds():
    session = _FakeSession([_FakeResp(503), _FakeResp(200, "{}")])
    policy = RetryPolicy(max_attempts=3, jitter=False, base_delay=0)
    client = ServiceClient("http://svc", "tok", session=session, retry_policy=policy)
    resp = await client.post("/x")
    assert resp.status == 200
    assert len(session.calls) == 2


async def test_5xx_exhausts_and_raises_transient():
    session = _FakeSession([_FakeResp(500), _FakeResp(500)])
    policy = RetryPolicy(max_attempts=2, jitter=False, base_delay=0)
    client = ServiceClient("http://svc", "tok", session=session, retry_policy=policy)
    with pytest.raises(TransientHTTPError):
        await client.get("/x")


async def test_4xx_not_retried():
    session = _FakeSession([_FakeResp(404, "{}")])
    client = ServiceClient("http://svc", "tok", session=session)
    resp = await client.get("/missing")
    assert resp.status == 404
    assert len(session.calls) == 1


async def test_5xx_not_trip_when_disabled():
    session = _FakeSession([_FakeResp(503, '{"error":"x"}')])
    client = ServiceClient(
        "http://svc", "tok", session=session, trip_on_5xx=False
    )
    resp = await client.get("/x")
    assert resp.status == 503
    assert len(session.calls) == 1
