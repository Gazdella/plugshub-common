import pytest
from pydantic import BaseModel

from plugshub_common.errors import InvalidBodyError, ValidationFailedError
from plugshub_common.validation import parse_json_body, validate_model


class Payload(BaseModel):
    name: str
    amount: int


def test_parse_json_body_ok():
    assert parse_json_body('{"a": 1}') == {"a": 1}
    assert parse_json_body(b'{"a": 1}') == {"a": 1}
    assert parse_json_body({"a": 1}) == {"a": 1}


def test_parse_empty_body_is_invalid_body():
    with pytest.raises(InvalidBodyError):
        parse_json_body("")
    with pytest.raises(InvalidBodyError):
        parse_json_body(None)


def test_parse_garbage_is_invalid_body():
    with pytest.raises(InvalidBodyError):
        parse_json_body("{not json")


def test_validate_model_ok():
    obj = validate_model(Payload, {"name": "x", "amount": 5})
    assert obj.name == "x" and obj.amount == 5


def test_validate_model_reports_field_errors():
    with pytest.raises(ValidationFailedError) as ei:
        validate_model(Payload, {"name": "x"})
    assert "amount" in ei.value.details


def test_validate_model_non_object_is_invalid_body():
    with pytest.raises(InvalidBodyError):
        validate_model(Payload, [1, 2, 3])
