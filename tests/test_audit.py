from plugshub_common.audit import (
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    AuditWriter,
    InMemoryAuditSink,
)
from plugshub_common.logging import clear_request_context, set_request_context


def test_record_has_mandatory_shape():
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    clear_request_context()
    rec = writer.record(
        actor_id="u1",
        actor_type="user",
        action="role.grant",
        target="u2",
        outcome=OUTCOME_SUCCESS,
        tenant_id="t1",
        request_id="req-1",
    )
    d = rec.to_dict()
    for field in ("actor_id", "actor_type", "action", "target", "tenant_id", "timestamp",
                  "request_id", "outcome"):
        assert field in d
    assert d["timestamp"].endswith("Z")
    assert d["outcome"] == "success"


def test_context_defaults_used():
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    set_request_context(request_id="req-ctx", tenant_id="tenant-ctx")
    rec = writer.record(actor_id="s1", actor_type="service", action="secret.rotate", target="key")
    assert rec.request_id == "req-ctx" and rec.tenant_id == "tenant-ctx"
    clear_request_context()


def test_append_only_snapshot_is_immutable():
    sink = InMemoryAuditSink()
    writer = AuditWriter(sink)
    writer.record(actor_id="u1", actor_type="user", action="login", target="u1")
    snapshot = sink.records
    assert len(snapshot) == 1
    # snapshot is a tuple copy; mutating it does not affect the trail
    assert isinstance(snapshot, tuple)
    writer.record(actor_id="u1", actor_type="user", action="logout", target="u1",
                  outcome=OUTCOME_FAILURE)
    assert len(sink.records) == 2 and len(snapshot) == 1
