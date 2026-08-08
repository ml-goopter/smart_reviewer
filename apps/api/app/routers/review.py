from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.client_ip import client_ip
from app.db import get_db
from app.models import SmartReviewSuggestion
from app.providers.base import SuggestionProvider
from app.providers.openai_compat import OpenAICompatProvider
from app.schemas import (
    CompleteSessionRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    GenerateSuggestionsResponse,
    PublicMerchant,
    PublicSession,
    PublicSuggestion,
    SelectSuggestionRequest,
    SelectSuggestionResponse,
    SessionResponse,
)
from app.services import sessions as session_service
from app.services import suggestions as suggestion_service

router = APIRouter(prefix="/api/review")

# Built once per process; the SDK client holds a connection pool. Exposed as a
# dependency so tests can substitute a stub without patching module globals.
_provider: SuggestionProvider | None = None


def get_provider() -> SuggestionProvider:
    global _provider
    if _provider is None:
        _provider = OpenAICompatProvider()
    return _provider


@router.post("/sessions", status_code=201, response_model=CreateSessionResponse)
def create_session(
    payload: CreateSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> CreateSessionResponse:
    session = session_service.create_session(
        db, payload.merchant_id, client_ip(request)
    )
    db.commit()

    return CreateSessionResponse(token=session.token)


@router.get("/sessions/{token}", response_model=SessionResponse)
def get_session(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Validates and loads. Never generates.

    Generation is a paid, multi-second provider call; putting it here would
    mean a link-preview crawler or a refresh spends money before a human has
    arrived, and would make the merchant's name wait on the AI. The client asks
    for the first batch separately.
    """
    session = session_service.load_valid_session(db, token)
    merchant = session.merchant

    session_service.mark_opened(
        db,
        session,
        ip_hash=session_service.hash_ip(client_ip(request)),
        user_agent=request.headers.get("user-agent"),
    )

    suggestions = db.scalars(
        select(SmartReviewSuggestion)
        .where(SmartReviewSuggestion.session_id == session.id)
        # Only the newest batch: the customer is looking at three cards, and
        # earlier generations are history, not current options.
        .where(
            SmartReviewSuggestion.generation_number
            == select(SmartReviewSuggestion.generation_number)
            .where(SmartReviewSuggestion.session_id == session.id)
            .order_by(SmartReviewSuggestion.generation_number.desc())
            .limit(1)
            .scalar_subquery()
        )
        .order_by(SmartReviewSuggestion.position)
    ).all()

    db.commit()

    return SessionResponse(
        merchant=PublicMerchant(name=merchant.name, category=merchant.category),
        session=PublicSession(expires_at=session.expires_at),
        suggestions=[
            PublicSuggestion(id=item.id, text=item.text_) for item in suggestions
        ],
        google_review_url=merchant.google_review_url or "",
    )


@router.post(
    "/sessions/{token}/suggestions",
    status_code=201,
    response_model=GenerateSuggestionsResponse,
)
def generate_suggestions(
    token: str,
    db: Session = Depends(get_db),
    provider: SuggestionProvider = Depends(get_provider),
) -> GenerateSuggestionsResponse:
    session = session_service.load_valid_session(db, token)

    stored = suggestion_service.generate(db, session, provider)
    db.commit()

    return GenerateSuggestionsResponse(
        suggestions=[PublicSuggestion(id=item.id, text=item.text_) for item in stored]
    )


@router.post("/sessions/{token}/select", response_model=SelectSuggestionResponse)
def select_suggestion(
    token: str,
    payload: SelectSuggestionRequest,
    db: Session = Depends(get_db),
) -> SelectSuggestionResponse:
    session = session_service.load_valid_session(db, token)

    session_service.select_suggestion(db, session, payload.suggestion_id)
    db.commit()

    return SelectSuggestionResponse(selected=True)


@router.post("/sessions/{token}/complete", status_code=204)
async def complete_session(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Best-effort. Fired during page unload and never awaited by the client.

    The body is parsed by hand rather than declared as a Pydantic parameter,
    because a declared body is a *required* one: no body, an empty body, a body
    truncated by unload, or `navigator.sendBeacon`'s `text/plain` content type
    would each 400. All four are normal for a request the contract calls
    optional and fires during navigation, and the client never sees the
    response, so rejecting them only loses analytics.

    Recording completion must never revoke access either: a customer who
    reaches Google and presses back has to find their session intact, so this
    writes a milestone and nothing that validation reads.
    """
    session = session_service.load_valid_session(db, token)
    payload = await _parse_complete_body(request)

    session_service.complete_session(
        db, session, payload.suggestion_id, payload.review_copied
    )
    db.commit()

    return Response(status_code=204)


async def _parse_complete_body(request: Request) -> CompleteSessionRequest:
    try:
        raw = await request.body()
        if not raw.strip():
            return CompleteSessionRequest()
        return CompleteSessionRequest.model_validate_json(raw)
    except (ValueError, UnicodeDecodeError):
        # A malformed beacon still means "the customer left for Google"; the
        # milestone is worth more than the payload.
        return CompleteSessionRequest()
