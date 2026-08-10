"""A places provider with no Google behind it.

Selected with LEAD_PROVIDER=fake. It exists so the crawler can be run and
demonstrated end to end without a billing account, and so every unit test
exercises the real service logic — pagination, filtering, the funnel, context
mapping — against a provider whose answers are fixed.

It imitates only what the service depends on: the radius restriction, the
rating floor, page tokens, and the shape of a Place Details payload. It is not
a Google emulator, and matching text does not pretend to be Google's ranking.
"""

from decimal import Decimal
from zlib import crc32

from app.geo import haversine_m
from app.providers.places_base import (
    GeocodeResult,
    PlaceDetails,
    PlaceResult,
    PlacesQuery,
    ProviderError,
    SearchPage,
    rating_hint,
)

# Resolves to nothing, so the "location Google does not know" path is
# reachable in dev without guessing at a string Google will also reject.
NO_SUCH_PLACE = "nowhere"

RICHMOND = GeocodeResult(
    query="V6X 1T3",
    formatted="Richmond, BC V6X 1T3, Canada",
    lat=49.1745,
    lng=-123.1370,
)

GEOCODES = {
    "v6x 1t3": RICHMOND,
    "richmond": RICHMOND,
    "v5k 0a1": GeocodeResult(
        query="V5K 0A1",
        formatted="Vancouver, BC V5K 0A1, Canada",
        lat=49.2827,
        lng=-123.1207,
    ),
    "vancouver": GeocodeResult(
        query="Vancouver",
        formatted="Vancouver, BC, Canada",
        lat=49.2827,
        lng=-123.1207,
    ),
}


def _place(
    place_id: str,
    name: str,
    category: str,
    primary_type: str,
    lat: float,
    lng: float,
    rating: str | None,
    reviews: int | None,
    *,
    city: str = "Richmond",
    postal: str = "V6X 3K1",
    summary: str | None = None,
    attributes: tuple[str, ...] = (),
    website: str | None = None,
) -> tuple[PlaceDetails, str, float, float]:
    """One listing, written once. The type and the coordinates are returned
    alongside the details rather than restated in the table below: two
    hand-maintained copies diverge, and the served answer wins silently."""
    details = PlaceDetails(
        place_id=place_id,
        name=name,
        category=category,
        # crc32, never hash(): str hashing is salted per process, so hash() gives
        # the same listing a different street number on every restart and a
        # different one per worker. These answers are fixed.
        address=f"{crc32(place_id.encode()) % 8000 + 1000} No 3 Rd",
        city=city,
        province_state="BC",
        postal_code=postal,
        country="Canada",
        phone="+1-604-555-0100",
        website=website,
        maps_uri=f"https://maps.google.com/?cid={place_id}",
        rating=Decimal(rating) if rating else None,
        review_count=reviews,
        editorial_summary=summary,
        attributes=list(attributes),
    )
    return details, primary_type, lat, lng


# Deliberately varied: listings with no rating at all, review counts either side
# of a typical cap, and one with no editorial summary so the fallback summary
# path is exercised by simply running the tool.
PLACES: list[tuple[PlaceDetails, str, float, float]] = [
    _place(
        "fake-sushi-mura", "Sushi Mura", "Sushi Restaurant", "sushi_restaurant",
        49.1701, -123.1372, "4.2", 187,
        summary="Long-running sushi counter known for chirashi bowls.",
        attributes=("dine-in", "takeout", "takes reservations"),
        website="https://sushimura.example.test",
    ),
    _place(
        "fake-pho-37", "Pho 37", "Vietnamese Restaurant", "vietnamese_restaurant",
        49.1830, -123.1145, "3.9", 64,
        attributes=("dine-in", "takeout", "good for children"),
    ),
    _place(
        "fake-green-basil", "Green Basil", "Thai Restaurant", "thai_restaurant",
        49.1622, -123.1401, "4.4", 142,
        summary="Neighbourhood Thai kitchen with a short, changing menu.",
        attributes=("dine-in", "delivery", "vegetarian options"),
    ),
    _place(
        "fake-copper-kettle", "Copper Kettle Cafe", "Cafe", "cafe",
        49.1766, -123.1290, "4.7", 892,
        attributes=("dine-in", "outdoor seating", "dog friendly"),
    ),
    _place(
        "fake-new-noodle", "New Noodle House", "Restaurant", "restaurant",
        49.1712, -123.1502, None, None,
    ),
    _place(
        "fake-riverside-grill", "Riverside Grill", "Restaurant", "restaurant",
        49.1955, -123.1010, "3.4", 51,
        attributes=("dine-in", "outdoor seating"),
    ),
    _place(
        "fake-lotus-bakery", "Lotus Bakery", "Bakery", "bakery",
        49.1688, -123.1338, "4.1", 39,
        attributes=("takeout",),
    ),
    _place(
        "fake-harbour-salon", "Harbour Hair Studio", "Hair Salon", "hair_salon",
        49.2801, -123.1180, "4.6", 118,
        city="Vancouver", postal="V5K 0A1",
        attributes=("takes reservations",),
    ),
]


class FakePlacesProvider:
    def __init__(
        self,
        places: list[tuple[PlaceDetails, str, float, float]] | None = None,
        geocodes: dict[str, GeocodeResult] | None = None,
        fail_after_page: int | None = None,
    ) -> None:
        """`fail_after_page` makes the provider raise once that many pages have
        been served, which is the only way to exercise the partial-results path
        without waiting for Google to actually fail."""
        self._places = PLACES if places is None else places
        self._geocodes = GEOCODES if geocodes is None else geocodes
        self._fail_after_page = fail_after_page
        self.pages_served = 0

    def geocode(self, query: str) -> GeocodeResult | None:
        key = query.strip().lower()
        if key == NO_SUCH_PLACE:
            return None
        found = self._geocodes.get(key)
        if found is not None:
            return found
        # Anything unrecognised still resolves, so a dev typing a real address
        # sees results rather than a dead end. The echoed `formatted` says so.
        return GeocodeResult(
            query=query,
            formatted=f"{query} (fake provider — not a real resolution)",
            lat=RICHMOND.lat,
            lng=RICHMOND.lng,
        )

    def search(self, query: PlacesQuery) -> SearchPage:
        if self._fail_after_page is not None and self.pages_served >= self._fail_after_page:
            raise ProviderError("fake provider: simulated Google failure")

        terms = [term for term in query.text_query.lower().split() if term]
        matched = [
            (details, lat, lng)
            for details, primary_type, lat, lng in self._places
            if self._matches(details, primary_type, terms, query)
            and haversine_m(query.lat, query.lng, lat, lng) <= query.radius_m
        ]

        start = int(query.page_token) if query.page_token else 0
        window = matched[start : start + query.page_size]
        next_start = start + query.page_size

        self.pages_served += 1
        return SearchPage(
            results=[_as_result(details, lat, lng) for details, lat, lng in window],
            next_page_token=str(next_start) if next_start < len(matched) else None,
        )

    def details(self, place_id: str) -> PlaceDetails:
        for details, _type, _lat, _lng in self._places:
            if details.place_id == place_id:
                return details
        raise ProviderError(f"fake provider: no place {place_id!r}")

    def _matches(
        self,
        details: PlaceDetails,
        primary_type: str,
        terms: list[str],
        query: PlacesQuery,
    ) -> bool:
        if query.included_type and query.included_type not in primary_type:
            return False
        # A rating floor excludes unrated listings, matching Google: minRating
        # is a filter, and an absent rating cannot satisfy it. The floor applied
        # is the 0.5 step Google is sent, not the operator's exact one — filter
        # on the exact floor and the band the service re-filters in `matches`
        # never reaches it, so the handoff between the two filters goes untested
        # and the funnel's `searched` looks smaller than Google would make it.
        if query.min_rating is not None:
            floor = rating_hint(query.min_rating)
            if details.rating is None or float(details.rating) < floor:
                return False
        if terms:
            haystack = f"{details.name} {details.category or ''}".lower()
            return any(term in haystack for term in terms)
        return True


def _as_result(details: PlaceDetails, lat: float, lng: float) -> PlaceResult:
    return PlaceResult(
        place_id=details.place_id,
        name=details.name,
        category=details.category,
        address=details.address,
        lat=lat,
        lng=lng,
        rating=details.rating,
        review_count=details.review_count,
        phone=details.phone,
        website=details.website,
    )
