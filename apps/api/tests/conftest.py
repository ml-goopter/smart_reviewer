import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Tests run against a real Postgres rather than SQLite: the schema depends on
# JSONB, gen_random_uuid(), partial indexes, a composite foreign key with a
# column-list SET NULL, and the atomic conditional UPDATE that enforces the
# generation cap. None of those behave the same on SQLite, so an in-memory
# substitute would pass while production broke.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://reviewer:reviewer@db:5432/reviewer_test",
)

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def engine():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    # Built by running the migration, not Base.metadata.create_all: the
    # migration is what production executes, and hand-edits to it (the circular
    # FK is added by hand) would otherwise be untested.
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def client(db):
    """A TestClient whose requests run inside the test's rolled-back
    transaction, so endpoint tests leave no rows behind."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def merchant(db):
    from app.models import Merchant, MerchantReviewContext

    record = Merchant(
        slug="pho37-test",
        name="Pho 37",
        category="Vietnamese Restaurant",
        google_review_url="https://example.test/writereview",
        status="ACTIVE",
    )
    db.add(record)
    db.flush()

    db.add(
        MerchantReviewContext(
            merchant_id=record.id,
            business_summary="Family-run Vietnamese restaurant.",
            selling_points=["large portions", "fast service"],
            experience_topics=["food", "service", "atmosphere", "value"],
            is_approved=True,
        )
    )
    db.flush()
    return record


@pytest.fixture
def db(engine) -> Session:
    """A session wrapped in a transaction that is always rolled back, so tests
    share one schema without leaking rows into each other.

    autoflush=False matches the production SessionLocal; without it the seed
    script's select() would flush pending state at a different moment here than
    it does in production.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        # Endpoints call db.commit(). Without this the commit would end the
        # outer transaction and defeat the rollback; with it, each commit
        # releases a savepoint instead, so the test still isolates cleanly
        # while the endpoint's real commit path is exercised.
        join_transaction_mode="create_savepoint",
    )()

    try:
        yield session
    finally:
        session.close()
        # A test that asserts a constraint violation leaves the transaction
        # already aborted, so rolling back unconditionally warns.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
