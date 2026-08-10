"""The crawler routes: criteria in, an allowlisted payload out.

The service is substituted, so these assert on translation — status codes,
camelCase, the error vocabulary, and the one thing the router itself decides:
which rows get a copyable URL.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import get_db
from app.main import app
from app.providers.places_base import GeocodeResult, PlaceResult, ProviderError
from app.routers.leads import get_places_provider
from app.services import leads as lead_service
from app.services.leads import LocationNotFound, SearchHit, SearchOutcome

RESOLVED = GeocodeResult(
    query="V6X 1T3", formatted="Richmond, BC V6X 1T3, Canada", lat=49.1745, lng=-123.137
)

BODY = {"location": "V6X 1T3", "radiusMeters": 5000}


def hit(place_id="a", **overrides):
    place = PlaceResult(
        place_id=place_id,
        name="Sushi Mura",
        category="Sushi Restaurant",
        address="120 No 3 Rd",
        lat=49.17,
        lng=-123.13,
        rating=None,
        review_count=187,
        phone="(604) 555-0100",
        website="https://example.test",
    )
    defaults = {"place": place, "distance_m": 1200, "saved": False}
    return SearchHit(**{**defaults, **overrides})


def outcome(results=(), **overrides):
    defaults = {
        "resolved": RESOLVED,
        "searched": 60,
        "matched": len(results),
        "partial": False,
        "results": list(results),
    }
    return SearchOutcome(**{**defaults, **overrides})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://reviews.example.test")
    config.get_settings.cache_clear()

    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_places_provider] = lambda: object()

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        config.get_settings.cache_clear()


def serve(monkeypatch, result):
    def _search(_db, _provider, _criteria):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(lead_service, "search", _search)


# --- the happy path ---------------------------------------------------------


def test_search_returns_the_funnel_and_camel_case_keys(client, monkeypatch):
    serve(monkeypatch, outcome([hit()]))

    body = client.post("/api/leads/search", json=BODY).json()

    assert body["searched"] == 60
    assert body["matched"] == 1
    assert body["partial"] is False
    assert body["resolvedLocation"]["formatted"] == "Richmond, BC V6X 1T3, Canada"
    result = body["results"][0]
    assert result["placeId"] == "a"
    assert result["distanceMeters"] == 1200
    assert result["reviewCount"] == 187


def test_a_partial_search_says_so(client, monkeypatch):
    serve(monkeypatch, outcome([hit()], searched=20, partial=True))

    body = client.post("/api/leads/search", json=BODY).json()

    assert body["partial"] is True
    assert body["searched"] == 20


def test_a_truncated_search_says_so(client, monkeypatch):
    """The operator asked for fewer results than Google had. Saying nothing
    makes the shorter list read as everything Google had."""
    serve(monkeypatch, outcome([hit()], searched=20, truncated=True))

    body = client.post("/api/leads/search", json=BODY).json()

    assert body["truncated"] is True
    assert body["partial"] is False


def test_criteria_reach_the_service_intact(client, monkeypatch):
    seen = {}

    def _search(_db, _provider, criteria):
        seen["criteria"] = criteria
        return outcome()

    monkeypatch.setattr(lead_service, "search", _search)

    client.post(
        "/api/leads/search",
        json={
            "location": "V6X 1T3", "radiusMeters": 5000,
            "textQuery": "Sushi Mura omakase", "category": "restaurant",
            "minRating": 3.5, "maxRating": 4.5, "maxReviewCount": 200,
        },
    )

    criteria = seen["criteria"]
    assert criteria.text_query == "Sushi Mura omakase"
    assert criteria.category == "restaurant"
    assert (criteria.min_rating, criteria.max_rating) == (3.5, 4.5)
    assert criteria.max_review_count == 200


# --- the URL the router itself decides --------------------------------------


def test_a_saved_active_row_carries_an_absolute_url(client, monkeypatch):
    merchant_id = uuid4()
    serve(monkeypatch, outcome([
        hit(saved=True, merchant_id=merchant_id, status="ACTIVE")
    ]))

    result = client.post("/api/leads/search", json=BODY).json()["results"][0]

    assert result["saved"] is True
    assert result["url"] == f"https://reviews.example.test/m/{merchant_id}"
    assert result["merchantId"] == str(merchant_id)


def test_an_archived_row_is_marked_saved_but_offers_no_url(client, monkeypatch):
    """Its URL redirects to /unavailable, so handing it over to copy would be
    handing over a dead link."""
    serve(monkeypatch, outcome([
        hit(saved=True, merchant_id=uuid4(), status="ARCHIVED")
    ]))

    result = client.post("/api/leads/search", json=BODY).json()["results"][0]

    assert result["saved"] is True
    assert result["status"] == "ARCHIVED"
    assert result["url"] is None


def test_an_unsaved_row_has_no_url(client, monkeypatch):
    serve(monkeypatch, outcome([hit()]))

    assert client.post("/api/leads/search", json=BODY).json()["results"][0]["url"] is None


# --- refusals ---------------------------------------------------------------


def test_an_unknown_category_is_refused_before_anything_is_billed(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        lead_service, "search", lambda *a: called.append(1) or outcome()
    )

    response = client.post(
        "/api/leads/search", json={**BODY, "category": "heliport"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "unknown_category"}
    assert called == []


def test_an_inverted_rating_range_is_refused(client, monkeypatch):
    serve(monkeypatch, outcome())

    response = client.post(
        "/api/leads/search", json={**BODY, "minRating": 4.5, "maxRating": 3.5}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_rating_range"}


def test_an_unresolvable_location_is_a_400_not_an_empty_list(client, monkeypatch):
    serve(monkeypatch, LocationNotFound("nowhere"))

    response = client.post("/api/leads/search", json=BODY)

    assert response.status_code == 400
    assert response.json() == {"error": "location_not_found"}


def test_a_provider_failure_is_502_and_says_nothing_about_google(client, monkeypatch):
    serve(monkeypatch, ProviderError("google returned 403: key disabled for project"))

    response = client.post("/api/leads/search", json=BODY)

    assert response.status_code == 502
    assert response.json() == {"error": "provider_unavailable"}


@pytest.mark.parametrize(
    "body",
    [
        {"location": "V6X 1T3", "radiusMeters": 0},
        {"location": "V6X 1T3", "radiusMeters": 50_001},
        {"location": "", "radiusMeters": 5000},
        {"radiusMeters": 5000},
        {"location": "V6X 1T3", "radiusMeters": 5000, "minRating": 9},
        {"location": "V6X 1T3", "radiusMeters": 5000, "maxReviewCount": -1},
        {"location": "V6X 1T3", "radiusMeters": 5000, "unexpected": "x"},
    ],
)
def test_out_of_bounds_criteria_are_rejected(client, monkeypatch, body):
    serve(monkeypatch, outcome())

    response = client.post("/api/leads/search", json=body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


# --- save -------------------------------------------------------------------


class CommitDb:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def stored(**overrides):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models import Merchant

    defaults = {
        "id": uuid4(),
        "name": "Sushi Mura",
        "slug": "sushi-mura-richmond",
        "category": "Sushi Restaurant",
        "address": "120 No 3 Rd",
        "city": "Richmond",
        "status": "ACTIVE",
        "website": "https://example.test",
        "google_place_id": "ChIJsushi",
        "google_rating": Decimal("4.2"),
        "google_review_count": 187,
        "google_synced_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
    }
    return Merchant(**{**defaults, **overrides})


@pytest.fixture
def saving(client, monkeypatch):
    db = CommitDb()
    app.dependency_overrides[get_db] = lambda: db

    def install(result):
        def _save(_db, _provider, _place_id):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(lead_service, "save_merchant", _save)
        return client, db

    return install


def test_a_new_merchant_is_201_with_a_copyable_url(saving):
    merchant = stored()
    client, db = saving((merchant, True))

    response = client.post("/api/leads/merchants", json={"placeId": "ChIJsushi"})
    body = response.json()

    assert response.status_code == 201
    assert body["created"] is True
    assert body["merchant"]["url"] == f"https://reviews.example.test/m/{merchant.id}"
    assert body["merchant"]["slug"] == "sushi-mura-richmond"
    assert body["note"] is None
    assert db.commits == 1


def test_a_known_merchant_is_200_with_the_same_url(saving):
    merchant = stored()
    client, _ = saving((merchant, False))

    response = client.post("/api/leads/merchants", json={"placeId": "ChIJsushi"})

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["merchant"]["url"].endswith(str(merchant.id))


def test_an_archived_merchant_offers_no_url_and_says_why(saving):
    client, _ = saving((stored(status="ARCHIVED"), False))

    body = client.post("/api/leads/merchants", json={"placeId": "ChIJsushi"}).json()

    assert body["merchant"]["url"] is None
    assert body["note"] == "archived — this URL will not open"


def test_the_slug_is_returned_so_the_operator_knows_it(saving):
    """It is the merchant's stable handle, and it is unique — someone naming a
    file or a query after it must not have to guess."""
    client, _ = saving((stored(), True))

    body = client.post("/api/leads/merchants", json={"placeId": "ChIJsushi"}).json()

    assert body["merchant"]["slug"] == "sushi-mura-richmond"


def test_the_snapshot_travels_with_its_date(saving):
    client, _ = saving((stored(), True))

    merchant = client.post(
        "/api/leads/merchants", json={"placeId": "ChIJsushi"}
    ).json()["merchant"]

    assert merchant["googleRating"] == 4.2
    assert merchant["googleReviewCount"] == 187
    assert merchant["googleSyncedAt"] is not None


def test_a_provider_failure_on_save_is_502(saving):
    client, _ = saving(ProviderError("google 500"))

    response = client.post("/api/leads/merchants", json={"placeId": "ChIJsushi"})

    assert response.status_code == 502
    assert response.json() == {"error": "provider_unavailable"}


@pytest.mark.parametrize(
    "body",
    [{}, {"placeId": ""}, {"placeId": "x", "name": "Invented Merchant"}],
)
def test_save_accepts_a_place_id_and_nothing_else(saving, body):
    client, _ = saving((stored(), True))

    response = client.post("/api/leads/merchants", json=body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


# --- the saved list ---------------------------------------------------------


def test_saved_merchants_are_listed_with_their_urls(client, monkeypatch):
    rows = [stored(name="Sushi Mura"), stored(name="Pho 37", status="INACTIVE")]
    monkeypatch.setattr(
        lead_service, "saved_merchants", lambda _db, limit, offset: rows
    )

    body = client.get("/api/leads/merchants").json()

    assert [m["name"] for m in body["merchants"]] == ["Sushi Mura", "Pho 37"]
    assert body["merchants"][0]["url"].startswith("https://reviews.example.test/m/")
    assert body["merchants"][1]["url"] is None


def test_paging_is_passed_through(client, monkeypatch):
    seen = {}

    def _list(_db, limit, offset):
        seen.update(limit=limit, offset=offset)
        return []

    monkeypatch.setattr(lead_service, "saved_merchants", _list)

    client.get("/api/leads/merchants?limit=10&offset=20")

    assert seen == {"limit": 10, "offset": 20}


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_nonsense_paging_is_refused(client, monkeypatch, query):
    monkeypatch.setattr(lead_service, "saved_merchants", lambda *a: [])

    assert client.get(f"/api/leads/merchants?{query}").status_code == 400


# --- categories -------------------------------------------------------------


def test_categories_are_served_rather_than_duplicated_in_the_bundle(client):
    body = client.get("/api/leads/categories").json()

    values = [category["value"] for category in body["categories"]]
    assert values == list(lead_service.CATEGORIES)
    assert {"value": "restaurant", "label": "Restaurant"} in body["categories"]


# --- which provider the process talks to ------------------------------------


@pytest.fixture
def provider_choice(monkeypatch):
    """The provider is memoised in a module global, so each test starts from an
    unbuilt one and leaves nothing behind for the next."""
    from app.routers import leads as leads_router

    monkeypatch.setattr(leads_router, "_provider", None)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    config.get_settings.cache_clear()
    try:
        yield leads_router
    finally:
        config.get_settings.cache_clear()


def test_the_fake_is_selected_by_name(provider_choice, monkeypatch):
    from app.providers.fake_places import FakePlacesProvider

    monkeypatch.setenv("LEAD_PROVIDER", "fake")
    config.get_settings.cache_clear()

    assert isinstance(provider_choice.get_places_provider(), FakePlacesProvider)


def test_google_is_selected_by_name(provider_choice, monkeypatch):
    from app.providers.google_places import GooglePlacesProvider

    monkeypatch.setenv("LEAD_PROVIDER", "google")
    config.get_settings.cache_clear()

    provider = provider_choice.get_places_provider()
    try:
        assert isinstance(provider, GooglePlacesProvider)
    finally:
        provider._client.close()


def test_an_unknown_provider_never_falls_back_to_google(provider_choice, monkeypatch):
    """Defaulting to Google on a typo would spend money the operator thought
    they were not spending. Settings refuses the value, so the process does not
    reach a request at all."""
    from pydantic import ValidationError

    monkeypatch.setenv("LEAD_PROVIDER", "nonsense")
    config.get_settings.cache_clear()

    with pytest.raises(ValidationError):
        provider_choice.get_places_provider()


def test_concurrent_first_requests_build_exactly_one_provider(
    provider_choice, monkeypatch
):
    """`def` endpoints run in a threadpool. A second provider means a second
    httpx.Client, and nothing ever closes the one that loses."""
    import threading
    import time

    built = []

    class SlowProvider:
        def __init__(self) -> None:
            time.sleep(0.05)
            built.append(self)

    monkeypatch.setenv("LEAD_PROVIDER", "fake")
    config.get_settings.cache_clear()
    monkeypatch.setattr(provider_choice, "FakePlacesProvider", SlowProvider)

    seen: list[object] = []
    threads = [
        threading.Thread(target=lambda: seen.append(provider_choice.get_places_provider()))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(built) == 1
    assert all(provider is built[0] for provider in seen)


def test_a_search_with_nothing_to_look_for_is_refused(client, monkeypatch):
    serve(monkeypatch, lead_service.CriteriaTooBroad())

    response = client.post("/api/leads/search", json=BODY)

    assert response.status_code == 400
    assert response.json() == {"error": "criteria_too_broad"}
