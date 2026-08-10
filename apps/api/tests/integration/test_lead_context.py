"""Edited context, stored as JSONB and read back by the generator.

Only what the database itself decides: that a list survives the round trip
through JSONB, and that clearing a field clears the stored row rather than the
in-memory object. That an edit changes the prompt is a unit test — the database
is scaffolding there, and tests/unit/test_lead_context.py holds it.
"""

from app.models import MerchantReviewContext
from app.services import leads as lead_service
from app.services import suggestions as suggestion_service


def test_edited_context_round_trips_through_jsonb(db, merchant):
    lead_service.replace_context(db, merchant.id, {
        "business_summary": "Family-run Vietnamese kitchen since 2009.",
        "products": ["beef pho", "spring rolls"],
        "menu_items": ["chicken pho"],
        "selling_points": ["broth simmered daily"],
        "approved_keywords": ["pho", "richmond"],
        "experience_topics": ["the broth", "the service"],
        "custom_instructions": "Keep it under three sentences.",
    })
    db.expire_all()

    stored = db.get(MerchantReviewContext, lead_service.load_context(db, merchant.id).id)

    assert stored.products == ["beef pho", "spring rolls"]
    assert stored.approved_keywords == ["pho", "richmond"]
    assert stored.is_approved is True


def test_clearing_a_field_removes_it_from_the_prompt(db, merchant):
    lead_service.replace_context(db, merchant.id, {"products": ["beef pho"]})
    db.flush()

    lead_service.replace_context(db, merchant.id, {})
    db.flush()

    context = lead_service.load_context(db, merchant.id)
    lines = suggestion_service._context_lines(merchant, context)

    assert "beef pho" not in lines
    assert lines.startswith("Business name: Pho 37")


def test_a_crawler_saved_merchants_context_is_used_without_a_human_touching_it(db):
    """Auto-fill sets is_approved, so a freshly saved lead demos with grounding
    rather than with the generic fallback."""
    from decimal import Decimal

    from app.providers.places_base import PlaceDetails

    class Listing:
        def details(self, place_id):
            return PlaceDetails(
                place_id=place_id,
                name="Sushi Mura",
                category="Sushi Restaurant",
                city="Richmond",
                rating=Decimal("4.2"),
                editorial_summary="Long-running sushi counter.",
                attributes=["dine-in", "takeout"],
            )

        def geocode(self, query):  # pragma: no cover
            raise AssertionError

        def search(self, query):  # pragma: no cover
            raise AssertionError

    saved, _ = lead_service.save_merchant(db, Listing(), "ChIJfresh")
    db.flush()

    context = lead_service.load_context(db, saved.id)
    lines = suggestion_service._context_lines(saved, context)
    topics = suggestion_service.topics_for_generation(context, 1, 3)

    assert "Long-running sushi counter." in lines
    assert "dine-in" in lines
    assert topics[0] == "the food"
