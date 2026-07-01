import pytest

from plugshub_common.tenant import validate_tenant

_UUID = "239cca94-9c80-4bcd-915e-445f35b6a260"
_MEMBERS = {_UUID}


def test_known_tenant_passes():
    assert validate_tenant(_UUID, _MEMBERS, raise_on_invalid=False) is True


def test_prefixed_form_passes():
    assert validate_tenant("tenant" + _UUID, _MEMBERS, raise_on_invalid=False) is True


def test_unknown_rejected_fail_closed():
    assert validate_tenant("11111111-1111-1111-1111-111111111111", _MEMBERS, raise_on_invalid=False) is False


def test_injection_and_empty_rejected():
    assert validate_tenant("1' OR '1'='1", _MEMBERS, raise_on_invalid=False) is False
    assert validate_tenant(f"{_UUID}; DROP DATABASE x", _MEMBERS, raise_on_invalid=False) is False
    assert validate_tenant("", _MEMBERS, raise_on_invalid=False) is False


def test_raise_mode():
    with pytest.raises(ValueError):
        validate_tenant("nope", _MEMBERS, raise_on_invalid=True)


def test_regex_only_window_when_no_set():
    # before the set loads (tenants=None) -> regex-only, so a well-formed uuid passes
    assert validate_tenant(_UUID, None, raise_on_invalid=False) is True
