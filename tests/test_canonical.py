from datetime import datetime, timedelta, timezone

import pytest

from plugshub_common.canonical import Money, ensure_utc, parse_rfc3339, to_rfc3339, utc_now


def test_utc_now_is_aware_utc():
    now = utc_now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_to_rfc3339_uses_z_suffix():
    dt = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
    assert to_rfc3339(dt) == "2026-07-06T12:00:00Z"


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 7, 6, 12, 0, 0))


def test_offset_converted_to_utc():
    dt = datetime(2026, 7, 6, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_rfc3339(dt) == "2026-07-06T12:00:00Z"


def test_parse_roundtrip():
    parsed = parse_rfc3339("2026-07-06T12:00:00Z")
    assert parsed == datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
    assert to_rfc3339(parsed) == "2026-07-06T12:00:00Z"


def test_parse_rejects_naive():
    with pytest.raises(ValueError):
        parse_rfc3339("2026-07-06T12:00:00")


def test_money_is_integer_minor_units():
    m = Money(1050, "eur")
    assert m.minor_units == 1050 and m.currency == "EUR"
    assert m.to_dict() == {"minor_units": 1050, "currency": "EUR"}


def test_money_rejects_float_and_bad_currency():
    with pytest.raises(TypeError):
        Money(10.5, "EUR")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(100, "EURO")
    with pytest.raises(TypeError):
        Money(True, "EUR")  # bool is not an acceptable int amount


def test_money_arithmetic_same_currency():
    assert Money(100, "EUR").add(Money(50, "EUR")) == Money(150, "EUR")
    assert Money(100, "EUR").subtract(Money(30, "EUR")) == Money(70, "EUR")
    with pytest.raises(ValueError):
        Money(100, "EUR").add(Money(50, "USD"))


def test_money_from_dict():
    assert Money.from_dict({"minor_units": 999, "currency": "USD"}) == Money(999, "USD")
