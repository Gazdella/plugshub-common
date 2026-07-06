import importlib.util

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


class _FakeSdk:
    def __init__(self):
        self.init_kwargs = None
        self.before_send = None
        self.captured = []
        self.tags = {}

    def init(self, **kwargs):
        self.init_kwargs = kwargs
        self.before_send = kwargs.get("before_send")

    def capture_exception(self, exc):
        self.captured.append(exc)

    def set_tag(self, key, value):
        self.tags[key] = value


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    reset_error_tracking()
    clear_request_context()
    yield
    reset_error_tracking()
    clear_request_context()


def test_sentry_sdk_is_optional_and_not_required_for_import():
    # The whole point: core import works without the SDK installed.
    assert importlib.util.find_spec("sentry_sdk") is None
    import plugshub_common  # noqa: F401


def test_no_dsn_is_safe_noop():
    assert init_error_tracking() is False
    assert is_error_tracking_enabled() is False
    # capture is a no-op when disabled
    assert capture_exception(RuntimeError("boom")) is False


def test_no_dsn_noop_without_sdk_installed():
    # Even though sentry-sdk is absent, the unset-DSN path must not try to import it.
    assert init_error_tracking(dsn=None) is False


def test_dsn_without_sdk_raises_clear_hint():
    with pytest.raises(RuntimeError) as ei:
        init_error_tracking(dsn="https://x@example.com/1")
    assert "sentry-sdk" in str(ei.value)


def test_init_path_with_injected_sdk():
    fake = _FakeSdk()
    ok = init_error_tracking(
        dsn="https://k@example.com/42", environment="prod", service="svc", sdk=fake
    )
    assert ok is True and is_error_tracking_enabled() is True
    assert fake.init_kwargs["dsn"] == "https://k@example.com/42"
    assert fake.init_kwargs["send_default_pii"] is False
    assert callable(fake.init_kwargs["before_send"])
    assert fake.tags.get("service") == "svc"


def test_dsn_read_from_env(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://env@example.com/7")
    fake = _FakeSdk()
    assert init_error_tracking(sdk=fake) is True
    assert fake.init_kwargs["dsn"] == "https://env@example.com/7"


def test_should_report_filters_4xx():
    assert should_report(RuntimeError("x")) is True
    assert should_report(InternalError("x")) is True  # 500
    assert should_report(NotFoundError("x")) is False  # 404
    assert should_report(InvalidBodyError("x")) is False  # 400
    assert should_report(PlugsHubError("x", http_status=503)) is True


def test_capture_reports_server_faults_only():
    fake = _FakeSdk()
    init_error_tracking(dsn="https://k@example.com/1", sdk=fake)

    assert capture_exception(RuntimeError("server boom")) is True
    assert capture_exception(InternalError("db down")) is True
    # 4xx client errors are never sent (Article XVI §5)
    assert capture_exception(NotFoundError("missing")) is False
    assert capture_exception(InvalidBodyError("empty")) is False

    assert len(fake.captured) == 2


def test_before_send_scrubs_and_tags():
    fake = _FakeSdk()
    init_error_tracking(dsn="https://k@example.com/1", sdk=fake)
    set_request_context(request_id="req-77", tenant_id="tenant-x")

    event = {
        "message": "boom",
        "request": {
            "headers": {"Authorization": "Bearer abc", "User-Agent": "curl"},
            "data": {"password": "hunter2", "keep": "ok"},
        },
    }
    scrubbed = fake.before_send(event, {})
    assert scrubbed["request"]["headers"]["Authorization"] == "***"
    assert scrubbed["request"]["headers"]["User-Agent"] == "curl"
    assert scrubbed["request"]["data"]["password"] == "***"
    assert scrubbed["request"]["data"]["keep"] == "ok"
    assert scrubbed["tags"]["request_id"] == "req-77"
    assert scrubbed["tags"]["tenant_id"] == "tenant-x"
