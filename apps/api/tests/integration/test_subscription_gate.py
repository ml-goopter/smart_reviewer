"""The subscription gate on session creation.

Integration rather than unit: the gate reads a row through a relationship the
schema defines, and the states being asserted are rows, not branches.

Every rejection is the same 409 with the same code. Which reason applied is the
merchant's private business information — a customer cannot act on any of them,
and telling them a business is behind on payment is not ours to do.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Subscription

CREATE = "/api/review/sessions"


def _create(client, merchant):
    return client.post(CREATE, json={"merchantId": str(merchant.id)})


def test_a_subscribed_merchant_can_create_a_session(client, merchant):
    assert _create(client, merchant).status_code == 201


def test_a_merchant_with_no_subscription_cannot(client, merchant, db):
    """Never subscribed is not a special case — it is the same INACTIVE as an
    expired one. A gate that passes when its data is missing is not a gate."""
    db.query(Subscription).filter_by(merchant_id=merchant.id).delete()
    db.flush()

    response = _create(client, merchant)

    assert response.status_code == 409
    assert response.json() == {"error": "merchant_unavailable"}


def test_an_expired_subscription_cannot(client, merchant, db):
    subscription = db.query(Subscription).filter_by(merchant_id=merchant.id).one()
    subscription.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert _create(client, merchant).status_code == 409


def test_the_expiry_instant_itself_is_already_over(client, merchant, db):
    """The gate is strictly `now < expires_at`. `expires_at` names the first
    dead midnight, so at exactly that instant the term has ended."""
    subscription = db.query(Subscription).filter_by(merchant_id=merchant.id).one()
    subscription.expires_at = datetime.now(UTC)
    db.flush()

    assert _create(client, merchant).status_code == 409


@pytest.mark.parametrize("status", ["CANCELLED", "PAUSED"])
def test_a_suspended_subscription_cannot_even_with_time_left(
    client, merchant, db, status
):
    """Suspension closes the gate without touching expires_at — the clock keeps
    running, which is why resuming is a status change and nothing else."""
    subscription = db.query(Subscription).filter_by(merchant_id=merchant.id).one()
    subscription.status = status
    expires_at = subscription.expires_at
    db.flush()

    assert _create(client, merchant).status_code == 409
    db.refresh(subscription)
    assert subscription.expires_at == expires_at


def test_an_unsubscribed_merchant_redirects_to_unavailable_not_busy(
    client, merchant, db
):
    """The QR entry route sends every unavailable cause to the same terminal
    copy. Only rate limiting gets the retryable destination, because only it
    clears on its own."""
    db.query(Subscription).filter_by(merchant_id=merchant.id).delete()
    db.flush()

    response = client.get(f"/m/{merchant.id}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unavailable"


def test_a_session_minted_while_active_survives_the_subscription_expiring(
    client, merchant, db
):
    """The whole reason the gate is create-only. A customer typing a review at
    23:59:58 must not lose it at midnight; the exposure is bounded by the
    session TTL and is self-limiting."""
    token = _create(client, merchant).json()["token"]

    subscription = db.query(Subscription).filter_by(merchant_id=merchant.id).one()
    subscription.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert client.get(f"{CREATE}/{token}").status_code == 200


def test_a_session_minted_while_active_survives_a_cancellation(client, merchant, db):
    """Same rule for a deliberate suspension. Cutting live sessions off would
    be defensible, but it is not what the gate does, and a half-applied rule is
    worse than either."""
    token = _create(client, merchant).json()["token"]

    subscription = db.query(Subscription).filter_by(merchant_id=merchant.id).one()
    subscription.status = "CANCELLED"
    db.flush()

    assert client.get(f"{CREATE}/{token}").status_code == 200
