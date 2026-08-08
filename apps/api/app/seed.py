"""Load merchants from YAML into the database.

There is no admin UI in the MVP, so this script is the entire merchant
onboarding path. Run it as:

    python -m app.seed merchants/pho37.yaml
    python -m app.seed merchants/*.yaml

Upserts are keyed on `slug`, so re-running is safe and is the intended way to
edit a merchant: change the file, run it again.

Updates are a merge, not a replace. A field omitted from the YAML keeps its
existing value rather than being cleared — so removing a line does not remove
the data. To clear a field, set it explicitly to an empty value. The one
exception is `status`, which is deliberately never inferred (see _apply).

All files in one invocation share a single transaction: any error rolls the
whole run back, so a bad file in a glob never leaves a half-seeded database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import MERCHANT_STATUSES, Merchant, MerchantReviewContext
from app.services.suggestions import _URL

# Google's documented public review destination for a Place ID. Derived rather
# than hand-copied so a merchant record cannot drift from its place id, but an
# explicit google_review_url in the YAML always wins — some listings use a
# short g.page link that this pattern cannot produce.
GOOGLE_REVIEW_URL_TEMPLATE = "https://search.google.com/local/writereview?placeid={place_id}"

# Text fields copied straight across. `status` and `google_review_url` are
# handled separately because both are derived rather than assigned.
MERCHANT_FIELDS = (
    "name",
    "category",
    "description",
    "phone",
    "address",
    "city",
    "province_state",
    "postal_code",
    "country",
    "google_place_id",
    "google_profile_url",
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

CONTEXT_FIELDS = CONTEXT_LIST_FIELDS + CONTEXT_TEXT_FIELDS + ("is_approved",)


class SeedError(Exception):
    """A problem with the file, not with the database."""


def _require_str(data: dict[str, Any], field: str, path: Path) -> str:
    """YAML is untyped: `slug: 37` is an int and `slug: yes` is a bool. Both
    would crash on .strip() with a traceback instead of a usable message."""
    value = data.get(field)

    if value is None or isinstance(value, bool) or not isinstance(value, str):
        raise SeedError(
            f"{path}: '{field}' must be a quoted string, got {type(value).__name__}"
        )

    if not value.strip():
        raise SeedError(f"{path}: '{field}' is required")

    return value.strip()


def _optional_str(data: dict[str, Any], field: str, path: Path) -> str | None:
    if field not in data or data[field] is None:
        return None

    value = data[field]
    if isinstance(value, bool) or not isinstance(value, str):
        raise SeedError(
            f"{path}: '{field}' must be a quoted string, got {type(value).__name__}"
        )

    return value.strip() or None


def _derived_url(place_id: str | None) -> str | None:
    return GOOGLE_REVIEW_URL_TEMPLATE.format(place_id=place_id) if place_id else None


def _is_derived(url: str | None) -> bool:
    prefix = GOOGLE_REVIEW_URL_TEMPLATE.split("{", 1)[0]
    return bool(url) and url.startswith(prefix)


def _review_url_for(
    merchant: Merchant, data: dict[str, Any], path: Path
) -> str | None:
    """Decide the review URL from the *merged* record, not the YAML alone.

    Reading only the file in hand would null a perfectly good URL whenever a
    later edit omitted google_place_id, while the stale place id stayed in the
    row — the exact drift this derivation exists to prevent.

    An explicit URL is an override and survives edits that don't mention it.
    A stored URL that matches the derivation pattern is not an override, so it
    re-derives and follows the place id.
    """
    explicit = _optional_str(data, "google_review_url", path)
    derived = _derived_url(merchant.google_place_id)

    if explicit:
        return explicit

    # Mentioned but blank means "drop the override".
    if "google_review_url" in data:
        return derived

    if merchant.google_review_url and not _is_derived(merchant.google_review_url):
        return merchant.google_review_url

    return derived


def _validate(data: dict[str, Any], path: Path) -> None:
    if not isinstance(data, dict):
        raise SeedError(f"{path}: expected a YAML mapping at the top level")

    _require_str(data, "slug", path)
    _require_str(data, "name", path)

    if "status" in data:
        status = data["status"]
        if status not in MERCHANT_STATUSES:
            raise SeedError(
                f"{path}: status {status!r} must be one of {list(MERCHANT_STATUSES)}"
            )

    for field in ("google_place_id", "google_review_url", "google_profile_url"):
        _optional_str(data, field, path)

    unknown = (
        set(data)
        - set(MERCHANT_FIELDS)
        - {"slug", "status", "google_review_url", "review_context"}
    )
    if unknown:
        raise SeedError(f"{path}: unknown merchant field(s): {sorted(unknown)}")

    context = data.get("review_context")
    if context is None:
        return

    if not isinstance(context, dict):
        raise SeedError(f"{path}: review_context must be a mapping")

    unknown_context = set(context) - set(CONTEXT_FIELDS)
    if unknown_context:
        raise SeedError(
            f"{path}: unknown review_context field(s): {sorted(unknown_context)}"
        )

    # These feed the prompt directly. A scalar where a list belongs would be
    # stored as a JSON string and then iterated character by character during
    # topic rotation, producing nonsense rather than an error.
    for field in CONTEXT_LIST_FIELDS:
        if field in context and context[field] is not None:
            value = context[field]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise SeedError(
                    f"{path}: review_context.{field} must be a list of strings"
                )

    if "is_approved" in context and not isinstance(context["is_approved"], bool):
        raise SeedError(
            f"{path}: review_context.is_approved must be true or false, "
            f"got {context['is_approved']!r}"
        )

    # Caught here because the failure it causes is otherwise invisible and
    # permanent: instructions go straight into the prompt, generated text
    # containing a URL fails validation, so every batch fails and the merchant
    # has silently bricked their own reviewer with no clue why.
    instructions = context.get("custom_instructions")
    if isinstance(instructions, str) and _URL.search(instructions):
        raise SeedError(
            f"{path}: review_context.custom_instructions asks for a link or "
            "address. Generated reviews reject URLs, so every suggestion for "
            "this merchant would fail — remove it."
        )


def _apply(db: Session, data: dict[str, Any], path: Path) -> tuple[Merchant, bool]:
    slug = data["slug"].strip()
    merchant = db.execute(
        select(Merchant).where(Merchant.slug == slug)
    ).scalar_one_or_none()

    created = merchant is None
    if merchant is None:
        merchant = Merchant(slug=slug, status="ACTIVE")
        db.add(merchant)

    for field in MERCHANT_FIELDS:
        if field in data:
            setattr(merchant, field, data[field])

    # Only assigned when the YAML says so. Defaulting to ACTIVE on every run
    # would silently resurrect a merchant that was archived by removing the
    # status line, putting a dead business back into service.
    if "status" in data:
        merchant.status = data["status"]

    merchant.archived_at = (
        merchant.archived_at or datetime.now(UTC)
        if merchant.status == "ARCHIVED"
        else None
    )

    merchant.google_review_url = _review_url_for(merchant, data, path)

    if merchant.status == "ACTIVE" and not merchant.google_review_url:
        # Caught here rather than at session-create time, where it would reach
        # a customer as an unexplained "link unavailable".
        raise SeedError(
            f"{path}: an ACTIVE merchant needs google_review_url or google_place_id, "
            "otherwise it can never create a review session"
        )

    db.flush()

    context_data = data.get("review_context")
    if context_data is not None:
        context = db.execute(
            select(MerchantReviewContext).where(
                MerchantReviewContext.merchant_id == merchant.id
            )
        ).scalar_one_or_none()

        if context is None:
            context = MerchantReviewContext(merchant_id=merchant.id)
            db.add(context)

        for field in CONTEXT_FIELDS:
            if field in context_data:
                setattr(context, field, context_data[field])

        # is_approved has no approver behind it in the MVP — writing the YAML
        # by hand is the approval step, so the timestamp records when that
        # happened rather than pretending a workflow exists.
        if context.is_approved and context.approved_at is None:
            context.approved_at = datetime.now(UTC)
        elif not context.is_approved:
            context.approved_at = None

    return merchant, created


def seed_merchant(db: Session, data: dict[str, Any], path: Path) -> tuple[Merchant, bool]:
    _validate(data, path)
    return _apply(db, data, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed merchants from YAML files.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    db = SessionLocal()
    results: list[tuple[str, str, bool]] = []

    try:
        for path in args.paths:
            if not path.exists():
                print(f"error: {path} does not exist", file=sys.stderr)
                db.rollback()
                return 1

            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                merchant, created = seed_merchant(db, data, path)
                results.append((merchant.slug, str(merchant.id), created))
            except (SeedError, yaml.YAMLError) as exc:
                db.rollback()
                print(f"error: {exc}", file=sys.stderr)
                return 1
            except SQLAlchemyError as exc:
                # Most likely a duplicate google_place_id across two files.
                # Surfacing psycopg internals to whoever is onboarding a
                # merchant is not a usable error message, but the underlying
                # text still names the constraint.
                db.rollback()
                print(f"error: {path}: database rejected this merchant: {exc}", file=sys.stderr)
                return 1

        db.commit()
    finally:
        db.close()

    # Printed only after the commit succeeds — reporting a merchant URL for
    # work that was then rolled back would send someone to a dead link.
    for slug, merchant_id, created in results:
        print(f"{'created' if created else 'updated'} {slug} ({merchant_id}) -> /m/{merchant_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
