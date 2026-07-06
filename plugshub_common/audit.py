"""Append-only audit trail (SaaS Constitution Article XX).

Operational logs (Article IV) deliberately exclude sensitive detail; security-relevant actions need
the opposite — a complete, durable, tamper-evident record. This module writes that trail. Each
record carries the mandatory shape (§2): actor (id + type), action, target, tenant, UTC timestamp,
``request_id``, and outcome. The trail is **append-only** (§3): sinks expose write + read, never
edit or delete.

Two sinks ship here:

* :class:`LoggingAuditSink` — emits one JSON line per record to a **dedicated** ``plugshub.audit``
  logger, kept separate from operational logs (§3). Point that logger at durable, append-only
  storage in production (the production backend — e.g. an append-only table or log store — is wired
  in by the service).
* :class:`InMemoryAuditSink` — a correct, unit-testable default with no external dependency.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from plugshub_common.canonical import to_rfc3339
from plugshub_common.logging import current_request_id, current_tenant_id

__all__ = [
    "AuditRecord",
    "AuditSink",
    "InMemoryAuditSink",
    "LoggingAuditSink",
    "AuditWriter",
    "OUTCOME_SUCCESS",
    "OUTCOME_FAILURE",
]

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"


@dataclass(frozen=True)
class AuditRecord:
    """A single audit entry with the mandatory Article XX §2 shape."""

    actor_id: str
    actor_type: str
    action: str
    target: str
    tenant_id: Optional[str]
    timestamp: str
    request_id: Optional[str]
    outcome: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the canonical record dict (omitting empty ``details``)."""
        data: Dict[str, Any] = {
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "action": self.action,
            "target": self.target,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "outcome": self.outcome,
        }
        if self.details:
            data["details"] = self.details
        return data


class AuditSink(ABC):
    """Where audit records are durably written. Append-only — no update/delete (Article XX §3)."""

    @abstractmethod
    def write(self, record: AuditRecord) -> None:
        """Persist one record. MUST NOT modify or remove any prior record."""
        raise NotImplementedError


class InMemoryAuditSink(AuditSink):
    """An append-only in-memory sink — correct default for tests and single-process tools.

    Records are readable but the exposed collection is a copy, so callers cannot mutate the trail
    (Article XX §3). Production services point :class:`LoggingAuditSink` (or their own sink) at
    durable storage.
    """

    def __init__(self) -> None:
        self._records: List[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self._records.append(record)

    @property
    def records(self) -> Tuple[AuditRecord, ...]:
        """An immutable snapshot of the trail (read access, Article XX §4)."""
        return tuple(self._records)


class LoggingAuditSink(AuditSink):
    """Emit each record as a JSON line to a dedicated audit logger (Article XX §3).

    Uses its own logger (default ``plugshub.audit``), separate from operational logs. In production,
    route this logger to append-only, retained storage (Article XXI).
    """

    def __init__(self, logger_name: str = "plugshub.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    def write(self, record: AuditRecord) -> None:
        self._logger.info(json.dumps(record.to_dict(), default=str, ensure_ascii=False))


class AuditWriter:
    """Builds and writes audit records, filling timestamp/context automatically (Article XX)."""

    def __init__(self, sink: Optional[AuditSink] = None) -> None:
        self.sink: AuditSink = sink or InMemoryAuditSink()

    def record(
        self,
        *,
        actor_id: str,
        actor_type: str,
        action: str,
        target: str,
        outcome: str = OUTCOME_SUCCESS,
        tenant_id: Optional[str] = None,
        request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        """Write one audit record, defaulting ``request_id``/``tenant_id`` from context.

        ``timestamp`` is always a fresh UTC RFC-3339 instant (Article XXIV §1). Returns the written
        record.
        """
        entry = AuditRecord(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            target=target,
            tenant_id=tenant_id if tenant_id is not None else current_tenant_id(),
            timestamp=to_rfc3339(),
            request_id=request_id if request_id is not None else current_request_id(),
            outcome=outcome,
            details=details,
        )
        self.sink.write(entry)
        return entry
