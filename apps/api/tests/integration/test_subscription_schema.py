"""What the database refuses on its own, for subscriptions.

Per R15a these are here rather than in tests/unit because a failure would mean
"the schema is wrong", not "the code is wrong". Mocking them would assert that a
stub does what it was told.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Merchant, Subscription


def _merchant(db) -> Merchant:
    merchant = Merchant(
        slug=f"m-{uuid.uuid4().hex[:8]}",
        name="Test Merchant",
        google_review_url="https://example.test/review",
    )
    db.add(merchant)
    db.flush()
    return merchant


def _subscription(db, merchant, **overrides) -> Subscription:
    values = {
        "merchant_id": merchant.id,
        "expires_at": datetime.now(UTC) + timedelta(days=30),
        "duration": 30,
        "duration_unit": "day",
    }
    values.update(overrides)
    subscription = Subscription(**values)
    db.add(subscription)
    db.flush()
    return subscription


def test_a_merchant_cannot_hold_two_subscriptions(db):
    """The one-to-one is enforced here, not only by the service. Two rows would
    make "the merchant's expiry" ambiguous, and whichever the query happened to
    return would decide whether the link opens."""
    merchant = _merchant(db)
    _subscription(db, merchant)

    with pytest.raises(IntegrityError):
        _subscription(db, merchant)


def test_an_unknown_status_is_refused(db):
    merchant = _merchant(db)

    with pytest.raises(IntegrityError):
        _subscription(db, merchant, status="EXPIRED")


@pytest.mark.parametrize("status", ["ACTIVE", "CANCELLED", "PAUSED"])
def test_the_three_states_that_exist_are_accepted(db, status):
    merchant = _merchant(db)

    assert _subscription(db, merchant, status=status).status == status


def test_an_unknown_duration_unit_is_refused(db):
    merchant = _merchant(db)

    with pytest.raises(IntegrityError):
        _subscription(db, merchant, duration_unit="fortnight")


@pytest.mark.parametrize("unit", ["day", "month", "year"])
def test_units_the_schema_accepts_include_ones_nothing_implements_yet(db, unit):
    """The CHECK is deliberately wider than the API. Adding months later is
    then a change to one validator rather than a migration."""
    merchant = _merchant(db)

    assert _subscription(db, merchant, duration_unit=unit).duration_unit == unit


@pytest.mark.parametrize("duration", [0, -1])
def test_a_non_positive_duration_is_refused(db, duration):
    merchant = _merchant(db)

    with pytest.raises(IntegrityError):
        _subscription(db, merchant, duration=duration)


def test_status_defaults_to_active(db):
    """A server default, not only a Python one, so a psql fixup or any future
    non-ORM insert cannot produce a NULL in a NOT NULL column."""
    merchant = _merchant(db)
    db.execute(
        text(
            "INSERT INTO subscriptions (merchant_id, expires_at, duration, "
            "duration_unit) VALUES (:mid, :expires, 30, 'day')"
        ),
        {"mid": merchant.id, "expires": datetime.now(UTC) + timedelta(days=30)},
    )

    stored = db.execute(
        text("SELECT status FROM subscriptions WHERE merchant_id = :mid"),
        {"mid": merchant.id},
    ).scalar_one()

    assert stored == "ACTIVE"


def test_deleting_a_merchant_takes_its_subscription(db):
    """A subscription has no meaning without its merchant. Note this only
    reaches the cascade for a merchant with no sessions: smart_review_sessions
    and smart_review_events hold non-cascading FKs to merchants and block the
    delete outright."""
    merchant = _merchant(db)
    _subscription(db, merchant)
    merchant_id = merchant.id

    db.delete(merchant)
    db.flush()

    remaining = db.execute(
        text("SELECT count(*) FROM subscriptions WHERE merchant_id = :mid"),
        {"mid": merchant_id},
    ).scalar_one()

    assert remaining == 0
