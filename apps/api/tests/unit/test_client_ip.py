"""The create-session rate limit keys on client_ip, so a bug here is either a
bypassed cost control or a lockout of every customer at once."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.client_ip import client_ip
from app.config import get_settings


@pytest.fixture
def app() -> FastAPI:
    api = FastAPI()

    @api.get("/whoami")
    def whoami(request: Request) -> dict[str, str]:
        return {"ip": client_ip(request)}

    return api


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_trusted_proxy_uses_x_real_ip(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()

    response = TestClient(app).get("/whoami", headers={"X-Real-IP": "203.0.113.7"})

    assert response.json()["ip"] == "203.0.113.7"


def test_x_forwarded_for_is_never_trusted(app, monkeypatch):
    """XFF is client-supplied. Honouring its leftmost entry is the standard
    way an IP-keyed limit gets bypassed."""
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()

    response = TestClient(app).get(
        "/whoami",
        headers={"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "203.0.113.7"},
    )

    assert response.json()["ip"] == "203.0.113.7"


def test_untrusted_deployment_ignores_headers(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    get_settings.cache_clear()

    response = TestClient(app).get("/whoami", headers={"X-Real-IP": "6.6.6.6"})

    assert response.json()["ip"] != "6.6.6.6"


def test_missing_header_falls_back_to_peer(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()

    response = TestClient(app).get("/whoami")

    assert response.json()["ip"] == "testclient"
