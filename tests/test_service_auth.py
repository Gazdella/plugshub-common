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
