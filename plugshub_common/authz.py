"""Authorization — deny-by-default permission enforcement (SaaS Constitution Article XIX).

Authentication proves *who* the caller is; authorization decides *what they may do* — separate,
both mandatory. This module enforces:

* **Explicit permission per endpoint** (§1) — ``require_permission`` / :class:`PermissionChecker`.
* **Deny-by-default** (§2) — an action with no matching grant is refused; authorization is evaluated
  server-side from the **verified** principal's claims, never a client-supplied role/``is_admin``.
* **Object-level checks** (§3) — :func:`check_object_ownership`: "the row exists" is not "the caller
  may touch it" (reinforces Article XVI §7, IX §5).

Framework-agnostic. A :class:`PermissionChecker` is directly usable as a FastAPI dependency when the
service supplies a resolver that returns the verified :class:`Principal`.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, FrozenSet, Mapping, Optional

from plugshub_common.errors import ForbiddenError, UnauthorizedError

__all__ = [
    "Principal",
    "principal_from_claims",
    "has_permission",
    "require_permission",
    "check_object_ownership",
    "PermissionChecker",
]


@dataclass(frozen=True)
class Principal:
    """A verified caller (Article XIX §2). Never construct from unverified/client-supplied data.

    ``principal_type`` is ``"user"`` (signed JWT) or ``"service"`` (D-2 service credential).
    ``permissions`` and ``roles`` come from *verified* claims. A ``"*"`` permission denotes a
    super-grant (use sparingly, e.g. platform admin).
    """

    id: str
    principal_type: str = "user"
    tenant_id: Optional[str] = None
    roles: FrozenSet[str] = field(default_factory=frozenset)
    permissions: FrozenSet[str] = field(default_factory=frozenset)
    claims: Mapping[str, Any] = field(default_factory=dict)

    def has(self, permission: str) -> bool:
        """Whether this principal holds ``permission`` (or a wildcard grant)."""
        return "*" in self.permissions or permission in self.permissions


def _as_frozenset(value: Any) -> FrozenSet[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    return frozenset(str(v) for v in value)


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Build a :class:`Principal` from already-verified token claims (Article XIX §2).

    Reads ``sub``/``id`` (subject), ``type``, ``tenant_id``, ``roles``, and ``permissions``/
    ``scope``/``scopes``. The caller MUST have verified the token signature first — this function
    does not trust anything by itself; it only structures verified data.
    """
    subject = claims.get("sub") or claims.get("id")
    if not subject:
        raise UnauthorizedError("token has no subject claim")
    perms = claims.get("permissions")
    if perms is None:
        scope = claims.get("scope") or claims.get("scopes")
        # OAuth-style space-delimited scope string, or a list.
        perms = scope.split() if isinstance(scope, str) else scope
    return Principal(
        id=str(subject),
        principal_type=str(claims.get("type", "user")),
        tenant_id=claims.get("tenant_id"),
        roles=_as_frozenset(claims.get("roles")),
        permissions=_as_frozenset(perms),
        claims=dict(claims),
    )


def has_permission(principal: Optional[Principal], permission: str) -> bool:
    """Deny-by-default membership check (Article XIX §2). ``None`` principal → ``False``."""
    return principal is not None and principal.has(permission)


def require_permission(principal: Optional[Principal], permission: str) -> Principal:
    """Enforce a permission, raising the shared errors on failure (Article XIX §1/§2).

    No principal → 401 ``common.unauthorized``; principal without the grant → 403
    ``common.forbidden``. Returns the principal on success for convenient chaining.
    """
    if principal is None:
        raise UnauthorizedError("authentication required")
    if not principal.has(permission):
        raise ForbiddenError(
            "permission '{}' required".format(permission),
            details={"required_permission": permission},
        )
    return principal


def check_object_ownership(
    principal: Optional[Principal],
    owner_id: Any,
    *,
    resource_tenant_id: Optional[str] = None,
    allow_permission: Optional[str] = None,
) -> Principal:
    """Object-level authorization: the principal may act on *this* resource (Article XIX §3).

    Passes when the principal owns the resource (``principal.id == owner_id``) or holds an explicit
    override ``allow_permission`` (e.g. an admin grant). When ``resource_tenant_id`` is given, the
    principal's tenant MUST match too (cross-tenant access is refused, Article IX §5). Raises
    401/403 otherwise.
    """
    if principal is None:
        raise UnauthorizedError("authentication required")

    if resource_tenant_id is not None and principal.tenant_id != resource_tenant_id:
        raise ForbiddenError("resource belongs to another tenant")

    if str(principal.id) == str(owner_id):
        return principal
    if allow_permission is not None and principal.has(allow_permission):
        return principal
    raise ForbiddenError("not the owner of this resource")


class PermissionChecker:
    """A reusable, deny-by-default permission dependency (Article XIX §1).

    Construct with the required ``permission`` and a ``principal_resolver`` that returns the
    verified :class:`Principal` (e.g. a FastAPI dependency that decodes the JWT). Calling the
    checker enforces the permission and returns the principal. Directly usable as a dependency::

        require_billing = PermissionChecker("billing.write", get_current_principal)

        @router.post("/api/v1/invoices")
        def create(principal: Principal = Depends(require_billing)): ...
    """

    def __init__(
        self,
        permission: str,
        principal_resolver: Callable[..., Optional[Principal]],
    ) -> None:
        self.permission = permission
        self._resolver = principal_resolver

    def __call__(self, *args: Any, **kwargs: Any) -> Principal:
        principal = self._resolver(*args, **kwargs)
        return require_permission(principal, self.permission)
