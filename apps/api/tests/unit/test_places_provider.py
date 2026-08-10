"""The Google adapter's two jobs: build the request, parse the response.

Every call is served by an httpx MockTransport, so these assert on the exact
bytes that would go to Google without a key, a network, or a bill.
"""

from decimal import Decimal

import httpx
import pytest

from app.geo import haversine_m
from app.providers.fake_places import FakePlacesProvider
from app.providers.google_places import GooglePlacesProvider
from app.providers.places_base import PlacesQuery, ProviderError

SEARCH_BODY = {
    "places": [
        {
            "id": "ChIJsushi",
            "displayName": {"text": "Sushi Mura", "languageCode": "en"},
            "primaryTypeDisplayName": {"text": "Sushi Restaurant"},
            "formattedAddress": "120 No 3 Rd, Richmond, BC",
            "location": {"latitude": 49.17, "longitude": -123.13},
            "rating": 4.2,
            "userRatingCount": 187,
            "nationalPhoneNumber": "(604) 555-0100",
            "websiteUri": "https://example.test",
        }
    ],
    "nextPageToken": "TOKEN2",
}

DETAILS_BODY = {
    "id": "ChIJsushi",
    "displayName": {"text": "Sushi Mura"},
    "primaryTypeDisplayName": {"text": "Sushi Restaurant"},
    "formattedAddress": "120 No 3 Rd, Richmond, BC V6X 1T3, Canada",
    "addressComponents": [
        {"longText": "Richmond", "shortText": "Richmond", "types": ["locality"]},
        {
            "longText": "British Columbia",
            "shortText": "BC",
            "types": ["administrative_area_level_1"],
        },
        {"longText": "V6X 1T3", "shortText": "V6X 1T3", "types": ["postal_code"]},
        {"longText": "Canada", "shortText": "CA", "types": ["country"]},
    ],
    "nationalPhoneNumber": "(604) 555-0100",
    "websiteUri": "https://example.test",
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "rating": 4.2,
    "userRatingCount": 187,
    "editorialSummary": {"text": "Long-running sushi counter."},
    "dineIn": True,
    "takeout": True,
    "delivery": False,
    "allowsDogs": False,
}


def provider_serving(handler, monkeypatch, key: str = "test-key"):
    """A GooglePlacesProvider whose transport is `handler`."""
    from app import config

    monkeypatch.setenv("GOOGLE_API_KEY", key)
    config.get_settings.cache_clear()

    provider = GooglePlacesProvider()
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app import config

    yield
    config.get_settings.cache_clear()


# --- the time one call may take ---------------------------------------------


def test_the_client_is_built_from_the_configured_budget(monkeypatch):
    """The setting has to reach the client that makes the calls: a default
    httpx.Client has no timeout at all on three of the four phases."""
    from app import config
    from app.providers.google_places import request_timeout

    monkeypatch.setenv("LEAD_SEARCH_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    config.get_settings.cache_clear()

    provider = GooglePlacesProvider()
    try:
        timeout = provider._client.timeout
    finally:
        provider._client.close()

    assert timeout == request_timeout(6.0)


def test_the_budget_is_spent_where_googles_latency_is(monkeypatch):
    """The shipped seconds, pinned so a rebalance is a deliberate edit.

    Read is the phase that decides whether a search survives: a `searchText` at
    p99 aborting the whole search is a 502 for a request that was going to
    succeed. Write sends a few hundred bytes of JSON and the pool is never
    contended — one provider per process against httpx's default of 100
    connections — so neither is worth funding at read's expense. Connect covers
    a cold TCP+TLS handshake, and it is paid once per process because the
    client is reused across pages."""
    from app.providers.google_places import request_timeout

    timeout = request_timeout(8.0)

    assert (timeout.connect, timeout.read) == (2.0, 5.2)
    assert (timeout.write, timeout.pool) == (0.4, 0.4)
    assert timeout.read > sum((timeout.connect, timeout.write, timeout.pool))
    # The reason for splitting at all: a bare `timeout=X` gives every phase X,
    # so one call could burn 4X while config.py budgets it at X per call.
    assert sum((timeout.connect, timeout.read, timeout.write, timeout.pool)) <= 8.0


# --- request construction --------------------------------------------------


def test_search_sends_the_box_type_and_rating_floor(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(
            text_query="Sushi Mura omakase",
            lat=49.1745,
            lng=-123.1370,
            radius_m=5000,
            included_type="restaurant",
            min_rating=3.5,
            page_size=20,
        )
    )

    body = seen["json"]
    assert body["textQuery"] == "Sushi Mura omakase"
    assert body["includedType"] == "restaurant"
    assert body["minRating"] == 3.5
    assert body["pageSize"] == 20
    assert seen["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "places.userRatingCount" in seen["headers"]["X-Goog-FieldMask"]

    # A rectangle. searchText rejects `circle` here with INVALID_ARGUMENT —
    # circles belong to searchNearby and to locationBias.
    rectangle = body["locationRestriction"]["rectangle"]
    assert set(rectangle) == {"low", "high"}
    assert rectangle["low"]["latitude"] < 49.1745 < rectangle["high"]["latitude"]
    assert rectangle["low"]["longitude"] < -123.1370 < rectangle["high"]["longitude"]


def test_the_restriction_is_never_a_circle(monkeypatch):
    """The shape Google refuses. Pinned because the failure is a 400 from
    Google, invisible to any test that only checks our own consistency."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(text_query="", lat=49.0, lng=-123.0, radius_m=5000)
    )

    assert "circle" not in seen["json"]["locationRestriction"]


def test_the_rectangle_encloses_the_requested_radius(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(text_query="", lat=49.1745, lng=-123.137, radius_m=5000)
    )

    box = seen["json"]["locationRestriction"]["rectangle"]
    # Due north of the centre, at exactly the radius, must be inside the box:
    # a box that clipped the circle would hide merchants that are in range.
    north = haversine_m(49.1745, -123.137, box["high"]["latitude"], -123.137)
    east = haversine_m(49.1745, -123.137, 49.1745, box["high"]["longitude"])
    assert north >= 5000
    assert east >= 5000


def test_strict_type_filtering_is_off_so_subtypes_survive(monkeypatch):
    """A sushi_restaurant must still appear under a `restaurant` search."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(
            text_query="", lat=49.0, lng=-123.0, radius_m=1000,
            included_type="restaurant",
        )
    )

    assert seen["json"]["strictTypeFiltering"] is False


def test_omitted_filters_are_absent_not_null(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(PlacesQuery(text_query="cafe", lat=49.0, lng=-123.0, radius_m=800))

    assert "includedType" not in seen["json"]
    assert "minRating" not in seen["json"]
    assert "pageToken" not in seen["json"]


def test_the_rating_floor_is_rounded_down_to_a_step_google_honours(monkeypatch):
    """minRating moves in 0.5 steps. Sent as 4.2 it is applied as 4.5 and the
    4.2-to-4.4 listings never arrive; app.services.leads.matches then has
    nothing left to filter and the funnel blames the operator's own criteria."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=SEARCH_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(text_query="sushi", lat=49.0, lng=-123.0, radius_m=800, min_rating=4.2)
    )

    assert seen["json"]["minRating"] == 4.0


def test_page_token_rides_with_the_original_criteria(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"places": []})

    provider = provider_serving(handler, monkeypatch)
    provider.search(
        PlacesQuery(
            text_query="cafe", lat=49.0, lng=-123.0, radius_m=800,
            min_rating=4.0, page_token="TOKEN2",
        )
    )

    assert seen["json"]["pageToken"] == "TOKEN2"
    assert seen["json"]["minRating"] == 4.0


# --- response parsing ------------------------------------------------------


def test_search_parses_results_and_next_page_token(monkeypatch):
    provider = provider_serving(
        lambda request: httpx.Response(200, json=SEARCH_BODY), monkeypatch
    )
    page = provider.search(
        PlacesQuery(text_query="sushi", lat=49.0, lng=-123.0, radius_m=5000)
    )

    assert page.next_page_token == "TOKEN2"
    result = page.results[0]
    assert result.place_id == "ChIJsushi"
    assert result.name == "Sushi Mura"
    assert result.category == "Sushi Restaurant"
    assert result.review_count == 187
    # Decimal, not float: the column is numeric(2,1) and 4.2 has no exact
    # binary representation to inherit.
    assert result.rating == Decimal("4.2")
    assert isinstance(result.rating, Decimal)


def test_search_tolerates_a_listing_with_no_rating(monkeypatch):
    body = {"places": [{"id": "x", "displayName": {"text": "New Place"}}]}
    provider = provider_serving(
        lambda request: httpx.Response(200, json=body), monkeypatch
    )
    result = provider.search(
        PlacesQuery(text_query="", lat=49.0, lng=-123.0, radius_m=100)
    ).results[0]

    assert result.rating is None
    assert result.review_count is None
    assert result.address is None


def test_details_maps_components_and_true_attributes_only(monkeypatch):
    provider = provider_serving(
        lambda request: httpx.Response(200, json=DETAILS_BODY), monkeypatch
    )
    details = provider.details("ChIJsushi")

    assert details.city == "Richmond"
    # shortText for the province, matching the seeded merchants' "BC".
    assert details.province_state == "BC"
    assert details.postal_code == "V6X 1T3"
    assert details.country == "Canada"
    assert details.editorial_summary == "Long-running sushi counter."
    assert details.attributes == ["dine-in", "takeout"]


def test_details_field_mask_has_no_places_prefix(monkeypatch):
    """Place Details returns one resource; a `places.` prefix is rejected."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["mask"] = request.headers["X-Goog-FieldMask"]
        return httpx.Response(200, json=DETAILS_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.details("ChIJsushi")

    assert "places." not in seen["mask"]
    assert seen["mask"].startswith("id,")


# --- geocoding -------------------------------------------------------------


def test_geocode_returns_the_top_hit(monkeypatch):
    body = {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Richmond, BC V6X 1T3, Canada",
                "geometry": {"location": {"lat": 49.1745, "lng": -123.137}},
            }
        ],
    }
    provider = provider_serving(
        lambda request: httpx.Response(200, json=body), monkeypatch
    )
    resolved = provider.geocode("V6X 1T3")

    assert resolved.formatted == "Richmond, BC V6X 1T3, Canada"
    assert (resolved.lat, resolved.lng) == (49.1745, -123.137)
    assert resolved.query == "V6X 1T3"


def test_geocode_sends_the_key_only_where_it_is_read(monkeypatch):
    """The legacy geocode endpoint honours ?key= and ignores X-Goog-Api-Key.
    Sending the header too would read as if the key never touched the query
    string, which is exactly where it necessarily ends up — and in every
    intermediate access log with it."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["url"] = request.url
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

    provider = provider_serving(handler, monkeypatch)
    provider.geocode("V6X 1T3")

    assert "X-Goog-Api-Key" not in seen["headers"]
    assert seen["url"].params["key"] == "test-key"


def test_the_places_endpoints_keep_the_key_out_of_the_query_string(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["url"] = request.url
        return httpx.Response(200, json=DETAILS_BODY)

    provider = provider_serving(handler, monkeypatch)
    provider.details("ChIJsushi")

    assert seen["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "key" not in seen["url"].params


def test_geocode_zero_results_is_none_not_an_error(monkeypatch):
    """The operator typed a place that does not exist. That is a 400 upstream,
    not a provider failure."""
    body = {"status": "ZERO_RESULTS", "results": []}
    provider = provider_serving(
        lambda request: httpx.Response(200, json=body), monkeypatch
    )

    assert provider.geocode("nowhere at all") is None


def test_geocode_other_statuses_raise(monkeypatch):
    body = {"status": "REQUEST_DENIED", "results": []}
    provider = provider_serving(
        lambda request: httpx.Response(200, json=body), monkeypatch
    )

    with pytest.raises(ProviderError, match="REQUEST_DENIED"):
        provider.geocode("V6X 1T3")


# --- failures --------------------------------------------------------------


def test_http_error_carries_googles_reason(monkeypatch):
    provider = provider_serving(
        lambda request: httpx.Response(429, text="quota exceeded"), monkeypatch
    )

    with pytest.raises(ProviderError, match="429.*quota exceeded"):
        provider.search(PlacesQuery(text_query="", lat=49.0, lng=-123.0, radius_m=100))


def test_missing_key_fails_before_any_request(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be made without a key")

    provider = provider_serving(handler, monkeypatch, key="")

    with pytest.raises(ProviderError, match="GOOGLE_API_KEY"):
        provider.details("anything")


# --- the fake --------------------------------------------------------------


def test_fake_paginates_with_tokens():
    provider = FakePlacesProvider()
    first = provider.search(
        PlacesQuery(text_query="", lat=49.1745, lng=-123.137, radius_m=50_000, page_size=3)
    )
    second = provider.search(
        PlacesQuery(
            text_query="", lat=49.1745, lng=-123.137, radius_m=50_000, page_size=3,
            page_token=first.next_page_token,
        )
    )

    assert len(first.results) == 3
    assert first.next_page_token == "3"
    assert {r.place_id for r in first.results}.isdisjoint(
        {r.place_id for r in second.results}
    )


def test_fake_honours_radius_and_rating_floor():
    richmond_only = FakePlacesProvider().search(
        PlacesQuery(text_query="", lat=49.1745, lng=-123.137, radius_m=5000, page_size=20)
    )
    assert "fake-harbour-salon" not in {r.place_id for r in richmond_only.results}

    rated = FakePlacesProvider().search(
        PlacesQuery(
            text_query="", lat=49.1745, lng=-123.137, radius_m=50_000,
            min_rating=4.0, page_size=20,
        )
    )
    # An unrated listing cannot satisfy a rating floor, which is how Google
    # behaves — it is a filter, not a sort.
    assert "fake-new-noodle" not in {r.place_id for r in rated.results}
    assert all(float(r.rating) >= 4.0 for r in rated.results)


def test_fake_can_simulate_a_failure_partway_through():
    provider = FakePlacesProvider(fail_after_page=1)
    query = PlacesQuery(
        text_query="", lat=49.1745, lng=-123.137, radius_m=50_000, page_size=2
    )

    provider.search(query)
    with pytest.raises(ProviderError):
        provider.search(query)


def test_fake_addresses_are_the_same_on_every_run():
    """The docstring promises fixed answers. hash() on a str is salted per
    process, so a hash-derived address differs across restarts and between
    workers of the same deployment."""
    assert FakePlacesProvider().details("fake-sushi-mura").address == "8892 No 3 Rd"


def test_a_fixture_is_written_once_and_served_as_written():
    """The type and the coordinates come from the same call that builds the
    details, so there is no second copy to disagree with the one served."""
    from app.providers.fake_places import _place

    provider = FakePlacesProvider(
        places=[
            _place(
                "fake-solo", "Solo Cafe", "Cafe", "cafe",
                49.1745, -123.137, "4.0", 5,
            )
        ]
    )

    result = provider.search(
        PlacesQuery(
            text_query="", lat=49.1745, lng=-123.137, radius_m=100,
            included_type="cafe",
        )
    ).results[0]

    assert (result.lat, result.lng) == (49.1745, -123.137)
    assert result.place_id == "fake-solo"


def test_fake_geocode_has_an_unresolvable_sentinel():
    provider = FakePlacesProvider()

    assert provider.geocode("nowhere") is None
    assert provider.geocode("V6X 1T3").formatted.startswith("Richmond")
    # Anything unrecognised still resolves, and says so.
    assert "fake provider" in provider.geocode("12 Somewhere St").formatted
