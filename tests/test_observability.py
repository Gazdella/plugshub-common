import importlib.util
import logging

import pytest

from plugshub_common.errors import InternalError, InvalidBodyError, NotFoundError, PlugsHubError
from plugshub_common.logging import clear_request_context, set_request_context
from plugshub_common.observability import (
    capture_exception,
    init_error_tracking,
    is_error_tracking_enabled,
    reset_error_tracking,
    should_report,
)

FAULT_LOGGER = "plugshub.server_fault"


@pytest.fixture(autouse=True)
def _clean_state():
    reset_error_tracking()
    clear_request_context()
    yield
    reset_error_tracking()
    clear_request_context()


def test_no_error_tracking_sdk_is_installed():
    """The error destination is the log stream, so no vendor client is a dependency at all."""
    assert importlib.util.find_spec("sentry_sdk") is None
    import plugshub_common  # noqa: F401


def test_capture_works_without_init():
    """Nothing has to be armed: there is no DSN, so §6 cannot be 'wired but dormant'."""
    assert is_error_tracking_enabled() is True
    assert capture_exception(RuntimeError("boom")) is True


def test_init_is_idempotent_and_always_enabled():
    assert init_error_tracking() is True
    assert init_error_tracking(service="svc", environment="prod", release="1.2.3") is True
    assert is_error_tracking_enabled() is True


def test_should_report_filters_4xx():
    assert should_report(RuntimeError("x")) is True
    assert should_report(InternalError("x")) is True  # 500
    assert should_report(NotFoundError("x")) is False  # 404
    assert should_report(InvalidBodyError("x")) is False  # 400
    assert should_report(PlugsHubError("x", http_status=503)) is True


def test_capture_reports_server_faults_only(caplog):
    """A 5xx becomes exactly one ERROR record for Vector to ship; a 4xx becomes none."""
    with caplog.at_level(logging.ERROR, logger=FAULT_LOGGER):
        assert capture_exception(RuntimeError("server boom")) is True
        assert capture_exception(InternalError("db down")) is True
        # 4xx client errors are never reported (Article XVI §5)
        assert capture_exception(NotFoundError("missing")) is False
        assert capture_exception(InvalidBodyError("empty")) is False

    records = [r for r in caplog.records if r.name == FAULT_LOGGER]
    assert len(records) == 2
    assert [r.levelno for r in records] == [logging.ERROR, logging.ERROR]


def test_report_carries_the_traceback(caplog):
    """Without exc_info the log line names the fault but cannot be debugged from."""
    with caplog.at_level(logging.ERROR, logger=FAULT_LOGGER):
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            capture_exception(exc)

    record = next(r for r in caplog.records if r.name == FAULT_LOGGER)
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert "RuntimeError" in record.getMessage()


def test_report_is_correlated_and_tagged(caplog):
    init_error_tracking(service="svc", environment="prod", release="1.2.3")
    set_request_context(request_id="req-77", tenant_id="tenant-x")

    with caplog.at_level(logging.ERROR, logger=FAULT_LOGGER):
        capture_exception(InternalError("db down"))

    record = next(r for r in caplog.records if r.name == FAULT_LOGGER)
    assert record.tags["request_id"] == "req-77"
    assert record.tags["tenant_id"] == "tenant-x"
    assert record.tags["service"] == "svc"
    assert record.tags["environment"] == "prod"
    assert record.tags["release"] == "1.2.3"
    assert record.exception_type == "InternalError"
    assert record.fault == "server"


def test_attached_context_is_masked(caplog):
    """A caller attaching a request payload must not be able to leak a secret into the logs."""
    init_error_tracking(extra_sensitive_keys=["x-tenant-secret"])

    with caplog.at_level(logging.ERROR, logger=FAULT_LOGGER):
        capture_exception(
            InternalError("db down"),
            {
                "route": "/api/v1/sessions",
                "headers": {"Authorization": "Bearer abc", "User-Agent": "curl"},
                "body": {"password": "hunter2", "keep": "ok"},
                "x-tenant-secret": "s3cret",
            },
        )

    record = next(r for r in caplog.records if r.name == FAULT_LOGGER)
    assert record.route == "/api/v1/sessions"
    assert record.headers["Authorization"] == "***"
    assert record.headers["User-Agent"] == "curl"
    assert record.body["password"] == "***"
    assert record.body["keep"] == "ok"
    assert getattr(record, "x-tenant-secret") == "***"


def test_reset_clears_the_static_tags(caplog):
    init_error_tracking(service="svc")
    reset_error_tracking()

    with caplog.at_level(logging.ERROR, logger=FAULT_LOGGER):
        capture_exception(InternalError("db down"))

    record = next(r for r in caplog.records if r.name == FAULT_LOGGER)
    assert "service" not in record.tags
