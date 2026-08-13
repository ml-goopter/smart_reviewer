import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import Merchant, SmartReviewSession, SmartReviewSuggestion
from app.services import events
from app.services.subscription_terms import is_active

# 32 bytes of entropy, urlsafe-encoded to 43 characters. The column allows 64.
TOKEN_BYTES = 32


def hash_ip(ip: str) -> str:
    """One-way, salted. The salt is what stops the hash from being a lookup
    table — the IPv4 space is small enough to enumerate in seconds otherwise,
    which would make an unsalted 'privacy-preserving' hash purely decorative."""
    salt = get_settings().ip_hash_salt
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def _rate_limit_exceeded(db: Session, ip_hash: str) -> bool:
    """Counted in the database rather than in process memory.

    In-memory counters are per-worker and per-instance, so `--workers 4` would
    silently quadruple the limit and a restart would reset it. This uses the
    (created_ip_hash, created_at) index and is correct regardless of how many
    API processes are running.
    """
    settings = get_settings()
    window_start = datetime.now(UTC) - timedelta(hours=1)

    recent = db.scalar(
        select(func.count())
        .select_from(SmartReviewSession)
        .where(
            SmartReviewSession.created_ip_hash == ip_hash,
            SmartReviewSession.created_at >= window_start,
        )
    )

    return (recent or 0) >= settings.create_rate_limit_per_hour


def create_session(db: Session, merchant_id: UUID, client_ip: str) -> SmartReviewSession:
    merchant = db.get(Merchant, merchant_id)

    if merchant is None:
        raise ApiError(404, "merchant_not_found")

    # Misconfigured rather than switched off: without this the customer would
    # reach the reviewer and then a dead end where Google should be.
    if not merchant.google_review_url:
        raise ApiError(409, "merchant_unavailable")

    # Whether the merchant is paid up. Checked here and nowhere else: expiry is
    # a clock running out at midnight, not somebody deliberately switching a
    # merchant off, so enforcing it per request would delete the review a
    # customer was typing at 23:59:58. A session, once minted, runs to its own
    # expiry; the exposure is bounded by SESSION_TTL_HOURS.
    #
    # No subscription at all is the same as an expired one. A gate that passes
    # when its data is missing is not a gate.
    subscription = merchant.subscription
    if subscription is None or not is_active(
        subscription.status, subscription.expires_at, datetime.now(UTC)
    ):
        raise ApiError(409, "merchant_unavailable")

    ip_hash = hash_ip(client_ip)
    if _rate_limit_exceeded(db, ip_hash):
        raise ApiError(429, "rate_limited")

    settings = get_settings()
    session = SmartReviewSession(
        merchant_id=merchant.id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        created_ip_hash=ip_hash,
    )
    db.add(session)
    db.flush()

    events.record(db, session, "SESSION_CREATED", ip_hash=ip_hash)

    return session


def load_valid_session(db: Session, token: str) -> SmartReviewSession:
    """The single validation path for every token-authenticated endpoint.

    Deliberately does not check `status`. Completion is a milestone, not a gate:
    a customer who reaches Google and presses back must find their session and
    their edited text still there. Access ends at expiry, which is the only
    thing the customer cannot influence by using the product normally.
    """
    session = db.scalar(
        select(SmartReviewSession).where(SmartReviewSession.token == token)
    )

    if session is None:
        raise ApiError(404, "session_not_found")

    if session.expires_at <= datetime.now(UTC):
        raise ApiError(410, "session_unavailable")

    # Re-checked on every request, not only at creation: a merchant that loses
    # its review URL mid-session would otherwise keep spending AI money and
    # then hand the customer an empty Google URL.
    #
    # The subscription is deliberately NOT re-checked here — see create_session.
    merchant = session.merchant
    if not merchant.google_review_url:
        raise ApiError(410, "session_unavailable")

    return session


def select_suggestion(
    db: Session, session: SmartReviewSession, suggestion_id: UUID
) -> None:
    suggestion = db.get(SmartReviewSuggestion, suggestion_id)

    if suggestion is None:
        raise ApiError(404, "suggestion_not_found")

    # The one real authorization rule in the system. A valid suggestion id from
    # somebody else's session must never be accepted — otherwise the id space
    # becomes a way to read or attach another customer's content. The composite
    # foreign key enforces this again at the database level; both are cheap and
    # this one produces the documented 409.
    if suggestion.session_id != session.id:
        raise ApiError(409, "suggestion_mismatch")

    session.selected_suggestion_id = suggestion.id
    if suggestion.selected_at is None:
        suggestion.selected_at = datetime.now(UTC)

    events.record(db, session, "SUGGESTION_SELECTED", suggestion_id=suggestion.id)


def complete_session(
    db: Session,
    session: SmartReviewSession,
    suggestion_id: UUID | None,
    review_copied: bool,
) -> None:
    """Records the handoff to Google.

    Tolerant by design: this arrives during page unload with keepalive, so a
    missing or stale suggestion id is normal and must not turn into an error
    that the client will never see anyway. A suggestion belonging to another
    session is ignored rather than rejected, for the same reason — but it is
    never written.
    """
    now = datetime.now(UTC)

    session.status = "COMPLETED"
    session.completed_at = session.completed_at or now
    session.google_redirected_at = session.google_redirected_at or now

    if suggestion_id is not None:
        suggestion = db.get(SmartReviewSuggestion, suggestion_id)
        if suggestion is not None and suggestion.session_id == session.id:
            session.selected_suggestion_id = suggestion.id
            if suggestion.selected_at is None:
                suggestion.selected_at = now

    events.record(
        db,
        session,
        "SESSION_COMPLETED",
        suggestion_id=session.selected_suggestion_id,
        metadata={"review_copied": review_copied},
    )


def mark_opened(db: Session, session: SmartReviewSession, ip_hash: str | None, user_agent: str | None) -> None:
    now = datetime.now(UTC)

    # SQL increment rather than a Python read-modify-write: concurrent opens
    # would otherwise each read the same value and write back the same total,
    # silently losing opens from the funnel.
    db.execute(
        sql_text(
            "UPDATE smart_review_sessions SET "
            "  open_count = open_count + 1, "
            "  last_opened_at = :now, "
            "  first_opened_at = COALESCE(first_opened_at, :now) "
            "WHERE id = :session_id"
        ),
        {"now": now, "session_id": session.id},
    )

    events.record(
        db, session, "SESSION_OPENED", ip_hash=ip_hash, user_agent=user_agent
    )
