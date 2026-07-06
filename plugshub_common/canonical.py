"""Canonical data representation — time, money, units (SaaS Constitution Article XXIV).

One representation per concept, fleet-wide, because time/money/units corrupt *silently* when
represented inconsistently. This module is the single source of truth for:

* **Time** — UTC, serialized RFC 3339 / ISO-8601 (``2026-07-06T12:00:00Z``). Naive local times are
  forbidden (§1).
* **Money** — integer *minor units* (e.g. cents) with an explicit ISO-4217 currency code; never a
  binary float (§2).
* **Units** — physical quantities carry their unit in the field name (``energy_kwh``,
  ``duration_seconds``, ``power_kw``); a bare number is a billing incident waiting to happen (§3).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

__all__ = [
    "utc_now",
    "to_rfc3339",
    "parse_rfc3339",
    "ensure_utc",
    "Money",
]


def utc_now() -> datetime:
    """The current instant as a timezone-aware UTC ``datetime`` (Article XXIV §1)."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as timezone-aware UTC. A naive datetime is rejected (Article XXIV §1).

    Naive local times are forbidden — we refuse to guess a timezone. Aware non-UTC times are
    converted to UTC.
    """
    if value.tzinfo is None:
        raise ValueError("naive datetime is forbidden; timestamps MUST be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def to_rfc3339(value: Optional[datetime] = None) -> str:
    """Serialize an instant as RFC 3339 UTC with a trailing ``Z`` (Article XXIV §1).

    ``None`` serializes the current time. Sub-second precision is preserved when present.
    """
    dt = ensure_utc(value) if value is not None else utc_now()
    text = dt.isoformat()
    # ``isoformat`` renders UTC as ``+00:00``; the canonical form uses ``Z``.
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    return text


def parse_rfc3339(text: str) -> datetime:
    """Parse an RFC 3339 / ISO-8601 timestamp into aware UTC (Article XXIV §1).

    Accepts a trailing ``Z`` or an explicit offset; a string without any offset is rejected as a
    forbidden naive time.
    """
    if not text:
        raise ValueError("timestamp is required")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)


@dataclass(frozen=True)
class Money:
    """An exact monetary amount: integer *minor units* + ISO-4217 code (Article XXIV §2).

    ``minor_units`` is the amount in the currency's smallest unit (e.g. 1050 == 10.50 for a
    two-decimal currency). No binary floats ever touch the value. ``currency`` is a 3-letter
    ISO-4217 code, stored upper-case.
    """

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int) or isinstance(self.minor_units, bool):
            raise TypeError("minor_units MUST be an int (integer minor units, never a float)")
        code = self.currency
        if not isinstance(code, str) or len(code) != 3 or not code.isalpha():
            raise ValueError("currency MUST be a 3-letter ISO-4217 code")
        object.__setattr__(self, "currency", code.upper())

    def _check_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(
                "cannot combine {} and {} — currencies differ".format(self.currency, other.currency)
            )

    def add(self, other: "Money") -> "Money":
        """Add two amounts of the same currency (Article XXIV §2)."""
        self._check_same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def subtract(self, other: "Money") -> "Money":
        """Subtract an amount of the same currency (Article XXIV §2)."""
        self._check_same_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def to_dict(self) -> Dict[str, Any]:
        """Wire form: ``{"minor_units": int, "currency": "EUR"}`` — no floats (Article XXIV §2)."""
        return {"minor_units": self.minor_units, "currency": self.currency}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Money":
        """Rebuild from the canonical wire form."""
        return cls(int(data["minor_units"]), str(data["currency"]))
