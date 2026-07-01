"""Standard tenant-id validator (SaaS Constitution Article IX §2/§6).

The single source of truth for fail-closed tenant validation before a tenant id is used to form a
schema name. Membership against the auto-discovered authoritative set is the primary check; strict
regex, length, and dangerous-character scans are defense-in-depth **on top of** it (never instead).
The service owns discovery of the live set (``SHOW DATABASES LIKE 'tenant%'``) and passes it in.

Reference: auth-service ``utils/tenant_whitelist``.
"""

import logging
import re
from typing import Optional, Set

LOGGER = logging.getLogger("plugshub_common.tenant")

# Accepted forms: the tenant-prefixed schema name, or a bare UUID.
_PREFIXED_RE = re.compile(r"^tenant[a-zA-Z0-9\-]+$")
_UUID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE
)
_DANGEROUS = (
    "`", "'", '"', ";", "--", "/*", "*/",
    "UNION", "SELECT", "DROP", "INSERT", "UPDATE", "DELETE", "WHERE", "FROM", "TABLE", "DATABASE",
)


def validate_tenant(
    tenant_id: str, tenants: Optional[Set[str]], raise_on_invalid: bool = True
) -> bool:
    """Validate ``tenant_id`` before it forms a schema name (Article IX §2/§6).

    ``tenants`` is the auto-discovered authoritative set of bare tenant ids (or ``None`` during the
    brief pre-load window → regex-only). Layers, in order: (1) fail-closed membership, (2) strict
    regex, (3) length 8–60, (4) dangerous SQL char/keyword scan. Returns ``True``/``False`` when
    ``raise_on_invalid`` is false, else raises ``ValueError``.
    """
    if not tenant_id:
        if raise_on_invalid:
            raise ValueError("tenant_id is required")
        return False

    # Layer 1 — fail-closed membership (strongest). Accept the bare id or the tenant-prefixed form.
    if tenants is not None:
        bare = tenant_id[len("tenant") :] if tenant_id.startswith("tenant") else tenant_id
        if bare not in tenants and tenant_id not in tenants:
            LOGGER.error("SECURITY: Tenant ID not in whitelist - REJECTED")
            if raise_on_invalid:
                raise ValueError("Invalid tenant_id: not in whitelist")
            return False

    # Layer 2 — strict regex (tenant-prefixed or plain UUID).
    if not _PREFIXED_RE.match(tenant_id) and not _UUID_RE.match(tenant_id):
        LOGGER.error("SECURITY: Tenant ID failed regex validation - REJECTED")
        if raise_on_invalid:
            raise ValueError("Invalid tenant_id format")
        return False

    # Layer 3 — length.
    if len(tenant_id) < 8 or len(tenant_id) > 60:
        LOGGER.error("SECURITY: Tenant ID length %d out of range - REJECTED", len(tenant_id))
        if raise_on_invalid:
            raise ValueError("Invalid tenant_id length")
        return False

    # Layer 4 — dangerous SQL characters/keywords (defense-in-depth).
    up = tenant_id.upper()
    for pattern in _DANGEROUS:
        if pattern in up:
            LOGGER.error("SECURITY: Dangerous SQL pattern in tenant_id - REJECTED")
            if raise_on_invalid:
                raise ValueError("Invalid tenant_id: contains dangerous pattern")
            return False

    return True
