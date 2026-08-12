from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import SmartReviewEvent, SmartReviewSession, SmartReviewSuggestion

CREATE = "/api/review/sessions"


def _create(client, merchant):
    return client.post(CREATE, json={"merchantId": str(merchant.id)})


# --- POST /sessions -------------------------------------------------------




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







def test_rate_limit_returns_429_after_the_hourly_cap(client, merchant, db):
    for _ in range(60):
        assert _create(client, merchant).status_code == 201

    assert _create(client, merchant).status_code == 429


# --- GET /sessions/{token} ------------------------------------------------




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



def test_expired_session_is_410(client, merchant, db):
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
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


def _seed_batches(db, session, merchant, generations):
    for generation in generations:
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


def test_every_generation_is_returned(client, merchant, db):
    """Generating more adds to what is on screen rather than replacing it.

    Replacing meant a customer who liked the second card of batch two and
    pressed the button once more could never get it back, and at the cap was
    left with whatever batch happened to be last.
    """
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    _seed_batches(db, session, merchant, (1, 2, 3))

    suggestions = client.get(f"{CREATE}/{token}").json()["suggestions"]

    assert len(suggestions) == 9
    assert {item["text"][:12] for item in suggestions} == {
        "Suggestion 1",
        "Suggestion 2",
        "Suggestion 3",
    }


def test_generations_are_returned_oldest_first(client, merchant, db):
    """Order is generation then position, so the newest batch lands at the
    bottom of the list — directly where the customer just tapped Generate
    More, rather than off-screen above them."""
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    _seed_batches(db, session, merchant, (1, 2))

    texts = [item["text"] for item in client.get(f"{CREATE}/{token}").json()["suggestions"]]

    assert texts == [
        f"Suggestion {generation}-{position} about the food."
        for generation in (1, 2)
        for position in (1, 2, 3)
    ]


def test_batches_written_out_of_order_still_come_back_in_order(client, merchant, db):
    """Ordering comes from generation_number, not insertion order — a refunded
    or retried generation can write a lower number after a higher one."""
    token = _create(client, merchant).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    _seed_batches(db, session, merchant, (3, 1, 2))

    texts = [item["text"] for item in client.get(f"{CREATE}/{token}").json()["suggestions"]]

    assert texts == sorted(texts)


def test_suggestions_from_another_session_are_never_included(client, merchant, db):
    """The session filter is the only thing keeping one customer's cards out of
    another's, on a page that shows every batch rather than the last one."""
    mine = _create(client, merchant).json()["token"]
    _create(client, merchant)

    first, second = db.scalars(
        select(SmartReviewSession).order_by(SmartReviewSession.created_at)
    ).all()
    owner = first if first.token == mine else second
    other = second if owner is first else first

    _seed_batches(db, owner, merchant, (1,))
    db.add(
        SmartReviewSuggestion(
            session_id=other.id,
            merchant_id=merchant.id,
            generation_number=1,
            position=1,
            text_="Somebody else's suggestion about the food.",
        )
    )
    db.flush()

    texts = [item["text"] for item in client.get(f"{CREATE}/{mine}").json()["suggestions"]]

    assert len(texts) == 3
    assert not any("Somebody else" in text for text in texts)
