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

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values with no sensible default: they are per-deployment secrets, and shipping
# one would mean a deployment that looks configured but is not. Emitted blank in
# .env.example so an unset one is visible rather than inherited.
SECRETS = frozenset({"openai_api_key", "ip_hash_salt", "google_api_key"})

# The places adapters that exist. Anything else is refused at startup rather
# than at the first request.
LEAD_PROVIDERS = frozenset({"google", "fake"})

# nginx proxies /api/* with proxy_read_timeout 60s. A search that runs longer
# reaches the operator as nginx's own 504 HTML instead of the API's JSON error
# envelope, so the worst-case search must fit inside this, which is itself well
# under 60. Read twice: as the ceiling the settings below are validated against,
# and as the wall-clock deadline app.services.leads.search stops paging on.
LEAD_SEARCH_BUDGET_SECONDS = 45.0


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

    # --- lead crawler ------------------------------------------------------

    public_base_url: str = Field(
        "http://localhost:8080",
        description=(
            "Origin the public reaches this deployment at. The merchant URL the "
            "lead crawler hands over is built from this rather than from the "
            "operator's browser origin, which is routinely a dev port — a link "
            "copied from the Vite server would otherwise read as normal and be "
            "dead everywhere else. Never stored; composed per response."
        ),
    )
    lead_provider: str = Field(
        "google",
        description=(
            "Which places provider the crawler talks to: 'google' or 'fake'. "
            "The fake answers from a fixed set of Richmond and Vancouver "
            "listings and needs no key, so the tool can be run and demonstrated "
            "without a billing account. Unlike ai_provider this does select an "
            "adapter — an unknown value is refused at startup."
        ),
    )
    google_api_key: str = Field(
        "",
        description=(
            "Credential for Places API (New) and the Geocoding API. Required to "
            "search. Restrict it to those two APIs and set a per-day quota on "
            "each: the crawler endpoints are unauthenticated in the MVP, so that "
            "quota is the only ceiling on what a stranger can spend."
        ),
    )
    lead_search_max_pages: int = Field(
        3,
        ge=1,
        description=(
            "Pages of Google results fetched per search, and the hard bound on "
            "what one search bills. Google stops issuing page tokens after 60 "
            "results, which is three pages at the default page size."
        ),
    )
    lead_search_page_size: int = Field(
        20,
        ge=1,
        le=20,
        description=(
            "Listings Google returns per page, up to its ceiling of 20. Billing "
            "is per request, not per listing, so a smaller page buys fewer "
            "listings for the same price; it is a way to shrink a demo, not to "
            "save money. It never caps the search — that is "
            "LEAD_SEARCH_MAX_RESULTS."
        ),
    )
    lead_search_max_results: int = Field(
        60,
        ge=1,
        description=(
            "Post-filter matches that are enough: pagination stops once the "
            "search holds this many and the response says `truncated`. Defaults "
            "to Google's own ceiling of 60 results, so by default nothing is "
            "cut short. Lowering it saves billed pages; the flag is what keeps "
            "the shorter list from reading as everything Google had."
        ),
    )
    lead_search_timeout_seconds: float = Field(
        8.0,
        gt=0,
        description=(
            "Budget for one Google call, split across httpx's connect, write, "
            "read and pool phases so the phases sum to it rather than each "
            "getting all of it. One search makes up to one geocode plus "
            "LEAD_SEARCH_MAX_PAGES search requests, so its planned worst case "
            "is (LEAD_SEARCH_MAX_PAGES + 1) x this: 32s at the defaults, and "
            "startup refuses a combination whose product exceeds the budget "
            "that keeps a search under nginx's 60s proxy_read_timeout. What "
            "enforces that at run time is the deadline in "
            "app.services.leads.search, which stops paging once the budget is "
            "nearly spent: httpx phase timeouts cannot, because `read` bounds "
            "the gap between chunks and not the length of a response, so a "
            "single trickled response still outlives any of them."
        ),
    )

    @field_validator("lead_provider")
    @classmethod
    def _known_lead_provider(cls, value: str) -> str:
        # Unlike ai_provider this selects an adapter. A typo must stop the
        # process: defaulting to Google would spend money the operator thought
        # they were not spending, and answering every request with a 500 while
        # the healthcheck stays green hides the fault entirely.
        if value not in LEAD_PROVIDERS:
            raise ValueError(f"must be one of {sorted(LEAD_PROVIDERS)}")
        return value

    @model_validator(mode="after")
    def _search_fits_inside_the_proxy_timeout(self) -> "Settings":
        # Refuses a combination that cannot fit even when every call behaves.
        # Run-time enforcement is the deadline in app.services.leads.search;
        # this only keeps the configured plan from blowing the budget on its
        # own, which no deadline could rescue without abandoning every page.
        worst_case = self.lead_search_timeout_seconds * (self.lead_search_max_pages + 1)
        if worst_case > LEAD_SEARCH_BUDGET_SECONDS:
            raise ValueError(
                "LEAD_SEARCH_TIMEOUT_SECONDS x (LEAD_SEARCH_MAX_PAGES + 1) is "
                f"{worst_case}s, above the {LEAD_SEARCH_BUDGET_SECONDS}s budget "
                "that keeps a search inside nginx's proxy_read_timeout"
            )
        return self


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
