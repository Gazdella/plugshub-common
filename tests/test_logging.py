import io
import json
import logging

from plugshub_common.logging import (
    clear_request_context,
    configure_logging,
    current_request_id,
    mask,
    mask_mapping,
    set_request_context,
)


def _capture(service="svc", level="INFO"):
    stream = io.StringIO()
    logger = configure_logging(service, level=level, stream=stream)
    return logger, stream


def test_json_line_has_required_fields():
    logger, stream = _capture()
    clear_request_context()
    logger.info("hello")
    line = json.loads(stream.getvalue().strip())
    assert set(["timestamp", "level", "service", "message"]).issubset(line)
    assert line["level"] == "INFO" and line["service"] == "svc" and line["message"] == "hello"
    assert line["timestamp"].endswith("Z")


def test_context_ids_attached():
    logger, stream = _capture()
    set_request_context(request_id="req-9", tenant_id="tenant-a")
    logger.info("with context")
    line = json.loads(stream.getvalue().strip())
    assert line["request_id"] == "req-9" and line["tenant_id"] == "tenant-a"
    assert current_request_id() == "req-9"
    clear_request_context()


def test_extra_fields_merged():
    logger, stream = _capture()
    clear_request_context()
    logger.info("evt", extra={"order_id": "o1"})
    line = json.loads(stream.getvalue().strip())
    assert line["order_id"] == "o1"


def test_one_event_per_line():
    logger, stream = _capture()
    clear_request_context()
    logger.info("a")
    logger.info("b")
    lines = [ln for ln in stream.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "a"


def test_mask_scalar():
    assert mask("supersecret") == "***"
    assert mask("4111111111111111", keep=4) == "***1111"
    assert mask(None) == "***"


def test_mask_mapping_recursive_case_insensitive():
    data = {"Password": "x", "user": {"email": "a@b.com", "name": "ok"}, "n": 1}
    masked = mask_mapping(data)
    assert masked["Password"] == "***"
    assert masked["user"]["email"] == "***"
    assert masked["user"]["name"] == "ok"
    assert masked["n"] == 1


def test_configure_is_idempotent():
    _capture()
    _capture()
    assert len(logging.getLogger().handlers) == 1
