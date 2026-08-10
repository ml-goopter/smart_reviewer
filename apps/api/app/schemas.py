"""Public API shapes.

Everything here crosses the boundary to an untrusted browser, so the response
models are allowlists: they name the fields that may leave, rather than
excluding the ones that may not. A field added to a database model therefore
cannot leak by default.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Bounds on the context an editor may store. The endpoint is unauthenticated by
# decision, and every item lands verbatim in the AI prompt on every generation,
# so an unbounded list is an unbounded per-generation bill for anyone who can
# reach the host.
MAX_CONTEXT_ITEMS = 50
MAX_CONTEXT_ITEM_CHARS = 200

ContextItem = Annotated[str, StringConstraints(max_length=MAX_CONTEXT_ITEM_CHARS)]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: UUID = Field(alias="merchantId")


class CreateSessionResponse(BaseModel):
    token: str


class PublicMerchant(BaseModel):
    """Deliberately omits id, google_place_id, google_profile_url, address, and
    every internal field. The customer already knows which business they are
    standing in; the API adds nothing by confirming its database identity."""

    name: str
    category: str | None = None


class PublicSession(BaseModel):
    expires_at: datetime = Field(serialization_alias="expiresAt")


class PublicSuggestion(BaseModel):
    id: UUID
    text: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    merchant: PublicMerchant
    session: PublicSession
    suggestions: list[PublicSuggestion]
    # Returned here so that continuing to Google never waits on a network
    # round-trip. The browser holds a server-chosen value; it never supplies one.
    google_review_url: str = Field(serialization_alias="googleReviewUrl")


class GenerateSuggestionsResponse(BaseModel):
    suggestions: list[PublicSuggestion]


class SelectSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: UUID = Field(alias="suggestionId")


class SelectSuggestionResponse(BaseModel):
    selected: bool = True


class LeadSearchRequest(BaseModel):
    """Criteria from the crawler UI.

    Bounds are declared here rather than checked in the service so a nonsense
    radius or a rating of 9 is refused before anything is billed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    location: str = Field(min_length=1, max_length=200)
    radius_meters: int = Field(alias="radiusMeters", ge=1, le=50_000)
    text_query: str | None = Field(default=None, alias="textQuery", max_length=200)
    category: str | None = Field(default=None, max_length=60)
    min_rating: float | None = Field(default=None, alias="minRating", ge=0, le=5)
    max_rating: float | None = Field(default=None, alias="maxRating", ge=0, le=5)
    max_review_count: int | None = Field(default=None, alias="maxReviewCount", ge=0)


class ResolvedLocation(BaseModel):
    """Echoed on every search. A typo'd postal code otherwise searches the
    wrong suburb and returns a plausible list of the wrong merchants."""

    query: str
    formatted: str
    lat: float
    lng: float


class LeadSearchResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    place_id: str = Field(serialization_alias="placeId")
    name: str
    category: str | None = None
    address: str | None = None
    distance_meters: int | None = Field(default=None, serialization_alias="distanceMeters")
    rating: float | None = None
    review_count: int | None = Field(default=None, serialization_alias="reviewCount")
    phone: str | None = None
    website: str | None = None
    saved: bool = False
    merchant_id: UUID | None = Field(default=None, serialization_alias="merchantId")
    status: str | None = None
    url: str | None = None


class LeadSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resolved_location: ResolvedLocation = Field(serialization_alias="resolvedLocation")
    # The funnel. Without both numbers a strict review-count cap produces a
    # nearly empty list that reads as a broken search rather than a narrow one.
    searched: int
    matched: int
    partial: bool = False
    # Google still had pages when LEAD_SEARCH_MAX_RESULTS was reached. Without
    # it a deliberately shortened list reads as everything Google had.
    truncated: bool = False
    results: list[LeadSearchResult]


class SaveMerchantRequest(BaseModel):
    """A Place ID and nothing else.

    The server re-fetches the listing rather than trusting fields from the
    browser, so an open endpoint cannot be used to write an invented merchant,
    and a stale tab cannot record last week's rating as today's fact."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    place_id: str = Field(alias="placeId", min_length=1, max_length=255)


class SavedMerchant(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: UUID
    name: str
    slug: str
    category: str | None = None
    address: str | None = None
    city: str | None = None
    status: str
    website: str | None = None
    google_place_id: str | None = Field(default=None, serialization_alias="googlePlaceId")
    google_rating: float | None = Field(default=None, serialization_alias="googleRating")
    google_review_count: int | None = Field(
        default=None, serialization_alias="googleReviewCount"
    )
    google_synced_at: datetime | None = Field(
        default=None, serialization_alias="googleSyncedAt"
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    # Composed per response from PUBLIC_BASE_URL, never stored — a domain
    # change must not be a data migration. Null for anything not ACTIVE, whose
    # URL redirects to /unavailable.
    url: str | None = None


class SaveMerchantResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created: bool
    merchant: SavedMerchant
    note: str | None = None


class SavedMerchantsResponse(BaseModel):
    merchants: list[SavedMerchant]


class ReviewContextPayload(BaseModel):
    """The eight fields the AI reads, and the only thing the editor writes.

    Merchant fields are absent on purpose: those are Google's facts, and a form
    that could overwrite them would leave no way to tell what came from Google.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    business_summary: str | None = Field(
        default=None, alias="businessSummary", max_length=4000
    )
    products: list[ContextItem] | None = Field(default=None, max_length=MAX_CONTEXT_ITEMS)
    services: list[ContextItem] | None = Field(default=None, max_length=MAX_CONTEXT_ITEMS)
    menu_items: list[ContextItem] | None = Field(
        default=None, alias="menuItems", max_length=MAX_CONTEXT_ITEMS
    )
    selling_points: list[ContextItem] | None = Field(
        default=None, alias="sellingPoints", max_length=MAX_CONTEXT_ITEMS
    )
    approved_keywords: list[ContextItem] | None = Field(
        default=None, alias="approvedKeywords", max_length=MAX_CONTEXT_ITEMS
    )
    experience_topics: list[ContextItem] | None = Field(
        default=None, alias="experienceTopics", max_length=MAX_CONTEXT_ITEMS
    )
    custom_instructions: str | None = Field(
        default=None, alias="customInstructions", max_length=4000
    )


class ReviewContextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    business_summary: str | None = Field(
        default=None, serialization_alias="businessSummary"
    )
    products: list[str] | None = None
    services: list[str] | None = None
    menu_items: list[str] | None = Field(default=None, serialization_alias="menuItems")
    selling_points: list[str] | None = Field(
        default=None, serialization_alias="sellingPoints"
    )
    approved_keywords: list[str] | None = Field(
        default=None, serialization_alias="approvedKeywords"
    )
    experience_topics: list[str] | None = Field(
        default=None, serialization_alias="experienceTopics"
    )
    custom_instructions: str | None = Field(
        default=None, serialization_alias="customInstructions"
    )


class MerchantContextResponse(BaseModel):
    merchant: SavedMerchant
    context: ReviewContextResponse


class LeadCategory(BaseModel):
    value: str
    label: str


class LeadCategoriesResponse(BaseModel):
    categories: list[LeadCategory]


class CompleteSessionRequest(BaseModel):
    """Sent during page unload with keepalive, so it must tolerate anything —
    a missing body, a partial body, or no suggestion at all when the customer
    skipped the suggestions entirely."""

    model_config = ConfigDict(extra="ignore")

    suggestion_id: UUID | None = Field(default=None, alias="suggestionId")
    review_copied: bool = Field(default=False, alias="reviewCopied")
