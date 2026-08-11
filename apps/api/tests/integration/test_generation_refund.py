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

from app.config import get_settings
from app.models import LANGUAGES
from app.services.suggestions import (
    _CLAIM_ATTEMPT,
    _CLAIM_GENERATION,
    _RELEASE_GENERATION,
)
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_suggestions import GOOD, StubProvider

CREATE = "/api/review/sessions"


@pytest.fixture
def provider():
    return StubProvider()


@pytest.fixture
def raw():
    """A session row and its own engine.

    Its own engine because these tests drive the claim statements directly to
    reach interleavings the HTTP surface cannot produce on demand — the point
    is the SQL, not the route.
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

    yield engine, session_id

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM smart_review_sessions WHERE id = :i"), {"i": session_id}
        )
        conn.execute(text("DELETE FROM merchants WHERE id = :m"), {"m": merchant_id})
    engine.dispose()


def claim(session_id, language="en"):
    return {
        "session_id": session_id,
        "language": language,
        "cap": get_settings().max_generations_per_language,
    }


def release(session_id, claimed, language="en"):
    return {"session_id": session_id, "language": language, "claimed": claimed}


@pytest.fixture
def api(client, provider):
    from app.main import app
    from app.routers.review import get_provider

    app.dependency_overrides[get_provider] = lambda: provider
    yield client
    app.dependency_overrides.pop(get_provider, None)


def test_refund_does_not_reissue_a_used_generation_number(raw):
    """The interleaving that permanently bricks a session.

    A claims 1, B claims 2 and stores rows numbered 2, then A's provider call
    fails. An unconditional decrement would leave the counter at 1, so the next
    caller claims 2 again — colliding with B's rows on the unique constraint.
    The failure rolls the claim back, so it recurs on every retry and the
    session's Generate More button 500s until it expires.
    """
    engine, session_id = raw

    with engine.begin() as conn:
        first = conn.execute(_CLAIM_GENERATION, claim(session_id)).scalar()
        second = conn.execute(_CLAIM_GENERATION, claim(session_id)).scalar()

        # The earlier claim fails and tries to give its slot back.
        conn.execute(_RELEASE_GENERATION, release(session_id, first))

        third = conn.execute(_CLAIM_GENERATION, claim(session_id)).scalar()

    assert (first, second) == (1, 2)
    # Must not be 2 again: that number belongs to a batch already stored.
    assert third == 3


def test_refund_applies_when_the_claim_is_still_the_newest(raw):
    """The ordinary case: a lone failure genuinely gives the slot back."""
    engine, session_id = raw
    attempt_cap = get_settings().max_generation_attempts_per_session

    with engine.begin() as conn:
        claimed = conn.execute(_CLAIM_GENERATION, claim(session_id)).scalar()
        conn.execute(
            _CLAIM_ATTEMPT, {"session_id": session_id, "attempt_cap": attempt_cap}
        )
        conn.execute(_RELEASE_GENERATION, release(session_id, claimed))

        count = conn.execute(
            text(
                "SELECT generation_count FROM smart_review_session_languages "
                "WHERE session_id = :i AND language = 'en'"
            ),
            {"i": session_id},
        ).scalar()
        attempts = conn.execute(
            text(
                "SELECT generation_attempts FROM smart_review_sessions WHERE id = :i"
            ),
            {"i": session_id},
        ).scalar()

    assert count == 0, "the customer keeps their allowance"
    assert attempts == 1, "but the attempt is still on the record"


def test_each_language_holds_its_own_allowance(raw):
    """The cap is per language, so spending one language's allowance in full
    must leave every other language untouched — that is the whole reason the
    counter moved off the session row."""
    engine, session_id = raw
    cap = get_settings().max_generations_per_language

    with engine.begin() as conn:
        for _ in range(cap):
            assert conn.execute(_CLAIM_GENERATION, claim(session_id, "en")).scalar()

        # English is spent.
        assert conn.execute(_CLAIM_GENERATION, claim(session_id, "en")).scalar() is None

        # Every other language still starts from one.
        for language in (item for item in LANGUAGES if item != "en"):
            first = conn.execute(
                _CLAIM_GENERATION, claim(session_id, language)
            ).scalar()
            assert first == 1


def test_a_zero_cap_grants_nothing_at_all(raw):
    """Zero is a legitimate setting — it turns generation off. The cap has to
    bite on the very first request in a language, not only once a counter row
    exists, or "disabled" would still buy one batch per language."""
    engine, session_id = raw

    with engine.begin() as conn:
        for language in LANGUAGES:
            granted = conn.execute(
                _CLAIM_GENERATION,
                {"session_id": session_id, "language": language, "cap": 0},
            ).scalar()
            assert granted is None, language

        rows = conn.execute(
            text(
                "SELECT count(*) FROM smart_review_session_languages "
                "WHERE session_id = :i"
            ),
            {"i": session_id},
        ).scalar()

    assert rows == 0, "a refused claim leaves no counter row behind"


def test_a_refund_in_one_language_does_not_credit_another(raw):
    """The release statement is keyed on the language as well as the session.
    Without that, a failure while reading Chinese would hand a slot back to
    English — free generations for anyone willing to switch languages."""
    engine, session_id = raw

    with engine.begin() as conn:
        english = conn.execute(_CLAIM_GENERATION, claim(session_id, "en")).scalar()
        conn.execute(_CLAIM_GENERATION, claim(session_id, "zh-Hant"))

        # A Chinese generation fails and refunds, quoting the number it holds.
        conn.execute(_RELEASE_GENERATION, release(session_id, 1, "zh-Hant"))

        counts = dict(
            conn.execute(
                text(
                    "SELECT language, generation_count "
                    "FROM smart_review_session_languages WHERE session_id = :i"
                ),
                {"i": session_id},
            ).all()
        )

    assert english == 1
    assert counts == {"en": 1, "zh-Hant": 0}


def test_failures_are_forgiven_but_not_unlimited(api, merchant, provider):
    """Without a monotonic ceiling, refunded failures make provider calls free
    and endlessly repeatable — one token would buy unlimited AI spend."""
    ceiling = get_settings().max_generation_attempts_per_session
    provider.error = True
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    statuses = [
        api.post(f"{CREATE}/{token}/suggestions").status_code
        for _ in range(ceiling + 2)
    ]

    assert statuses[0] == 502
    # Forgiveness runs out: once the attempt ceiling is reached the endpoint
    # stops calling the provider at all.
    assert statuses[-1] == 429
    assert statuses.count(502) == ceiling


def test_forgiveness_still_allows_recovery_after_a_transient_outage(
    api, merchant, provider
):
    """The reason refunds exist at all: a customer whose first tries hit a
    broken provider must not lose their allowance."""
    settings = get_settings()
    cap = settings.max_generations_per_language
    # Spend part of the never-refunded ceiling on failures, leaving enough for
    # the full success allowance afterwards — which is the property under test.
    wasted = settings.max_generation_attempts_per_session - cap

    provider.error = True
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]
    for _ in range(wasted):
        assert api.post(f"{CREATE}/{token}/suggestions").status_code == 502

    provider.error = False
    provider.responses = [json.dumps(GOOD) for _ in range(cap)]

    for _ in range(cap):
        assert api.post(f"{CREATE}/{token}/suggestions").status_code == 201
