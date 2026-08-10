"""The settings module is the only place a default is written.

That is a claim about the repository, not about the code, so it needs a test
that reads the repository. The three copies this replaced — a field default, a
`${VAR:-default}` fallback in compose, and a literal in .env.example — disagreed
about IP_HASH_SALT for as long as they existed, because nothing checked.
"""

import os
from pathlib import Path

import pytest

from app.config import SECRETS, Settings, env_example


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


def test_the_attempt_ceiling_stays_above_the_success_cap():
    """The ceiling exists to bound failures, which refund their slot. At or
    below the success cap it would instead stop customers from spending an
    allowance they still have."""
    settings = Settings()

    assert (
        settings.max_generation_attempts_per_session
        > settings.max_generations_per_session
    )
