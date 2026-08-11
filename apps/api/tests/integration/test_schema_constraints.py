"""The schema is the last line of defence for rules the application also
enforces. These assert the database refuses illegal states on its own."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from app.models import Merchant, SmartReviewSession, SmartReviewSuggestion


def _merchant(db) -> Merchant:
    merchant = Merchant(
        slug=f"m-{uuid.uuid4().hex[:8]}",
        name="Test Merchant",
        google_review_url="https://example.test/review",
    )
    db.add(merchant)
    db.flush()
    return merchant


def _session(db, merchant, **overrides) -> SmartReviewSession:
    values = {
        "merchant_id": merchant.id,
        "token": uuid.uuid4().hex,
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    }
    values.update(overrides)
    session = SmartReviewSession(**values)
    db.add(session)
    db.flush()
    return session


def _suggestion(db, session, merchant, **overrides) -> SmartReviewSuggestion:
    values = {
        "session_id": session.id,
        "merchant_id": merchant.id,
        "generation_number": 1,
        "position": 1,
        "text_": "The food was good and the service was quick.",
    }
    values.update(overrides)
    suggestion = SmartReviewSuggestion(**values)
    db.add(suggestion)
    db.flush()
    return suggestion


def test_counters_default_without_the_orm(db):
    """A psql fixup or any non-ORM insert path must not hit a NOT NULL
    violation on columns the spec documents as defaulted."""
    merchant = _merchant(db)

    row = db.execute(
        text(
            "INSERT INTO smart_review_sessions (merchant_id, token, expires_at) "
            "VALUES (:m, :t, now() + interval '24 hours') "
            "RETURNING status, open_count, suggestion_count"
        ),
        {"m": merchant.id, "t": uuid.uuid4().hex},
    ).one()

    assert row == ("ACTIVE", 0, 0)


def test_the_language_generation_counter_defaults_without_the_orm(db):
    """Same guarantee as above for the per-language counter, which the claim
    statement inserts directly rather than through the ORM."""
    merchant = _merchant(db)
    session = _session(db, merchant)

    row = db.execute(
        text(
            "INSERT INTO smart_review_session_languages (session_id, language) "
            "VALUES (:i, 'en') RETURNING generation_count"
        ),
        {"i": session.id},
    ).one()

    assert row == (0,)


def test_negative_generation_count_is_rejected(db):
    """Turns a buggy decrement into an error rather than free generations."""
    merchant = _merchant(db)
    session = _session(db, merchant)

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO smart_review_session_languages "
                "    (session_id, language, generation_count) "
                "VALUES (:i, 'en', -1)"
            ),
            {"i": session.id},
        )


def test_an_unknown_suggestion_language_is_rejected(db):
    """The language reaches the model prompt, so the database refuses anything
    outside the served set even if the API layer is bypassed."""
    merchant = _merchant(db)
    session = _session(db, merchant)

    with pytest.raises(IntegrityError):
        _suggestion(db, session, merchant, language="klingon")


def test_the_same_position_may_repeat_across_languages(db):
    """generation_number restarts per language, so English batch 1 and Chinese
    batch 1 both hold a position 1. The unique constraint carries the language
    for exactly this reason."""
    merchant = _merchant(db)
    session = _session(db, merchant)

    _suggestion(db, session, merchant, generation_number=1, position=1, language="en")
    _suggestion(
        db, session, merchant, generation_number=1, position=1, language="zh-Hant"
    )

    stored = db.execute(
        text(
            "SELECT count(*) FROM smart_review_suggestions WHERE session_id = :i"
        ),
        {"i": session.id},
    ).scalar()

    assert stored == 2


def test_duplicate_token_is_rejected(db):
    merchant = _merchant(db)
    session = _session(db, merchant)

    with pytest.raises(IntegrityError):
        _session(db, merchant, token=session.token)


def test_unknown_session_status_is_rejected(db):
    """EXPIRED was deliberately removed: expires_at is authoritative and
    nothing would ever write that row state."""
    merchant = _merchant(db)

    with pytest.raises(IntegrityError):
        _session(db, merchant, status="EXPIRED")


def test_unknown_event_type_is_rejected(db):
    merchant = _merchant(db)
    session = _session(db, merchant)

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO smart_review_events (session_id, merchant_id, event_type) "
                "VALUES (:s, :m, 'SUGGESTION_EDITED')"
            ),
            {"s": session.id, "m": merchant.id},
        )


def test_blank_suggestion_text_is_rejected(db):
    merchant = _merchant(db)
    session = _session(db, merchant)

    with pytest.raises(IntegrityError):
        _suggestion(db, session, merchant, text_="   ")


def test_duplicate_position_within_a_generation_is_rejected(db):
    merchant = _merchant(db)
    session = _session(db, merchant)
    _suggestion(db, session, merchant, generation_number=1, position=1)

    with pytest.raises(IntegrityError):
        _suggestion(db, session, merchant, generation_number=1, position=1)


def test_short_batches_renumbered_from_one_are_accepted(db):
    """When only some of a batch validates, positions are renumbered 1..n, so
    generations of differing length must coexist."""
    merchant = _merchant(db)
    session = _session(db, merchant)

    for position in (1, 2, 3):
        _suggestion(db, session, merchant, generation_number=1, position=position)
    for position in (1, 2):
        _suggestion(db, session, merchant, generation_number=2, position=position)
    _suggestion(db, session, merchant, generation_number=3, position=1)

    assert db.query(SmartReviewSuggestion).count() == 6


def test_session_cannot_select_another_sessions_suggestion(db):
    """The one real authorization rule in the system, enforced by a composite
    foreign key so a bug in the application cannot corrupt the row."""
    merchant = _merchant(db)
    session_a = _session(db, merchant)
    session_b = _session(db, merchant)
    suggestion_a = _suggestion(db, session_a, merchant)

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "UPDATE smart_review_sessions SET selected_suggestion_id = :s "
                "WHERE id = :i"
            ),
            {"s": suggestion_a.id, "i": session_b.id},
        )


def test_session_can_select_its_own_suggestion(db):
    merchant = _merchant(db)
    session = _session(db, merchant)
    suggestion = _suggestion(db, session, merchant)

    db.execute(
        text("UPDATE smart_review_sessions SET selected_suggestion_id = :s WHERE id = :i"),
        {"s": suggestion.id, "i": session.id},
    )

    stored = db.execute(
        text("SELECT selected_suggestion_id FROM smart_review_sessions WHERE id = :i"),
        {"i": session.id},
    ).scalar_one()

    assert stored == suggestion.id


def test_deleting_a_selected_suggestion_nulls_the_pointer_not_the_session(db):
    """A bare ON DELETE SET NULL on the composite key would try to null the
    session's own primary key; the column list keeps the session alive."""
    merchant = _merchant(db)
    session = _session(db, merchant)
    suggestion = _suggestion(db, session, merchant)

    db.execute(
        text("UPDATE smart_review_sessions SET selected_suggestion_id = :s WHERE id = :i"),
        {"s": suggestion.id, "i": session.id},
    )
    db.execute(
        text("DELETE FROM smart_review_suggestions WHERE id = :s"), {"s": suggestion.id}
    )

    row = db.execute(
        text("SELECT id, selected_suggestion_id FROM smart_review_sessions WHERE id = :i"),
        {"i": session.id},
    ).one()

    assert row == (session.id, None)
