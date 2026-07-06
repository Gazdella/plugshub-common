"""Feature flags & kill switches (SaaS Constitution Article XXVI §4).

Risky or newly launched features sit behind a flag so a broken feature can be disabled at runtime
without a redeploy — turning a potential outage into a merely degraded feature (Article XXVI §3/§4).
This module defines the fleet-standard flag interface plus two dependency-free implementations; a
Redis-backed provider (for runtime, cross-instance flips) is included and works against any
duck-typed client.

A *kill switch* is just a flag consulted before running a risky path: ``if not flags.is_enabled(
"feature.x"): return fallback``.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

__all__ = [
    "FeatureFlagProvider",
    "InMemoryFeatureFlags",
    "EnvFeatureFlags",
    "RedisFeatureFlags",
]


class FeatureFlagProvider(ABC):
    """The flag-lookup contract every backend implements (Article XXVI §4).

    ``is_enabled`` is deny-safe: on any lookup error a provider MUST fall back to ``default`` rather
    than raise, so the flag system can never itself cause an outage.
    """

    @abstractmethod
    def is_enabled(
        self,
        flag: str,
        *,
        tenant_id: Optional[str] = None,
        default: bool = False,
    ) -> bool:
        """Whether ``flag`` is on, optionally for ``tenant_id``; returns ``default`` if unknown."""
        raise NotImplementedError


class InMemoryFeatureFlags(FeatureFlagProvider):
    """A correct, unit-testable provider with global + per-tenant overrides.

    Suitable for tests, workers, and single-process tools. For runtime cross-instance flips in a
    multi-instance deployment (Article XXVI §2), use :class:`RedisFeatureFlags` or another shared
    store.
    """

    def __init__(self, flags: Optional[Dict[str, bool]] = None) -> None:
        self._global: Dict[str, bool] = dict(flags or {})
        self._per_tenant: Dict[str, Dict[str, bool]] = {}

    def set(self, flag: str, enabled: bool, *, tenant_id: Optional[str] = None) -> None:
        """Set a flag globally, or scoped to a single tenant when ``tenant_id`` is given."""
        if tenant_id is None:
            self._global[flag] = enabled
        else:
            self._per_tenant.setdefault(tenant_id, {})[flag] = enabled

    def enable(self, flag: str, *, tenant_id: Optional[str] = None) -> None:
        self.set(flag, True, tenant_id=tenant_id)

    def disable(self, flag: str, *, tenant_id: Optional[str] = None) -> None:
        self.set(flag, False, tenant_id=tenant_id)

    def is_enabled(
        self,
        flag: str,
        *,
        tenant_id: Optional[str] = None,
        default: bool = False,
    ) -> bool:
        if tenant_id is not None:
            tenant_flags = self._per_tenant.get(tenant_id)
            if tenant_flags is not None and flag in tenant_flags:
                return tenant_flags[flag]
        return self._global.get(flag, default)


class EnvFeatureFlags(FeatureFlagProvider):
    """Read flags from environment variables (Article III + XXVI §4).

    A flag ``feature.new_billing`` maps to ``<PREFIX>FEATURE_NEW_BILLING`` (dots → underscores,
    upper-cased). Truthy values: ``1/true/yes/on`` (case-insensitive). Static per deploy — use a
    shared store for runtime flips.
    """

    _TRUTHY = frozenset({"1", "true", "yes", "on"})

    def __init__(self, prefix: str = "PLUGSHUB_FLAG_") -> None:
        self.prefix = prefix

    def _env_name(self, flag: str) -> str:
        return self.prefix + flag.replace(".", "_").replace("-", "_").upper()

    def is_enabled(
        self,
        flag: str,
        *,
        tenant_id: Optional[str] = None,
        default: bool = False,
    ) -> bool:
        raw = os.getenv(self._env_name(flag))
        if raw is None:
            return default
        return raw.strip().lower() in self._TRUTHY


class RedisFeatureFlags(FeatureFlagProvider):
    """Cross-instance flags backed by any Redis-like client (Article XXVI §2/§4).

    The client only needs a synchronous ``get(key) -> Optional[bytes|str]``, so a real
    ``redis.Redis`` or a fake both work (keeping this unit-testable without a server). Per-tenant
    keys (``<prefix><tenant>:<flag>``) take precedence over global (``<prefix><flag>``). Any client
    error falls back to ``default`` — the flag store never causes an outage.
    """

    _TRUTHY = frozenset({"1", "true", "yes", "on"})

    def __init__(self, client: Any, prefix: str = "flag:") -> None:
        self._client = client
        self.prefix = prefix

    def _coerce(self, raw: Any) -> Optional[bool]:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        return str(raw).strip().lower() in self._TRUTHY

    def is_enabled(
        self,
        flag: str,
        *,
        tenant_id: Optional[str] = None,
        default: bool = False,
    ) -> bool:
        try:
            if tenant_id is not None:
                scoped = self._coerce(self._client.get(self.prefix + tenant_id + ":" + flag))
                if scoped is not None:
                    return scoped
            value = self._coerce(self._client.get(self.prefix + flag))
        except Exception:  # noqa: BLE001 - a flag lookup must never crash the caller
            return default
        return default if value is None else value
