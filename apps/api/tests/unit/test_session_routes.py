"""POST /api/review/sessions and GET /api/review/sessions/{token}.

The contract these endpoints owe the browser: a status the client can map to
fixed copy, and a payload that names what may leave rather than excluding what
may not. What the session service does behind them — how expiry is decided, how
the rate limit counts, which rows the suggestion query selects — is the
integration layer's subject.
"""

from uuid import uuid4

import pytest

from app.errors import ApiError
from tests.unit.conftest import TOKEN, FakeMerchant, FakeSession, FakeSuggestion

CREATE = "/api/review/sessions"


# --- POST /sessions --------------------------------------------------------


def test_create_returns_201_and_the_minted_token(api):
    api.on_create_session = FakeSession(token="a-freshly-minted-token")

    response = api.post(CREATE, json={"merchantId": str(uuid4())})

    assert response.status_code == 201
    assert response.json()["token"] == "a-freshly-minted-token"


def test_create_response_contains_only_the_token(api):
    """The merchant is resolved from the session afterwards; returning any
    merchant data here would invite the client to hold on to it."""
    response = api.post(CREATE, json={"merchantId": str(uuid4())})

    assert set(response.json()) == {"token"}


def test_create_passes_the_parsed_uuid_and_the_client_ip(api):
    """The per-IP creation limit is only as good as the address handed to it."""
    merchant_id = uuid4()

    api.post(CREATE, json={"merchantId": str(merchant_id)})

    assert api.calls["create_session"] == [(merchant_id, "testclient")]


def test_malformed_merchant_id_is_400_not_422(api):
    """The contract specifies 400; FastAPI's default 422 also volunteers a
    field-by-field breakdown that a public endpoint should not."""
    response = api.post(CREATE, json={"merchantId": "not-a-uuid"})

    assert response.status_code == 400
    assert api.called("create_session") == 0


def test_unknown_field_in_the_create_body_is_rejected(api):
    """extra='forbid'. A body the client did not mean to send is a bug worth
    surfacing, not something to silently drop."""
    response = api.post(
        CREATE, json={"merchantId": str(uuid4()), "merchantName": "Pho 37"}
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "status_code,code",
    [(404, "merchant_not_found"), (409, "merchant_unavailable"), (429, "rate_limited")],
)
def test_create_maps_the_service_error_to_its_status(api, status_code, code):
    api.on_create_session = ApiError(status_code, code)

    response = api.post(CREATE, json={"merchantId": str(uuid4())})

    assert response.status_code == status_code


def test_create_failures_never_describe_the_cause(api):
    """Whether a business is inactive, archived, or never finished setup is the
    merchant's private information, not something a public URL should reveal."""
    api.on_create_session = ApiError(409, "merchant_unavailable")
    archived = api.post(CREATE, json={"merchantId": str(uuid4())})

    api.on_create_session = ApiError(409, "merchant_unavailable")
    no_url = api.post(CREATE, json={"merchantId": str(uuid4())})

    assert archived.json() == no_url.json()
    assert "merchant" not in archived.text.lower().replace("merchant_unavailable", "")


# --- GET /sessions/{token} -------------------------------------------------


def test_get_returns_the_public_payload(api):
    api.db.suggestions = [FakeSuggestion("The food was delicious.")]

    body = api.get(f"{CREATE}/{TOKEN}").json()

    assert body["merchant"] == {"name": "Pho 37", "category": "Vietnamese Restaurant"}
    assert body["googleReviewUrl"] == "https://example.test/writereview"
    assert [item["text"] for item in body["suggestions"]] == ["The food was delicious."]
    assert "expiresAt" in body["session"]


def test_get_serialises_camel_case(api):
    """The SPA's types mirror these names. snake_case here is a silent break:
    the field arrives, TypeScript is satisfied, and the value is undefined."""
    body = api.get(f"{CREATE}/{TOKEN}").json()

    assert "expiresAt" in body["session"]
    assert "expires_at" not in body["session"]
    assert "googleReviewUrl" in body
    assert "google_review_url" not in body


def test_get_never_leaks_internal_fields(api):
    """The response models are allowlists, so a field added to a database model
    cannot leak by default. This is the test that keeps that true."""
    raw = api.get(f"{CREATE}/{TOKEN}").text

    for leaked in ("merchant_id", "google_place_id", "slug", "created_ip_hash", TOKEN):
        assert leaked not in raw


def test_get_omits_a_category_the_merchant_does_not_have(api):
    api.on_load_valid_session = FakeSession(merchant=FakeMerchant(category=None))

    assert api.get(f"{CREATE}/{TOKEN}").json()["merchant"]["category"] is None


def test_get_passes_the_token_through_to_validation(api):
    api.get(f"{CREATE}/{TOKEN}")

    assert api.calls["load_valid_session"] == [(TOKEN,)]


def test_get_does_not_generate(api):
    """R4. Generation is a paid, multi-second provider call; putting it here
    would mean a link-preview crawler or a refresh spends money before a human
    has arrived, and would make the merchant's name wait on the AI."""
    api.get(f"{CREATE}/{TOKEN}")

    assert api.called("generate") == 0


def test_get_records_the_open(api):
    api.get(f"{CREATE}/{TOKEN}")

    assert api.called("mark_opened") == 1
    _, ip_hash, user_agent = api.calls["mark_opened"][0]
    # Hashed before it reaches the recorder, never the address itself.
    assert ip_hash is not None
    assert "testclient" not in ip_hash
    assert user_agent is not None


def test_get_returns_an_empty_list_when_nothing_has_been_generated(api):
    """The normal first load, because R4 means GET never generates. The client
    treats this as "ask for a batch", not as a failure."""
    assert api.get(f"{CREATE}/{TOKEN}").json()["suggestions"] == []


@pytest.mark.parametrize(
    "status_code,code",
    [(404, "session_not_found"), (410, "session_unavailable")],
)
def test_get_maps_the_validation_error_to_its_status(api, status_code, code):
    api.on_load_valid_session = ApiError(status_code, code)

    assert api.get(f"{CREATE}/{TOKEN}").status_code == status_code


def test_a_rejected_session_is_never_committed(api):
    api.on_load_valid_session = ApiError(410, "session_unavailable")

    api.get(f"{CREATE}/{TOKEN}")

    assert api.db.commits == 0


def test_a_missing_google_url_serialises_as_empty_rather_than_null(api):
    """The client's one defensive check is that this is a non-empty string, so
    the shape has to stay a string for that check to be the thing that fires."""
    api.on_load_valid_session = FakeSession(
        merchant=FakeMerchant(google_review_url=None)
    )

    assert api.get(f"{CREATE}/{TOKEN}").json()["googleReviewUrl"] == ""
