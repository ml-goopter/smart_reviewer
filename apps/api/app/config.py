from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from the environment.

    Every knob the MVP tunes in production lives here rather than in code, so
    changing a limit or swapping an AI provider is a restart, not a deploy.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://reviewer:reviewer@db:5432/reviewer"

    # AI provider. The `openai` SDK is used purely as a transport: pointing
    # base_url at any OpenAI-compatible endpoint switches providers with no
    # code change. Providers that are not wire-compatible get a new adapter
    # implementing app.providers.base.SuggestionProvider.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    ai_provider: str = "openai"
    ai_timeout_seconds: float = 20.0
    prompt_version: str = "v1"

    # Salts the stored IP hashes. Without a secret, an IP "hash" is reversible
    # by brute force in seconds — the entire IPv4 space is only 4 billion
    # SHA-256 calls — which would make the privacy claim decorative. Override
    # in every real deployment.
    ip_hash_salt: str = "dev-only-change-me"

    # Session lifetime. 24h covers the customer who scans at the table and
    # writes the review that evening; expiry is authoritative on every read.
    session_ttl_hours: int = 24

    # Cost control. Enforced as an atomic UPDATE on generation_count, so it
    # holds across workers and instances without shared state.
    max_generations_per_session: int = 5

    # A monotonic ceiling on provider calls per session. Because a failed
    # generation refunds its slot, generation_count alone bounds only successful
    # batches — failures would otherwise be free and endlessly repeatable, which
    # is unbounded spend for anyone holding a single token. Set above the
    # success cap so ordinary transient failures are still forgiven.
    max_generation_attempts_per_session: int = 10

    # Runaway-script guard only. Deliberately loose: customers share public IPs
    # behind carrier-grade NAT and restaurant wifi, so a tight limit here locks
    # out real people rather than attackers.
    create_rate_limit_per_hour: int = 60

    # Off by default so that any deployment without a proxy in front — local
    # uvicorn, a test client, a future direct-exposed instance — ignores
    # client-supplied IP headers instead of believing them. docker-compose
    # turns it on for the api service, where nginx guarantees the header.
    trust_proxy_headers: bool = False

    suggestions_per_batch: int = 3
    suggestion_min_chars: int = 20
    suggestion_max_chars: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
