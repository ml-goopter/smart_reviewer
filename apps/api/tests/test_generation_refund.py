"""The refund is the subtlest part of the cost control.

Giving a slot back after a provider failure is what stops an outage from
burning a real customer's allowance. But a refund is a decrement on a shared
counter, and both of the ways it can go wrong are severe: hand back a number
another request already used and the session breaks permanently, or forgive
failures without limit and a single token buys unlimited paid provider calls.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from app.services.suggestions import _CLAIM_GENERATION, _RELEASE_GENERATION
from tests.conftest import TEST_DATABASE_URL
from tests.test_suggestions import GOOD, StubProvider

CREATE = "/api/review/sessions"


@pytest.fixture
def provider():
    return StubProvider()


@pytest.fixture
def api(client, provider):
    from app.main import app
    from app.routers.review import get_provider

    app.dependency_overrides[get_provider] = lambda: provider
    yield client
    app.dependency_overrides.pop(get_provider, None)


def test_refund_does_not_reissue_a_used_generation_number():
    """The interleaving that permanently bricks a session.

    A claims 1, B claims 2 and stores rows numbered 2, then A's provider call
    fails. An unconditional decrement would leave the counter at 1, so the next
    caller claims 2 again — colliding with B's rows on the unique constraint.
    The failure rolls the claim back, so it recurs on every retry and the
    session's Generate More button 500s until it expires.
    """
    engine = create_engine(TEST_DATABASE_URL)

    with engine.begin() as conn:
        merchant_id = conn.execute(
            text(
                "INSERT INTO merchants (slug, name, google_review_url) VALUES "
                "(:s, 'Refund Test', 'https://example.test/r') RETURNING id"
            ),
            {"s": f"refund-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        session_id = conn.execute(
            text(
                "INSERT INTO smart_review_sessions (merchant_id, token, expires_at) "
                "VALUES (:m, :t, :e) RETURNING id"
            ),
            {
                "m": merchant_id,
                "t": uuid.uuid4().hex,
                "e": datetime.now(UTC) + timedelta(hours=24),
            },
        ).scalar_one()

    params = {"session_id": session_id, "cap": 5, "attempt_cap": 10}

    with engine.begin() as conn:
        first = conn.execute(_CLAIM_GENERATION, params).scalar()
        second = conn.execute(_CLAIM_GENERATION, params).scalar()

        # The earlier claim fails and tries to give its slot back.
        conn.execute(
            _RELEASE_GENERATION, {"session_id": session_id, "claimed": first}
        )

        third = conn.execute(_CLAIM_GENERATION, params).scalar()

    assert (first, second) == (1, 2)
    # Must not be 2 again: that number belongs to a batch already stored.
    assert third == 3

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM smart_review_sessions WHERE id = :i"), {"i": session_id}
        )
        conn.execute(text("DELETE FROM merchants WHERE id = :m"), {"m": merchant_id})
    engine.dispose()


def test_refund_applies_when_the_claim_is_still_the_newest():
    """The ordinary case: a lone failure genuinely gives the slot back."""
    engine = create_engine(TEST_DATABASE_URL)

    with engine.begin() as conn:
        merchant_id = conn.execute(
            text(
                "INSERT INTO merchants (slug, name, google_review_url) VALUES "
                "(:s, 'Refund Test', 'https://example.test/r') RETURNING id"
            ),
            {"s": f"refund-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        session_id = conn.execute(
            text(
                "INSERT INTO smart_review_sessions (merchant_id, token, expires_at) "
                "VALUES (:m, :t, :e) RETURNING id"
            ),
            {
                "m": merchant_id,
                "t": uuid.uuid4().hex,
                "e": datetime.now(UTC) + timedelta(hours=24),
            },
        ).scalar_one()

    params = {"session_id": session_id, "cap": 5, "attempt_cap": 10}

    with engine.begin() as conn:
        claimed = conn.execute(_CLAIM_GENERATION, params).scalar()
        conn.execute(
            _RELEASE_GENERATION, {"session_id": session_id, "claimed": claimed}
        )
        count, attempts = conn.execute(
            text(
                "SELECT generation_count, generation_attempts "
                "FROM smart_review_sessions WHERE id = :i"
            ),
            {"i": session_id},
        ).one()

    assert count == 0, "the customer keeps their allowance"
    assert attempts == 1, "but the attempt is still on the record"

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM smart_review_sessions WHERE id = :i"), {"i": session_id}
        )
        conn.execute(text("DELETE FROM merchants WHERE id = :m"), {"m": merchant_id})
    engine.dispose()


def test_failures_are_forgiven_but_not_unlimited(api, merchant, provider):
    """Without a monotonic ceiling, refunded failures make provider calls free
    and endlessly repeatable — one token would buy unlimited AI spend."""
    provider.error = True
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    statuses = [
        api.post(f"{CREATE}/{token}/suggestions").status_code for _ in range(12)
    ]

    assert statuses[0] == 502
    # Forgiveness runs out: once the attempt ceiling is reached the endpoint
    # stops calling the provider at all.
    assert statuses[-1] == 429
    assert statuses.count(502) == 10


def test_forgiveness_still_allows_recovery_after_a_transient_outage(
    api, merchant, provider
):
    """The reason refunds exist at all: a customer whose first tries hit a
    broken provider must not lose their allowance."""
    provider.error = True
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]
    for _ in range(3):
        assert api.post(f"{CREATE}/{token}/suggestions").status_code == 502

    provider.error = False
    provider.responses = [json.dumps(GOOD) for _ in range(5)]

    for _ in range(5):
        assert api.post(f"{CREATE}/{token}/suggestions").status_code == 201
