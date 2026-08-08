from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models import SmartReviewEvent, SmartReviewSession, SmartReviewSuggestion

CREATE = "/api/review/sessions"


def _create(client, merchant):
    return client.post(CREATE, json={"merchantId": str(merchant.id)})


# --- POST /sessions -------------------------------------------------------


def test_create_returns_201_and_a_token(client, merchant):
    response = _create(client, merchant)

    assert response.status_code == 201
    token = response.json()["token"]
    # 32 bytes urlsafe-encoded. Short enough for a URL, long enough that
    # guessing is not a strategy.
    assert len(token) >= 40


def test_create_response_contains_only_the_token(client, merchant):
    """The merchant is resolved from the session afterwards; returning any
    merchant data here would invite the client to hold on to it."""
    assert set(_create(client, merchant).json()) == {"token"}


def test_tokens_are_unique_per_session(client, merchant):
    first = _create(client, merchant).json()["token"]
    second = _create(client, merchant).json()["token"]

    assert first != second


def test_create_records_the_session_created_event(client, merchant, db):
    _create(client, merchant)

    events = db.scalars(
        select(SmartReviewEvent).where(SmartReviewEvent.event_type == "SESSION_CREATED")
    ).all()

    assert len(events) == 1
    assert events[0].merchant_id == merchant.id
    assert events[0].ip_hash is not None


def test_created_ip_is_stored_hashed_not_in_the_clear(client, merchant, db):
    _create(client, merchant)

    session = db.scalars(select(SmartReviewSession)).one()

    assert session.created_ip_hash is not None
    assert len(session.created_ip_hash) == 64
    # The stored value must not be derivable without the salt, which is what
    # makes it privacy-preserving rather than a reversible lookup.
    import hashlib

    unsalted = hashlib.sha256(b"testclient").hexdigest()
    assert session.created_ip_hash != unsalted


def test_expiry_is_set_to_the_configured_ttl(client, merchant, db):
    _create(client, merchant)

    session = db.scalars(select(SmartReviewSession)).one()
    expected = datetime.now(UTC) + timedelta(hours=24)

    assert abs((session.expires_at - expected).total_seconds()) < 60


def test_unknown_merchant_is_404(client):
    response = client.post(CREATE, json={"merchantId": str(uuid4())})

    assert response.status_code == 404


def test_malformed_merchant_id_is_400_not_422(client):
    """The contract specifies 400; FastAPI's default 422 also volunteers a
    field-by-field breakdown that a public endpoint should not."""
    response = client.post(CREATE, json={"merchantId": "not-a-uuid"})

    assert response.status_code == 400


def test_inactive_merchant_is_409(client, merchant, db):
    merchant.status = "INACTIVE"
    db.flush()

    assert _create(client, merchant).status_code == 409


def test_merchant_without_google_url_is_409(client, merchant, db):
    merchant.google_review_url = None
    db.flush()

    assert _create(client, merchant).status_code == 409


def test_unavailable_reasons_are_indistinguishable(client, merchant, db):
    """Whether a business is inactive, archived, or never finished setup is the
    merchant's private information, not something a public URL should reveal."""
    merchant.status = "ARCHIVED"
    db.flush()
    archived = _create(client, merchant)

    merchant.status = "ACTIVE"
    merchant.google_review_url = None
    db.flush()
    no_url = _create(client, merchant)

    assert archived.status_code == no_url.status_code == 409
    assert archived.json() == no_url.json()


def test_rate_limit_returns_429_after_the_hourly_cap(client, merchant, db):
    for _ in range(60):
        assert _create(client, merchant).status_code == 201

    assert _create(client, merchant).status_code == 429


# --- GET /sessions/{token} ------------------------------------------------


def test_get_returns_the_public_payload(client, merchant):
    token = _create(client, merchant).json()["token"]

    body = client.get(f"{CREATE}/{token}").json()

    assert body["merchant"] == {"name": "Pho 37", "category": "Vietnamese Restaurant"}
    assert body["googleReviewUrl"] == "https://example.test/writereview"
    assert body["suggestions"] == []
    assert "expiresAt" in body["session"]


def test_get_never_leaks_internal_fields(client, merchant):
    token = _create(client, merchant).json()["token"]

    raw = client.get(f"{CREATE}/{token}").text

    for leaked in ("merchant_id", "google_place_id", "token", "slug", "created_ip_hash"):
        assert leaked not in raw


def test_get_does_not_generate_suggestions(client, merchant, db):
    """Generation is a paid provider call; a crawler fetching a shared link
    must not spend money, and the merchant name must not wait on the AI."""
    token = _create(client, merchant).json()["token"]

    client.get(f"{CREATE}/{token}")

    assert db.scalars(select(SmartReviewSuggestion)).all() == []


def test_get_is_idempotent_apart_from_open_tracking(client, merchant, db):
    token = _create(client, merchant).json()["token"]

    first = client.get(f"{CREATE}/{token}").json()
    second = client.get(f"{CREATE}/{token}").json()

    assert first == second

    session = db.scalars(select(SmartReviewSession)).one()
    assert session.open_count == 2
    assert session.first_opened_at < session.last_opened_at


def test_get_records_session_opened(client, merchant, db):
    token = _create(client, merchant).json()["token"]

    client.get(f"{CREATE}/{token}")

    events = db.scalars(
        select(SmartReviewEvent).where(SmartReviewEvent.event_type == "SESSION_OPENED")
    ).all()

    assert len(events) == 1


def test_unknown_token_is_404(client):
    assert client.get(f"{CREATE}/nosuchtoken").status_code == 404


def test_expired_session_is_410(client, merchant, db):
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert client.get(f"{CREATE}/{token}").status_code == 410


def test_disabled_session_is_410(client, merchant, db):
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    session.disabled_at = datetime.now(UTC)
    db.flush()

    assert client.get(f"{CREATE}/{token}").status_code == 410


def test_completed_session_remains_usable(client, merchant, db):
    """Completion is a milestone, not a gate. A customer who reaches Google and
    presses back must find their session and their edited text still there."""
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    session.status = "COMPLETED"
    session.completed_at = datetime.now(UTC)
    db.flush()

    assert client.get(f"{CREATE}/{token}").status_code == 200


def test_only_the_newest_generation_is_returned(client, merchant, db):
    """The customer is looking at one batch of cards; earlier generations are
    history, not current options."""
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()

    for generation in (1, 2):
        for position in (1, 2, 3):
            db.add(
                SmartReviewSuggestion(
                    session_id=session.id,
                    merchant_id=merchant.id,
                    generation_number=generation,
                    position=position,
                    text_=f"Suggestion {generation}-{position} about the food.",
                )
            )
    db.flush()

    suggestions = client.get(f"{CREATE}/{token}").json()["suggestions"]

    assert len(suggestions) == 3
    assert all("Suggestion 2-" in item["text"] for item in suggestions)
    assert [item["text"][-len("about the food.") :] for item in suggestions] == [
        "about the food."
    ] * 3
