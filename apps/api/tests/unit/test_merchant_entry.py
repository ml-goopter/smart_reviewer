"""GET /m/{merchantId} — the QR code's destination.

Route tests, not database tests. The endpoint touches Postgres exactly once, to
call `session_service.create_session`, and that call is scripted here. What is
under test is the translation of its outcome into a status, a Location and a set
of headers — the browser renders this response directly, so every assertion is
really about one thing: a customer standing in a restaurant must never see
anything other than a redirect.

Nothing here connects to a database, so a failure points at the route rather
than at the schema, a fixture, or a missing container. `create_session` itself
is covered against a real Postgres in test_sessions_api.py, which is where the
rate-limit counting and the merchant-status rules belong.
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.errors import ApiError
from app.main import app
from app.services import sessions as session_service

UNAVAILABLE = "/unavailable"
BUSY = "/unavailable?retry=1"

MERCHANT_ID = "468db718-4e09-4705-883e-4af80875c682"

# The shape `secrets.token_urlsafe(32)` produces. Deliberately contains both
# `-` and `_`: they are the two non-alphanumeric characters a real token can
# hold, and the ones a careless URL builder would percent-encode.
TOKEN = "Ks92MxD7yP-abcdefghijklmnopqrstuvwxyz_01234"


class FakeSession:
    """The route reads exactly one attribute off what the service returns."""

    def __init__(self, token: str) -> None:
        self.token = token


class FakeDb:
    """Stands in for the request-scoped Session. The route only ever commits."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class Scan:
    """A client for /m/ with the merchant lookup scripted.

    Defaults to minting a session. `fails(...)` replaces that with the ApiError
    the real service would raise, and `raises(...)` with something it never
    would — a database going down mid-request.
    """

    def __init__(self, db: FakeDb) -> None:
        self.db = db
        self.client: TestClient
        self.calls: list[tuple[UUID, str]] = []
        self._outcome: object = FakeSession(TOKEN)

    # Substituted for session_service.create_session.
    def _create_session(self, _db, merchant_id, client_ip):
        self.calls.append((merchant_id, client_ip))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    def fails(self, status_code: int, code: str) -> None:
        self._outcome = ApiError(status_code, code)

    def raises(self, error: Exception) -> None:
        self._outcome = error

    def get(self, merchant_id: object = MERCHANT_ID, method: str = "GET"):
        return self.client.request(
            method, f"/m/{merchant_id}", follow_redirects=False
        )

    def path(self, path: str):
        return self.client.get(path, follow_redirects=False)


@pytest.fixture
def scan(monkeypatch):
    db = FakeDb()
    harness = Scan(db)

    # entry.py holds the module and resolves the attribute at call time, so
    # patching it here is what the route will actually invoke.
    monkeypatch.setattr(session_service, "create_session", harness._create_session)
    app.dependency_overrides[get_db] = lambda: db
    harness.client = TestClient(app)

    try:
        yield harness
    finally:
        app.dependency_overrides.clear()


# --- a scan that finds a reviewable merchant -------------------------------


def test_redirects_to_the_session_the_service_minted(scan):
    response = scan.get()

    assert response.status_code == 302
    # Exact, not startswith: this is the assertion that the token survives the
    # trip into the header intact, `-` and `_` included.
    assert response.headers["location"] == f"/r/{TOKEN}"


def test_the_parsed_uuid_reaches_the_service(scan):
    """Parsed, not passed through as text. The service takes a UUID, and a
    string that merely looks like one would fail deeper and less clearly."""
    scan.get()

    merchant_id, _ = scan.calls[0]

    assert merchant_id == UUID(MERCHANT_ID)
    assert isinstance(merchant_id, UUID)


def test_the_client_ip_reaches_the_service(scan):
    """The per-IP creation limit is only as good as the address handed to it.
    Passing something constant here would collapse every customer into one
    bucket, silently."""
    scan.get()

    _, client_ip = scan.calls[0]

    assert client_ip == "testclient"


def test_one_scan_is_one_creation(scan):
    scan.get()
    scan.get()

    assert len(scan.calls) == 2


def test_a_successful_scan_is_committed(scan):
    scan.get()

    assert scan.db.commits == 1


def test_location_is_relative(scan):
    """An absolute URL would carry the proxied Host — `api:8000` inside the
    compose network — which the customer's browser cannot resolve."""
    location = scan.get().headers["location"]

    assert location.startswith("/r/")
    assert "://" not in location


def test_redirect_is_temporary_and_uncached(scan):
    """A permanent redirect is cached by the browser, so the second scan of the
    same QR code would skip this endpoint entirely and reuse a token that by
    then has expired or belongs to somebody else."""
    response = scan.get()

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"


def test_redirect_is_not_indexable(scan):
    """The SPA's noindex meta tag cannot apply to a redirect. Without this the
    permanent QR URL is crawlable, and every crawl mints a session against the
    per-IP budget."""
    assert scan.get().headers["x-robots-tag"] == "noindex, nofollow"


def test_no_cookie_is_ever_set(scan):
    """The token in the URL is the whole session mechanism. A cookie would
    outlive the tab and turn a shared phone into a shared session."""
    assert "set-cookie" not in scan.get().headers


def test_head_is_answered_with_the_same_redirect(scan):
    """Link unfurlers and some scanner apps probe with HEAD first. FastAPI does
    not register HEAD for a GET route, so without it they see 405 and treat the
    permanent QR URL as dead."""
    response = scan.get(method="HEAD")

    assert response.status_code == 302
    assert response.headers["location"] == f"/r/{TOKEN}"


# --- a scan that finds nothing it can use ----------------------------------


@pytest.mark.parametrize(
    "status_code,code",
    [
        (404, "merchant_not_found"),
        (409, "merchant_unavailable"),
    ],
)
def test_an_unusable_merchant_redirects_to_unavailable(scan, status_code, code):
    scan.fails(status_code, code)

    response = scan.get()

    assert response.status_code == 302
    assert response.headers["location"] == UNAVAILABLE


def test_unavailable_causes_are_indistinguishable(scan):
    """Which of unknown, inactive, archived, or never-finished-setup applies is
    the merchant's private information. A difference in any header is a side
    channel that says which business is merely paused."""

    def shape(response):
        return (response.status_code, dict(response.headers), response.content)

    scan.fails(404, "merchant_not_found")
    not_found = shape(scan.get())

    scan.fails(409, "merchant_unavailable")
    unavailable = shape(scan.get())

    malformed = shape(scan.get("not-a-uuid"))

    assert not_found == unavailable == malformed


def test_failure_carries_no_body_and_no_reason(scan):
    scan.fails(409, "merchant_unavailable")

    response = scan.get()

    assert response.content == b""
    combined = " ".join(f"{k}: {v}" for k, v in response.headers.items()).lower()
    assert "merchant" not in combined
    assert "unavailable" not in combined.replace("/unavailable", "")


def test_nothing_is_committed_when_creation_fails(scan):
    """A partial write here would leave a session row nobody can reach."""
    scan.fails(404, "merchant_not_found")

    scan.get()

    assert scan.db.commits == 0


def test_failure_redirect_is_also_uncached(scan):
    """Otherwise a merchant fixed after a bad scan stays broken for everyone
    whose browser cached the failure."""
    scan.fails(404, "merchant_not_found")

    assert scan.get().headers["cache-control"] == "no-store"


# --- rate limiting is told apart from an unusable merchant -----------------


def test_a_rate_limited_scan_gets_its_own_destination(scan):
    """A restaurant behind one NAT address can exhaust the hourly budget with
    nobody misbehaving. "This link is no longer available. Ask the business for
    assistance." is wrong advice for something that clears in minutes — and
    unlike the other causes, this one is not the merchant's private
    information."""
    scan.fails(429, "rate_limited")

    response = scan.get()

    assert response.status_code == 302
    assert response.headers["location"] == BUSY
    assert response.headers["cache-control"] == "no-store"


# --- paths that are not a single merchant id -------------------------------


def test_a_malformed_id_never_reaches_the_service(scan):
    """Parsed before the lookup, so text that cannot name a merchant costs no
    query — and, more importantly, produces a redirect rather than the JSON
    validation error a declared UUID parameter would."""
    response = scan.get("not-a-uuid")

    assert response.status_code == 302
    assert response.headers["location"] == UNAVAILABLE
    assert scan.calls == []


@pytest.mark.parametrize("path", ["/m", "/m/", "/m/one/two", "/m//"])
def test_truncated_qr_paths_redirect_instead_of_erroring(scan, path):
    """A partly obscured QR, a scanner that drops the last segment, or somebody
    typing half the URL. Starlette answers these with {"detail":"Not Found"} —
    a raw error document in front of a customer holding a phone."""
    response = scan.path(path)

    assert response.status_code == 302, path
    assert response.headers["location"] == UNAVAILABLE, path
    assert scan.calls == []


def test_an_unknown_merchant_id_is_still_a_redirect(scan):
    scan.fails(404, "merchant_not_found")

    assert scan.get(uuid4()).headers["location"] == UNAVAILABLE


# --- failures the contract does not describe -------------------------------


def test_an_unexpected_failure_is_not_disguised_as_an_unavailable_merchant(scan):
    """Only ApiError becomes a redirect. A database outage is an alert, and
    dressing it up as an unavailable merchant would hide a real failure behind
    a plausible business explanation — the kind that gets investigated as a
    merchant onboarding problem for a week."""
    scan.raises(RuntimeError("connection pool exhausted"))

    with pytest.raises(RuntimeError):
        scan.get()
