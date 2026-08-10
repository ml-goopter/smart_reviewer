"""POST /sessions/{token}/suggestions.

The endpoint's own contract: 201 with an allowlisted batch, or a status the
client can map to fixed copy. Prompt construction, topic rotation, batch
validation and the cap's atomicity are the service's, and stay in the
integration layer.
"""

import pytest

from app.errors import ApiError
from tests.unit.conftest import TOKEN, FakeSuggestion

SUGGEST = f"/api/review/sessions/{TOKEN}/suggestions"


def test_returns_201_with_the_generated_batch(api):
    api.on_generate = [
        FakeSuggestion("The broth had real depth."),
        FakeSuggestion("Staff were friendly without hovering."),
    ]

    response = api.post(SUGGEST, json={})

    assert response.status_code == 201
    assert [item["text"] for item in response.json()["suggestions"]] == [
        "The broth had real depth.",
        "Staff were friendly without hovering.",
    ]


def test_a_suggestion_exposes_only_id_and_text(api):
    """The stored row also carries a topic, a prompt version, a model name and
    a generation number. None of it is the customer's business, and a response
    model that named them would put the prompt strategy on a public endpoint."""
    api.on_generate = [FakeSuggestion("The broth had real depth.")]

    item = api.post(SUGGEST, json={}).json()["suggestions"][0]

    assert set(item) == {"id", "text"}


def test_a_short_batch_is_returned_as_is(api):
    """R11: 1-3 suggestions, not always 3. Every one that validates is stored
    and returned rather than failing the batch."""
    api.on_generate = [FakeSuggestion("Only one survived validation.")]

    assert len(api.post(SUGGEST, json={}).json()["suggestions"]) == 1


def test_an_empty_body_is_accepted(api):
    """The contract says the request body is empty. Requiring a shape the
    client has no reason to send would be a 400 for nothing."""
    assert api.post(SUGGEST, json={}).status_code == 201


def test_no_body_at_all_is_accepted(api):
    assert api.post(SUGGEST).status_code == 201


def test_the_session_is_validated_before_the_provider_is_called(api):
    """Generation is the one paid operation in the system. A dead token must
    not reach it."""
    api.on_load_valid_session = ApiError(410, "session_unavailable")

    response = api.post(SUGGEST, json={})

    assert response.status_code == 410
    assert api.called("generate") == 0


@pytest.mark.parametrize(
    "status_code,code",
    [
        (404, "session_not_found"),
        (410, "session_unavailable"),
        (429, "generation_limit_reached"),
        (502, "generation_unavailable"),
    ],
)
def test_maps_the_service_error_to_its_status(api, status_code, code):
    """These four are the whole client contract: 404/410 is terminal, 429 hides
    Generate More, 502 offers a retry."""
    api.on_generate = ApiError(status_code, code)
    api.on_load_valid_session = (
        ApiError(status_code, code) if status_code in (404, 410) else api.on_load_valid_session
    )

    assert api.post(SUGGEST, json={}).status_code == status_code


def test_a_failed_generation_is_never_committed(api):
    """The cap refund is the service's, but the router must not commit a
    transaction the service abandoned."""
    api.on_generate = ApiError(502, "generation_unavailable")

    api.post(SUGGEST, json={})

    assert api.db.commits == 0


def test_a_failure_never_names_the_provider(api):
    """A provider's exception text can carry an endpoint, a model name, or a
    quota message. None of it belongs on a public endpoint."""
    api.on_generate = ApiError(502, "generation_unavailable")

    body = api.post(SUGGEST, json={}).text

    for leaked in ("openai", "gemini", "api_key", "quota", "http"):
        assert leaked not in body.lower()
