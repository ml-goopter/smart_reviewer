"""Creating, renewing and suspending a merchant's subscription.

The arithmetic lives in subscription_terms; this module is the database side of
it — one row per merchant, mutated in place.
"""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import SUBSCRIPTION_STATUSES, Merchant, Subscription
from app.services.subscription_terms import (
    UnsupportedDurationUnit,
    compute_expires_at,
    last_valid_day,
)


def operator_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().operator_timezone)


def _load(db: Session, merchant_id: UUID) -> Subscription | None:
    return db.scalar(
        select(Subscription).where(Subscription.merchant_id == merchant_id)
    )


def _require_merchant(db: Session, merchant_id: UUID) -> Merchant:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise ApiError(404, "merchant_not_found")
    return merchant


def subscribe(
    db: Session, merchant_id: UUID, duration: int, duration_unit: str
) -> tuple[Subscription, bool]:
    """Create or renew. Returns the row and whether it was created.

    One entry point for both because `merchant_id` is unique — there is exactly
    one row to write, and the caller has no reason to know which it did.

    Renewal moves `expires_at` and nothing else. In particular it does not
    reactivate a suspended subscription: extending a term and reopening the URL
    are separate decisions, and folding them together would mean every renewal
    silently un-cancelled a merchant somebody had cancelled on purpose.
    """
    _require_merchant(db, merchant_id)

    if duration <= 0:
        raise ApiError(400, "invalid_request")

    existing = _load(db, merchant_id)
    tz = operator_timezone()

    try:
        expires_at = compute_expires_at(
            existing.expires_at if existing else None,
            duration,
            duration_unit,
            datetime.now(UTC),
            tz,
        )
    except UnsupportedDurationUnit:
        # Its own code rather than invalid_request: the value is valid and will
        # one day work, and a caller that cannot tell the two apart will read a
        # temporary limitation as a bug in its own payload.
        raise ApiError(400, "unsupported_duration_unit") from None

    if existing is None:
        subscription = Subscription(
            merchant_id=merchant_id,
            expires_at=expires_at,
            duration=duration,
            duration_unit=duration_unit,
        )
        db.add(subscription)
        db.flush()
        return subscription, True

    existing.expires_at = expires_at
    existing.duration = duration
    existing.duration_unit = duration_unit
    db.flush()
    return existing, False


def set_status(db: Session, merchant_id: UUID, status: str) -> Subscription:
    """Suspend or resume. Never moves `expires_at`.

    The clock keeps running while a subscription is suspended, so resuming is
    this and nothing else. Crediting the suspended time back would mean storing
    when the pause began and handling pause-while-expired, double-pause and
    resume-after-expiry — three edge cases bought for a fairness the operator
    can deliver with a renewal instead.
    """
    _require_merchant(db, merchant_id)

    if status not in SUBSCRIPTION_STATUSES:
        raise ApiError(400, "invalid_request")

    subscription = _load(db, merchant_id)
    if subscription is None:
        # Distinct from merchant_not_found: the merchant exists and the fix is
        # to subscribe it, which is a different call, not a corrected id.
        raise ApiError(404, "subscription_not_found")

    subscription.status = status
    db.flush()
    return subscription


def last_valid_day_of(subscription: Subscription) -> date:
    return last_valid_day(subscription.expires_at, operator_timezone())
