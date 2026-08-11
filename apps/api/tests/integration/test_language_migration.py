"""The per-language migration, up and back down.

Every other integration test builds the schema by running `upgrade head` against
an empty database, so the branches that matter here — backfilling rows that
already exist, and the downgrade — are never executed by them. Both are the
paths that touch a live deployment's data.

Runs against its own database so that stepping the schema up and down cannot
disturb the session-scoped one every other test shares.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.integration.conftest import API_ROOT, TEST_DATABASE_URL

REVISION = "c7a2e91b4d63"
PREVIOUS = "b1d4c2f7a3e9"

DB_NAME = "reviewer_migration_test"


@pytest.fixture
def stepped():
    """A database at the revision *before* this one, with data in it."""
    base = TEST_DATABASE_URL.rsplit("/", 1)[0]
    url = f"{base}/{DB_NAME}"

    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    admin.dispose()

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, PREVIOUS)

    engine = create_engine(url)
    yield config, engine

    engine.dispose()
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin.dispose()


def seed(engine, generation_count: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A session that has already generated, as it looked before this revision."""
    with engine.begin() as conn:
        merchant_id = conn.execute(
            text(
                "INSERT INTO merchants (slug, name, google_review_url) VALUES "
                "(:s, 'Migration Test', 'https://example.test/r') RETURNING id"
            ),
            {"s": f"mig-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()

        session_id = conn.execute(
            text(
                "INSERT INTO smart_review_sessions "
                "    (merchant_id, token, expires_at, generation_count) "
                "VALUES (:m, :t, :e, :g) RETURNING id"
            ),
            {
                "m": merchant_id,
                "t": uuid.uuid4().hex,
                "e": datetime.now(UTC) + timedelta(hours=24),
                "g": generation_count,
            },
        ).scalar_one()

        for number in range(1, generation_count + 1):
            conn.execute(
                text(
                    "INSERT INTO smart_review_suggestions "
                    "    (session_id, merchant_id, generation_number, position, text) "
                    "VALUES (:s, :m, :g, 1, :t)"
                ),
                {
                    "s": session_id,
                    "m": merchant_id,
                    "g": number,
                    "t": f"An existing English suggestion, batch {number}.",
                },
            )

    return merchant_id, session_id


def test_existing_suggestions_are_backfilled_as_english(stepped):
    """They were written by an English-only prompt, so 'en' is the fact rather
    than a plausible guess."""
    config, engine = stepped
    _merchant_id, session_id = seed(engine, generation_count=2)

    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        languages = conn.execute(
            text(
                "SELECT DISTINCT language FROM smart_review_suggestions "
                "WHERE session_id = :i"
            ),
            {"i": session_id},
        ).scalars().all()

    assert languages == ["en"]


def test_a_session_mid_flight_keeps_the_generations_it_has_spent(stepped):
    """Without carrying the counter across, a customer who had already used
    their allowance would find a fresh one waiting after the deploy."""
    config, engine = stepped
    _merchant_id, session_id = seed(engine, generation_count=2)

    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT language, generation_count "
                "FROM smart_review_session_languages WHERE session_id = :i"
            ),
            {"i": session_id},
        ).all()

    assert rows == [("en", 2)]


def test_a_session_that_never_generated_gets_no_row(stepped):
    """No row and a zero mean the same thing to the claim statement, and the
    insert branch handles the missing one."""
    config, engine = stepped
    _merchant_id, session_id = seed(engine, generation_count=0)

    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM smart_review_session_languages "
                "WHERE session_id = :i"
            ),
            {"i": session_id},
        ).scalar()

    assert count == 0


def test_downgrade_sums_the_languages_back_into_one_counter(stepped):
    config, engine = stepped
    _merchant_id, session_id = seed(engine, generation_count=1)

    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO smart_review_session_languages "
                "    (session_id, language, generation_count) "
                "VALUES (:i, 'zh-Hant', 2)"
            ),
            {"i": session_id},
        )

    command.downgrade(config, PREVIOUS)

    with engine.begin() as conn:
        total = conn.execute(
            text("SELECT generation_count FROM smart_review_sessions WHERE id = :i"),
            {"i": session_id},
        ).scalar()

    # 1 English + 2 Chinese. Over the old per-session cap, which is the honest
    # answer: those batches were generated and paid for.
    assert total == 3


def test_downgrade_drops_suggestions_it_cannot_represent(stepped):
    """Two languages both hold a generation 1 position 1, which collides once
    language leaves the unique key. Dropping the non-English rows is the only
    way back, and it is destructive — which is why it is tested rather than
    discovered during a rollback."""
    config, engine = stepped
    merchant_id, session_id = seed(engine, generation_count=1)

    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO smart_review_suggestions "
                "    (session_id, merchant_id, generation_number, position, text, "
                "     language) "
                "VALUES (:s, :m, 1, 1, :t, 'zh-Hant')"
            ),
            {"s": session_id, "m": merchant_id, "t": "湯頭很濃郁，份量也很足。"},
        )

    command.downgrade(config, PREVIOUS)

    with engine.begin() as conn:
        remaining = conn.execute(
            text(
                "SELECT count(*) FROM smart_review_suggestions WHERE session_id = :i"
            ),
            {"i": session_id},
        ).scalar()

    assert remaining == 1, "the English row survives; the Chinese one cannot"


def test_upgrade_downgrade_upgrade_leaves_a_working_schema(stepped):
    """A rollback and a re-deploy is one incident, not two."""
    config, engine = stepped
    _merchant_id, session_id = seed(engine, generation_count=1)

    command.upgrade(config, REVISION)
    command.downgrade(config, PREVIOUS)
    command.upgrade(config, REVISION)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO smart_review_session_languages "
                "    (session_id, language, generation_count) "
                "VALUES (:i, 'zh-Hans', 1) "
                "ON CONFLICT (session_id, language) DO NOTHING"
            ),
            {"i": session_id},
        )
        languages = conn.execute(
            text(
                "SELECT DISTINCT language FROM smart_review_suggestions "
                "WHERE session_id = :i"
            ),
            {"i": session_id},
        ).scalars().all()

    assert languages == ["en"]
