import pytest

from plugshub_common.errors import UnauthorizedError
from plugshub_common.service_auth import (
    DEFAULT_PUBLIC_PATHS,
    INTERNAL_TOKEN_HEADER,
    is_public_path,
    require_service_token,
    verify_service_token,
)


def test_verify_constant_time_match():
    assert verify_service_token("secret", "secret") is True
    assert verify_service_token("secret", "other") is False


def test_verify_fails_closed_on_empty():
    assert verify_service_token(None, "secret") is False
    assert verify_service_token("", "secret") is False
    assert verify_service_token("secret", "") is False


def test_public_paths_exempt():
    for path in DEFAULT_PUBLIC_PATHS:
        assert is_public_path(path)
    assert is_public_path("/health/")
    assert not is_public_path("/api/v1/orders")


def test_require_service_token_enforced_on_private():
    # public path: no token needed
    require_service_token(None, "secret", "/health")
    # private path with valid token: ok
    require_service_token("secret", "secret", "/api/v1/orders")
    # private path without token: rejected fail-closed
    with pytest.raises(UnauthorizedError):
        require_service_token(None, "secret", "/api/v1/orders")
    with pytest.raises(UnauthorizedError):
        require_service_token("wrong", "secret", "/api/v1/orders")


def test_header_name_is_distinct_from_authorization():
    assert INTERNAL_TOKEN_HEADER == "X-Internal-Service-Token"
    assert INTERNAL_TOKEN_HEADER.lower() != "authorization"


def test_a_non_ascii_token_is_rejected_rather_than_raising():
    """`hmac.compare_digest` raises TypeError on a `str` with a non-ASCII character, and
    Starlette latin-1-decodes header values.

    So comparing the raw strings turned one high byte in `X-Internal-Service-Token` into an
    unhandled TypeError — a 500 that any unauthenticated caller could trigger, on every
    service that uses this. It is a wrong token; it must return False.
    """
    assert verify_service_token("sécret", "secret") is False
    assert verify_service_token("secret", "sécret") is False
    # A lone surrogate is what a latin-1 decode of arbitrary bytes can produce, and plain
    # UTF-8 encoding rejects it too.
    assert verify_service_token("\udce9", "secret") is False


def test_an_identical_non_ascii_token_still_matches():
    """Rejecting non-ASCII outright would be a different bug: a deployment whose shared
    secret contains one would stop authenticating entirely."""
    assert verify_service_token("sécret", "sécret") is True
