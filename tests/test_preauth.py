import pytest

from plugshub_common.preauth import PREAUTH_KEY_TEMPLATE, preauth_key


def test_the_key_is_positional_tenant_charger_connector():
    assert preauth_key("t-1", "CH-001", 1) == "terminal:preauth:t-1:CH-001:1"


@pytest.mark.parametrize("connector", [1, "1"])
def test_an_int_and_a_string_connector_produce_the_same_key(connector):
    """The detail two independent implementations get wrong.

    terminal-service holds `connector_id` as an ``int``; session-service receives it from
    ocpp, where it can arrive as a string. If the two stringify at different points the
    keys differ, the park is not found, and the session runs uncapped against a card hold
    that has already been taken — silently, because a missing key is not an error.
    """
    assert preauth_key("t-1", "CH-001", connector) == "terminal:preauth:t-1:CH-001:1"


def test_the_template_is_the_declared_wire_format():
    """Pinned as a literal. Changing it is a breaking change to a cross-service contract
    and both services must move together, so it should be a deliberate edit to this
    assertion rather than a side effect of editing the builder."""
    assert PREAUTH_KEY_TEMPLATE == "terminal:preauth:{tenant}:{charger}:{connector}"


def test_a_different_connector_is_a_different_key():
    """The property that makes a positional key safe without a transaction reference: one
    connector's hold can never be read as another's."""
    assert preauth_key("t", "CH", 1) != preauth_key("t", "CH", 2)
    assert preauth_key("t", "CH-A", 1) != preauth_key("t", "CH-B", 1)
    assert preauth_key("t-a", "CH", 1) != preauth_key("t-b", "CH", 1)
