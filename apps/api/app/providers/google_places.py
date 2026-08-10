"""Places API (New) and Geocoding, over HTTP.

The legacy Places API is closed to new projects, so this targets the `v1`
endpoints exclusively. Both take the key in a header or query string rather
than a signed request, which is why the key must be API-restricted and
quota-capped in the console — see config.google_api_key.
"""

from decimal import Decimal

import httpx

from app.config import get_settings
from app.geo import bounding_box
from app.providers.places_base import (
    GeocodeResult,
    PlaceDetails,
    PlaceResult,
    PlacesQuery,
    ProviderError,
    SearchPage,
    rating_hint,
)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Field masks are mandatory and they are the bill: every field named here moves
# the request into the SKU tier that field belongs to. Add nothing casually.
SEARCH_FIELDS = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.primaryTypeDisplayName",
        "nextPageToken",
    )
)

# No `places.` prefix: Place Details returns one resource, not a collection.
DETAILS_FIELDS = ",".join(
    (
        "id",
        "displayName",
        "formattedAddress",
        "addressComponents",
        "nationalPhoneNumber",
        "websiteUri",
        "googleMapsUri",
        "rating",
        "userRatingCount",
        "primaryTypeDisplayName",
        "editorialSummary",
        "dineIn",
        "takeout",
        "delivery",
        "outdoorSeating",
        "servesVegetarianFood",
        "goodForChildren",
        "allowsDogs",
        "reservable",
    )
)

# Google's boolean attribute name -> the phrase that reads sensibly as a
# selling point. Only the true ones are ever used.
ATTRIBUTE_LABELS = {
    "dineIn": "dine-in",
    "takeout": "takeout",
    "delivery": "delivery",
    "outdoorSeating": "outdoor seating",
    "servesVegetarianFood": "vegetarian options",
    "goodForChildren": "good for children",
    "allowsDogs": "dog friendly",
    "reservable": "takes reservations",
}

# Which addressComponent type feeds which column.
_COMPONENTS = {
    "locality": "city",
    "administrative_area_level_1": "province_state",
    "postal_code": "postal_code",
    "country": "country",
}


def _decimal(value: object) -> Decimal | None:
    """Google sends a float; numeric(2,1) should not inherit its noise."""
    if value is None:
        return None
    return Decimal(str(value))


def _text(node: object) -> str | None:
    """displayName and editorialSummary are {text, languageCode} objects."""
    if isinstance(node, dict):
        return node.get("text")
    return None


def request_timeout(budget: float) -> httpx.Timeout:
    """Split a per-request budget across httpx's phases.

    A bare `timeout=X` gives *every* phase X, so one request can burn 4X and the
    search budget in config.py — which multiplies this by the number of requests
    — would understate its worst case by the same factor. The shares sum to the
    budget instead.

    Read takes most of it because that is where Google's latency is, and a
    search that aborts on a slow `searchText` is a 502 for a request that was
    going to succeed. Write and pool are near-zero phases and are funded like
    it: the request body is a few hundred bytes of JSON, and the pool is one
    provider per process against httpx's default of 100 connections, so nothing
    ever queues for one.

    These bound a phase, never the response: `read` limits the gap between
    chunks, so a body trickled slower than the whole budget still outlives
    every value here. The wall clock is bounded in app.services.leads.search.
    """
    return httpx.Timeout(
        None,
        connect=budget * 0.25,
        read=budget * 0.65,
        write=budget * 0.05,
        pool=budget * 0.05,
    )


class GooglePlacesProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._key = settings.google_api_key
        self._client = httpx.Client(
            timeout=request_timeout(settings.lead_search_timeout_seconds)
        )

    def _post(self, url: str, body: dict, field_mask: str) -> dict:
        return self._request("POST", url, field_mask=field_mask, json=body)

    def _get(
        self,
        url: str,
        field_mask: str | None = None,
        params: dict | None = None,
        *,
        key_in_header: bool = True,
    ) -> dict:
        return self._request(
            "GET", url, field_mask=field_mask, key_in_header=key_in_header, params=params
        )

    def _request(
        self,
        method: str,
        url: str,
        field_mask: str | None,
        *,
        key_in_header: bool = True,
        **kwargs,
    ) -> dict:
        if not self._key:
            raise ProviderError("GOOGLE_API_KEY is not set")

        # Only the v1 Places endpoints read X-Goog-Api-Key. The legacy geocode
        # endpoint ignores it and takes ?key= instead, so sending both would
        # read as if the key were header-only while it still lands in every
        # intermediate access log.
        headers = {"X-Goog-Api-Key": self._key} if key_in_header else {}
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask

        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            # The body carries Google's own reason (bad field mask, exhausted
            # quota, disabled API); the bare status alone is unactionable.
            raise ProviderError(
                f"google returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(str(exc)) from exc

    # --- geocoding ---------------------------------------------------------

    def geocode(self, query: str) -> GeocodeResult | None:
        payload = self._get(
            GEOCODE_URL,
            params={"address": query, "key": self._key},
            key_in_header=False,
        )
        status = payload.get("status")

        # Status is judged before emptiness, never alongside it. REQUEST_DENIED
        # and OVER_QUERY_LIMIT also arrive with an empty results array, and
        # reading those as "no such place" would send the operator off to fix a
        # postal code when the real fault is the key or the bill.
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            raise ProviderError(f"geocode returned {status}")
        if not payload.get("results"):
            return None

        top = payload["results"][0]
        location = top.get("geometry", {}).get("location", {})
        if "lat" not in location or "lng" not in location:
            raise ProviderError("geocode result carried no coordinates")

        return GeocodeResult(
            query=query,
            formatted=top.get("formatted_address", query),
            lat=float(location["lat"]),
            lng=float(location["lng"]),
        )

    # --- search ------------------------------------------------------------

    def search(self, query: PlacesQuery) -> SearchPage:
        # A rectangle, not a circle: searchText's locationRestriction accepts
        # only rectangles and rejects `circle` with INVALID_ARGUMENT. The true
        # radius is applied by the service, which already measures distance.
        low_lat, low_lng, high_lat, high_lng = bounding_box(
            query.lat, query.lng, query.radius_m
        )

        body: dict[str, object] = {
            "textQuery": query.text_query,
            "pageSize": query.page_size,
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": low_lat, "longitude": low_lng},
                    "high": {"latitude": high_lat, "longitude": high_lng},
                }
            },
        }
        if query.included_type:
            body["includedType"] = query.included_type
            # Left off deliberately: it keeps only places whose *primary* type
            # is the included type, which drops a sushi_restaurant from a
            # restaurant search.
            body["strictTypeFiltering"] = False
        if query.min_rating is not None:
            body["minRating"] = rating_hint(query.min_rating)
        if query.page_token:
            # Every other parameter must stay identical to the first call, or
            # Google rejects the token.
            body["pageToken"] = query.page_token

        payload = self._post(SEARCH_URL, body, SEARCH_FIELDS)

        return SearchPage(
            results=[_result(place) for place in payload.get("places", [])],
            next_page_token=payload.get("nextPageToken"),
        )

    # --- details -----------------------------------------------------------

    def details(self, place_id: str) -> PlaceDetails:
        payload = self._get(
            DETAILS_URL.format(place_id=place_id), field_mask=DETAILS_FIELDS
        )
        return _details(payload)


def _result(place: dict) -> PlaceResult:
    location = place.get("location") or {}
    return PlaceResult(
        place_id=place.get("id", ""),
        name=_text(place.get("displayName")) or "",
        category=_text(place.get("primaryTypeDisplayName")),
        address=place.get("formattedAddress"),
        lat=location.get("latitude"),
        lng=location.get("longitude"),
        rating=_decimal(place.get("rating")),
        review_count=place.get("userRatingCount"),
        phone=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
    )


def _details(place: dict) -> PlaceDetails:
    parts: dict[str, str | None] = {name: None for name in _COMPONENTS.values()}
    for component in place.get("addressComponents", []):
        for type_ in component.get("types", []):
            column = _COMPONENTS.get(type_)
            if column and parts[column] is None:
                # shortText for the province so the column holds "BC" rather
                # than "British Columbia", matching the seeded merchants.
                parts[column] = (
                    component.get("shortText")
                    if column == "province_state"
                    else component.get("longText")
                )

    attributes = [
        label for key, label in ATTRIBUTE_LABELS.items() if place.get(key) is True
    ]

    return PlaceDetails(
        place_id=place.get("id", ""),
        name=_text(place.get("displayName")) or "",
        category=_text(place.get("primaryTypeDisplayName")),
        address=place.get("formattedAddress"),
        city=parts["city"],
        province_state=parts["province_state"],
        postal_code=parts["postal_code"],
        country=parts["country"],
        phone=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
        maps_uri=place.get("googleMapsUri"),
        rating=_decimal(place.get("rating")),
        review_count=place.get("userRatingCount"),
        editorial_summary=_text(place.get("editorialSummary")),
        attributes=attributes,
    )
