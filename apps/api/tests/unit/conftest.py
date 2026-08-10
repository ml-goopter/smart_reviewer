"""A review API with nothing behind it.

The routers' job is to translate: a path and a body in, a status, a set of
headers and an allowlisted payload out. Everything they call outward — the
request-scoped Session, the session and suggestion services, the AI provider —
is substituted here, so a test states the outcome it wants and asserts on the
translation rather than on a database's ability to store a row.

What the substituted services *do* is the integration layer's subject. That
split is R15a; `tests/README.md` has the rule for placing a new test.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.routers.review import get_provider
from app.services import sessions as session_service
from app.services import suggestions as suggestion_service

TOKEN = "Ks92MxD7yP-abcdefghijklmnopqrstuvwxyz_01234"
MERCHANT_ID = UUID("468db718-4e09-4705-883e-4af80875c682")


class FakeMerchant:
    def __init__(self, **overrides) -> None:
        self.id = MERCHANT_ID
        self.name = "Pho 37"
        self.category = "Vietnamese Restaurant"
        self.google_review_url = "https://example.test/writereview"
        self.status = "ACTIVE"
        self.slug = "pho37"
        self.google_place_id = "ChIJPrivateInternalValue"
        self.__dict__.update(overrides)


class FakeSuggestion:
    def __init__(self, text: str, id_: UUID | None = None) -> None:
        self.id = id_ or uuid4()
        self.text_ = text


class FakeSession:
    """Only the attributes the routers actually read."""

    def __init__(self, **overrides) -> None:
        self.id = uuid4()
        self.token = TOKEN
        self.merchant = FakeMerchant()
        self.merchant_id = MERCHANT_ID
        self.expires_at = datetime.now(UTC) + timedelta(hours=24)
        self.__dict__.update(overrides)


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDb:
    """Stands in for the request-scoped Session.

    `scalars` answers the one query a router issues directly — the suggestion
    list in GET /sessions/:token. Whether that query selects the right rows in
    the right order is a database question, and lives in
    tests/integration/test_sessions_api.py.
    """

    def __init__(self) -> None:
        self.commits = 0
        self.suggestions: list[FakeSuggestion] = []

    def commit(self) -> None:
        self.commits += 1

    def scalars(self, _statement):
        return FakeResult(self.suggestions)


class Api:
    """Scripts the service layer, then lets a test drive the routes.

    Each `on_*` attribute is either a value to return or an exception to raise.
    `calls` records what each substituted service was invoked with, so a test
    can assert on what left the router as well as what came back.
    """

    def __init__(self, db: FakeDb) -> None:
        self.db = db
        self.client: TestClient
        self.calls: dict[str, list] = {
            "create_session": [],
            "load_valid_session": [],
            "mark_opened": [],
            "select_suggestion": [],
            "complete_session": [],
            "generate": [],
        }

        self.on_create_session: object = FakeSession()
        self.on_load_valid_session: object = FakeSession()
        self.on_generate: object = []

    def _resolve(self, name: str, args, result):
        self.calls[name].append(args)
        if isinstance(result, Exception):
            raise result
        return result

    # --- substituted services ---------------------------------------------

    def create_session(self, _db, merchant_id, client_ip):
        return self._resolve(
            "create_session", (merchant_id, client_ip), self.on_create_session
        )

    def load_valid_session(self, _db, token):
        return self._resolve(
            "load_valid_session", (token,), self.on_load_valid_session
        )

    def mark_opened(self, _db, session, ip_hash=None, user_agent=None):
        self.calls["mark_opened"].append((session, ip_hash, user_agent))

    def select_suggestion(self, _db, session, suggestion_id):
        return self._resolve(
            "select_suggestion", (session, suggestion_id), self.on_select_suggestion
        )

    def complete_session(self, _db, session, suggestion_id, review_copied):
        self.calls["complete_session"].append((session, suggestion_id, review_copied))

    def generate(self, _db, session, provider):
        return self._resolve("generate", (session, provider), self.on_generate)

    # --- convenience -------------------------------------------------------

    on_select_suggestion: object = None

    def called(self, name: str) -> int:
        return len(self.calls[name])

    def get(self, path: str, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(path, **kwargs)


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    harness = Api(db)

    # The routers hold the module and resolve the attribute at call time, so
    # patching here is what they will actually invoke.
    for name in ("create_session", "load_valid_session", "mark_opened",
                 "select_suggestion", "complete_session"):
        monkeypatch.setattr(session_service, name, getattr(harness, name))
    monkeypatch.setattr(suggestion_service, "generate", harness.generate)

    app.dependency_overrides[get_db] = lambda: db
    # Never a real client: a test must not make a paid, non-deterministic call.
    app.dependency_overrides[get_provider] = lambda: object()
    harness.client = TestClient(app)

    try:
        yield harness
    finally:
        app.dependency_overrides.clear()
