"""The subscribe / renew / suspend endpoints.

Integration because what is under test is a row being created or mutated in
place, and the arithmetic's own edge cases already have a unit suite
(tests/unit/test_subscription_terms.py).
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Merchant, Subscription


def url(merchant) -> str:
    return f"/api/leads/merchants/{merchant.id}/subscription"


def _unsubscribed(db) -> Merchant:
    """A crawled merchant with no subscription — what save leaves behind.

    source=GOOGLE_PLACES because the saved list filters on it; a row without it
    is not something the crawler would ever have produced.
    """
    merchant = Merchant(
        slug="unsubscribed",
        name="Kam Do",
        google_review_url="https://example.test/r",
        source="GOOGLE_PLACES",
    )
    db.add(merchant)
    db.flush()
    return merchant


def _row(db, merchant) -> Subscription:
    return db.query(Subscription).filter_by(merchant_id=merchant.id).one()


# --- create and renew -------------------------------------------------------


def test_subscribing_a_new_merchant_is_201(client, db):
    merchant = _unsubscribed(db)

    response = client.post(url(merchant), json={"duration": 30, "durationUnit": "day"})
    body = response.json()

    assert response.status_code == 201
    assert body["status"] == "ACTIVE"
    assert body["duration"] == 30
    assert body["durationUnit"] == "day"


def test_the_last_valid_day_is_the_day_before_the_stored_expiry(client, db):
    """The stored timestamp names the first dead midnight. Rendering it raw
    would tell the merchant they have a day they do not have."""
    merchant = _unsubscribed(db)

    body = client.post(
        url(merchant), json={"duration": 30, "durationUnit": "day"}
    ).json()

    expires = datetime.fromisoformat(body["expiresAt"])
    last_valid = datetime.fromisoformat(body["lastValidDay"]).date()

    assert last_valid == _row(db, merchant).last_valid_day
    assert last_valid < expires.date() or last_valid == expires.date() - timedelta(
        days=1
    )


def test_subscribing_makes_the_merchants_url_open(client, db):
    """The whole point of the endpoint."""
    merchant = _unsubscribed(db)
    create = "/api/review/sessions"

    assert client.post(create, json={"merchantId": str(merchant.id)}).status_code == 409

    client.post(url(merchant), json={"duration": 30, "durationUnit": "day"})
    # Every request shares this test's one Session, so the merchant loaded by
    # the 409 above is still in the identity map with subscription=None.
    # Production gives each request its own session; this is the equivalent.
    db.expire_all()

    assert client.post(create, json={"merchantId": str(merchant.id)}).status_code == 201


def test_renewing_an_existing_subscription_is_200_not_201(client, merchant):
    """The fixture merchant is already subscribed, so this is the second write
    to the same row — a caller should not have to compare payloads to tell."""
    response = client.post(url(merchant), json={"duration": 30, "durationUnit": "day"})

    assert response.status_code == 200


def test_renewing_extends_rather_than_replaces_the_term(client, merchant, db):
    """Renewing early must not burn the days already paid for."""
    before = _row(db, merchant).expires_at

    body = client.post(
        url(merchant), json={"duration": 30, "durationUnit": "day"}
    ).json()

    assert datetime.fromisoformat(body["expiresAt"]) > before


def test_a_merchant_never_ends_up_with_two_subscriptions(client, merchant, db):
    for _ in range(3):
        client.post(url(merchant), json={"duration": 7, "durationUnit": "day"})

    assert db.query(Subscription).filter_by(merchant_id=merchant.id).count() == 1


def test_renewing_a_cancelled_subscription_does_not_reactivate_it(client, merchant, db):
    """Extending a term and reopening the URL are separate decisions. Folding
    them together would silently un-cancel a merchant somebody cancelled on
    purpose."""
    client.patch(url(merchant), json={"status": "CANCELLED"})

    body = client.post(
        url(merchant), json={"duration": 30, "durationUnit": "day"}
    ).json()

    assert body["status"] == "CANCELLED"
    assert (
        client.post(
            "/api/review/sessions", json={"merchantId": str(merchant.id)}
        ).status_code
        == 409
    )


# --- suspend and resume -----------------------------------------------------


@pytest.mark.parametrize("status", ["CANCELLED", "PAUSED"])
def test_suspending_closes_the_url_without_moving_the_expiry(
    client, merchant, db, status
):
    before = _row(db, merchant).expires_at

    body = client.patch(url(merchant), json={"status": status}).json()

    assert body["status"] == status
    assert datetime.fromisoformat(body["expiresAt"]) == before


def test_resuming_reopens_it_with_the_same_expiry(client, merchant, db):
    """The clock kept running while it was suspended, which is why resuming is
    a status change and nothing else."""
    before = _row(db, merchant).expires_at
    client.patch(url(merchant), json={"status": "PAUSED"})

    body = client.patch(url(merchant), json={"status": "ACTIVE"}).json()

    assert datetime.fromisoformat(body["expiresAt"]) == before
    assert (
        client.post(
            "/api/review/sessions", json={"merchantId": str(merchant.id)}
        ).status_code
        == 201
    )


# --- refusals ---------------------------------------------------------------


def test_an_unknown_merchant_is_404(client):
    unknown = "00000000-0000-4000-8000-000000000000"

    response = client.post(
        f"/api/leads/merchants/{unknown}/subscription",
        json={"duration": 30, "durationUnit": "day"},
    )

    assert response.status_code == 404
    assert response.json() == {"error": "merchant_not_found"}


def test_patching_a_merchant_that_was_never_subscribed_is_its_own_404(client, db):
    """Distinct from merchant_not_found: the merchant exists and the fix is to
    subscribe it, which is a different call rather than a corrected id."""
    merchant = _unsubscribed(db)

    response = client.patch(url(merchant), json={"status": "CANCELLED"})

    assert response.status_code == 404
    assert response.json() == {"error": "subscription_not_found"}


@pytest.mark.parametrize("unit", ["month", "year"])
def test_a_unit_the_schema_allows_but_nothing_implements_says_so(client, merchant, unit):
    """Its own code rather than invalid_request: the value is valid and will one
    day work, and a caller that cannot tell the two apart reads a temporary
    limitation as a bug in its own payload."""
    response = client.post(url(merchant), json={"duration": 1, "durationUnit": unit})

    assert response.status_code == 400
    assert response.json() == {"error": "unsupported_duration_unit"}


@pytest.mark.parametrize("duration", [0, -1])
def test_a_non_positive_duration_is_refused(client, merchant, duration):
    response = client.post(
        url(merchant), json={"duration": duration, "durationUnit": "day"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


def test_an_unknown_status_is_refused(client, merchant):
    response = client.patch(url(merchant), json={"status": "EXPIRED"})

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


def test_a_status_change_cannot_smuggle_in_a_new_term(client, merchant, db):
    """Separate verbs exist precisely so this is impossible."""
    before = _row(db, merchant).expires_at

    response = client.patch(
        url(merchant), json={"status": "ACTIVE", "duration": 3650}
    )

    assert response.status_code == 400
    assert _row(db, merchant).expires_at == before


# --- what the operator sees -------------------------------------------------


def test_a_saved_merchant_starts_with_no_subscription_object(client, db):
    merchant = _unsubscribed(db)

    body = client.get("/api/leads/merchants").json()
    row = next(m for m in body["merchants"] if m["id"] == str(merchant.id))

    # Null, not an object of nulls: there is no term to describe.
    assert row["subscription"] is None
    # The URL exists regardless — whether it opens is the subscription's answer.
    assert row["url"].endswith(str(merchant.id))


def test_the_saved_list_carries_status_and_both_dates(client, db):
    """The list is the only place a lapsing subscription becomes visible —
    nothing warns before expiry — so it has to carry enough to act on."""
    merchant = _unsubscribed(db)
    client.post(url(merchant), json={"duration": 30, "durationUnit": "day"})

    body = client.get("/api/leads/merchants").json()
    row = next(m for m in body["merchants"] if m["id"] == str(merchant.id))

    assert row["subscription"]["status"] == "ACTIVE"
    assert row["subscription"]["expiresAt"]
    assert row["subscription"]["lastValidDay"]
