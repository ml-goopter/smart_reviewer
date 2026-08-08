import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Merchant, SmartReviewEvent, SmartReviewSession, SmartReviewSuggestion
from app.routers.review import get_provider
from tests.test_suggestions import GOOD, StubProvider

CREATE = "/api/review/sessions"


@pytest.fixture
def api(client):
    from app.main import app

    app.dependency_overrides[get_provider] = lambda: StubProvider(
        [json.dumps(GOOD) for _ in range(6)]
    )
    yield client
    app.dependency_overrides.pop(get_provider, None)


def _session_with_suggestions(api, merchant) -> tuple[str, list[dict]]:
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]
    suggestions = api.post(f"{CREATE}/{token}/suggestions").json()["suggestions"]
    return token, suggestions


# --- select ---------------------------------------------------------------


def test_select_returns_selected_true(api, merchant):
    token, suggestions = _session_with_suggestions(api, merchant)

    response = api.post(
        f"{CREATE}/{token}/select", json={"suggestionId": suggestions[0]["id"]}
    )

    assert response.status_code == 200
    assert response.json() == {"selected": True}


def test_select_records_the_choice(api, merchant, db):
    token, suggestions = _session_with_suggestions(api, merchant)

    api.post(f"{CREATE}/{token}/select", json={"suggestionId": suggestions[1]["id"]})

    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    assert str(session.selected_suggestion_id) == suggestions[1]["id"]

    suggestion = db.get(SmartReviewSuggestion, suggestions[1]["id"])
    assert suggestion.selected_at is not None

    events = db.scalars(
        select(SmartReviewEvent).where(
            SmartReviewEvent.event_type == "SUGGESTION_SELECTED"
        )
    ).all()
    assert len(events) == 1


def test_selecting_another_sessions_suggestion_is_409(api, merchant, db):
    """The one real authorization rule: a valid id from somebody else's session
    must never attach to this one."""
    _, mine = _session_with_suggestions(api, merchant)
    other_token, theirs = _session_with_suggestions(api, merchant)

    response = api.post(
        f"{CREATE}/{other_token}/select", json={"suggestionId": mine[0]["id"]}
    )

    assert response.status_code == 409

    session = db.scalars(
        select(SmartReviewSession).where(SmartReviewSession.token == other_token)
    ).one()
    db.refresh(session)
    assert session.selected_suggestion_id is None


def test_selecting_an_unknown_suggestion_is_404(api, merchant):
    token, _ = _session_with_suggestions(api, merchant)

    response = api.post(f"{CREATE}/{token}/select", json={"suggestionId": str(uuid4())})

    assert response.status_code == 404


def test_malformed_suggestion_id_is_400(api, merchant):
    token, _ = _session_with_suggestions(api, merchant)

    assert api.post(f"{CREATE}/{token}/select", json={"suggestionId": "nope"}).status_code == 400


def test_missing_suggestion_id_is_400(api, merchant):
    token, _ = _session_with_suggestions(api, merchant)

    assert api.post(f"{CREATE}/{token}/select", json={}).status_code == 400


def test_select_on_expired_session_is_410(api, merchant, db):
    token, suggestions = _session_with_suggestions(api, merchant)
    session = db.scalars(select(SmartReviewSession)).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    response = api.post(
        f"{CREATE}/{token}/select", json={"suggestionId": suggestions[0]["id"]}
    )

    assert response.status_code == 410


def test_select_may_be_changed(api, merchant, db):
    """Customers go back and pick a different card; that is not an error."""
    token, suggestions = _session_with_suggestions(api, merchant)

    api.post(f"{CREATE}/{token}/select", json={"suggestionId": suggestions[0]["id"]})
    api.post(f"{CREATE}/{token}/select", json={"suggestionId": suggestions[2]["id"]})

    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    assert str(session.selected_suggestion_id) == suggestions[2]["id"]


# --- complete -------------------------------------------------------------


def test_complete_returns_204(api, merchant):
    token, suggestions = _session_with_suggestions(api, merchant)

    response = api.post(
        f"{CREATE}/{token}/complete",
        json={"suggestionId": suggestions[0]["id"], "reviewCopied": True},
    )

    assert response.status_code == 204
    assert response.content == b""


def test_complete_records_the_milestone_and_copy_outcome(api, merchant, db):
    token, suggestions = _session_with_suggestions(api, merchant)

    api.post(
        f"{CREATE}/{token}/complete",
        json={"suggestionId": suggestions[0]["id"], "reviewCopied": True},
    )

    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    assert session.status == "COMPLETED"
    assert session.completed_at is not None
    assert session.google_redirected_at is not None

    event = db.scalars(
        select(SmartReviewEvent).where(
            SmartReviewEvent.event_type == "SESSION_COMPLETED"
        )
    ).one()
    assert event.event_metadata == {"review_copied": True}


def test_session_stays_usable_after_completion(api, merchant):
    """The back button must not destroy the customer's review. Completion is a
    milestone, not a gate."""
    token, suggestions = _session_with_suggestions(api, merchant)
    api.post(
        f"{CREATE}/{token}/complete",
        json={"suggestionId": suggestions[0]["id"], "reviewCopied": True},
    )

    reopened = api.get(f"{CREATE}/{token}")

    assert reopened.status_code == 200
    assert len(reopened.json()["suggestions"]) == 3
    assert api.post(f"{CREATE}/{token}/suggestions").status_code == 201


def test_complete_without_a_suggestion_is_accepted(api, merchant, db):
    """The skip-suggestions path: no selection, no clipboard action."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    response = api.post(f"{CREATE}/{token}/complete", json={"reviewCopied": False})

    assert response.status_code == 204

    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    assert session.status == "COMPLETED"
    assert session.selected_suggestion_id is None


def test_complete_with_an_empty_body_is_accepted(api, merchant):
    """Fired during unload; a truncated body must not become an error the
    client will never see."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    assert api.post(f"{CREATE}/{token}/complete", json={}).status_code == 204


def test_complete_ignores_unknown_extra_fields(api, merchant):
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    response = api.post(
        f"{CREATE}/{token}/complete", json={"reviewCopied": True, "somethingElse": 1}
    )

    assert response.status_code == 204


def test_complete_never_writes_another_sessions_suggestion(api, merchant, db):
    _, mine = _session_with_suggestions(api, merchant)
    other_token, _ = _session_with_suggestions(api, merchant)

    response = api.post(
        f"{CREATE}/{other_token}/complete",
        json={"suggestionId": mine[0]["id"], "reviewCopied": True},
    )

    # Tolerated rather than rejected — nobody is reading this response — but
    # the foreign id must not be written.
    assert response.status_code == 204

    session = db.scalars(
        select(SmartReviewSession).where(SmartReviewSession.token == other_token)
    ).one()
    db.refresh(session)
    assert session.selected_suggestion_id is None


def test_complete_is_idempotent(api, merchant, db):
    """keepalive requests can be retried by the browser."""
    token, suggestions = _session_with_suggestions(api, merchant)

    api.post(f"{CREATE}/{token}/complete", json={"suggestionId": suggestions[0]["id"]})
    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    first_completed_at = session.completed_at

    api.post(f"{CREATE}/{token}/complete", json={"suggestionId": suggestions[0]["id"]})
    db.refresh(session)

    assert session.completed_at == first_completed_at


def test_complete_on_expired_session_is_410(api, merchant, db):
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]
    session = db.scalars(select(SmartReviewSession)).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert api.post(f"{CREATE}/{token}/complete", json={}).status_code == 410


# --- regressions from adversarial review ----------------------------------


def test_complete_accepts_a_request_with_no_body_at_all(api, merchant):
    """Fired during unload. A declared Pydantic body would make this a 400,
    and the contract calls the body optional."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    response = api.post(f"{CREATE}/{token}/complete")

    assert response.status_code == 204


def test_complete_accepts_a_sendbeacon_content_type(api, merchant, db):
    """navigator.sendBeacon sends text/plain;charset=UTF-8 and cannot be made
    to send anything else — and the contract recommends sendBeacon by name."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    response = api.post(
        f"{CREATE}/{token}/complete",
        content='{"reviewCopied": true}',
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )

    assert response.status_code == 204

    event = db.scalars(
        select(SmartReviewEvent).where(
            SmartReviewEvent.event_type == "SESSION_COMPLETED"
        )
    ).one()
    assert event.event_metadata == {"review_copied": True}


def test_complete_accepts_a_body_truncated_by_unload(api, merchant, db):
    """The milestone is worth more than the payload."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    response = api.post(
        f"{CREATE}/{token}/complete",
        content='{"reviewCopied": tr',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 204

    session = db.scalars(select(SmartReviewSession)).one()
    db.refresh(session)
    assert session.status == "COMPLETED"


def test_deactivated_merchant_closes_its_live_sessions(api, merchant, db):
    """Without re-validation, taking a merchant offline leaves a full TTL of
    sessions that keep spending AI money and then hand the customer an empty
    Google URL."""
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]
    assert api.get(f"{CREATE}/{token}").status_code == 200

    merchant.status = "INACTIVE"
    db.flush()

    assert api.get(f"{CREATE}/{token}").status_code == 410
    assert api.post(f"{CREATE}/{token}/suggestions").status_code == 410


def test_merchant_losing_its_google_url_closes_live_sessions(api, merchant, db):
    token = api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]

    merchant.google_review_url = None
    db.flush()

    assert api.get(f"{CREATE}/{token}").status_code == 410
