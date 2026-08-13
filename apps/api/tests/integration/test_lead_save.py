"""What only Postgres can answer about saving a lead.

Everything about *choosing* what to write is a unit test; this layer holds the
guarantees the schema itself makes — the partial unique index on
google_place_id, the slug's uniqueness, the source vocabulary, and that
create-or-read really does leave an existing row byte-identical.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Merchant, MerchantReviewContext
from app.providers.places_base import PlaceDetails
from app.services import leads as lead_service

DETAILS = PlaceDetails(
    place_id="ChIJcrawler",
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


class Listing:
    def __init__(self, details=DETAILS):
        self._details = details

    def details(self, place_id):
        return self._details

    def geocode(self, query):  # pragma: no cover
        raise AssertionError

    def search(self, query):  # pragma: no cover
        raise AssertionError


def test_a_saved_lead_round_trips_through_the_real_schema(db):
    merchant, created = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    stored = db.execute(
        select(Merchant).where(Merchant.google_place_id == "ChIJcrawler")
    ).scalar_one()

    assert created is True
    assert stored.id == merchant.id
    # numeric(2,1) round-trips as Decimal, not as a float that has drifted.
    assert stored.google_rating == Decimal("4.2")
    assert stored.source == "GOOGLE_PLACES"
    # Saved, and inert: a crawled lead is a prospect, not a customer, so its
    # URL stays shut until somebody subscribes it.
    assert stored.subscription is None


def test_context_is_stored_approved_and_readable_as_jsonb(db):
    merchant, _ = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    context = db.execute(
        select(MerchantReviewContext).where(
            MerchantReviewContext.merchant_id == merchant.id
        )
    ).scalar_one()

    assert context.is_approved is True
    assert context.selling_points == ["dine-in", "takeout"]
    assert context.experience_topics[0] == "the food"
    assert context.products is None


def test_the_partial_unique_index_rejects_a_second_row_for_one_place_id(db):
    lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    db.add(
        Merchant(
            slug="a-different-slug",
            name="Impostor",
            google_place_id="ChIJcrawler",
            google_review_url="https://example.test/writereview",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_many_merchants_may_have_no_place_id_at_all(db):
    """Which is why the index is partial: a plain UNIQUE would allow only one
    NULL in some engines."""
    for slug in ("no-place-a", "no-place-b", "no-place-c"):
        db.add(Merchant(slug=slug, name=slug, google_place_id=None))

    db.flush()

    assert db.execute(
        select(Merchant).where(Merchant.google_place_id.is_(None))
    ).scalars().all()


def test_saving_the_same_listing_twice_changes_no_column(db):
    first, created_first = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()
    before = {
        column.name: getattr(first, column.name)
        for column in Merchant.__table__.columns
    }

    second, created_second = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()
    after = {
        column.name: getattr(second, column.name)
        for column in Merchant.__table__.columns
    }

    assert (created_first, created_second) == (True, False)
    assert before == after


def test_a_seeded_merchant_is_returned_untouched_not_refreshed(db, merchant):
    """The row a person curated must survive a salesperson re-running a
    search that happens to find it."""
    merchant.google_place_id = "ChIJcrawler"
    db.flush()

    found, created = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    assert created is False
    assert found.id == merchant.id
    assert found.name == "Pho 37"
    assert found.source == "YAML"
    assert found.google_rating is None
    assert found.google_synced_at is None


def test_a_second_merchant_with_the_same_name_and_city_gets_a_distinct_slug(db):
    lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    twin = PlaceDetails(
        place_id="ChIJcrawler2", name="Sushi Mura", category="Sushi Restaurant",
        city="Richmond",
    )
    second, _ = lead_service.save_merchant(db, Listing(twin), "ChIJcrawler2")
    db.flush()

    assert second.slug == "sushi-mura-richmond-2"


def test_the_slug_unique_constraint_is_real(db):
    lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    db.flush()

    db.add(
        Merchant(slug="sushi-mura-richmond", name="Impostor", google_place_id=None)
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_the_source_vocabulary_is_enforced_by_the_database(db):
    db.add(Merchant(slug="bad-source", name="Bad", source="SCRAPED"))

    with pytest.raises(IntegrityError):
        db.flush()


def test_an_existing_row_defaults_to_yaml_without_a_backfill(db):
    """Seeding is the only path that predates the crawler, so the column
    default labels every pre-existing row correctly on its own."""
    db.add(Merchant(slug="seeded-no-source", name="Seeded"))
    db.flush()

    stored = db.execute(
        select(Merchant).where(Merchant.slug == "seeded-no-source")
    ).scalar_one()

    assert stored.source == "YAML"


def test_the_saved_list_holds_only_crawler_rows_newest_first(db, merchant):
    older, _ = lead_service.save_merchant(db, Listing(), "ChIJcrawler")
    second = PlaceDetails(place_id="ChIJcrawler2", name="Green Basil", city="Richmond")
    newer, _ = lead_service.save_merchant(db, Listing(second), "ChIJcrawler2")

    # now() is transaction time in Postgres, so rows written in one transaction
    # share created_at and the order would fall to the meaningless id
    # tie-break. Production saves are separate transactions; the timestamps are
    # set apart here so this asserts the ORDER BY rather than luck.
    older.created_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    newer.created_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    db.flush()

    listed = lead_service.saved_merchants(db, limit=50, offset=0)

    assert [row.name for row in listed] == ["Green Basil", "Sushi Mura"]
    # The seeded demo merchant is not a lead.
    assert merchant.id not in {row.id for row in listed}
