"""The lead crawler's API.

Unauthenticated, deliberately: auth is deferred for the prototype and nginx
proxies every /api/* path, so these endpoints are reachable by anyone who can
reach the host. What bounds the damage is the per-day quota on the Google key
and the fact that save accepts only a Place ID — see MVP-SPEC/lead-crawler-spec
§2.1.12.
"""

import logging
from threading import Lock
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.providers.fake_places import FakePlacesProvider
from app.providers.google_places import GooglePlacesProvider
from app.providers.places_base import PlacesProvider, ProviderError
from app.models import Merchant
from app.schemas import (
    LeadCategoriesResponse,
    LeadCategory,
    LeadSearchRequest,
    LeadSearchResponse,
    LeadSearchResult,
    MerchantContextResponse,
    ResolvedLocation,
    ReviewContextPayload,
    ReviewContextResponse,
    SavedMerchant,
    SavedMerchantsResponse,
    SaveMerchantRequest,
    SaveMerchantResponse,
    SubscribeRequest,
    SubscriptionResponse,
    SubscriptionStatusRequest,
)
from app.services import leads as lead_service
from app.services import subscriptions as subscription_service

# The same pattern the generator validates its own output against. A second
# copy of this rule would drift from the first.
from app.services.suggestions import _URL

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads")

# One provider per process, because its HTTP client holds a connection pool.
# Exposed as a dependency so a test substitutes a fake without patching this
# module. The lock is taken on every request, not only the first: `def`
# endpoints run in a threadpool, so two concurrent first requests would
# otherwise each build a provider and orphan one httpx.Client, which nothing
# ever closes. An uncontended lock around one null check costs less than the
# double-checked read that would skip it.
_provider: PlacesProvider | None = None
_provider_lock = Lock()


def get_places_provider() -> PlacesProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            # config refuses any other value at startup: this selects an
            # adapter, and falling back to Google on a typo would spend money
            # the operator thought they were not spending.
            _provider = (
                FakePlacesProvider()
                if get_settings().lead_provider == "fake"
                else GooglePlacesProvider()
            )
    return _provider


def merchant_url(merchant_id) -> str:
    """Composed per response, never stored: a domain change must not be a
    data migration."""
    return f"{get_settings().public_base_url.rstrip('/')}/m/{merchant_id}"


def _as_saved(merchant: Merchant) -> SavedMerchant:
    payload = SavedMerchant.model_validate(merchant)
    # Always present. The URL is derived from the merchant id and exists
    # whether or not it currently opens — whether it does is the subscription's
    # answer, and the operator reads that from the subscription itself.
    payload.url = merchant_url(merchant.id)
    return payload


@router.get("/categories", response_model=LeadCategoriesResponse)
def categories() -> LeadCategoriesResponse:
    """The dropdown's contents.

    Served rather than duplicated in the bundle: a category the SPA offers but
    the server rejects would be a 400 the operator cannot act on.
    """
    return LeadCategoriesResponse(
        categories=[
            LeadCategory(value=value, label=label)
            for value, label in lead_service.CATEGORIES.items()
        ]
    )


@router.post("/merchants", response_model=SaveMerchantResponse)
def save_merchant(
    payload: SaveMerchantRequest,
    response: Response,
    db: Session = Depends(get_db),
    provider: PlacesProvider = Depends(get_places_provider),
) -> SaveMerchantResponse:
    try:
        merchant, created = lead_service.save_merchant(db, provider, payload.place_id)
    except ProviderError as exc:
        log.warning("lead save failed for %s: %s", payload.place_id, exc)
        raise ApiError(502, "provider_unavailable") from None

    db.commit()

    # 201 only when a row was written. A caller re-saving a listing it already
    # holds should be able to tell the difference without comparing payloads.
    response.status_code = 201 if created else 200

    return SaveMerchantResponse(created=created, merchant=_as_saved(merchant))


@router.get("/merchants", response_model=SavedMerchantsResponse)
def list_merchants(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SavedMerchantsResponse:
    """No Google call. Without this, a URL not pasted in the moment is
    recoverable only by paying to find the same listing again."""
    return SavedMerchantsResponse(
        merchants=[
            _as_saved(merchant)
            for merchant in lead_service.saved_merchants(db, limit, offset)
        ]
    )


def _as_subscription(subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        status=subscription.status,
        expires_at=subscription.expires_at,
        last_valid_day=subscription_service.last_valid_day_of(subscription),
        duration=subscription.duration,
        duration_unit=subscription.duration_unit,
    )


@router.post(
    "/merchants/{merchant_id}/subscription", response_model=SubscriptionResponse
)
def subscribe(
    merchant_id: UUID,
    payload: SubscribeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Create or renew a term. This is what makes /m/:merchantId open.

    201 when the row was created, 200 when it was renewed — the same
    create-or-read distinction save already draws, and the caller does not have
    to compare payloads to tell which happened.
    """
    subscription, created = subscription_service.subscribe(
        db, merchant_id, payload.duration, payload.duration_unit
    )
    db.commit()

    response.status_code = 201 if created else 200
    return _as_subscription(subscription)


@router.patch(
    "/merchants/{merchant_id}/subscription", response_model=SubscriptionResponse
)
def set_subscription_status(
    merchant_id: UUID,
    payload: SubscriptionStatusRequest,
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Suspend or resume. Separate from the verb above because a term change
    and a state change are different decisions with different consequences;
    one body for both invites a suspend that silently re-dates the term."""
    subscription = subscription_service.set_status(db, merchant_id, payload.status)
    db.commit()

    return _as_subscription(subscription)


@router.get("/merchants/{merchant_id}/context", response_model=MerchantContextResponse)
def get_context(
    merchant_id: UUID, db: Session = Depends(get_db)
) -> MerchantContextResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise ApiError(404, "merchant_not_found")

    context = lead_service.load_context(db, merchant_id)

    return MerchantContextResponse(
        merchant=_as_saved(merchant),
        context=(
            ReviewContextResponse.model_validate(context)
            if context is not None
            else ReviewContextResponse()
        ),
    )


@router.put("/merchants/{merchant_id}/context", response_model=ReviewContextResponse)
def put_context(
    merchant_id: UUID,
    payload: ReviewContextPayload,
    db: Session = Depends(get_db),
) -> ReviewContextResponse:
    """Replaces all eight fields. An empty box clears, it does not omit."""
    # Rejected here rather than in a Pydantic validator so the operator gets a
    # code they can act on. An instruction like "always mention our website
    # example.com" makes every generated suggestion fail URL validation, which
    # breaks that merchant permanently and silently — the same failure seed.py
    # refuses at onboarding, using this same pattern.
    if payload.custom_instructions and _URL.search(payload.custom_instructions):
        raise ApiError(400, "instructions_contain_url")

    context = lead_service.replace_context(
        db, merchant_id, payload.model_dump(exclude_unset=False)
    )
    if context is None:
        raise ApiError(404, "merchant_not_found")

    db.commit()
    return ReviewContextResponse.model_validate(context)


@router.post("/search", response_model=LeadSearchResponse)
def search(
    payload: LeadSearchRequest,
    db: Session = Depends(get_db),
    provider: PlacesProvider = Depends(get_places_provider),
) -> LeadSearchResponse:
    if payload.category and payload.category not in lead_service.CATEGORIES:
        raise ApiError(400, "unknown_category")

    if (
        payload.min_rating is not None
        and payload.max_rating is not None
        and payload.min_rating > payload.max_rating
    ):
        raise ApiError(400, "invalid_rating_range")

    criteria = lead_service.SearchCriteria(
        location=payload.location,
        radius_m=payload.radius_meters,
        text_query=payload.text_query,
        category=payload.category,
        min_rating=payload.min_rating,
        max_rating=payload.max_rating,
        max_review_count=payload.max_review_count,
    )

    try:
        outcome = lead_service.search(db, provider, criteria)
    except lead_service.CriteriaTooBroad:
        raise ApiError(400, "criteria_too_broad") from None
    except lead_service.LocationNotFound:
        raise ApiError(400, "location_not_found") from None
    except ProviderError as exc:
        # Google's own message never reaches the client — it can name the key,
        # the quota, or the project. It does reach the log, because without it
        # a 502 is indistinguishable between an unset key, an unenabled API, an
        # exhausted quota and a malformed request, and the operator has nothing
        # to act on.
        log.warning("lead search failed: %s", exc)
        raise ApiError(502, "provider_unavailable") from None

    return LeadSearchResponse(
        resolved_location=ResolvedLocation(
            query=outcome.resolved.query,
            formatted=outcome.resolved.formatted,
            lat=outcome.resolved.lat,
            lng=outcome.resolved.lng,
        ),
        searched=outcome.searched,
        matched=outcome.matched,
        partial=outcome.partial,
        truncated=outcome.truncated,
        results=[
            LeadSearchResult(
                place_id=hit.place.place_id,
                name=hit.place.name,
                category=hit.place.category,
                address=hit.place.address,
                distance_meters=hit.distance_m,
                rating=float(hit.place.rating) if hit.place.rating is not None else None,
                review_count=hit.place.review_count,
                phone=hit.place.phone,
                website=hit.place.website,
                saved=hit.saved,
                merchant_id=hit.merchant_id,
                subscription=hit.subscription,
                url=(
                    merchant_url(hit.merchant_id)
                    if hit.merchant_id is not None
                    else None
                ),
            )
            for hit in outcome.results
        ],
    )
