"""Save: create-or-read, slug choice, and what Places becomes.

The database is substituted; what the constraints actually enforce is the
integration layer's subject (R15a).
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Merchant, MerchantReviewContext
from app.providers.places_base import PlaceDetails, ProviderError
from app.services import leads as lead_service

DETAILS = PlaceDetails(
    place_id="ChIJsushi",
    name="Sushi Mura",
    category="Sushi Restaurant",
    address="120 No 3 Rd",
    city="Richmond",
    province_state="BC",
    postal_code="V6X 1T3",
    country="Canada",
    phone="(604) 555-0100",
    website="https://example.test",
    maps_uri="https://maps.google.com/?cid=1",
    rating=Decimal("4.2"),
    review_count=187,
    editorial_summary="Long-running sushi counter.",
    attributes=["dine-in", "takeout"],
)


class FakeDb:
    """Enough Session for the save path: one lookup, adds, flushes."""

    def __init__(
        self,
        existing: Merchant | None = None,
        slugs=(),
        fail_flush=False,
        fail_every_flush=False,
    ):
        self.existing = existing
        self.slugs = list(slugs)
        self.fail_flush = fail_flush or fail_every_flush
        self.fail_every_flush = fail_every_flush
        self.added: list[object] = []
        self.flushes = 0
        self.rollbacks = 0
        self._scalar_queue: list[object] = []

    # The service issues exactly two shapes of query: merchant-by-place-id and
    # the slug prefix scan.
    def execute(self, statement):
        text = str(statement)
        if "merchants.slug" in text and "FROM merchants" in text and "SELECT merchants.slug" in text:
            return _Scalars(self.slugs)
        return _ScalarOne(self.existing)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushes += 1
        if self.fail_flush and (self.fail_every_flush or self.flushes == 1):
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        for obj in self.added:
            if isinstance(obj, Merchant) and obj.id is None:
                from uuid import uuid4

                obj.id = uuid4()

    def rollback(self):
        self.rollbacks += 1


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self.rows


class _ScalarOne:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class OneListing:
    def __init__(self, details=DETAILS):
        self.details_calls: list[str] = []
        self._details = details

    def details(self, place_id):
        self.details_calls.append(place_id)
        if isinstance(self._details, Exception):
            raise self._details
        return self._details

    def geocode(self, query):  # pragma: no cover
        raise AssertionError

    def search(self, query):  # pragma: no cover
        raise AssertionError


def merchant(**overrides) -> Merchant:
    defaults = {
        "name": "Existing", "slug": "existing",
        "google_place_id": "ChIJsushi", "source": "YAML",
    }
    return Merchant(**{**defaults, **overrides})


# --- create-or-read ---------------------------------------------------------


def test_a_new_listing_is_created():
    db, provider = FakeDb(), OneListing()

    saved, created = lead_service.save_merchant(db, provider, "ChIJsushi")

    assert created is True
    assert saved.name == "Sushi Mura"
    assert provider.details_calls == ["ChIJsushi"]


def test_a_known_place_id_is_returned_without_touching_google():
    existing = merchant()
    db, provider = FakeDb(existing=existing), OneListing()

    saved, created = lead_service.save_merchant(db, provider, "ChIJsushi")

    assert created is False
    assert saved is existing
    # Not merely cheap: a Place Details call here would be the merchant-data
    # refresh the MVP defers, arriving through a side door.
    assert provider.details_calls == []
    assert db.added == []


def test_a_curated_merchants_fields_are_never_overwritten():
    existing = merchant(name="Curated Name", category="Curated Category")
    db = FakeDb(existing=existing)

    saved, _ = lead_service.save_merchant(db, OneListing(), "ChIJsushi")

    assert saved.name == "Curated Name"
    assert saved.category == "Curated Category"
    assert saved.source == "YAML"


def test_losing_the_insert_race_still_answers_with_the_winners_row():
    """Two operators saving the same listing at once. The promise is
    create-or-read, so the loser must not 500."""
    winner = merchant()
    db = FakeDb(fail_flush=True)
    db.existing = None

    def execute(statement):
        text = str(statement)
        if "SELECT merchants.slug" in text:
            return _Scalars([])
        # Absent on the first lookup, present after the rollback.
        return _ScalarOne(winner if db.rollbacks else None)

    db.execute = execute

    saved, created = lead_service.save_merchant(db, OneListing(), "ChIJsushi")

    assert (created, saved) == (False, winner)
    assert db.rollbacks == 1


def test_a_slug_collision_with_no_winner_is_retried_rather_than_500ing():
    """Two operators save two *different* listings that slugify the same way.

    The loser violates `merchants.slug`, and the place-id lookup finds nothing
    because there is no duplicate listing — only a duplicate slug. Re-raising
    leaves a bare 500 with a plain-text body, outside the `{"error": "<code>"}`
    contract of §2.1.9 that the SPA has no case for; the answer the operator
    wants is their merchant, saved under the next free slug."""
    db = FakeDb(fail_flush=True)
    provider = OneListing()

    def execute(statement):
        if "SELECT merchants.slug" in str(statement):
            # The winner's slug becomes visible only after the rollback.
            return _Scalars(["sushi-mura-richmond"] if db.rollbacks else [])
        return _ScalarOne(None)

    db.execute = execute

    saved, created = lead_service.save_merchant(db, provider, "ChIJsushi")

    assert (created, saved.slug) == (True, "sushi-mura-richmond-2")
    assert db.rollbacks == 1
    # Place Details is fetched before the first attempt, so a retry is not a
    # second bill.
    assert provider.details_calls == ["ChIJsushi"]


def test_an_integrity_error_that_is_not_a_race_is_not_retried_forever():
    """A constraint no retry can satisfy has to surface, not spin."""
    db = FakeDb(fail_every_flush=True)
    db.execute = lambda statement: (
        _Scalars([]) if "SELECT merchants.slug" in str(statement) else _ScalarOne(None)
    )

    with pytest.raises(IntegrityError):
        lead_service.save_merchant(db, OneListing(), "ChIJsushi")

    assert db.flushes == lead_service.SAVE_ATTEMPTS


def test_a_provider_failure_writes_nothing():
    db = FakeDb()
    provider = OneListing(ProviderError("google 502"))

    with pytest.raises(ProviderError):
        lead_service.save_merchant(db, provider, "ChIJsushi")

    assert db.added == []


# --- the id Google answers with ---------------------------------------------


def looking_up(db, existing_after_rollback=None, existing=None):
    """A db that records which place id each lookup asked for."""
    asked: list[str] = []

    def execute(statement):
        if "SELECT merchants.slug" in str(statement):
            return _Scalars([])
        asked.append(statement.compile().params["google_place_id_1"])
        return _ScalarOne(existing_after_rollback if db.rollbacks else existing)

    db.execute = execute
    return asked


def test_a_deprecated_place_id_resolves_to_the_row_google_renamed_it_to():
    """Google answers a deprecated Place ID with its canonical one. The row is
    keyed on what came back, so the second save of that listing has to look for
    that id or it re-inserts a duplicate the index refuses."""
    db = FakeDb()
    winner = merchant(google_place_id="ChIJcanonical")
    calls = 0

    def execute(statement):
        nonlocal calls
        if "SELECT merchants.slug" in str(statement):
            return _Scalars([])
        calls += 1
        # The requested id is unknown; the canonical one is already saved.
        return _ScalarOne(None if calls == 1 else winner)

    db.execute = execute
    details = replace(DETAILS, place_id="ChIJcanonical")

    saved, created = lead_service.save_merchant(
        db, OneListing(details), "ChIJdeprecated"
    )

    assert (created, saved) == (False, winner)
    assert db.added == []


def test_the_race_retry_asks_for_the_id_that_was_written():
    """Losing the race under a canonical id and then looking up the requested
    one finds nothing and re-raises — a 500 that repeats on every later save of
    that listing."""
    db = FakeDb(fail_flush=True)
    winner = merchant(google_place_id="ChIJcanonical")
    asked = looking_up(db, existing_after_rollback=winner)
    details = replace(DETAILS, place_id="ChIJcanonical")

    saved, created = lead_service.save_merchant(
        db, OneListing(details), "ChIJdeprecated"
    )

    assert asked == ["ChIJdeprecated", "ChIJcanonical", "ChIJcanonical"]
    assert (created, saved) == (False, winner)


def test_details_with_no_id_are_refused_rather_than_stored_under_an_empty_key():
    """An empty google_place_id is a key: it collides with the next listing
    Google answers the same way, under the partial unique index."""
    db = FakeDb()
    details = replace(DETAILS, place_id="")

    with pytest.raises(ProviderError):
        lead_service.save_merchant(db, OneListing(details), "ChIJsushi")

    assert db.added == []


# --- what gets written ------------------------------------------------------


def written(db) -> Merchant:
    return next(obj for obj in db.added if isinstance(obj, Merchant))


def context_of(db) -> MerchantReviewContext:
    return next(obj for obj in db.added if isinstance(obj, MerchantReviewContext))


def test_google_fields_are_copied_verbatim():
    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")
    row = written(db)

    assert row.city == "Richmond"
    assert row.province_state == "BC"
    assert row.postal_code == "V6X 1T3"
    assert row.website == "https://example.test"
    assert row.google_rating == Decimal("4.2")
    assert row.google_review_count == 187
    assert row.google_profile_url == "https://maps.google.com/?cid=1"


def test_the_row_is_marked_as_crawler_sourced_and_left_unsubscribed():
    """A saved lead is inert: its URL does not open until somebody subscribes
    it, so nothing here may write a subscription."""
    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")
    row = written(db)

    assert row.source == "GOOGLE_PLACES"
    assert row.google_synced_at is not None
    assert not any(type(obj).__name__ == "Subscription" for obj in db.added)


def test_the_review_url_is_derived_from_the_place_id():
    from app.services.leads import GOOGLE_REVIEW_URL_TEMPLATE

    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")

    assert written(db).google_review_url == GOOGLE_REVIEW_URL_TEMPLATE.format(
        place_id="ChIJsushi"
    )


def test_the_snapshot_is_stamped_with_when_it_was_taken():
    before = datetime.now(UTC)
    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")

    assert written(db).google_synced_at >= before


# --- slugs ------------------------------------------------------------------


def test_slug_is_name_and_city():
    assert lead_service.slugify("Sushi Mura", "Richmond") == "sushi-mura-richmond"


def test_slug_strips_punctuation_and_accents_of_spacing():
    assert lead_service.slugify("Ben's Café & Bar!", "Vancouver") == (
        "ben-s-caf-bar-vancouver"
    )


def test_slug_survives_a_nameless_city():
    assert lead_service.slugify("Pho 37", None) == "pho-37"


def test_slug_never_exceeds_the_column():
    slug = lead_service.slugify("x" * 400, "y" * 400)

    assert len(slug) <= lead_service.MAX_SLUG_BASE


def test_a_slug_that_is_all_punctuation_still_produces_something():
    assert lead_service.slugify("!!!", None) == "merchant"


def test_collisions_take_the_next_free_suffix():
    db = FakeDb(slugs=["sushi-mura-richmond", "sushi-mura-richmond-2"])

    assert lead_service.unique_slug(db, "sushi-mura-richmond") == (
        "sushi-mura-richmond-3"
    )


def test_a_free_slug_is_used_as_is():
    assert lead_service.unique_slug(FakeDb(slugs=[]), "pho-37") == "pho-37"


def test_a_prefix_match_is_not_a_collision():
    """`pho-37-noodle-house` must not push `pho-37` to `pho-37-2`."""
    db = FakeDb(slugs=["pho-37-noodle-house"])

    assert lead_service.unique_slug(db, "pho-37") == "pho-37"


# --- review context ---------------------------------------------------------


def test_context_is_written_and_approved():
    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")
    context = context_of(db)

    assert context.is_approved is True
    assert context.approved_at is not None
    assert context.business_summary == "Long-running sushi counter."
    assert context.selling_points == ["dine-in", "takeout"]


def test_what_google_cannot_supply_stays_null():
    db = FakeDb()
    lead_service.save_merchant(db, OneListing(), "ChIJsushi")
    context = context_of(db)

    assert context.products is None
    assert context.services is None
    assert context.menu_items is None
    assert context.custom_instructions is None


def test_a_listing_with_no_editorial_summary_gets_a_plain_sentence():
    details = PlaceDetails(
        place_id="x", name="New Noodle House", category="Restaurant", city="Richmond"
    )

    assert lead_service.summary_for(details) == (
        "New Noodle House is a restaurant in Richmond."
    )


def test_the_fallback_sentence_omits_a_city_it_does_not_have():
    details = PlaceDetails(place_id="x", name="Nomad", category="Cafe")

    assert lead_service.summary_for(details) == "Nomad is a cafe."


def test_no_attributes_stores_null_rather_than_an_empty_list():
    """An empty list would read as 'we checked and there are none'."""
    db = FakeDb()
    details = PlaceDetails(place_id="x", name="Quiet Place", attributes=[])
    lead_service.save_merchant(db, OneListing(details), "x")

    assert context_of(db).selling_points is None


@pytest.mark.parametrize(
    "category,expected_first",
    [
        ("Sushi Restaurant", "the food"),
        ("Vietnamese Restaurant", "the food"),
        ("Cafe", "the coffee"),
        ("Hair Salon", "the result"),
        ("Day Spa", "the treatment"),
        ("Locksmith", "the quality"),
        (None, "the quality"),
    ],
)
def test_topics_follow_the_kind_of_business(category, expected_first):
    assert lead_service.topics_for(category)[0] == expected_first
