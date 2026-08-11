"""Generating in more than one language, end to end.

The per-language cap is proved against the SQL in test_generation_cap.py and
test_generation_refund.py. What is proved here is the behaviour a customer
tapping the drawer actually gets: the languages do not spend each other's
allowance, every language's suggestions come back from one GET, and the
avoid-list does not leak across languages.
"""

import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import (
    LANGUAGES,
    SmartReviewSessionLanguage,
    SmartReviewSuggestion,
)
from app.routers.review import get_provider
from tests.integration.test_suggestions import GOOD, StubProvider

CREATE = "/api/review/sessions"

CHINESE = [
    "湯頭很濃郁，牛肉份量也很足，午餐時間上菜很快。",
    "店員親切但不會一直來打擾，水也會主動幫忙加。",
    "店面樸實但坐起來舒服，中午還算安靜，可以好好聊天。",
]


@pytest.fixture
def provider():
    return StubProvider()


@pytest.fixture
def api(client, provider):
    from app.main import app

    app.dependency_overrides[get_provider] = lambda: provider
    yield client
    app.dependency_overrides.pop(get_provider, None)


def token_for(api, merchant) -> str:
    return api.post(CREATE, json={"merchantId": str(merchant.id)}).json()["token"]


def generate(api, token, language=None):
    body = {} if language is None else {"language": language}
    return api.post(f"{CREATE}/{token}/suggestions", json=body)


def test_each_language_gets_its_own_full_allowance(api, merchant, provider):
    """The point of the change: a customer reading Chinese is not handed
    whatever English happened to leave behind."""
    cap = get_settings().max_generations_per_language
    provider.responses = [json.dumps(GOOD) for _ in range(cap * 2 + 2)]
    token = token_for(api, merchant)

    for _ in range(cap):
        assert generate(api, token, "en").status_code == 201

    assert generate(api, token, "en").status_code == 429

    # Traditional Chinese starts from a full allowance of its own.
    for _ in range(cap):
        assert generate(api, token, "zh-Hant").status_code == 201

    assert generate(api, token, "zh-Hant").status_code == 429

    # And English is still spent — one language's cap is not reset by another.
    assert generate(api, token, "en").status_code == 429


def test_the_session_wide_ceiling_still_bounds_every_language_together(
    api, merchant, provider
):
    """The attempts ceiling is deliberately not per language: it is what one
    leaked token can cost, and splitting it would multiply that."""
    provider.error = True
    ceiling = get_settings().max_generation_attempts_per_session
    token = token_for(api, merchant)

    languages = ["en", "zh-Hant", "zh-Hans"]
    statuses = [
        generate(api, token, languages[index % len(languages)]).status_code
        for index in range(ceiling + 2)
    ]

    # Spread across languages, the failures still run into one shared ceiling.
    assert statuses.count(502) == ceiling
    assert statuses[-1] == 429


def test_the_attempt_ceiling_does_not_consume_a_language_cap(
    api, merchant, provider, db
):
    """A request refused by the session ceiling never reached the provider, so
    the generation it claimed on the way in has to go back — otherwise the
    ceiling silently eats allowances in languages that never generated."""
    provider.error = True
    ceiling = get_settings().max_generation_attempts_per_session
    token = token_for(api, merchant)

    for _ in range(ceiling):
        assert generate(api, token, "en").status_code == 502

    # The ceiling is spent. A first-ever request in another language is refused
    # and must leave that language's counter untouched.
    assert generate(api, token, "zh-Hans").status_code == 429

    spent = db.scalars(
        select(SmartReviewSessionLanguage.generation_count).where(
            SmartReviewSessionLanguage.language == "zh-Hans"
        )
    ).all()

    # Either no row at all, or a row that was created and immediately given
    # back. Both mean the same thing: nothing was spent.
    assert spent in ([], [0])


def test_a_session_returns_every_language_tagged(api, merchant, provider):
    """The browser holds all of them and shows the ones matching the screen, so
    switching back to a language it has already generated costs no round-trip
    and does not re-mark the session opened."""
    provider.responses = [json.dumps(GOOD), json.dumps(CHINESE)]
    token = token_for(api, merchant)

    generate(api, token, "en")
    generate(api, token, "zh-Hant")

    suggestions = api.get(f"{CREATE}/{token}").json()["suggestions"]
    by_language = {}
    for item in suggestions:
        by_language.setdefault(item["language"], []).append(item["text"])

    assert set(by_language) == {"en", "zh-Hant"}
    assert by_language["en"] == GOOD
    assert by_language["zh-Hant"] == CHINESE


def test_the_avoid_list_does_not_cross_languages(api, merchant, provider):
    """The previous suggestions become a do-not-repeat instruction. Feeding the
    English batch into a Chinese prompt spends budget on text the model cannot
    repeat anyway, and invites it to translate those rather than write new
    ones."""
    provider.responses = [json.dumps(GOOD), json.dumps(CHINESE)]
    token = token_for(api, merchant)

    generate(api, token, "en")
    generate(api, token, "zh-Hant")

    _system, chinese_prompt = provider.calls[-1]

    for english in GOOD:
        assert english not in chinese_prompt


def test_generation_numbers_restart_in_each_language(api, merchant, provider, db):
    """Each language is a faithful copy of the single-language product, so its
    first batch covers the same strongest topics rather than continuing another
    language's rotation."""
    provider.responses = [json.dumps(GOOD), json.dumps(CHINESE)]
    token = token_for(api, merchant)

    generate(api, token, "en")
    generate(api, token, "zh-Hant")

    numbers = db.execute(
        select(
            SmartReviewSuggestion.language, SmartReviewSuggestion.generation_number
        ).distinct()
    ).all()

    assert sorted(numbers) == [("en", 1), ("zh-Hant", 1)]


def test_the_stored_rows_carry_the_language_they_were_asked_for(
    api, merchant, provider, db
):
    provider.responses = [json.dumps(CHINESE)]
    token = token_for(api, merchant)

    generate(api, token, "zh-Hans")

    languages = db.scalars(select(SmartReviewSuggestion.language)).all()

    assert set(languages) == {"zh-Hans"}


def test_a_body_less_post_still_generates_english(api, merchant, provider, db):
    """The client that predates this field must keep working unchanged."""
    token = token_for(api, merchant)

    assert generate(api, token).status_code == 201

    languages = db.scalars(select(SmartReviewSuggestion.language)).all()

    assert set(languages) == {"en"}


def test_the_batch_that_spends_the_last_slot_reports_the_cap(api, merchant, provider):
    """The browser cannot know the cap, so a batch that leaves no allowance has
    to say so. Without it the limit is discoverable only from the request that
    fails on it — one press after Generate More should have gone."""
    cap = get_settings().max_generations_per_language
    provider.responses = [json.dumps(GOOD) for _ in range(cap)]
    token = token_for(api, merchant)

    flags = [generate(api, token, "en").json()["capReached"] for _ in range(cap)]

    # False until the last, and true on it — the boundary, not one either side.
    assert flags == [False] * (cap - 1) + [True]


def test_a_spent_language_does_not_report_another_as_capped(api, merchant, provider):
    cap = get_settings().max_generations_per_language
    provider.responses = [json.dumps(GOOD) for _ in range(cap)] + [json.dumps(CHINESE)]
    token = token_for(api, merchant)

    for _ in range(cap):
        generate(api, token, "en")

    # zh-Hant has no row at all, which is not the same as having no allowance.
    assert generate(api, token, "zh-Hant").json()["capReached"] is False


def test_get_reports_the_languages_a_returning_customer_has_spent(
    api, merchant, provider
):
    """A session outlives the tab. The browser starts from this list, or it
    starts every load believing the whole allowance is still there."""
    cap = get_settings().max_generations_per_language
    provider.responses = [json.dumps(GOOD) for _ in range(cap)] + [json.dumps(CHINESE)]
    token = token_for(api, merchant)

    assert api.get(f"{CREATE}/{token}").json()["cappedLanguages"] == []

    for _ in range(cap):
        generate(api, token, "en")
    generate(api, token, "zh-Hant")

    body = api.get(f"{CREATE}/{token}").json()

    # Spent in English, and one batch into an allowance in Chinese.
    assert body["cappedLanguages"] == ["en"]


def test_a_zero_cap_is_reported_as_spent_before_anything_is_generated(
    api, merchant, monkeypatch
):
    """Zero turns generation off, which the claim statement supports. A
    language with no row is at zero generations, so the reported answer has to
    come from comparing against the cap rather than from the row existing."""
    monkeypatch.setenv("MAX_GENERATIONS_PER_LANGUAGE", "0")
    get_settings.cache_clear()

    try:
        token = token_for(api, merchant)

        assert api.get(f"{CREATE}/{token}").json()["cappedLanguages"] == list(LANGUAGES)
    finally:
        # Process-wide cache: leaving a zero cap behind would silently disarm
        # every generation test that runs after this one.
        get_settings.cache_clear()
