"""Runtime configuration, and the single place any of these values is written.

Every knob the MVP tunes lives here rather than in code, so changing a limit or
swapping an AI provider is a restart, not a deploy.

Nothing restates a default. `docker-compose.yml` sets only what genuinely
differs by environment — where the database is, and whether a proxy sits in
front — and `.env.example` is generated from this module rather than maintained
beside it. A test fails if the committed file drifts, because the three copies
this replaced disagreed with each other and nobody noticed.

Regenerate with:

    docker compose run --rm api python -m app.config --example > .env.example
"""

import sys
import textwrap
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values with no sensible default: they are per-deployment secrets, and shipping
# one would mean a deployment that looks configured but is not. Emitted blank in
# .env.example so an unset one is visible rather than inherited.
SECRETS = frozenset({"openai_api_key", "ip_hash_salt"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        "postgresql+psycopg://reviewer:reviewer@localhost:5433/reviewer",
        description=(
            "Where Postgres lives. Defaults to the host-published port so the "
            "API and Alembic run outside Docker without configuration; compose "
            "overrides it with the service name, which resolves only inside the "
            "compose network."
        ),
    )

    # --- AI provider -------------------------------------------------------

    openai_api_key: str = Field(
        "",
        description="Credential for the endpoint below. Required to generate.",
    )
    openai_base_url: str = Field(
        "https://api.openai.com/v1",
        description=(
            "The `openai` SDK is used purely as transport: pointing this at any "
            "OpenAI-compatible endpoint switches providers with no code change "
            "— Azure, OpenRouter, Together, Groq, vLLM, Ollama. Providers that "
            "are not wire-compatible need a new adapter implementing "
            "app.providers.base.SuggestionProvider."
        ),
    )
    openai_model: str = Field(
        "gpt-4o-mini",
        description="Model id, as the endpoint above names it.",
    )
    ai_provider: str = Field(
        "openai",
        description=(
            "Recorded on every generated row as model_provider, so a provider "
            "switch is visible in the data rather than inferred. A label only: "
            "it does not select an adapter, so changing it without also "
            "changing the base URL mislabels the rows."
        ),
    )
    ai_timeout_seconds: float = Field(
        20.0,
        description=(
            "Must stay below nginx's proxy_read_timeout, or a slow generation "
            "surfaces as a gateway timeout the client cannot interpret rather "
            "than the API's own 502."
        ),
    )
    prompt_version: str = Field(
        "v1",
        description="Stamped on generated rows so a prompt change is traceable.",
    )

    # --- privacy -----------------------------------------------------------

    ip_hash_salt: str = Field(
        "dev-only-change-me",
        description=(
            "Salts stored IP hashes. MUST be a random secret in any real "
            "deployment: without one an IP hash is reversible by brute force in "
            "seconds, because the whole IPv4 space is only 4 billion SHA-256 "
            "calls, which would make the privacy claim decorative."
        ),
    )

    # --- session and cost control ------------------------------------------

    session_ttl_hours: int = Field(
        24,
        description=(
            "Covers the customer who scans at the table and writes the review "
            "that evening. Expiry is authoritative on every read."
        ),
    )
    max_generations_per_session: int = Field(
        3,
        description=(
            "Successful suggestion batches per session. Enforced as an atomic "
            "UPDATE on generation_count, so it holds across workers and "
            "instances without shared state."
        ),
    )
    max_generation_attempts_per_session: int = Field(
        6,
        description=(
            "A monotonic ceiling on provider calls per session. Because a "
            "failed generation refunds its slot, the cap above bounds only "
            "successful batches — failures would otherwise be free and "
            "endlessly repeatable, which is unbounded spend for anyone holding "
            "a single token. Set above the success cap so ordinary transient "
            "failures are still forgiven."
        ),
    )
    create_rate_limit_per_hour: int = Field(
        60,
        description=(
            "Sessions per IP per hour. A runaway-script guard only, and "
            "deliberately loose: customers share public IPs behind "
            "carrier-grade NAT and restaurant wifi, so a tight limit locks out "
            "real people rather than attackers."
        ),
    )

    # --- deployment --------------------------------------------------------

    trust_proxy_headers: bool = Field(
        False,
        description=(
            "Trust X-Real-IP for rate limiting. Off by default so any "
            "deployment without a proxy in front — local uvicorn, a test "
            "client, a directly exposed instance — ignores client-supplied IP "
            "headers instead of believing them. Enable ONLY where a reverse "
            "proxy overwrites the header."
        ),
    )

    # --- generation shape --------------------------------------------------

    suggestions_per_batch: int = Field(
        3,
        description="Suggestions requested per generation. Fewer may be stored.",
    )
    suggestion_min_chars: int = Field(
        20,
        description="Below this a suggestion is discarded as not a review.",
    )
    suggestion_max_chars: int = Field(
        500,
        description="Above this a suggestion is discarded as unusable on a phone.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def env_example() -> str:
    """Renders .env.example from the fields above.

    Settings with a usable default are emitted commented out: they document
    what exists without becoming a second place the value is written. Secrets
    are emitted blank, because there is nothing to copy and leaving one unset
    should be obvious rather than silently inherited.
    """
    lines = [
        "# Generated from apps/api/app/config.py — do not edit by hand.",
        "#",
        "# Regenerate with:",
        "#   docker compose run --rm api python -m app.config --example > .env.example",
        "#",
        "# Copy to `.env` (that exact name — compose reads `.env`, not this file)",
        "# and fill in the secrets. Everything commented out already has the",
        "# value shown; uncomment only to override it.",
    ]

    for name, field in Settings.model_fields.items():
        lines.append("")
        if field.description:
            lines += textwrap.wrap(
                field.description, 76, initial_indent="# ", subsequent_indent="# "
            )
        key = name.upper()
        lines.append(f"{key}=" if name in SECRETS else f"# {key}={field.default}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if "--example" in sys.argv:
        sys.stdout.write(env_example())
    else:
        raise SystemExit("usage: python -m app.config --example")
