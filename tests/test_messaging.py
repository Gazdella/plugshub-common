from plugshub_common.logging import clear_request_context, set_request_context
from plugshub_common.messaging import (
    IdempotentConsumer,
    InMemoryDeadLetterQueue,
    InMemoryOutbox,
    InMemoryProcessedStore,
    OutboxRecord,
    OutboxRelay,
    event_envelope,
)


def test_event_envelope_shape():
    clear_request_context()
    set_request_context(request_id="req-e", tenant_id="t-e")
    env = event_envelope("order.created", {"id": "o1"})
    assert env["event_type"] == "order.created"
    assert env["data"] == {"id": "o1"}
    assert env["tenant_id"] == "t-e" and env["request_id"] == "req-e"
    assert env["occurred_at"].endswith("Z")
    assert env["event_id"]
    clear_request_context()


async def test_outbox_relay_publishes_and_marks():
    store = InMemoryOutbox()
    store.add(OutboxRecord(event_envelope("e", {"n": 1})))
    store.add(OutboxRecord(event_envelope("e", {"n": 2})))
    published = []

    async def publish(env):
        published.append(env)

    relay = OutboxRelay(store, publish)
    count = await relay.relay_once()
    assert count == 2 and len(published) == 2
    assert store.list_unpublished() == []
    # second pass publishes nothing
    assert await relay.relay_once() == 0


async def test_outbox_failure_leaves_unpublished():
    store = InMemoryOutbox()
    store.add(OutboxRecord(event_envelope("e", {"n": 1})))

    async def failing_publish(env):
        raise RuntimeError("broker down")

    relay = OutboxRelay(store, failing_publish)
    try:
        await relay.relay_once()
    except RuntimeError:
        pass
    assert len(store.list_unpublished()) == 1


async def test_idempotent_consumer_dedupes():
    seen = []
    processed = InMemoryProcessedStore()

    async def handler(env):
        seen.append(env["event_id"])

    consumer = IdempotentConsumer(handler, processed=processed)
    env = event_envelope("e", {"x": 1})
    assert await consumer.handle(env) is True
    assert await consumer.handle(env) is False  # duplicate skipped
    assert len(seen) == 1


async def test_poison_message_goes_to_dlq():
    dlq = InMemoryDeadLetterQueue()

    async def handler(env):
        raise ValueError("cannot process")

    consumer = IdempotentConsumer(handler, dlq=dlq)
    env = event_envelope("e", {"x": 1})
    ran = await consumer.handle(env)
    assert ran is False
    assert len(dlq.messages) == 1
    assert dlq.messages[0]["envelope"] == env
