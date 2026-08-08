"""Turning merchant context into review suggestions.

Everything vendor-neutral lives here: prompt construction, topic rotation, the
avoid-list, and validation. The provider only turns two strings into one.
"""

from __future__ import annotations

import json
import unicodedata
import re
from dataclasses import dataclass

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import (
    Merchant,
    MerchantReviewContext,
    SmartReviewSession,
    SmartReviewSuggestion,
)
from app.providers.base import ProviderError, SuggestionProvider
from app.services import events

# Reads sensibly for a salon or a dentist as well as a restaurant. `food` would
# not, which is why it is not in the fallback.
DEFAULT_TOPICS = ("quality", "service", "value", "atmosphere")

# Matches smart_review_suggestions.topic. Truncated rather than rejected: an
# over-long topic from a seed file would otherwise fail the INSERT *after* the
# provider call has already been paid for.
TOPIC_MAX_CHARS = 60

# Markup would render as literal characters in Google's plain-text review box,
# and a link or handle in a review reads as spam and risks the merchant's
# listing — which is the merchant's asset, not ours to gamble.
_HTML = re.compile(r"<[^>]+>|&[a-z]+;|&#\d+;", re.I)

# A five-TLD allowlist let through .io, .ai, .shop and most of the real
# internet, so this covers the common TLDs instead.
_TLDS = (
    "com|net|org|io|ai|co|ca|uk|shop|store|app|dev|me|biz|info|us|au|nz"
    "|de|fr|es|it|nl|jp|cn|in|xyz|site|online|link|page|tech"
)

# The domain alternative is deliberately case-sensitive — `(?-i:…)` — so that a
# missing space after a full stop ("Loved it.Came back") is not read as a
# hostname. Real domains are written in lower case; sentence boundaries are not.
_URL = re.compile(
    rf"""(
        https?://
      | www\.
      | (?-i:\b[a-z0-9][a-z0-9-]*\.({_TLDS})\b)   # example.io, example.shop
      | \b\d{{1,3}}(\.\d{{1,3}}){{3}}\b            # bare IPv4
      | \b[a-z0-9._%+-]+@[a-z0-9.-]+\b             # email
      | (?:^|\s)@[a-z0-9._]{{2,}}                  # social handle
      | \bdot\s+({_TLDS})\b                        # "example dot com"
    )""",
    re.I | re.X,
)

# Zero-width and bidirectional-override characters. They pad the length check
# without adding anything a reader can see, and an RTL override can reorder how
# the text renders on Google.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")

# The cost-control statement. The predicate is evaluated by the database while
# the row is locked, so concurrent requests cannot both pass it. Callers must
# take the generation number from RETURNING — reading the ORM attribute gives a
# stale value, and SELECT max()+1 races.
_CLAIM_GENERATION = sql_text(
    "UPDATE smart_review_sessions "
    "SET generation_count = generation_count + 1, "
    "    generation_attempts = generation_attempts + 1 "
    "WHERE id = :session_id "
    "  AND generation_count < :cap "
    "  AND generation_attempts < :attempt_cap "
    "RETURNING generation_count"
)

# Conditional on the claim still being the newest one. An unconditional
# decrement refunds *the counter*, not *this caller's claim*: if another
# request claimed a higher number while this one was waiting on the provider,
# decrementing hands the next caller a generation_number that is already in use,
# and the unique constraint then rejects every subsequent attempt — permanently,
# because the failure rolls the claim back so the collision repeats forever.
#
# generation_attempts is deliberately not refunded; it is what bounds spend.
_RELEASE_GENERATION = sql_text(
    "UPDATE smart_review_sessions "
    "SET generation_count = generation_count - 1 "
    "WHERE id = :session_id AND generation_count = :claimed"
)


@dataclass(frozen=True)
class Draft:
    text: str
    topic: str


def topics_for_generation(
    context: MerchantReviewContext | None, generation_number: int, count: int
) -> list[str]:
    """One topic per suggestion, rotating by generation.

    Within a batch the three cards cover different angles, so they read as
    genuinely different reviews rather than three paraphrases — that difference
    is what the customer sees side by side. Across batches the window advances,
    so Generate More is not a slot machine returning the same ideas.
    """
    # Gated on approval like every other context field. Topics are rendered
    # verbatim into the prompt, so an unapproved list is an unreviewed
    # instruction channel straight to the model — the one path that would
    # otherwise bypass the approval check in _context_lines.
    stored = context.experience_topics if context is not None and context.is_approved else None

    # The list check is on the container, not just the items. JSONB holds
    # whatever the seed file put there, and iterating a bare string yields
    # single characters — each of which is itself a string, so an item-level
    # check alone would happily produce the topics 'q', 'u', 'a'.
    raw = stored if isinstance(stored, list) else []

    available = [
        topic.strip()[:TOPIC_MAX_CHARS]
        for topic in raw
        if isinstance(topic, str) and topic.strip()
    ] or list(DEFAULT_TOPICS)

    offset = (generation_number - 1) * count
    return [available[(offset + index) % len(available)] for index in range(count)]


def _context_lines(merchant: Merchant, context: MerchantReviewContext | None) -> str:
    lines = [f"Business name: {merchant.name}"]
    if merchant.category:
        lines.append(f"Category: {merchant.category}")
    if merchant.city:
        lines.append(f"City: {merchant.city}")

    # An unapproved context is merchant data nobody has signed off on. Using it
    # would put unreviewed claims about the business into a public review.
    if context is None or not context.is_approved:
        return "\n".join(lines)

    if context.business_summary:
        lines.append(f"About: {context.business_summary.strip()}")

    for label, values in (
        ("Products", context.products),
        ("Services", context.services),
        ("Menu items", context.menu_items),
        ("What regulars praise", context.selling_points),
        ("Keywords the merchant approved", context.approved_keywords),
    ):
        if values:
            lines.append(f"{label}: {', '.join(str(value) for value in values)}")

    if context.custom_instructions:
        lines.append(f"Merchant instructions: {context.custom_instructions.strip()}")

    return "\n".join(lines)


def build_prompt(
    merchant: Merchant,
    context: MerchantReviewContext | None,
    topics: list[str],
    avoid: list[str],
    *,
    stricter: bool = False,
) -> tuple[str, str]:
    settings = get_settings()

    system = (
        "You draft short review suggestions that a real customer could choose "
        "to post about a business they visited. You are writing options for a "
        "person to pick from and edit, never a finished review posted on their "
        "behalf.\n\n"
        "Rules:\n"
        f"- Each suggestion is between {settings.suggestion_min_chars} and "
        f"{settings.suggestion_max_chars} characters.\n"
        "- Plain text only. No markup, no links, no email addresses, no emoji.\n"
        "- Sound like an ordinary person typing on a phone: plain words, "
        "everyday sentence shapes, no marketing language, no exclamation marks.\n"
        "- Stay within the supplied facts. Never invent a dish, a staff member, "
        "a price, a date, or a detail that is not listed.\n"
        "- Write nothing that assumes a specific rating, visit date, or party size.\n"
        "- Return only a JSON array of strings, one per requested topic, in order."
    )

    if stricter:
        system += (
            "\n\nThe previous attempt was unusable. Return ONLY a JSON array of "
            "plain strings — no prose, no code fences, no object wrapper."
        )

    parts = [
        _context_lines(merchant, context),
        "",
        f"Write exactly {len(topics)} suggestions, one for each of these topics, in order:",
    ]
    parts += [f"{index + 1}. {topic}" for index, topic in enumerate(topics)]

    if avoid:
        parts += [
            "",
            "This customer has already seen the suggestions below. Cover a "
            "different angle and do not reuse their wording:",
        ]
        parts += [f"- {item}" for item in avoid]

    parts += ["", 'Respond with JSON only, for example: ["first", "second", "third"]']

    return system, "\n".join(parts)


def parse_batch(raw: str) -> list[str]:
    """Pull a list of strings out of whatever the model returned.

    Written defensively on purpose: not using vendor-specific structured output
    is what keeps this portable across compatible endpoints, and the cost of
    that choice is paid here rather than in a lock-in.
    """
    if not raw:
        return []

    candidate = raw.strip()

    # Strip ``` fences, with or without a language tag.
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)

    parsed = _loads(candidate)

    # Bracket extraction only after a clean parse has failed. Doing it first
    # would rewrite every JSON object down to its first array, making the
    # wrapper branch below unreachable and mangling {"topics": [...],
    # "suggestions": [...]} into the wrong list.
    if parsed is None:
        start, end = candidate.find("["), candidate.rfind("]")
        if start != -1 and end > start:
            parsed = _loads(candidate[start : end + 1])

    # Some models answer {"suggestions": [...]} despite being told not to, and
    # some add a sibling array such as {"topics": [...]}. Prefer the key that
    # names what we asked for; taking the first list would return the topics.
    if isinstance(parsed, dict):
        named = [
            value
            for key, value in parsed.items()
            if isinstance(value, list)
            and any(word in str(key).lower() for word in ("suggestion", "review"))
        ]
        others = [value for value in parsed.values() if isinstance(value, list)]
        parsed = next(iter(named or others), None)

    if not isinstance(parsed, list):
        return []

    return [item.strip() for item in parsed if isinstance(item, str) and item.strip()]


def _loads(candidate: str) -> object | None:
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def normalise(candidate: str) -> str:
    """Canonical form before any rule is applied.

    NFKC folds lookalike codepoints onto their plain equivalents, invisible
    characters are removed outright, and runs of whitespace collapse. Without
    this the length rule counts characters nobody can see — twenty zero-width
    spaces would satisfy a twenty-character minimum.
    """
    folded = unicodedata.normalize("NFKC", candidate)
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", folded)).strip()


def validate(candidate: str) -> bool:
    settings = get_settings()
    text_value = normalise(candidate)

    if not (
        settings.suggestion_min_chars
        <= len(text_value)
        <= settings.suggestion_max_chars
    ):
        return False

    return not _HTML.search(text_value) and not _URL.search(text_value)


def _previous_texts(db: Session, session: SmartReviewSession) -> list[str]:
    return list(
        db.scalars(
            select(SmartReviewSuggestion.text_)
            .where(SmartReviewSuggestion.session_id == session.id)
            .order_by(SmartReviewSuggestion.created_at)
        ).all()
    )


def generate(
    db: Session,
    session: SmartReviewSession,
    provider: SuggestionProvider,
) -> list[SmartReviewSuggestion]:
    settings = get_settings()

    # Claimed before the provider call, not after: the whole point is that two
    # concurrent requests cannot both decide there is quota left.
    generation_number = db.execute(
        _CLAIM_GENERATION,
        {
            "session_id": session.id,
            "cap": settings.max_generations_per_session,
            "attempt_cap": settings.max_generation_attempts_per_session,
        },
    ).scalar()

    if generation_number is None:
        raise ApiError(429, "generation_limit_reached")

    # Committed before the provider call. Otherwise the row's write lock and a
    # pooled connection are both held for the whole multi-second generation,
    # which blocks every other request touching this session — including the
    # unload-time completion beacon — and exhausts the connection pool under a
    # handful of concurrent generations.
    db.commit()

    merchant = session.merchant
    context = db.scalar(
        select(MerchantReviewContext).where(
            MerchantReviewContext.merchant_id == merchant.id
        )
    )

    topics = topics_for_generation(
        context, generation_number, settings.suggestions_per_batch
    )
    avoid = _previous_texts(db, session)

    drafts = _attempt(provider, merchant, context, topics, avoid, stricter=False)

    if not drafts:
        # One retry, and only on total failure. Retrying a partly-good batch
        # would double the customer's wait to gain a third card they did not
        # ask for.
        drafts = _attempt(provider, merchant, context, topics, avoid, stricter=True)

    if not drafts:
        # Refund the slot, but only if no one else claimed a higher number in
        # the meantime. A provider outage must not consume a real customer's
        # allowance; generation_attempts still went up, so this forgiveness
        # cannot be repeated without limit.
        db.execute(
            _RELEASE_GENERATION,
            {"session_id": session.id, "claimed": generation_number},
        )
        events.record(
            db,
            session,
            "GENERATION_FAILED",
            metadata={"generation_number": generation_number},
        )
        db.commit()
        raise ApiError(502, "generation_unavailable")

    stored = []
    for position, draft in enumerate(drafts, start=1):
        suggestion = SmartReviewSuggestion(
            session_id=session.id,
            merchant_id=merchant.id,
            generation_number=generation_number,
            # Renumbered 1..n: a batch where only some drafts validated is
            # shorter, never sparse.
            position=position,
            text_=draft.text,
            topic=draft.topic,
            model_provider=provider.name,
            model_name=provider.model,
            prompt_version=settings.prompt_version,
        )
        db.add(suggestion)
        stored.append(suggestion)

    # SQL increment, not a Python read-modify-write on the ORM attribute: two
    # concurrent generations reading the same value would each write back the
    # same total and lose one batch from the count.
    db.execute(
        sql_text(
            "UPDATE smart_review_sessions "
            "SET suggestion_count = suggestion_count + :n WHERE id = :session_id"
        ),
        {"n": len(stored), "session_id": session.id},
    )
    db.flush()

    events.record(
        db,
        session,
        "SUGGESTIONS_GENERATED",
        metadata={
            "generation_number": generation_number,
            "count": len(stored),
            "topics": [draft.topic for draft in drafts],
        },
    )

    return stored


def _attempt(
    provider: SuggestionProvider,
    merchant: Merchant,
    context: MerchantReviewContext | None,
    topics: list[str],
    avoid: list[str],
    *,
    stricter: bool,
) -> list[Draft]:
    system, user = build_prompt(merchant, context, topics, avoid, stricter=stricter)

    try:
        raw = provider.complete(system, user)
    except ProviderError:
        return []

    candidates = parse_batch(raw)

    # Zip against topics so a suggestion keeps the angle it was asked for even
    # when an earlier one in the batch was dropped.
    return [
        Draft(text=candidate, topic=topic)
        for candidate, topic in zip(candidates, topics, strict=False)
        if validate(candidate)
    ]
