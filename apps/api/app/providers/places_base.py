"""The seam between the lead crawler and Google.

Everything that makes a search *useful* — the rating ceiling, the review-count
cap, pagination, the funnel counts, distance — lives outside this file, in
app.services.leads. A places provider only fetches: one page, one place, one
geocode. That split is the same one the AI provider already has, and it is why
the whole crawler is testable without a key and without a network.

`ProviderError` is deliberately shared with the AI provider: nothing above the
provider layer should import a vendor's exception types, whichever vendor it is.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from math import floor
from typing import Protocol

from app.providers.base import ProviderError

__all__ = [
    "GeocodeResult",
    "PlaceDetails",
    "PlaceResult",
    "PlacesProvider",
    "PlacesQuery",
    "ProviderError",
    "SearchPage",
    "rating_hint",
]


def rating_hint(min_rating: float) -> float:
    """The coarse floor a provider is actually asked for.

    Google honours minRating in 0.5 steps only, and which way it rounds is
    unconfirmed (spec §2.1.17), so the hint is floored to a step: sent as-is, a
    4.2 floor rounded up is applied as 4.5 and the 4.2-to-4.4 listings never
    arrive. Flooring is safe under either rule. The exact floor the operator
    asked for is applied in app.services.leads.matches.

    It lives here rather than in the Google adapter because every provider owes
    the service the same behaviour: a fake that filters on the exact floor hides
    the band those two filters exist to hand off between.
    """
    return floor(min_rating * 2) / 2


@dataclass(frozen=True)
class GeocodeResult:
    """What a postal code, city or address resolved to.

    `formatted` is echoed to the operator on every search. A typo otherwise
    searches the wrong suburb and returns a plausible list of the wrong
    merchants, with nothing on screen to suggest anything went wrong.
    """

    query: str
    formatted: str
    lat: float
    lng: float


@dataclass(frozen=True)
class PlacesQuery:
    """One page's worth of request. The service decides how many pages to ask for."""

    text_query: str
    lat: float
    lng: float
    radius_m: int
    included_type: str | None = None
    min_rating: float | None = None
    page_size: int = 20
    page_token: str | None = None


@dataclass(frozen=True)
class PlaceResult:
    """A search hit. Rating and review count may be absent on new listings."""

    place_id: str
    name: str
    category: str | None
    address: str | None
    lat: float | None
    lng: float | None
    rating: Decimal | None
    review_count: int | None
    phone: str | None
    website: str | None


@dataclass(frozen=True)
class SearchPage:
    results: list[PlaceResult]
    next_page_token: str | None = None


@dataclass(frozen=True)
class PlaceDetails:
    """Everything save needs, from the one call it makes.

    `attributes` holds only the atmosphere booleans Google reported **true**;
    a false and an absent one are the same thing to us, and neither belongs in
    a selling point.
    """

    place_id: str
    name: str
    category: str | None = None
    address: str | None = None
    city: str | None = None
    province_state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    phone: str | None = None
    website: str | None = None
    maps_uri: str | None = None
    rating: Decimal | None = None
    review_count: int | None = None
    editorial_summary: str | None = None
    attributes: list[str] = field(default_factory=list)


class PlacesProvider(Protocol):
    """The entire surface a places provider has to implement."""

    def geocode(self, query: str) -> GeocodeResult | None:
        """Resolve free text to a point, or None when Google knows no such place."""
        ...

    def search(self, query: PlacesQuery) -> SearchPage:
        """One page. Pagination is the caller's business."""
        ...

    def details(self, place_id: str) -> PlaceDetails: ...
