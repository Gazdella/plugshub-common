import pytest

from plugshub_common.errors import (
    InvalidBodyError,
    NotFoundError,
    PlugsHubError,
    RateLimitedError,
    error_envelope,
    error_from_exception,
    success_envelope,
)


def test_success_envelope_shapes():
    assert success_envelope({"id": 1}) == {"data": {"id": 1}}
    body = success_envelope([{"id": 1}], meta={"page": 1})
    assert body == {"data": [{"id": 1}], "meta": {"page": 1}}
    assert "success" not in body


def test_error_envelope_omits_empty_details():
    env = error_envelope("common.not_found", "nope", "req-1")
    assert env == {"error": {"code": "common.not_found", "message": "nope", "request_id": "req-1"}}
    env2 = error_envelope("x.y", "m", "r", {"field": "bad"})
    assert env2["error"]["details"] == {"field": "bad"}


def test_exception_carries_code_and_status():
    exc = InvalidBodyError("empty")
    assert exc.code == "common.invalid_body" and exc.http_status == 400
    assert exc.to_envelope("req-2")["error"]["code"] == "common.invalid_body"


def test_namespaced_code_override():
    exc = PlugsHubError("boom", code="billing.insufficient_funds", http_status=402)
    assert exc.code == "billing.insufficient_funds" and exc.http_status == 402


def test_rate_limited_retry_after():
    exc = RateLimitedError("slow down", retry_after=30)
    assert exc.http_status == 429 and exc.retry_after == 30


def test_error_from_exception_hides_internals():
    env = error_from_exception(ValueError("secret detail"), "req-3")
    assert env["error"]["code"] == "common.internal"
    assert "secret detail" not in env["error"]["message"]
    known = error_from_exception(NotFoundError("gone"), "req-4")
    assert known["error"]["code"] == "common.not_found"


def test_is_exception():
    with pytest.raises(PlugsHubError):
        raise NotFoundError("x")
