from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Merchant, MerchantReviewContext
from app.seed import SeedError, seed_merchant

PATH = Path("merchants/test.yaml")
DERIVED = "https://search.google.com/local/writereview?placeid="


def _merchant(**overrides) -> dict:
    data = {
        "slug": "test-merchant",
        "name": "Test Merchant",
        "category": "Restaurant",
        "google_place_id": "ChIJTestPlaceId",
        "status": "ACTIVE",
    }
    data.update(overrides)
    return data


def _seed(db, **overrides):
    merchant, created = seed_merchant(db, _merchant(**overrides), PATH)
    db.flush()
    return merchant, created


# --- upsert behaviour ------------------------------------------------------


def test_creates_then_updates_without_duplicating(db):
    """Re-running the seed is the intended way to edit a merchant, so the
    second run must update in place rather than create a second row."""
    merchant, created = _seed(db)
    original_id = merchant.id
    assert created is True

    merchant, created = _seed(db, name="Renamed")

    assert created is False
    assert merchant.id == original_id
    assert merchant.name == "Renamed"
    assert db.scalars(select(Merchant)).all() == [merchant]


def test_omitted_fields_keep_their_stored_value(db):
    """Updates merge rather than replace; removing a line must not silently
    erase data."""
    _seed(db, phone="+1-604-555-0100")

    data = _merchant(name="Renamed")
    del data["category"]
    merchant, _ = seed_merchant(db, data, PATH)
    db.flush()

    assert merchant.phone == "+1-604-555-0100"
    assert merchant.category == "Restaurant"


# --- status --------------------------------------------------------------


def test_omitted_status_does_not_resurrect_an_archived_merchant(db):
    """Defaulting to ACTIVE on every run would put a dead business back into
    service just because someone deleted the status line."""
    _seed(db, status="ARCHIVED")

    data = _merchant()
    del data["status"]
    merchant, _ = seed_merchant(db, data, PATH)
    db.flush()

    assert merchant.status == "ARCHIVED"


def test_archiving_stamps_archived_at_and_reactivating_clears_it(db):
    merchant, _ = _seed(db, status="ARCHIVED")
    assert merchant.archived_at is not None

    merchant, _ = _seed(db, status="ACTIVE")
    assert merchant.archived_at is None


def test_unknown_status_is_rejected(db):
    with pytest.raises(SeedError, match="must be one of"):
        _seed(db, status="LIVE")


# --- google review url ----------------------------------------------------


def test_review_url_derived_from_place_id(db):
    merchant, _ = _seed(db)

    assert merchant.google_review_url == DERIVED + "ChIJTestPlaceId"


def test_explicit_review_url_wins_over_derivation(db):
    """Some listings use a short g.page link the template cannot produce."""
    merchant, _ = _seed(db, google_review_url="https://g.page/r/Custom/review")

    assert merchant.google_review_url == "https://g.page/r/Custom/review"


def test_explicit_review_url_survives_an_edit_that_omits_it(db):
    """An override is a deliberate choice; a later edit that doesn't mention it
    must not silently revert to the derived URL."""
    _seed(db, google_review_url="https://g.page/r/Custom/review")

    merchant, _ = _seed(db, name="Renamed")

    assert merchant.google_review_url == "https://g.page/r/Custom/review"


def test_derived_url_follows_a_changed_place_id(db):
    _seed(db)

    merchant, _ = _seed(db, google_place_id="ChIJDifferentPlace")

    assert merchant.google_review_url == DERIVED + "ChIJDifferentPlace"


def test_omitting_place_id_does_not_null_the_url(db):
    """The stored place id still justifies the URL; reading only the YAML in
    hand would leave a stale place id next to a NULL url."""
    _seed(db)

    data = _merchant()
    del data["google_place_id"]
    merchant, _ = seed_merchant(db, data, PATH)
    db.flush()

    assert merchant.google_review_url == DERIVED + "ChIJTestPlaceId"


def test_active_merchant_without_any_google_url_is_rejected(db):
    """Caught at seed time, not at session-create time where it would reach a
    customer as an unexplained 'link unavailable'."""
    data = _merchant()
    del data["google_place_id"]

    with pytest.raises(SeedError, match="can never create a review session"):
        seed_merchant(db, data, PATH)


def test_inactive_merchant_may_omit_google_url(db):
    data = _merchant(status="INACTIVE")
    del data["google_place_id"]

    merchant, _ = seed_merchant(db, data, PATH)

    assert merchant.google_review_url is None


# --- type validation ------------------------------------------------------


@pytest.mark.parametrize("value", [37, True, None, ["a"]])
def test_non_string_slug_is_a_clean_error_not_a_traceback(db, value):
    """YAML is untyped: `slug: 37` is an int and `slug: yes` is a bool."""
    with pytest.raises(SeedError, match="must be a quoted string|is required"):
        seed_merchant(db, _merchant(slug=value), PATH)


def test_non_string_place_id_is_rejected(db):
    with pytest.raises(SeedError, match="must be a quoted string"):
        seed_merchant(db, _merchant(google_place_id=12345), PATH)


def test_scalar_where_a_context_list_belongs_is_rejected(db):
    """Stored as a JSON string, this would be iterated character by character
    during topic rotation and produce nonsense instead of an error."""
    with pytest.raises(SeedError, match="must be a list of strings"):
        _seed(db, review_context={"experience_topics": "food"})


def test_non_boolean_is_approved_is_rejected(db):
    with pytest.raises(SeedError, match="must be true or false"):
        _seed(db, review_context={"is_approved": "no"})


def test_typo_in_field_name_is_rejected(db):
    """A silently ignored key would mean the merchant looks seeded but is
    missing the data that drives AI quality."""
    with pytest.raises(SeedError, match="unknown merchant field"):
        _seed(db, catagory="Restaurant")


def test_typo_in_review_context_field_is_rejected(db):
    with pytest.raises(SeedError, match="unknown review_context field"):
        _seed(db, review_context={"selling_point": ["fast"]})


def test_missing_required_field_is_rejected(db):
    data = _merchant()
    del data["name"]

    with pytest.raises(SeedError, match="must be a quoted string|is required"):
        seed_merchant(db, data, PATH)


# --- review context -------------------------------------------------------


def test_review_context_is_upserted_not_duplicated(db):
    _seed(db, review_context={"selling_points": ["fast"], "is_approved": True})

    merchant, _ = _seed(
        db, review_context={"selling_points": ["fast", "cheap"], "is_approved": True}
    )

    contexts = db.scalars(
        select(MerchantReviewContext).where(
            MerchantReviewContext.merchant_id == merchant.id
        )
    ).all()

    assert len(contexts) == 1
    assert contexts[0].selling_points == ["fast", "cheap"]
    assert contexts[0].approved_at is not None


def test_unapproving_context_clears_the_timestamp(db):
    _seed(db, review_context={"is_approved": True})

    merchant, _ = _seed(db, review_context={"is_approved": False})

    context = db.scalars(
        select(MerchantReviewContext).where(
            MerchantReviewContext.merchant_id == merchant.id
        )
    ).one()

    assert context.is_approved is False
    assert context.approved_at is None


def test_custom_instructions_asking_for_a_link_are_rejected(db):
    """Instructions go straight into the prompt, and generated text containing a
    URL fails validation — so this would make every suggestion fail, silently
    and permanently, with nothing pointing at the cause."""
    with pytest.raises(SeedError, match="asks for a link"):
        _seed(
            db,
            review_context={
                "custom_instructions": "Always mention our website www.example.com"
            },
        )


def test_ordinary_custom_instructions_are_accepted(db):
    merchant, _ = _seed(
        db,
        review_context={
            "custom_instructions": "Keep it plain and conversational. No exclamation marks."
        },
    )

    assert merchant.slug == "test-merchant"
