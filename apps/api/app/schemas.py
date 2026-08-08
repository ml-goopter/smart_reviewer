"""Public API shapes.

Everything here crosses the boundary to an untrusted browser, so the response
models are allowlists: they name the fields that may leave, rather than
excluding the ones that may not. A field added to a database model therefore
cannot leak by default.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class CompleteSessionRequest(BaseModel):
    """Sent during page unload with keepalive, so it must tolerate anything —
    a missing body, a partial body, or no suggestion at all when the customer
    skipped the suggestions entirely."""

    model_config = ConfigDict(extra="ignore")

    suggestion_id: UUID | None = Field(default=None, alias="suggestionId")
    review_copied: bool = Field(default=False, alias="reviewCopied")
