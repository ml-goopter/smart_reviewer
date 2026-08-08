"""The browser-facing merchant entry route.

This is the only endpoint a customer's browser reaches by scanning or typing
rather than by JavaScript, and the only one that answers with a redirect
instead of JSON. It exists so the permanent QR code can encode a URL that never
expires while the session behind it does.

Every response here is rendered directly by the browser, so no path through
this module may produce an error document.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.client_ip import client_ip
from app.db import get_db
from app.errors import ApiError
from app.services import sessions as session_service

router = APIRouter()

UNAVAILABLE = "/unavailable"
# Rate limiting is transient and is not the merchant's private information, so
# it is the one failure the customer is told apart from the rest — the
# unavailable copy is terminal ("ask the business for assistance") and would be
# wrong advice for a condition that clears on its own. The SPA reads this and
# shows retryable copy.
BUSY = "/unavailable?retry=1"


def _redirect(location: str) -> RedirectResponse:
    """302, never 301 or 308.

    A permanent redirect is cached by the browser, so the *second* scan of the
    same QR code would skip this endpoint entirely and reuse the first scan's
    token — which by then is very likely expired or belongs to a different
    customer. `no-store` is the same defence against intermediary caches.
    """
    response = RedirectResponse(url=location, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    # The SPA's own noindex meta tag never applies here: this response is a
    # redirect, not a document. Without this, the permanent QR URL is indexable
    # and every crawl mints a session against the per-IP budget.
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# HEAD as well as GET: FastAPI does not register HEAD for a GET route the way
# plain Starlette does, and link unfurlers and some QR scanners probe with HEAD
# first — a 405 there reads as a dead link. It mints a session exactly as GET
# does, which is no worse: an unfurled GET already does the same, and the per-IP
# limit is what bounds both.
@router.api_route("/m/{merchant_id}", methods=["GET", "HEAD"])
def merchant_entry(
    merchant_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Mint a session for a merchant and send the customer to it.

    `merchant_id` is taken as `str` and parsed by hand rather than declared as
    a `UUID` parameter: a declared one fails validation into the JSON error
    handler, and a customer who scanned a QR code would be looking at a raw
    error document.
    """
    try:
        parsed = UUID(merchant_id)
    except ValueError:
        return _redirect(UNAVAILABLE)

    try:
        session = session_service.create_session(db, parsed, client_ip(request))
    except ApiError as error:
        # Unknown, inactive, archived, and missing-a-Google-URL are one
        # destination: which applies is the merchant's private information, and
        # the customer can act on none of them. Rate limiting is neither, and
        # gets its own — see BUSY.
        #
        # Anything that is not an ApiError propagates: a database outage is an
        # alert, and dressing it up as an unavailable merchant would hide a real
        # failure behind a plausible business explanation.
        return _redirect(BUSY if error.status_code == 429 else UNAVAILABLE)

    db.commit()

    # Relative, never absolute. An absolute URL built from the request would
    # carry whatever Host the proxy passed through, and inside the compose
    # network that is `api:8000` — a hostname the customer's browser cannot
    # resolve.
    return _redirect(f"/r/{session.token}")


# A truncated or partly obscured QR, a scanner that drops the last segment, or
# somebody typing the domain and half the path. Registered after the route
# above, so the specific match still wins.
@router.api_route("/m", methods=["GET", "HEAD"])
@router.api_route("/m/{rest:path}", methods=["GET", "HEAD"])
def malformed_entry() -> RedirectResponse:
    """Anything under /m that is not a single merchant id.

    Without this the customer gets Starlette's `{"detail":"Not Found"}`, which
    is the raw error document the rest of this module exists to avoid.
    """
    return _redirect(UNAVAILABLE)
