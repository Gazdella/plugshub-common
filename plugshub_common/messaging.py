"""Reliable messaging: event envelope, transactional outbox, idempotent consumer, DLQ.

Implements the asynchronous half of inter-service communication (SaaS Constitution Article VIII §3):
producers publish **reliably, tied to the state change** (the transactional **outbox** pattern),
consumers are **idempotent**, every queue has a **dead-letter queue**, and events use the **standard
event envelope**.

The primitives here are broker-agnostic and dependency-free: the outbox/DLQ/processed-id stores are
interfaces with correct in-memory defaults, and the actual publish is a callable the service
supplies (Kafka/RabbitMQ/SQS — the production backend — is wired in by the service). This keeps the
patterns unit-testable without a broker while the reliability logic lives here, byte-identical
fleet-wide.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from plugshub_common.canonical import to_rfc3339
from plugshub_common.logging import current_request_id, current_tenant_id

__all__ = [
    "event_envelope",
    "OutboxRecord",
    "OutboxStore",
    "InMemoryOutbox",
    "OutboxRelay",
    "ProcessedStore",
    "InMemoryProcessedStore",
    "DeadLetterQueue",
    "InMemoryDeadLetterQueue",
    "IdempotentConsumer",
]


def event_envelope(
    event_type: str,
    data: Dict[str, Any],
    *,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    event_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the standard event envelope (Article VIII §3).

    Carries a unique ``event_id`` (idempotency key for consumers), ``event_type``, UTC
    ``occurred_at`` (Article XXIV §1), tenant/correlation context (defaulting from the logging
    context), and the ``data`` payload.
    """
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "event_type": event_type,
        "occurred_at": occurred_at or to_rfc3339(),
        "tenant_id": tenant_id if tenant_id is not None else current_tenant_id(),
        "request_id": request_id if request_id is not None else current_request_id(),
        "data": data,
    }


@dataclass
class OutboxRecord:
    """A pending event stored transactionally alongside a state change (Article VIII §3)."""

    envelope: Dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    published: bool = False

    @property
    def event_id(self) -> str:
        return str(self.envelope.get("event_id", self.id))


class OutboxStore(ABC):
    """Where unpublished events wait to be relayed. Backed by the service's DB in production."""

    @abstractmethod
    def add(self, record: OutboxRecord) -> None:
        """Append a record (in the same transaction as the state change)."""

    @abstractmethod
    def list_unpublished(self, limit: int = 100) -> List[OutboxRecord]:
        """Return up to ``limit`` not-yet-published records, oldest first."""

    @abstractmethod
    def mark_published(self, record_id: str) -> None:
        """Mark a record published once the broker has acknowledged it."""


class InMemoryOutbox(OutboxStore):
    """A correct, unit-testable outbox. Production uses an outbox *table* in the service DB."""

    def __init__(self) -> None:
        self._records: List[OutboxRecord] = []

    def add(self, record: OutboxRecord) -> None:
        self._records.append(record)

    def list_unpublished(self, limit: int = 100) -> List[OutboxRecord]:
        return [r for r in self._records if not r.published][:limit]

    def mark_published(self, record_id: str) -> None:
        for record in self._records:
            if record.id == record_id:
                record.published = True
                return


class OutboxRelay:
    """Relays outbox records to the broker at-least-once (Article VIII §3).

    A separate relay process (Article II §3) calls :meth:`relay_once` on a loop. Each record is
    published then marked; a publish failure leaves the record unpublished for the next pass (so no
    event is lost). Consumers dedupe on ``event_id`` via :class:`IdempotentConsumer`.
    """

    def __init__(
        self,
        store: OutboxStore,
        publish: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._store = store
        self._publish = publish

    async def relay_once(self, limit: int = 100) -> int:
        """Publish one batch; return how many were successfully published."""
        published = 0
        for record in self._store.list_unpublished(limit):
            await self._publish(record.envelope)
            self._store.mark_published(record.id)
            published += 1
        return published


class ProcessedStore(ABC):
    """Tracks already-processed event ids so consumers are idempotent (Article VIII §3)."""

    @abstractmethod
    def seen(self, event_id: str) -> bool:
        """Whether this event id has already been processed."""

    @abstractmethod
    def mark(self, event_id: str) -> None:
        """Record an event id as processed."""


class InMemoryProcessedStore(ProcessedStore):
    """A correct, unit-testable dedupe store. Production uses Redis/DB with a retention window."""

    def __init__(self) -> None:
        self._seen: Set[str] = set()

    def seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        self._seen.add(event_id)


class DeadLetterQueue(ABC):
    """Where events that cannot be processed are parked (Article VIII §3, XXVIII §2)."""

    @abstractmethod
    def send(self, envelope: Dict[str, Any], reason: str) -> None:
        """Park an undeliverable event with the failure reason."""


class InMemoryDeadLetterQueue(DeadLetterQueue):
    """A correct, unit-testable DLQ. Production uses the broker's dead-letter queue."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def send(self, envelope: Dict[str, Any], reason: str) -> None:
        self.messages.append({"envelope": envelope, "reason": reason})


class IdempotentConsumer:
    """Wraps a handler with dedupe + dead-lettering (Article VIII §3).

    Skips events whose ``event_id`` was already processed (at-least-once delivery is safe). On a
    handler exception the event is routed to the DLQ (never silently dropped) and the exception is
    swallowed so one poison message cannot stall the stream. Returns whether the handler ran.
    """

    def __init__(
        self,
        handler: Callable[[Dict[str, Any]], Awaitable[None]],
        processed: Optional[ProcessedStore] = None,
        dlq: Optional[DeadLetterQueue] = None,
    ) -> None:
        self._handler = handler
        self._processed = processed or InMemoryProcessedStore()
        self._dlq = dlq or InMemoryDeadLetterQueue()

    async def handle(self, envelope: Dict[str, Any]) -> bool:
        """Process one event idempotently; return ``True`` if the handler executed."""
        event_id = str(envelope.get("event_id", ""))
        if event_id and self._processed.seen(event_id):
            return False
        try:
            await self._handler(envelope)
        except Exception as exc:  # noqa: BLE001 - poison messages go to the DLQ, not the floor
            self._dlq.send(envelope, reason=repr(exc))
            return False
        if event_id:
            self._processed.mark(event_id)
        return True
