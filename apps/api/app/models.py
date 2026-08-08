import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Status and event vocabularies are varchar + CHECK rather than native Postgres
# enums: adding a value to a PG enum needs its own migration and cannot be done
# inside a transaction on older versions, whereas a CHECK is a one-line ALTER.
MERCHANT_STATUSES = ("ACTIVE", "INACTIVE", "ARCHIVED")

# No EXPIRED: expires_at is authoritative and evaluated on every read, and with
# no background job nothing would ever write that row state. A session that has
# passed its expiry is simply one whose expires_at is in the past.
SESSION_STATUSES = ("ACTIVE", "COMPLETED", "DISABLED")

# Only what the server actually witnesses. Editing happens in the browser and
# stays there, so there is no SUGGESTION_EDITED; whether the review reached the
# clipboard rides in SESSION_COMPLETED's metadata.
EVENT_TYPES = (
    "SESSION_CREATED",
    "SESSION_OPENED",
    "SUGGESTIONS_GENERATED",
    "SUGGESTION_SELECTED",
    "SESSION_COMPLETED",
    "GENERATION_FAILED",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    """Render `col IN ('A', 'B')` with escaping.

    Naive tuple interpolation produces `IN ('X',)` for a single value, which is
    a syntax error, and breaks outright on any value containing an apostrophe.
    """
    rendered = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"{column} IN ({rendered})"


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    province_state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(120))

    google_place_id: Mapped[str | None] = mapped_column(String(255))
    google_profile_url: Mapped[str | None] = mapped_column(Text)
    # Nullable in the schema but required in practice: the session service
    # refuses to create a session without one. Keeping it nullable lets a
    # merchant be seeded before its Google listing has been linked.
    google_review_url: Mapped[str | None] = mapped_column(Text)

    # Server defaults, not just Python-side ones, so a psql fixup or any future
    # non-ORM insert path cannot produce a NOT NULL violation on a column the
    # spec documents as having a default.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE"
    )

    # Stable identifier for the seed script to upsert on. Not exposed publicly;
    # the QR code carries the uuid so merchant ids stay opaque.
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        CheckConstraint(
            _in_clause("status", MERCHANT_STATUSES), name="ck_merchants_status"
        ),
        # Partial unique: many merchants may have no Google listing yet, and a
        # plain UNIQUE would let only one of them hold NULL in some engines.
        Index(
            "merchants_google_place_id_idx",
            "google_place_id",
            unique=True,
            postgresql_where=text("google_place_id IS NOT NULL"),
        ),
    )


class MerchantReviewContext(Base):
    __tablename__ = "merchant_review_context"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    business_summary: Mapped[str | None] = mapped_column(Text)
    products: Mapped[list | None] = mapped_column(JSONB)
    services: Mapped[list | None] = mapped_column(JSONB)
    menu_items: Mapped[list | None] = mapped_column(JSONB)
    selling_points: Mapped[list | None] = mapped_column(JSONB)
    approved_keywords: Mapped[list | None] = mapped_column(JSONB)
    # Drives the one-topic-per-suggestion rotation. When empty the generator
    # falls back to a generic set that reads sensibly outside hospitality.
    experience_topics: Mapped[list | None] = mapped_column(JSONB)
    custom_instructions: Mapped[str | None] = mapped_column(Text)

    is_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SmartReviewSession(Base):
    __tablename__ = "smart_review_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )

    # Stored in plaintext. Nothing behind this token is confidential — merchant
    # name, category, and the public Google URL — so hashing would guard a prize
    # not worth taking, while costing the ability to trace a session from a URL
    # a customer reports. Security rests on 256 bits of entropy, expiry, and the
    # generation cap.
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ACTIVE'"), default="ACTIVE"
    )

    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    first_opened_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_opened_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    # The cost control. Incremented by an atomic conditional UPDATE so the cap
    # holds across workers and instances without any shared cache. Callers must
    # take the new value from that statement's RETURNING clause — the session
    # is configured with expire_on_commit=False, so a previously loaded ORM
    # instance keeps reporting the stale count.
    generation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    suggestion_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )

    # Never refunded, unlike generation_count. A failed generation gives the
    # slot back so a provider outage does not burn a real customer's allowance
    # — but without a second, monotonic counter that forgiveness makes failures
    # free and infinitely repeatable, so anyone holding one token could drive
    # unlimited paid provider calls. This is the hard ceiling on spend.
    generation_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )

    selected_suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )

    google_redirected_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    created_ip_hash: Mapped[str | None] = mapped_column(String(64))
    session_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)

    # The session is the only identifier the browser sends after creation, so
    # the merchant is always resolved through this relationship. A merchant id
    # from the client is never trusted again once a session exists.
    merchant: Mapped["Merchant"] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(
            _in_clause("status", SESSION_STATUSES), name="ck_sessions_status"
        ),
        CheckConstraint("length(token) > 0", name="ck_sessions_token_not_blank"),
        # Turns a buggy decrement into an error instead of silently handing out
        # free generations past the cap.
        CheckConstraint(
            "open_count >= 0 AND generation_count >= 0 AND suggestion_count >= 0 "
            "AND generation_attempts >= 0",
            name="ck_sessions_counts_non_negative",
        ),
        # Composite FK, not a plain reference to suggestions.id: it makes the
        # database itself reject a session pointing at another session's
        # suggestion, which is the one real authorization rule in the system.
        # The column list on SET NULL (Postgres 15+) is required — a bare SET
        # NULL would try to null this session's own primary key.
        ForeignKeyConstraint(
            ["selected_suggestion_id", "id"],
            ["smart_review_suggestions.id", "smart_review_suggestions.session_id"],
            name="fk_session_selected_suggestion",
            use_alter=True,
            ondelete="SET NULL (selected_suggestion_id)",
        ),
        Index("smart_review_sessions_merchant_idx", "merchant_id"),
        Index("smart_review_sessions_expiry_idx", "expires_at"),
        # The create-session rate guard counts recent rows per IP on the hottest
        # write path; without this it is a sequential scan of the largest table.
        Index(
            "smart_review_sessions_ip_created_idx", "created_ip_hash", "created_at"
        ),
        # Scanned once per deleted suggestion by the SET NULL above.
        Index("smart_review_sessions_selected_idx", "selected_suggestion_id"),
    )


class SmartReviewSuggestion(Base):
    __tablename__ = "smart_review_suggestions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("smart_review_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )

    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text_: Mapped[str] = mapped_column("text", Text, nullable=False)

    # Which experience angle this suggestion was asked to cover. Never rendered.
    # It exists so selected_at becomes interpretable: knowing customers pick the
    # service card three times as often as the value card is the most actionable
    # thing the pilot can teach us about the prompt.
    topic: Mapped[str | None] = mapped_column(String(60))

    model_provider: Mapped[str | None] = mapped_column(String(60))
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(30))

    selected_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        # Positions are renumbered 1..n when only some of a batch validates, so
        # a batch may be shorter than three — but never sparse or duplicated.
        UniqueConstraint(
            "session_id",
            "generation_number",
            "position",
            name="uq_suggestion_session_generation_position",
        ),
        # Referenced by the sessions composite FK above. Redundant with the
        # primary key for uniqueness, but Postgres requires a unique constraint
        # on exactly the referenced column pair.
        UniqueConstraint("id", "session_id", name="uq_suggestion_id_session"),
        CheckConstraint("generation_number >= 1", name="ck_suggestion_generation_number"),
        CheckConstraint("position >= 1", name="ck_suggestion_position"),
        CheckConstraint("length(btrim(text)) > 0", name="ck_suggestion_text_not_blank"),
        # No standalone session_id index: it would be a strict leftmost prefix
        # of this one, so it would cost writes and serve no read.
        Index(
            "smart_review_suggestions_session_generation_idx",
            "session_id",
            "generation_number",
        ),
    )


class SmartReviewEvent(Base):
    __tablename__ = "smart_review_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("smart_review_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("smart_review_suggestions.id", ondelete="SET NULL")
    )

    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = _created_at()

    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    device_session_id: Mapped[str | None] = mapped_column(String(64))
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        CheckConstraint(
            _in_clause("event_type", EVENT_TYPES), name="ck_events_event_type"
        ),
        Index("smart_review_events_session_time_idx", "session_id", "created_at"),
        Index("smart_review_events_merchant_time_idx", "merchant_id", "created_at"),
        Index("smart_review_events_type_time_idx", "event_type", "created_at"),
    )
