"""The settings module is the only place a default is written.

That is a claim about the repository, not about the code, so it needs a test
that reads the repository. The three copies this replaced — a field default, a
`${VAR:-default}` fallback in compose, and a literal in .env.example — disagreed
about IP_HASH_SALT for as long as they existed, because nothing checked.
"""

import os
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import LANGUAGES
from app.config import (
    LEAD_SEARCH_BUDGET_SECONDS,
    SECRETS,
    Settings,
    env_example,
)


def _repo_root() -> Path | None:
    """Only apps/api is mounted into the container, so compose points REPO_ROOT
    at the two repo-level files these tests read. Outside Docker, walk up."""
    explicit = os.environ.get("REPO_ROOT")
    if explicit:
        return Path(explicit)

    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    return None


REPO_ROOT = _repo_root()

requires_repo = pytest.mark.skipif(
    REPO_ROOT is None, reason="repository files not reachable from here"
)


@requires_repo
def test_env_example_matches_the_settings_module():
    """Regenerate with:

    docker compose run --rm api python -m app.config --example > .env.example
    """
    assert (REPO_ROOT / ".env.example").read_text() == env_example(), (
        ".env.example is stale. It is generated from app/config.py; regenerate "
        "it rather than editing it by hand."
    )


def test_every_setting_is_documented():
    """A field with no description renders as a bare key in .env.example, which
    tells a reader the name and nothing about what setting it wrong costs."""
    undocumented = [
        name for name, field in Settings.model_fields.items() if not field.description
    ]

    assert undocumented == []


def test_secrets_are_emitted_blank():
    """A shipped default for a secret produces a deployment that looks
    configured and is not — the salt in particular, where the failure is
    invisible and the consequence is that stored IP hashes are reversible."""
    rendered = env_example()

    for name in SECRETS:
        assert f"\n{name.upper()}=\n" in rendered


def test_non_secrets_are_commented_out():
    """Uncommenting is how a reader overrides a value. Emitting them live would
    copy every default into .env, which is the duplication this removes."""
    rendered = env_example()

    for name, field in Settings.model_fields.items():
        if name in SECRETS:
            continue
        assert f"\n# {name.upper()}={field.default}\n" in rendered


@requires_repo
def test_compose_does_not_restate_a_default():
    """docker-compose.yml may set what differs by environment. A `${VAR:-...}`
    fallback is something else: a second source for a value config.py already
    owns, and the one that silently wins."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    offenders = [
        name
        for name in Settings.model_fields
        if f"${{{name.upper()}:-" in compose
    ]

    assert offenders == []


def test_an_unknown_lead_provider_stops_the_process(monkeypatch):
    """It selects an adapter, so a typo cannot be defaulted away. Refused at
    startup rather than per request: a container whose healthcheck stays green
    while every /api/leads call 500s reports itself as working."""
    monkeypatch.setenv("LEAD_PROVIDER", "nonsense")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("name", ["google", "fake"])
def test_the_adapters_that_exist_are_accepted(monkeypatch, name):
    monkeypatch.setenv("LEAD_PROVIDER", name)

    assert Settings().lead_provider == name


@pytest.mark.parametrize("value", ["Vancouver", "PST", "America/Notatown", ""])
def test_an_unknown_operator_timezone_stops_the_process(monkeypatch, value):
    """Every subscription expiry is computed in this zone. An unresolvable one
    would not surface until somebody subscribed a merchant, where it reads as a
    broken endpoint rather than a broken setting."""
    monkeypatch.setenv("OPERATOR_TIMEZONE", value)

    with pytest.raises(ValidationError):
        Settings()


def test_a_real_iana_zone_is_accepted(monkeypatch):
    monkeypatch.setenv("OPERATOR_TIMEZONE", "Europe/Berlin")

    assert Settings().operator_timezone == "Europe/Berlin"


@requires_repo
def test_the_search_budget_stays_under_the_proxy_that_actually_fronts_it():
    """The budget is only meaningful against nginx's real proxy_read_timeout;
    over it the operator gets nginx's 504 HTML instead of the API's JSON error
    envelope.

    Every `proxy_read_timeout` in `nginx/` has to clear the budget, because this
    reads the files rather than parsing their blocks. A location that genuinely
    wants a shorter one has to be excluded here deliberately — the alternative
    is a guard that skips itself the day the directory is renamed."""
    conf_dir = REPO_ROOT / "nginx"
    confs = sorted(conf_dir.glob("*.conf"))

    assert confs, f"no nginx config in {conf_dir}: the budget is unchecked"

    timeouts = [
        int(match.group(1))
        for conf in confs
        for match in re.finditer(r"proxy_read_timeout\s+(\d+)s", conf.read_text())
    ]

    assert timeouts, "no proxy_read_timeout found to check the budget against"
    assert LEAD_SEARCH_BUDGET_SECONDS < min(timeouts)


def test_a_timeout_that_blows_the_budget_is_refused(monkeypatch):
    monkeypatch.setenv("LEAD_SEARCH_TIMEOUT_SECONDS", "15")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "name,value",
    [
        # A negative page count makes the budget product negative, which passes
        # any ceiling: the guard has to be un-invertible, not merely present.
        ("LEAD_SEARCH_MAX_PAGES", "-5"),
        ("LEAD_SEARCH_MAX_PAGES", "0"),
        ("LEAD_SEARCH_TIMEOUT_SECONDS", "0"),
        # Above Google's ceiling every search is an INVALID_ARGUMENT, so the
        # tool is a 502 generator until someone reads the logs.
        ("LEAD_SEARCH_PAGE_SIZE", "50"),
        ("LEAD_SEARCH_PAGE_SIZE", "0"),
        ("LEAD_SEARCH_MAX_RESULTS", "0"),
    ],
)
def test_nonsense_search_bounds_are_refused_at_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_the_attempt_ceiling_stays_above_every_languages_success_cap():
    """The ceiling exists to bound failures, which refund their slot. It is
    session-wide while the success cap is per language, so it has to clear the
    total a customer can legitimately spend across every language — otherwise
    it stops them from using an allowance they still have, in a language they
    have not generated in yet."""
    settings = Settings()

    reachable = settings.max_generations_per_language * len(LANGUAGES)

    assert settings.max_generation_attempts_per_session > reachable
