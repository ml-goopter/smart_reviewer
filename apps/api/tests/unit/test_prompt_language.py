"""The language reaches the model as an instruction, not as a code.

This is the one place a customer-chosen value is interpolated into a prompt, so
the set of accepted values and the set of instructions have to agree exactly —
a gap between them is either a crash or an unconstrained prompt, depending on
which way it falls.
"""

import pytest

from app.models import DEFAULT_LANGUAGE, LANGUAGES
from app.services.suggestions import LANGUAGE_INSTRUCTIONS, build_prompt

TOPICS = ["quality", "service", "value"]


class FakeMerchant:
    name = "Pho 37"
    category = "Vietnamese Restaurant"
    city = "Richmond"


def prompt_for(language: str) -> str:
    system, user = build_prompt(
        FakeMerchant(), None, TOPICS, [], language=language
    )
    return system + "\n" + user


def test_every_served_language_has_an_instruction():
    """The comment on LANGUAGE_INSTRUCTIONS says a test enforces this rather
    than a default, because a default would silently draft in the wrong
    language instead of failing."""
    assert set(LANGUAGE_INSTRUCTIONS) == set(LANGUAGES)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_instruction_is_in_the_prompt(language):
    assert LANGUAGE_INSTRUCTIONS[language] in prompt_for(language)


def test_the_two_chinese_prompts_are_not_interchangeable():
    """Traditional and Simplified share codepoints, so 'write in Chinese' would
    let the model pick either. Naming the script is the whole point of serving
    the two separately."""
    traditional = prompt_for("zh-Hant")
    simplified = prompt_for("zh-Hans")

    assert "繁體中文" in traditional and "简体中文" not in traditional
    assert "简体中文" in simplified and "繁體中文" not in simplified


def test_an_unknown_language_raises_rather_than_defaulting():
    """Reaching build_prompt with an unserved language means validation let it
    through. Drafting in English instead would hide that behind output that
    looks deliberate."""
    with pytest.raises(KeyError):
        prompt_for("klingon")


def test_english_is_the_default():
    system, _ = build_prompt(FakeMerchant(), None, TOPICS, [])

    assert LANGUAGE_INSTRUCTIONS[DEFAULT_LANGUAGE] in system


def test_the_merchant_context_is_not_expected_to_be_translated_already():
    """Merchant details are stored in whatever language the merchant wrote
    them. Without this rule the model copies the business summary across
    verbatim and the suggestion comes back half English."""
    assert "translate what you need from them" in prompt_for("zh-Hant")
