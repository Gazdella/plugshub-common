"""The terminal pre-auth park: one key builder, for both sides of it.

terminal-service parks a customer's prepaid amount in Valkey just before it commands a
charger; session-service reads it when the session appears and uses it as the spending cap.
Until now each service built the key from its own format string — identical output, two
independent definitions — which is the drift Article XVII §2 exists to prevent.

**Why it matters more here than in most shared helpers.** If the two formats ever diverge,
nothing errors. The park is simply not found, session-service classifies the session as an
ordinary one, and the charger runs uncapped against a card hold that has already been
taken. The customer is charged and the cap silently does not apply. A cross-service
contract test catches the drift today; this removes the possibility.

**Positional, deliberately not per-transaction.** The key names a place, not a session:
tenant, charger, connector. A fresh pre-auth on the same connector OVERWRITES the previous
one, so an abandoned hold can never be claimed by a later session — which is the property
that makes it safe to have no transaction reference at park time, when no transaction
exists yet.

**Never widen the read.** A previous session-service revision, on an exact-key miss,
scanned the charger and took a sole remaining park, because a charger may StartTransaction
on a different connector than RemoteStart named. That read runs for *every* session, so the
rescue let an ordinary RFID session on connector 2 consume the hold parked for a terminal
driver on connector 1 — billing the wrong customer twice over. A connector mismatch must
read as absent. Losing a mismatched terminal start is strictly better than charging someone
else's card.
"""

from typing import Any

# The wire format. Changing this is a breaking change to a cross-service contract and
# requires both services to move together — see `docs/` in either service for the
# contract test that pins it.
PREAUTH_KEY_TEMPLATE = "terminal:preauth:{tenant}:{charger}:{connector}"


def preauth_key(tenant_id: str, charger_id: str, connector_id: Any) -> str:
    """The Valkey key holding the parked pre-auth for one charger connector.

    `connector_id` is typed `Any` on purpose: terminal-service holds it as an ``int`` and
    session-service receives it from ocpp, where it may arrive as a string. Both must
    produce the same key, so it is stringified here rather than at each call site — which
    is precisely the kind of detail two independent implementations get subtly wrong.
    """
    return PREAUTH_KEY_TEMPLATE.format(
        tenant=tenant_id, charger=charger_id, connector=connector_id
    )
