"""Search: the filtering Google will not do, and the funnel that reports it.

The provider is always fake, so these assert on our arithmetic — what was
fetched, what survived, what the operator is told — not on Google.
"""

from decimal import Decimal

import pytest

from app.providers.fake_places import FakePlacesProvider
from app.providers.places_base import (
    GeocodeResult,
    PlaceResult,
    PlacesQuery,
    ProviderError,
    SearchPage,
)
from app.services import leads as lead_service
from types import SimpleNamespace

from app.services.leads import LocationNotFound, SearchCriteria


class NoDb:
    """Search reads merchants once, to mark already-saved rows.

    `rows` are Merchant-shaped: the lookup selects entities so each saved row's
    subscription rides along on the same query rather than being lazy-loaded
    once per result.
    """

    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.queries = 0

    def execute(self, _statement):
        self.queries += 1
        return self

    def scalars(self):
        return self

    def all(self):
        return self.rows


class ScriptedProvider:
    """Serves prepared pages, so page count and page contents are exact."""

    def __init__(self, pages, resolved=None):
        self.pages = list(pages)
        self.calls: list[PlacesQuery] = []
        self.resolved = resolved or GeocodeResult(
            query="V6X 1T3", formatted="Richmond, BC", lat=49.1745, lng=-123.137
        )

    def geocode(self, query):
        return self.resolved

    def search(self, query):
        self.calls.append(query)
        page = self.pages[len(self.calls) - 1]
        if isinstance(page, Exception):
            raise page
        return page

    def details(self, place_id):  # pragma: no cover - not used here
        raise AssertionError


def place(place_id, *, rating=None, reviews=None, lat=49.17, lng=-123.13):
    return PlaceResult(
        place_id=place_id,
        name=place_id.replace("-", " ").title(),
        category="Restaurant",
        address="1 Main St",
        lat=lat,
        lng=lng,
        rating=Decimal(rating) if rating else None,
        review_count=reviews,
        phone=None,
        website=None,
    )


def page(*places, token=None):
    return SearchPage(results=list(places), next_page_token=token)


# Every search needs a subject: searchText rejects an empty textQuery, so a
# location on its own is refused before anything is billed.
CRITERIA = SearchCriteria(location="V6X 1T3", radius_m=5000, text_query="sushi")


# --- the filters Google cannot apply ---------------------------------------


def test_rating_ceiling_is_inclusive():
    criteria = SearchCriteria(location="x", radius_m=1000, max_rating=4.5)

    assert lead_service.matches(criteria, place("a", rating="4.5"))
    assert not lead_service.matches(criteria, place("b", rating="4.6"))


def test_review_cap_is_inclusive():
    criteria = SearchCriteria(location="x", radius_m=1000, max_review_count=200)

    assert lead_service.matches(criteria, place("a", reviews=200))
    assert not lead_service.matches(criteria, place("b", reviews=201))


def test_an_unreviewed_listing_survives_both_ceilings():
    """The best lead on the page is the business nobody has reviewed yet.
    Excluding it for lack of data would hide exactly what the tool hunts for."""
    criteria = SearchCriteria(
        location="x", radius_m=1000, max_rating=4.5, max_review_count=200
    )

    assert lead_service.matches(criteria, place("new", rating=None, reviews=None))


def test_the_rating_floor_is_enforced_here_not_only_by_google():
    """Google honours minRating in 0.5 steps, so a 4.2 floor sent alone is
    applied as 4.5 or as 4.0 depending on how it rounds. Ours is exact."""
    criteria = SearchCriteria(location="x", radius_m=1000, min_rating=4.2)

    assert lead_service.matches(criteria, place("a", rating="4.2"))
    assert not lead_service.matches(criteria, place("b", rating="4.1"))


def test_an_unrated_listing_survives_the_floor_too():
    """Google's own floor already drops unrated listings; one that still
    arrives is the business nobody has reviewed yet, which is the lead."""
    criteria = SearchCriteria(location="x", radius_m=1000, min_rating=4.2)

    assert lead_service.matches(criteria, place("new", rating=None))


def test_rating_compares_as_decimal_not_float():
    """4.3 has no exact binary form; a float comparison against 4.3 is a
    coin toss on the boundary."""
    criteria = SearchCriteria(location="x", radius_m=1000, max_rating=4.3)

    assert lead_service.matches(criteria, place("a", rating="4.3"))


# --- the funnel -------------------------------------------------------------


def test_funnel_counts_everything_fetched_not_everything_returned():
    provider = ScriptedProvider([
        page(
            place("a", rating="4.0", reviews=10),
            place("b", rating="4.0", reviews=900),
            place("c", rating="4.0", reviews=20),
        )
    ])
    criteria = SearchCriteria(
        location="V6X 1T3", radius_m=5000, text_query="sushi", max_review_count=200
    )

    outcome = lead_service.search(NoDb(), provider, criteria)

    assert outcome.searched == 3
    assert outcome.matched == 2
    assert [hit.place.place_id for hit in outcome.results] == ["a", "c"]


def test_zero_matches_is_a_result_not_an_error():
    provider = ScriptedProvider([page(place("a", rating="4.0", reviews=900))])
    criteria = SearchCriteria(
        location="V6X 1T3", radius_m=5000, text_query="sushi", max_review_count=10
    )

    outcome = lead_service.search(NoDb(), provider, criteria)

    assert (outcome.searched, outcome.matched) == (1, 0)
    assert outcome.results == []


# --- pagination -------------------------------------------------------------


def test_pagination_stops_when_google_offers_no_more_pages():
    provider = ScriptedProvider([
        page(place("a"), token="T2"),
        page(place("b"), token=None),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert len(provider.calls) == 2
    assert outcome.searched == 2


def test_pagination_stops_at_the_configured_page_cap(monkeypatch):
    from app import config

    monkeypatch.setenv("LEAD_SEARCH_MAX_PAGES", "2")
    monkeypatch.setenv("LEAD_SEARCH_PAGE_SIZE", "20")
    config.get_settings.cache_clear()

    provider = ScriptedProvider([
        page(place("a"), token="T2"),
        page(place("b"), token="T3"),
        page(place("c"), token="T4"),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)
    config.get_settings.cache_clear()

    assert len(provider.calls) == 2
    # Google offered T3 and the page cap declined it. Reporting nothing here is
    # the same short-list-reads-as-everything failure as the result cap.
    assert outcome.truncated is True


def test_the_result_target_bounds_the_list_and_not_only_the_paging(monkeypatch):
    """A cap of 2 that answers `matched: 3` reports a number the operator's own
    setting says is impossible."""
    from app import config

    monkeypatch.setenv("LEAD_SEARCH_MAX_RESULTS", "2")
    config.get_settings.cache_clear()

    # No page token: Google had nothing more, so only the trim can be what
    # makes this list shorter than what matched.
    provider = ScriptedProvider([
        page(place("a"), place("b"), place("c"), token=None)
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)
    config.get_settings.cache_clear()

    assert [hit.place.place_id for hit in outcome.results] == ["a", "b"]
    assert outcome.matched == 2
    # The whole page was fetched and billed, so the funnel still counts it.
    assert outcome.searched == 3
    # A dropped match is exactly the short list the operator must be told about.
    assert outcome.truncated is True


def test_paging_stops_once_the_wall_clock_budget_is_nearly_spent(monkeypatch):
    """The only real bound on how long a search takes.

    httpx times phases, not responses — `read` is the gap between chunks — so a
    slowly trickled body outlives every phase timeout and the next page starts
    anyway. Past nginx's proxy_read_timeout the operator gets its 504 HTML
    instead of the API's JSON envelope."""
    from itertools import chain, repeat

    from app.config import LEAD_SEARCH_BUDGET_SECONDS

    clock = chain([0.0], repeat(LEAD_SEARCH_BUDGET_SECONDS))
    monkeypatch.setattr(lead_service, "monotonic", lambda: next(clock))

    provider = ScriptedProvider([
        page(place("a"), token="T2"),
        page(place("b"), token="T3"),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert len(provider.calls) == 1
    # Not a failure — nothing errored — but Google still had pages.
    assert (outcome.partial, outcome.truncated) == (False, True)


def test_the_page_size_is_not_a_cap_on_the_whole_search(monkeypatch):
    """Page size buys cheaper pages, nothing else. Capping the search with it
    would answer `searched: 2, matched: 2` while Google still had more, which is
    the short-list-reads-as-everything failure the funnel exists to prevent."""
    from app import config

    monkeypatch.setenv("LEAD_SEARCH_PAGE_SIZE", "2")
    config.get_settings.cache_clear()

    provider = ScriptedProvider([
        page(place("a"), place("b"), token="T2"),
        page(place("c"), token=None),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)
    config.get_settings.cache_clear()

    assert len(provider.calls) == 2
    assert (outcome.searched, outcome.matched) == (3, 3)
    assert outcome.truncated is False


def test_pagination_stops_once_enough_have_matched_and_says_so(monkeypatch):
    from app import config

    monkeypatch.setenv("LEAD_SEARCH_MAX_RESULTS", "2")
    config.get_settings.cache_clear()

    provider = ScriptedProvider([
        page(place("a"), place("b"), token="T2"),
        page(place("c"), token=None),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)
    config.get_settings.cache_clear()

    # The second page is billed for results nobody asked to see.
    assert len(provider.calls) == 1
    assert outcome.matched == 2
    # Google still had a page. Silence here is the short-list-reads-as-
    # everything failure the funnel exists to prevent.
    assert outcome.truncated is True


def test_a_search_google_ran_out_of_pages_for_is_not_truncated(monkeypatch):
    """Truncated means we stopped early, not that the list is short."""
    from app import config

    monkeypatch.setenv("LEAD_SEARCH_MAX_RESULTS", "2")
    config.get_settings.cache_clear()

    provider = ScriptedProvider([page(place("a"), place("b"), token=None)])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)
    config.get_settings.cache_clear()

    assert (outcome.matched, outcome.truncated) == (2, False)


def test_the_page_token_is_carried_forward():
    provider = ScriptedProvider([page(place("a"), token="T2"), page(place("b"))])

    lead_service.search(NoDb(), provider, CRITERIA)

    assert provider.calls[0].page_token is None
    assert provider.calls[1].page_token == "T2"


def test_a_listing_repeated_across_pages_appears_once():
    provider = ScriptedProvider([
        page(place("a"), token="T2"),
        page(place("a"), place("b"), token=None),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert [hit.place.place_id for hit in outcome.results] == ["a", "b"]
    # The funnel counts what Google charged for, duplicates included.
    assert outcome.searched == 3


# --- failures ---------------------------------------------------------------


def test_failure_on_the_first_page_raises():
    provider = ScriptedProvider([ProviderError("boom")])

    with pytest.raises(ProviderError):
        lead_service.search(NoDb(), provider, CRITERIA)


def test_failure_after_a_good_page_returns_partial_results():
    provider = ScriptedProvider([
        page(place("a"), place("b"), token="T2"),
        ProviderError("boom"),
    ])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert outcome.partial is True
    assert outcome.matched == 2
    # Only what was actually looked at — the funnel must not claim 60.
    assert outcome.searched == 2


def test_an_unresolvable_location_never_reaches_google():
    provider = ScriptedProvider([], resolved=None)
    provider.geocode = lambda query: None

    with pytest.raises(LocationNotFound):
        lead_service.search(NoDb(), provider, CRITERIA)

    assert provider.calls == []


# --- request construction ---------------------------------------------------


def test_the_typed_text_reaches_google_as_is_without_the_category():
    provider = ScriptedProvider([page()])
    criteria = SearchCriteria(
        location="x", radius_m=1000, text_query="Sushi Mura omakase",
        category="restaurant",
    )

    lead_service.search(NoDb(), provider, criteria)

    assert provider.calls[0].text_query == "Sushi Mura omakase"


def test_the_category_fallback_reaches_google_when_nothing_was_typed():
    """The built query, not `criteria.text_query`, is what the request carries —
    sending the raw field would put an empty textQuery on the most ordinary
    search the tool performs, which searchText rejects outright."""
    provider = ScriptedProvider([page()])
    criteria = SearchCriteria(location="x", radius_m=1000, category="hair_salon")

    lead_service.search(NoDb(), provider, criteria)

    assert provider.calls[0].text_query == "hair salon"


def test_whitespace_alone_is_not_a_subject():
    """`max_length` bounds the field but nothing rejects "   ", and a blank
    query would be billed and refused by Google rather than by us."""
    criteria = SearchCriteria(location="x", radius_m=1000, text_query="   ")

    with pytest.raises(lead_service.CriteriaTooBroad):
        lead_service.build_text_query(criteria)


def test_the_radius_is_clamped_to_googles_ceiling():
    provider = ScriptedProvider([page()])

    lead_service.search(
        NoDb(), provider, SearchCriteria(location="x", radius_m=999_999, text_query="sushi")
    )

    assert provider.calls[0].radius_m == lead_service.MAX_RADIUS_M


def test_distance_is_measured_from_the_resolved_centre():
    provider = ScriptedProvider([page(place("a", lat=49.1745, lng=-123.137))])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert outcome.results[0].distance_m == 0


def test_a_listing_without_coordinates_has_no_distance():
    provider = ScriptedProvider([page(place("a", lat=None, lng=None))])

    outcome = lead_service.search(NoDb(), provider, CRITERIA)

    assert outcome.results[0].distance_m is None


# --- already-saved marking --------------------------------------------------


def test_saved_rows_are_marked_in_one_query():
    from uuid import uuid4

    merchant_id = uuid4()
    saved_row = SimpleNamespace(
        google_place_id="a", id=merchant_id, subscription=None
    )
    db = NoDb(rows=[saved_row])
    provider = ScriptedProvider([page(place("a"), place("b"))])

    outcome = lead_service.search(db, provider, CRITERIA)

    assert db.queries == 1
    by_id = {hit.place.place_id: hit for hit in outcome.results}
    assert by_id["a"].saved is True
    assert by_id["a"].merchant_id == merchant_id
    assert by_id["b"].saved is False


def test_no_results_means_no_lookup_at_all():
    db = NoDb()

    lead_service.search(db, ScriptedProvider([page()]), CRITERIA)

    assert db.queries == 0


# --- the fake provider, end to end -----------------------------------------


def test_the_shipped_fake_supports_a_realistic_search():
    """The §2.1.13 demo search, named result by result: the fixtures are fixed,
    so anything but an exact set means a filter moved."""
    outcome = lead_service.search(
        NoDb(),
        FakePlacesProvider(),
        SearchCriteria(
            location="V6X 1T3", radius_m=5000, category="restaurant",
            min_rating=3.5, max_rating=4.5, max_review_count=200,
        ),
    )

    assert outcome.resolved.formatted.startswith("Richmond")
    assert {hit.place.place_id for hit in outcome.results} == {
        "fake-sushi-mura",   # 4.2, 187 reviews
        "fake-pho-37",       # 3.9, 64 reviews
        "fake-green-basil",  # 4.4, 142 reviews
    }
    # The cafe and the bakery are the wrong type, Copper Kettle is over both
    # ceilings, Riverside Grill is under the floor, and the unrated New Noodle
    # House cannot satisfy a floor at all.
    assert (outcome.searched, outcome.matched) == (3, 3)


def test_a_listing_between_the_two_rating_floors_is_fetched_counted_and_dropped():
    """Google honours minRating in 0.5 steps, so a 4.3 floor is sent as 4.0 and
    the 4.0-to-4.2 listings arrive whatever the operator asked for. `matches` is
    the only thing that keeps them out of the list — and `searched` counts them
    on purpose, because Google charged for them."""
    outcome = lead_service.search(
        NoDb(),
        FakePlacesProvider(),
        SearchCriteria(
            location="V6X 1T3", radius_m=5000, category="restaurant", min_rating=4.3
        ),
    )

    # Sushi Mura is 4.2: above the 4.0 Google was sent, below the 4.3 asked for.
    assert {hit.place.place_id for hit in outcome.results} == {"fake-green-basil"}
    assert (outcome.searched, outcome.matched) == (2, 1)


# --- the radius Google could not enforce ------------------------------------


def test_a_result_outside_the_radius_is_dropped():
    """searchText restricts to a rectangle, so a merchant in the diagonal can
    be up to ~1.41x the radius away. "Within 5 km" has to mean 5 km."""
    provider = ScriptedProvider([
        page(
            place("near", lat=49.1745, lng=-123.137),
            # ~6.3 km north-east of the centre: inside the box, outside the
            # circle.
            place("corner", lat=49.2195, lng=-123.0755),
        )
    ])

    outcome = lead_service.search(
        NoDb(), provider, SearchCriteria(location="V6X 1T3", radius_m=5000, text_query="x")
    )

    assert [hit.place.place_id for hit in outcome.results] == ["near"]
    # Google was still asked about it, and still charged for it.
    assert outcome.searched == 2
    assert outcome.matched == 1


def test_a_result_without_coordinates_is_kept():
    """It satisfied the rectangle Google applied; dropping it for missing data
    would hide a merchant almost certainly in range."""
    provider = ScriptedProvider([page(place("nocoords", lat=None, lng=None))])

    outcome = lead_service.search(
        NoDb(), provider, SearchCriteria(location="V6X 1T3", radius_m=5000, text_query="x")
    )

    assert [hit.place.place_id for hit in outcome.results] == ["nocoords"]


# --- textQuery is mandatory -------------------------------------------------


def test_the_category_becomes_the_query_when_nothing_was_typed():
    """searchText rejects an empty textQuery, and "every restaurant near this
    postal code" is the most ordinary search the tool performs."""
    criteria = SearchCriteria(location="x", radius_m=1000, category="hair_salon")

    assert lead_service.build_text_query(criteria) == "hair salon"


def test_typed_text_still_wins_over_the_category():
    criteria = SearchCriteria(
        location="x", radius_m=1000, text_query="Sushi Mura", category="restaurant"
    )

    assert lead_service.build_text_query(criteria) == "Sushi Mura"


def test_a_location_with_no_subject_is_refused_before_any_call():
    provider = ScriptedProvider([page()])
    called = []
    provider.geocode = lambda query: called.append(query)

    with pytest.raises(lead_service.CriteriaTooBroad):
        lead_service.search(
            NoDb(), provider, SearchCriteria(location="V6X 1T3", radius_m=5000)
        )

    # Not even the geocode, which is billed too.
    assert called == []
    assert provider.calls == []
