from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import SmartReviewEvent, SmartReviewSession


def record(
    db: Session,
    session: SmartReviewSession,
    event_type: str,
    *,
    suggestion_id: UUID | None = None,
    ip_hash: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SmartReviewEvent:
    """Append one row to the activity log.

    merchant_id is copied from the session rather than accepted as an argument:
    passing it separately is how a caller ends up attributing an event to the
    wrong merchant and quietly corrupting the funnel.
    """
    event = SmartReviewEvent(
        session_id=session.id,
        merchant_id=session.merchant_id,
        suggestion_id=suggestion_id,
        event_type=event_type,
        ip_hash=ip_hash,
        user_agent=user_agent,
        event_metadata=metadata,
    )
    db.add(event)
    return event
