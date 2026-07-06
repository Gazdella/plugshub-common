import pytest

from plugshub_common.authz import (
    PermissionChecker,
    Principal,
    check_object_ownership,
    has_permission,
    principal_from_claims,
    require_permission,
)
from plugshub_common.errors import ForbiddenError, UnauthorizedError


def test_principal_from_claims_scope_string():
    p = principal_from_claims(
        {"sub": "u1", "tenant_id": "t1", "scope": "billing.read billing.write"}
    )
    assert p.id == "u1" and p.tenant_id == "t1"
    assert p.has("billing.read") and p.has("billing.write")


def test_principal_requires_subject():
    with pytest.raises(UnauthorizedError):
        principal_from_claims({"tenant_id": "t1"})


def test_deny_by_default():
    p = Principal(id="u1", permissions=frozenset({"a.read"}))
    assert has_permission(p, "a.read") is True
    assert has_permission(p, "a.write") is False
    assert has_permission(None, "a.read") is False


def test_require_permission_raises():
    p = Principal(id="u1", permissions=frozenset({"a.read"}))
    assert require_permission(p, "a.read") is p
    with pytest.raises(ForbiddenError):
        require_permission(p, "a.write")
    with pytest.raises(UnauthorizedError):
        require_permission(None, "a.read")


def test_wildcard_grant():
    admin = Principal(id="root", permissions=frozenset({"*"}))
    assert require_permission(admin, "anything.at.all") is admin


def test_object_ownership():
    owner = Principal(id="u1", tenant_id="t1")
    assert check_object_ownership(owner, "u1") is owner
    with pytest.raises(ForbiddenError):
        check_object_ownership(owner, "u2")
    # admin override
    admin = Principal(id="admin", tenant_id="t1", permissions=frozenset({"users.admin"}))
    assert check_object_ownership(admin, "u2", allow_permission="users.admin") is admin


def test_object_ownership_cross_tenant_denied():
    p = Principal(id="u1", tenant_id="t1")
    with pytest.raises(ForbiddenError):
        check_object_ownership(p, "u1", resource_tenant_id="t2")


def test_permission_checker_dependency():
    principal = Principal(id="u1", permissions=frozenset({"billing.write"}))
    checker = PermissionChecker("billing.write", lambda: principal)
    assert checker() is principal
    denied = PermissionChecker("billing.admin", lambda: principal)
    with pytest.raises(ForbiddenError):
        denied()
