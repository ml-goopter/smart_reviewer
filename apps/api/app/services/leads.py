"""Merchant discovery: everything Google will not do for us.

Google filters by radius, place type and a rating *floor*. It has no filter for
a rating ceiling and none at all for review count — which is the filter this
tool exists for, since a merchant with few reviews is the lead worth having. So
those run here, after the fetch, and the response reports the funnel (how many
listings were looked at, how many survived) rather than presenting a short list
as if it were everything Google had.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import LEAD_SEARCH_BUDGET_SECONDS, get_settings
from app.geo import haversine_m
from app.models import Merchant, MerchantReviewContext
from app.providers.places_base import (
    GeocodeResult,
    PlaceDetails,
    PlaceResult,
    PlacesProvider,
    PlacesQuery,
    ProviderError,
)
# The review destination is a plain template over the Place ID, not an API call
# — nothing here costs a Google request. Lived in the seed module until that was
# deleted; this is now its only consumer.
GOOGLE_REVIEW_URL_TEMPLATE = (
    "https://search.google.com/local/writereview?placeid={place_id}"
)

# Google place types the sales team actually prospects. Deliberately not
# Google's full table, most of which is irrelevant (heliport, cemetery), and
# deliberately server-side so the dropdown cannot send a type Google rejects.
CATEGORIES: dict[str, str] = {
    "restaurant": "Restaurant",
    "cafe": "Cafe",
    "bar": "Bar",
    "bakery": "Bakery",
    "meal_takeaway": "Takeout",
    "hair_salon": "Hair salon",
    "nail_salon": "Nail salon",
    "spa": "Spa",
    "gym": "Gym",
    "dentist": "Dentist",
    "car_repair": "Auto repair",
    "florist": "Florist",
    "pet_store": "Pet store",
    "book_store": "Book store",
}

# Google's own ceiling on a circle.
MAX_RADIUS_M = 50_000

# What a suggestion may be *about*, per kind of business, driving the one-topic
# per-suggestion rotation. Matched loosely against Google's display category,
# because that is free text: "Sushi Restaurant", "Vietnamese Restaurant" and
# "Restaurant" must all land on the same list.
TOPIC_DEFAULTS: dict[str, list[str]] = {
    "restaurant": ["the food", "the service", "the atmosphere", "value for money"],
    "cafe": ["the coffee", "the service", "the space", "the baking"],
    "bakery": ["the baking", "the service", "freshness", "value for money"],
    "bar": ["the drinks", "the service", "the atmosphere", "the music"],
    "salon": ["the result", "the stylist", "the space", "the booking experience"],
    "spa": ["the treatment", "the therapist", "the space", "how you felt after"],
    "dentist": ["the care", "the staff", "the clinic", "how the visit felt"],
    "gym": ["the equipment", "the staff", "the classes", "the facilities"],
}

# Used when nothing matches. The generator has its own fallback for an empty
# list, but a merchant-shaped default beats a generic one.
GENERIC_TOPICS = ["the quality", "the service", "the experience", "value for money"]

# Trimmed well inside merchants.slug's 120 characters so the collision suffix
# can never be what pushes it over.
MAX_SLUG_BASE = 100

# Inserts one save may attempt. Above one because a slug race is resolved by
# choosing a different slug, and the only way to know a slug was taken is to be
# refused it; bounded because a fault that is not a race would otherwise loop.
SAVE_ATTEMPTS = 3


class LocationNotFound(Exception):
    """The operator typed a place Google does not know."""


@dataclass(frozen=True)
class SearchCriteria:
    location: str
    radius_m: int
    text_query: str | None = None
    category: str | None = None
    min_rating: float | None = None
    max_rating: float | None = None
    max_review_count: int | None = None


@dataclass(frozen=True)
class SearchHit:
    place: PlaceResult
    distance_m: int | None
    saved: bool
    merchant_id: UUID | None = None
    # The saved row's subscription, if it has one. Carried so the operator can
    # see from the result list whether a URL they already hold still opens.
    subscription: object | None = None


@dataclass(frozen=True)
class SearchOutcome:
    resolved: GeocodeResult
    searched: int
    matched: int
    partial: bool
    results: list[SearchHit]
    # Google still had pages when this search stopped — the result target, the
    # page cap or the wall-clock deadline. Without it a deliberately short list
    # reads as everything Google had.
    truncated: bool = False


class CriteriaTooBroad(Exception):
    """Nothing to search *for*, only somewhere to search."""


def build_text_query(criteria: SearchCriteria) -> str:
    """What Google is actually asked for: the typed text, else the category.

    Not `criteria.text_query`: the request must carry this value, never the raw
    field, or the category fallback below is lost.

    The category normally rides in `includedType` alone, so it does not compete
    with the typed text for relevance — a category word in the text pulls in
    every listing that merely mentions it. But `searchText` rejects an empty
    textQuery outright, and "every restaurant near this postal code" is the
    most ordinary search this tool performs, so with nothing typed the category
    becomes the query as well as the type filter.
    """
    typed = (criteria.text_query or "").strip()
    if typed:
        return typed

    if criteria.category:
        return CATEGORIES.get(criteria.category, criteria.category).lower()

    # A location and nothing else. Inventing a term here would silently decide
    # what the operator was looking for; searchNearby is the API that answers
    # this question, and adopting it is a deliberate change, not a fallback.
    raise CriteriaTooBroad


def matches(criteria: SearchCriteria, place: PlaceResult) -> bool:
    """The filters Google cannot apply — and the rating floor it applies coarsely.

    Missing signal passes every bound, on purpose. A listing with no rating and
    no reviews is not a listing we know nothing about — it is a business nobody
    has reviewed yet, which is the strongest lead on the page. Excluding it
    would quietly hide exactly what the operator is hunting for; Google's own
    floor already drops unrated listings before we see them.

    The floor is re-applied here because Google honours `minRating` in 0.5
    steps only and which way it rounds is unconfirmed (spec §2.1.17). Google is
    sent the step *below* the asked-for floor, so it never filters past it, and
    the exact floor is this comparison.

    Listings between the sent step and the asked-for floor therefore arrive and
    are dropped here, after being counted in `searched`. That inflation is
    intended: `searched` is what Google was billed for, not what could have
    matched, and hiding those listings would understate the cost of a search.
    """
    if criteria.min_rating is not None and place.rating is not None:
        if place.rating < Decimal(str(criteria.min_rating)):
            return False

    if criteria.max_rating is not None and place.rating is not None:
        if place.rating > Decimal(str(criteria.max_rating)):
            return False

    if criteria.max_review_count is not None:
        if (place.review_count or 0) > criteria.max_review_count:
            return False

    return True


def _within(centre: GeocodeResult, radius_m: int, place: PlaceResult) -> bool:
    """The radius, enforced here because Google could not.

    searchText restricts to a *rectangle*, whose corners reach about 1.41x the
    radius — so "within 5 km" would otherwise include a merchant 7 km away in
    the diagonal. A listing Google returned without coordinates is kept: it
    satisfied the rectangle, and dropping it for missing data would hide a
    merchant that is almost certainly in range.
    """
    if place.lat is None or place.lng is None:
        return True
    return haversine_m(centre.lat, centre.lng, place.lat, place.lng) <= radius_m


def search(
    db: Session, provider: PlacesProvider, criteria: SearchCriteria
) -> SearchOutcome:
    settings = get_settings()
    started = monotonic()

    # Before the geocode, which is itself a billed call: a search with nothing
    # to look for cannot be answered however well the location resolves.
    text = build_text_query(criteria)

    resolved = provider.geocode(criteria.location)
    if resolved is None:
        # Nothing was searched, so an empty result list would be a lie: it would
        # read as "no merchants match" rather than "that is not a place".
        raise LocationNotFound(criteria.location)

    radius = max(1, min(criteria.radius_m, MAX_RADIUS_M))
    query = PlacesQuery(
        text_query=text,
        lat=resolved.lat,
        lng=resolved.lng,
        radius_m=radius,
        included_type=criteria.category,
        min_rating=criteria.min_rating,
        page_size=settings.lead_search_page_size,
    )

    searched = 0
    partial = False
    capped = False
    seen: set[str] = set()
    hits: list[PlaceResult] = []
    page_token: str | None = None

    # A page request that starts without a whole per-request budget left cannot
    # finish inside LEAD_SEARCH_BUDGET_SECONDS, so it is not started: past that
    # the operator gets nginx's 504 HTML instead of the API's error envelope.
    # This is the only wall-clock bound there is — httpx's `read` limits the gap
    # between chunks, never the length of a response — so it is checked here,
    # between pages, and the first page always runs: answering `matched: 0`
    # because time ran out would read as "no merchant matches".
    last_start_at = LEAD_SEARCH_BUDGET_SECONDS - settings.lead_search_timeout_seconds

    for page_number in range(settings.lead_search_max_pages):
        if page_number and monotonic() - started > last_start_at:
            break

        try:
            page = provider.search(
                PlacesQuery(**{**query.__dict__, "page_token": page_token})
            )
        except ProviderError:
            if page_number == 0:
                # Nothing succeeded; there is no partial answer to give.
                raise
            partial = True
            break

        searched += len(page.results)
        for place in page.results:
            # Google can repeat a listing across pages. Two identical rows in
            # the list would both offer a Save button for the same merchant.
            if place.place_id in seen:
                continue
            seen.add(place.place_id)
            if _within(resolved, radius, place) and matches(criteria, place):
                hits.append(place)

        # Page size is how many listings one billed request returns, and never
        # a ceiling on the search: capping totals with it is what makes a
        # five-result answer report `searched: 5, matched: 5` as if that were
        # everything Google had. The result target is its own setting, and it
        # bounds the list as well as the paging — a page that overshoots it is
        # trimmed, or `matched` reports a number the operator's own limit says
        # is impossible.
        if len(hits) > settings.lead_search_max_results:
            del hits[settings.lead_search_max_results :]
            capped = True

        page_token = page.next_page_token
        if not page_token:
            break
        if len(hits) >= settings.lead_search_max_results:
            break

    # Either a matched listing was dropped, or Google was still offering pages
    # when the loop ended — whichever bound stopped it. A short list the
    # operator was not told about is the failure the funnel exists to prevent;
    # `partial` already reports the one stop that is a fault rather than a
    # choice.
    truncated = capped or (bool(page_token) and not partial)

    saved = _saved_merchants(db, [place.place_id for place in hits])

    results = [
        SearchHit(
            place=place,
            distance_m=(
                haversine_m(resolved.lat, resolved.lng, place.lat, place.lng)
                if place.lat is not None and place.lng is not None
                else None
            ),
            saved=place.place_id in saved,
            merchant_id=getattr(saved.get(place.place_id), "id", None),
            subscription=getattr(saved.get(place.place_id), "subscription", None),
        )
        # Google's own ordering is relevance, and it is better at that than a
        # distance sort would be. The distance column is information, not the
        # sort key.
        for place in hits
    ]

    return SearchOutcome(
        resolved=resolved,
        searched=searched,
        matched=len(results),
        partial=partial,
        truncated=truncated,
        results=results,
    )


def slugify(*parts: str | None) -> str:
    """`Sushi Mura` in Richmond becomes `sushi-mura-richmond`."""
    joined = " ".join(part for part in parts if part)
    slug = re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-")
    return slug[:MAX_SLUG_BASE].rstrip("-") or "merchant"


def unique_slug(db: Session, base: str) -> str:
    """First free `base`, `base-2`, `base-3`…

    Two concurrent saves can still choose the same one; the unique constraint
    catches that, and `save_merchant` retries the insert, which re-reads the
    taken slugs and lands on the next free suffix. This only avoids the
    collision, it does not pretend to prevent it.
    """
    taken = set(
        db.execute(
            select(Merchant.slug).where(Merchant.slug.like(f"{base}%"))
        ).scalars()
    )
    if base not in taken:
        return base

    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def topics_for(category: str | None) -> list[str]:
    haystack = (category or "").lower()
    for keyword, topics in TOPIC_DEFAULTS.items():
        if keyword in haystack:
            return list(topics)
    return list(GENERIC_TOPICS)


def summary_for(details: PlaceDetails) -> str:
    """Google's editorial line where it has one, a plain sentence where it does
    not. Never invented detail: the fallback says only what the listing states."""
    if details.editorial_summary:
        return details.editorial_summary

    kind = (details.category or "business").lower()
    where = f" in {details.city}" if details.city else ""
    return f"{details.name} is a {kind}{where}."


def save_merchant(
    db: Session, provider: PlacesProvider, place_id: str
) -> tuple[Merchant, bool]:
    """Create-or-read. Returns (merchant, created).

    An existing row is returned untouched — not refreshed, not reactivated.
    Re-running a search must not overwrite a merchant somebody curated, and
    must not overrule whoever archived one.
    """
    existing = _by_place_id(db, place_id)
    if existing is not None:
        return existing, False

    details = provider.details(place_id)

    # The row is keyed on what Google returned, never on what was asked for.
    # Google answers a deprecated Place ID with its canonical one, and a row
    # keyed on the requested id would hit the unique index with nothing to
    # return. The guarantee is only about the canonical id: a later save of the
    # *deprecated* id still pays for Place Details, because that id is stored
    # nowhere, but the canonical id it resolves to then finds this row and reads
    # instead of inserting a duplicate.
    if not details.place_id:
        raise ProviderError(f"place details for {place_id!r} carried no id")

    if details.place_id != place_id:
        existing = _by_place_id(db, details.place_id)
        if existing is not None:
            return existing, False

    attempt = 0
    while True:
        attempt += 1
        try:
            return _insert(db, details), True
        except IntegrityError:
            # Another request saved the same listing, or claimed the same slug,
            # between the lookup above and this insert.
            db.rollback()
            existing = _by_place_id(db, details.place_id)
            if existing is not None:
                # The promise is create-or-read, so a lost race still answers
                # with the winner's row.
                return existing, False
            if attempt == SAVE_ATTEMPTS:
                raise
            # Nobody holds this place id, so what collided was the slug: two
            # different listings that slugify the same way. `unique_slug` re-
            # reads the taken slugs, which now include the winner's, so the
            # retry picks the next free suffix. Only the slug is contended, so
            # the retry terminates.


def _insert(db: Session, details: PlaceDetails) -> Merchant:
    now = datetime.now(UTC)
    merchant = Merchant(
        name=details.name,
        category=details.category,
        address=details.address,
        city=details.city,
        province_state=details.province_state,
        postal_code=details.postal_code,
        country=details.country,
        phone=details.phone,
        website=details.website,
        google_place_id=details.place_id,
        google_profile_url=details.maps_uri,
        # Derived from the same template the seed uses, so a crawled merchant
        # and a seeded one produce identical review URLs for the same listing.
        google_review_url=GOOGLE_REVIEW_URL_TEMPLATE.format(place_id=details.place_id),
        google_rating=details.rating,
        google_review_count=details.review_count,
        google_synced_at=now,
        source="GOOGLE_PLACES",
        # No subscription is written here. Saving a lead is prospecting; the
        # merchant's URL stays shut until somebody signs them up.
        slug=unique_slug(db, slugify(details.name, details.city)),
    )
    db.add(merchant)
    db.flush()

    db.add(
        MerchantReviewContext(
            merchant_id=merchant.id,
            business_summary=summary_for(details),
            # Only the attributes Google reported true. products, services,
            # menu_items and custom_instructions stay null: Google does not
            # know the menu, and inventing one is how the AI ends up praising a
            # dish that does not exist.
            selling_points=details.attributes or None,
            experience_topics=topics_for(details.category),
            # The generator ignores context that is not approved, so leaving
            # this false would store context that changes nothing — which is
            # the opposite of the reason for fetching it.
            is_approved=True,
            approved_at=now,
        )
    )
    db.flush()
    return merchant


def _by_place_id(db: Session, place_id: str) -> Merchant | None:
    return db.execute(
        select(Merchant).where(Merchant.google_place_id == place_id)
    ).scalar_one_or_none()


def saved_merchants(db: Session, limit: int, offset: int) -> list[Merchant]:
    """What the crawler has saved, newest first.

    Filtered to crawler-created rows: a seeded demo merchant is not a lead, and
    listing it here would blur what the operator is looking at.
    """
    return list(
        db.execute(
            select(Merchant)
            .where(Merchant.source == "GOOGLE_PLACES")
            # The id tie-break carries no meaning; it is there so LIMIT/OFFSET
            # paging is stable. Without a total order, rows with identical
            # created_at can repeat on one page and vanish from the next.
            .order_by(Merchant.created_at.desc(), Merchant.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


CONTEXT_LIST_FIELDS = (
    "products",
    "services",
    "menu_items",
    "selling_points",
    "approved_keywords",
    "experience_topics",
)

CONTEXT_TEXT_FIELDS = ("business_summary", "custom_instructions")


def _clean_list(value: list[str] | None) -> list[str] | None:
    """A textarea of one-per-line entries arrives with blank lines in it.

    An empty list is stored as NULL rather than []: the generator reads a
    missing list as "nothing to say about this", and [] would mean the same
    thing while looking like a deliberate, checked-and-empty answer.
    """
    if value is None:
        return None
    items = [item.strip() for item in value if item and item.strip()]
    return items or None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def load_context(db: Session, merchant_id: UUID) -> MerchantReviewContext | None:
    return db.execute(
        select(MerchantReviewContext).where(
            MerchantReviewContext.merchant_id == merchant_id
        )
    ).scalar_one_or_none()


def replace_context(
    db: Session, merchant_id: UUID, values: dict[str, object]
) -> MerchantReviewContext | None:
    """Writes all eight fields, every time. Returns None if there is no such
    merchant.

    A replace rather than a merge, unlike the seed: the editor renders every
    field, so an empty box is an instruction to clear rather than an omission.
    The seed merges because a YAML file legitimately mentions only some fields.
    """
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        return None

    context = load_context(db, merchant_id)
    if context is None:
        context = MerchantReviewContext(merchant_id=merchant_id)
        db.add(context)

    for field in CONTEXT_LIST_FIELDS:
        setattr(context, field, _clean_list(values.get(field)))
    for field in CONTEXT_TEXT_FIELDS:
        setattr(context, field, _clean_text(values.get(field)))

    # Editing is the approval. There is no second approver in the MVP, and
    # leaving it false would make the generator ignore what was just written.
    context.is_approved = True
    if context.approved_at is None:
        context.approved_at = datetime.now(UTC)

    db.flush()
    return context


def _saved_merchants(db: Session, place_ids: list[str]) -> dict[str, Merchant]:
    """One indexed lookup, served by merchants_google_place_id_idx.

    The subscription rides along on the same query rather than being lazy-loaded
    per row: a 20-result page would otherwise issue 20 follow-up selects to
    render one column.
    """
    if not place_ids:
        return {}

    rows = db.execute(
        select(Merchant)
        .options(joinedload(Merchant.subscription))
        .where(Merchant.google_place_id.in_(place_ids))
    ).scalars().all()

    return {merchant.google_place_id: merchant for merchant in rows}
