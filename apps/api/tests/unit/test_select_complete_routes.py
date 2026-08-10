"""POST /sessions/{token}/select and POST /sessions/{token}/complete.

`/complete` is the reason this file is worth having as unit tests. It parses its
body by hand (R3a) because a declared Pydantic body is a *required* one, and the
request arrives during page unload: no body, an empty body, a body truncated
mid-flight, and navigator.sendBeacon's text/plain content type are all normal.
Every one of those is route logic, and every one of them previously needed a
database to exercise.

Whether selecting actually records the choice, and whether a completed session
stays usable, are the service's behaviour and stay in the integration layer.
"""

from uuid import uuid4

import pytest

from app.errors import ApiError
from tests.unit.conftest import TOKEN

SELECT = f"/api/review/sessions/{TOKEN}/select"
COMPLETE = f"/api/review/sessions/{TOKEN}/complete"


# --- select ----------------------------------------------------------------


def test_select_returns_selected_true(api):
    response = api.post(SELECT, json={"suggestionId": str(uuid4())})

    assert response.status_code == 200
    assert response.json() == {"selected": True}


def test_select_passes_the_parsed_id_to_the_service(api):
    suggestion_id = uuid4()

    api.post(SELECT, json={"suggestionId": str(suggestion_id)})

    _, passed = api.calls["select_suggestion"][0]
    assert passed == suggestion_id


def test_select_validates_the_session_before_the_suggestion(api):
    """A dead token must not get as far as looking a suggestion up."""
    api.on_load_valid_session = ApiError(410, "session_unavailable")

    response = api.post(SELECT, json={"suggestionId": str(uuid4())})

    assert response.status_code == 410
    assert api.called("select_suggestion") == 0


@pytest.mark.parametrize("body", [{}, {"suggestionId": "not-a-uuid"}, {"wrong": "key"}])
def test_a_malformed_select_body_is_400(api, body):
    response = api.post(SELECT, json=body)

    assert response.status_code == 400
    assert api.called("select_suggestion") == 0


@pytest.mark.parametrize(
    "status_code,code",
    [(404, "suggestion_not_found"), (409, "suggestion_mismatch")],
)
def test_select_maps_the_service_error_to_its_status(api, status_code, code):
    api.on_select_suggestion = ApiError(status_code, code)

    response = api.post(SELECT, json={"suggestionId": str(uuid4())})

    assert response.status_code == status_code


def test_a_rejected_selection_is_never_committed(api):
    api.on_select_suggestion = ApiError(409, "suggestion_mismatch")

    api.post(SELECT, json={"suggestionId": str(uuid4())})

    assert api.db.commits == 0


# --- complete: the body may be anything ------------------------------------


def test_complete_returns_204_with_no_body(api):
    response = api.post(COMPLETE, json={"reviewCopied": True})

    assert response.status_code == 204
    assert response.content == b""


def test_complete_forwards_the_suggestion_and_the_copy_outcome(api):
    suggestion_id = uuid4()

    api.post(COMPLETE, json={"suggestionId": str(suggestion_id), "reviewCopied": True})

    _, passed_id, copied = api.calls["complete_session"][0]
    assert passed_id == suggestion_id
    assert copied is True


def test_complete_without_a_suggestion_is_the_skip_path(api):
    api.post(COMPLETE, json={"reviewCopied": False})

    _, passed_id, copied = api.calls["complete_session"][0]
    assert passed_id is None
    assert copied is False


def test_complete_defaults_review_copied_to_false(api):
    """Absent is not the same as true. The completion metric would otherwise
    count every truncated beacon as a successful copy."""
    api.post(COMPLETE, json={})

    _, _, copied = api.calls["complete_session"][0]
    assert copied is False


def test_complete_accepts_an_empty_json_body(api):
    assert api.post(COMPLETE, json={}).status_code == 204


def test_complete_accepts_no_body_at_all(api):
    """A declared Pydantic body would 400 here, and the client never reads the
    response — so rejecting it only loses the milestone."""
    assert api.post(COMPLETE).status_code == 204
    assert api.called("complete_session") == 1


def test_complete_accepts_a_sendbeacon_content_type(api):
    """navigator.sendBeacon sends text/plain. The body is still JSON."""
    response = api.post(
        COMPLETE,
        content=b'{"reviewCopied": true}',
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )

    assert response.status_code == 204
    _, _, copied = api.calls["complete_session"][0]
    assert copied is True


def test_complete_accepts_a_body_truncated_by_unload(api):
    """The page is navigating away mid-send. A malformed beacon still means the
    customer left for Google; the milestone is worth more than the payload."""
    response = api.post(
        COMPLETE,
        content=b'{"suggestionId": "abc',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 204
    _, passed_id, copied = api.calls["complete_session"][0]
    assert passed_id is None
    assert copied is False


def test_complete_ignores_unknown_extra_fields(api):
    """extra='ignore', unlike the create body. A future client sending more
    than this one understands must not lose its completion."""
    response = api.post(
        COMPLETE, json={"reviewCopied": True, "dwellMs": 4200, "variant": "b"}
    )

    assert response.status_code == 204


def test_complete_survives_a_body_that_is_not_an_object(api):
    assert api.post(COMPLETE, content=b"[]").status_code == 204


def test_complete_survives_undecodable_bytes(api):
    assert api.post(COMPLETE, content=b"\xff\xfe\x00garbage").status_code == 204


def test_complete_still_validates_the_session(api):
    """Best-effort about its body, not about its token. An unknown token has no
    milestone to record."""
    api.on_load_valid_session = ApiError(404, "session_not_found")

    response = api.post(COMPLETE, json={"reviewCopied": True})

    assert response.status_code == 404
    assert api.called("complete_session") == 0
