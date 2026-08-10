"""The generation cap is the cost control: it is the only thing bounding how
much AI spend a single session can cause. It is enforced as one atomic
conditional UPDATE precisely so it holds without shared state across workers,
so the test that matters is the concurrent one.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.suggestions import _CLAIM_GENERATION
from tests.integration.conftest import TEST_DATABASE_URL

CAP = 5

# Imported from production rather than retyped. A local copy drifts — an
# earlier version of this file pinned a statement with a different WHERE clause,
# so it would not have failed if the real one had been changed or deleted.
CLAIM = _CLAIM_GENERATION


def _seed_session(engine, merchant_id, token):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO smart_review_sessions (merchant_id, token, expires_at) "
                "VALUES (:m, :t, :e) RETURNING id"
            ),
            {"m": merchant_id, "t": token, "e": datetime.now(UTC) + timedelta(hours=24)},
        ).scalar_one()


def _merchant_id(engine) -> uuid.UUID:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO merchants (slug, name, google_review_url) "
                "VALUES (:s, 'Cap Test', 'https://example.test/review') RETURNING id"
            ),
            {"s": f"cap-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()


def test_concurrent_claims_never_exceed_the_cap(engine):
    """Two browser tabs hitting Generate More at the same moment is the exact
    case this statement exists for; a read-then-write would let both through."""
    # Real connections, not the rollback-wrapped fixture: concurrency cannot be
    # observed inside a single transaction.
    own_engine = create_engine(TEST_DATABASE_URL, pool_size=16, max_overflow=4)
    Session = sessionmaker(bind=own_engine)

    merchant_id = _merchant_id(own_engine)
    token = uuid.uuid4().hex
    session_id = _seed_session(own_engine, merchant_id, token)

    def claim() -> int | None:
        session = Session()
        try:
            granted = session.execute(CLAIM, {"session_id": session_id, "cap": CAP, "attempt_cap": 999}).scalar()
            session.commit()
            return granted
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: claim(), range(12)))

    granted = sorted(value for value in results if value is not None)
    denied = [value for value in results if value is None]

    assert granted == [1, 2, 3, 4, 5], granted
    assert len(denied) == 7

    with own_engine.begin() as conn:
        final = conn.execute(
            text("SELECT generation_count FROM smart_review_sessions WHERE token = :t"),
            {"t": token},
        ).scalar_one()

    assert final == CAP

    with own_engine.begin() as conn:
        conn.execute(text("DELETE FROM smart_review_sessions WHERE token = :t"), {"t": token})
        conn.execute(text("DELETE FROM merchants WHERE id = :m"), {"m": merchant_id})

    own_engine.dispose()


def test_returning_value_is_the_generation_number(engine):
    """Callers must take the generation number from RETURNING. Sessions use
    expire_on_commit=False, so a previously loaded ORM instance keeps reporting
    a stale count, and SELECT max()+1 would collide under concurrency."""
    own_engine = create_engine(TEST_DATABASE_URL)
    merchant_id = _merchant_id(own_engine)
    token = uuid.uuid4().hex
    session_id = _seed_session(own_engine, merchant_id, token)

    with own_engine.begin() as conn:
        first = conn.execute(CLAIM, {"session_id": session_id, "cap": CAP, "attempt_cap": 999}).scalar()
        second = conn.execute(CLAIM, {"session_id": session_id, "cap": CAP, "attempt_cap": 999}).scalar()

    assert (first, second) == (1, 2)

    with own_engine.begin() as conn:
        conn.execute(text("DELETE FROM smart_review_sessions WHERE token = :t"), {"t": token})
        conn.execute(text("DELETE FROM merchants WHERE id = :m"), {"m": merchant_id})

    own_engine.dispose()
