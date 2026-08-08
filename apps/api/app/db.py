from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Sync engine and sessions throughout. The workload is a handful of short
# statements per request with one blocking AI call, so async would buy nothing
# here while making the atomic generation-count UPDATE harder to reason about.
# FastAPI runs `def` endpoints in a threadpool, which is sufficient at this size.
engine = create_engine(
    get_settings().database_url,
    # Containers get restarted and connections go stale; without this the first
    # request after an idle period fails instead of transparently reconnecting.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
