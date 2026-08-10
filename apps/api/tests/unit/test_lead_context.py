"""The context editor: replace all eight, clear on blank, refuse a URL.

The URL rule is asserted against the *same* pattern seed.py refuses on, so the
two onboarding paths cannot drift into disagreeing about what is acceptable.
"""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import get_db
from app.main import app
from app.models import Merchant, MerchantReviewContext
from app.routers.leads import get_places_provider
from app.schemas import MAX_CONTEXT_ITEM_CHARS, MAX_CONTEXT_ITEMS
from app.services import leads as lead_service
from app.services import suggestions as suggestion_service

MERCHANT_ID = "468db718-4e09-4705-883e-4af80875c682"

FULL = {
    "businessSummary": "Family-run Vietnamese kitchen.",
    "products": ["beef pho", "spring rolls"],
    "services": ["catering"],
    "menuItems": ["chicken pho"],
    "sellingPoints": ["broth simmered daily"],
    "approvedKeywords": ["pho"],
    "experienceTopics": ["the food", "the service"],
    "customInstructions": "Keep it short.",
}


class ContextDb:
    """Enough Session for the editor: get a merchant, find or add a context."""

    def __init__(self, merchant=None, context=None):
        self.merchant = merchant
        self.context = context
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def get(self, _model, _id):
        return self.merchant

    def execute(self, _statement):
        return self

    def scalar_one_or_none(self):
        return self.context

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, MerchantReviewContext):
            self.context = obj

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1


def merchant():
    from datetime import UTC, datetime
    from uuid import UUID

    return Merchant(
        id=UUID(MERCHANT_ID),
        name="Pho 37",
        slug="pho-37-richmond",
        status="ACTIVE",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://reviews.example.test")
    config.get_settings.cache_clear()
    app.dependency_overrides[get_places_provider] = lambda: object()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        config.get_settings.cache_clear()


def api(db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# --- the service ------------------------------------------------------------


def test_every_field_is_written():
    db = ContextDb(merchant=merchant())

    context = lead_service.replace_context(db, MERCHANT_ID, {
        "business_summary": "A summary.",
        "products": ["pho"],
        "services": None,
        "menu_items": ["rice plate"],
        "selling_points": ["daily broth"],
        "approved_keywords": ["vietnamese"],
        "experience_topics": ["the food"],
        "custom_instructions": "Keep it short.",
    })

    assert context.business_summary == "A summary."
    assert context.products == ["pho"]
    assert context.services is None
    assert context.custom_instructions == "Keep it short."


def test_a_field_left_out_of_the_payload_is_cleared_not_kept():
    """A replace, not a merge: the editor renders every field, so an empty box
    is an instruction rather than an omission."""
    existing = MerchantReviewContext(
        merchant_id=MERCHANT_ID, products=["old"], business_summary="old"
    )
    db = ContextDb(merchant=merchant(), context=existing)

    context = lead_service.replace_context(db, MERCHANT_ID, {})

    assert context.products is None
    assert context.business_summary is None


def test_blank_entries_become_null_not_empty():
    db = ContextDb(merchant=merchant())

    context = lead_service.replace_context(db, MERCHANT_ID, {
        "products": ["", "   "], "business_summary": "   ",
    })

    # [] would read as "checked, and there are none"; the generator treats a
    # missing list as "nothing to say", which is the truth here.
    assert context.products is None
    assert context.business_summary is None


def test_blank_lines_inside_a_list_are_dropped():
    db = ContextDb(merchant=merchant())

    context = lead_service.replace_context(db, MERCHANT_ID, {
        "products": ["beef pho", "", "  spring rolls  "],
    })

    assert context.products == ["beef pho", "spring rolls"]


def test_editing_approves():
    db = ContextDb(merchant=merchant())

    context = lead_service.replace_context(db, MERCHANT_ID, FULL)

    assert context.is_approved is True
    assert context.approved_at is not None


def test_an_unknown_merchant_writes_nothing():
    db = ContextDb(merchant=None)

    assert lead_service.replace_context(db, MERCHANT_ID, FULL) is None
    assert db.added == []


def test_a_merchant_with_no_context_row_yet_gets_one():
    db = ContextDb(merchant=merchant(), context=None)

    lead_service.replace_context(db, MERCHANT_ID, FULL)

    assert any(isinstance(obj, MerchantReviewContext) for obj in db.added)


# --- what the editor changes about the prompt -------------------------------
#
# The point of the editor is that what an admin types changes what the AI is
# told. The database is only somewhere to put the row, so it is substituted:
# what these assert is the handoff between two services.


def test_what_the_admin_typed_reaches_the_prompt():
    db = ContextDb(merchant=merchant())

    lead_service.replace_context(db, MERCHANT_ID, {
        "business_summary": "Family-run Vietnamese kitchen since 2009.",
        "products": ["beef pho"],
        "selling_points": ["broth simmered daily"],
    })
    lines = suggestion_service._context_lines(
        merchant(), lead_service.load_context(db, MERCHANT_ID)
    )

    assert "Family-run Vietnamese kitchen since 2009." in lines
    assert "beef pho" in lines
    assert "broth simmered daily" in lines


def test_edited_topics_drive_the_rotation():
    db = ContextDb(merchant=merchant())

    lead_service.replace_context(db, MERCHANT_ID, {
        "experience_topics": ["the broth", "the service", "the value"],
    })
    context = lead_service.load_context(db, MERCHANT_ID)
    first = suggestion_service.topics_for_generation(context, 1, 3)
    second = suggestion_service.topics_for_generation(context, 2, 3)

    assert first == ["the broth", "the service", "the value"]
    # The window advances, so Generate More is not the same three ideas.
    assert second[0] == "the broth"
    assert set(first) == {"the broth", "the service", "the value"}


# --- the route --------------------------------------------------------------


def test_put_returns_the_stored_context_in_camel_case(client):
    db = ContextDb(merchant=merchant())

    response = api(db).put(f"/api/leads/merchants/{MERCHANT_ID}/context", json=FULL)
    body = response.json()

    assert response.status_code == 200
    assert body["businessSummary"] == "Family-run Vietnamese kitchen."
    assert body["menuItems"] == ["chicken pho"]
    assert body["sellingPoints"] == ["broth simmered daily"]
    assert db.commits == 1


def test_instructions_containing_a_url_are_refused_with_an_actionable_code(client):
    """Same rule seed.py enforces: a URL in the instructions makes every
    generated suggestion fail validation, breaking the merchant silently."""
    db = ContextDb(merchant=merchant())

    response = api(db).put(
        f"/api/leads/merchants/{MERCHANT_ID}/context",
        json={**FULL, "customInstructions": "always mention www.example.com"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "instructions_contain_url"}
    assert db.commits == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "visit https://example.com",
        "mention example.com",
        "see www.example.co.uk for details",
    ],
)
def test_every_shape_of_link_is_caught(client, instruction):
    db = ContextDb(merchant=merchant())

    response = api(db).put(
        f"/api/leads/merchants/{MERCHANT_ID}/context",
        json={"customInstructions": instruction},
    )

    assert response.status_code == 400


def test_the_url_rule_is_the_same_object_the_seed_uses():
    from app.routers import leads as leads_router
    from app import seed

    assert leads_router._URL is seed._URL


def test_an_unknown_merchant_is_404(client):
    db = ContextDb(merchant=None)

    response = api(db).put(f"/api/leads/merchants/{MERCHANT_ID}/context", json=FULL)

    assert response.status_code == 404
    assert response.json() == {"error": "merchant_not_found"}


def test_merchant_fields_cannot_be_edited_through_this_endpoint(client):
    db = ContextDb(merchant=merchant())

    response = api(db).put(
        f"/api/leads/merchants/{MERCHANT_ID}/context",
        json={**FULL, "name": "Renamed", "status": "ARCHIVED"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


@pytest.mark.parametrize(
    "payload",
    [
        {"products": ["pho"] * (MAX_CONTEXT_ITEMS + 1)},
        {"menuItems": ["x" * (MAX_CONTEXT_ITEM_CHARS + 1)]},
        {"experienceTopics": ["the food"] * (MAX_CONTEXT_ITEMS + 1)},
    ],
)
def test_oversized_lists_are_refused(client, payload):
    """The endpoint is unauthenticated by decision and everything stored here
    lands verbatim in the prompt on every generation, so an unbounded list is
    an unbounded per-generation bill."""
    db = ContextDb(merchant=merchant())

    response = api(db).put(f"/api/leads/merchants/{MERCHANT_ID}/context", json=payload)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}
    assert db.commits == 0


def test_a_list_at_the_bounds_is_still_accepted(client):
    db = ContextDb(merchant=merchant())

    response = api(db).put(
        f"/api/leads/merchants/{MERCHANT_ID}/context",
        json={"products": ["x" * MAX_CONTEXT_ITEM_CHARS] * MAX_CONTEXT_ITEMS},
    )

    assert response.status_code == 200


def test_a_malformed_merchant_id_is_400(client):
    response = api(ContextDb()).put("/api/leads/merchants/not-a-uuid/context", json=FULL)

    assert response.status_code == 400


def test_get_context_returns_the_merchant_and_its_current_values(client):
    existing = MerchantReviewContext(
        merchant_id=MERCHANT_ID,
        business_summary="Existing summary.",
        products=["beef pho"],
    )
    db = ContextDb(merchant=merchant(), context=existing)

    body = api(db).get(f"/api/leads/merchants/{MERCHANT_ID}/context").json()

    assert body["merchant"]["name"] == "Pho 37"
    assert body["merchant"]["url"] == f"https://reviews.example.test/m/{MERCHANT_ID}"
    assert body["context"]["businessSummary"] == "Existing summary."
    assert body["context"]["products"] == ["beef pho"]


def test_get_context_on_a_merchant_with_none_returns_empty_fields(client):
    db = ContextDb(merchant=merchant(), context=None)

    body = api(db).get(f"/api/leads/merchants/{MERCHANT_ID}/context").json()

    assert body["context"]["businessSummary"] is None
    assert body["context"]["products"] is None
