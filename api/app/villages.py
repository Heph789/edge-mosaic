"""Village membership + visibility helpers.

Villages are a community grouping (separate from `user_cities`). Membership is
backend-assigned, from two sources:
  * EdgeOS popup attendance (the third-party verification path): each popup the user
    attended per their EdgeOS profile stats maps to a village — see
    assign_villages_from_attendance(). Grants are additive-only; a membership is never
    revoked by a later sync.
  * The legacy default: magic-link / CSV-seeded users auto-join
    `config.DEFAULT_VILLAGE_NAME` ('EE '26'), which is also the fallback when EdgeOS
    stats couldn't be fetched (a user with zero villages would be invisible to — and
    blind to — every visibility='village' profile).
A user with visibility='village' is only discoverable by users who share ≥1 village.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import User, UserVillage, Village


def get_or_create_default_village(db: Session) -> Village:
    village = db.scalar(
        select(Village).where(Village.slug == config.DEFAULT_VILLAGE_SLUG)
    )
    if village is None:
        village = Village(
            name=config.DEFAULT_VILLAGE_NAME, slug=config.DEFAULT_VILLAGE_SLUG
        )
        db.add(village)
        db.flush()  # assign village.id for the membership row below
    return village


def enroll(db: Session, user: User, village: Village) -> None:
    """Idempotently add `user` to `village`. Caller commits."""
    exists = db.scalar(
        select(UserVillage).where(
            UserVillage.user_id == user.id, UserVillage.village_id == village.id
        )
    )
    if exists is None:
        db.add(UserVillage(user_id=user.id, village_id=village.id))


def assign_default_village(db: Session, user: User) -> None:
    """Idempotently enroll `user` in the default village. Caller commits."""
    enroll(db, user, get_or_create_default_village(db))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "village"


def village_for_popup(db: Session, popup_id: str, popup_name: str) -> Village:
    """Get-or-create the village mirroring an EdgeOS popup. Caller commits.

    Resolution order: a village already claimed by this popup_id → a pre-existing local
    village aliased in config.EDGEOS_POPUP_VILLAGE_SLUGS (claimed on first sight) → a new
    village named after the popup. Name/slug collisions with unrelated local villages are
    disambiguated with a popup-id suffix rather than hijacking the existing row.
    """
    village = db.scalar(select(Village).where(Village.edgeos_popup_id == popup_id))
    if village is not None:
        return village

    alias_slug = config.EDGEOS_POPUP_VILLAGE_SLUGS.get(popup_id)
    if alias_slug is not None:
        village = db.scalar(select(Village).where(Village.slug == alias_slug))
        if village is not None:
            village.edgeos_popup_id = popup_id  # claim the pre-existing village
            return village

    name, slug = popup_name.strip() or popup_id, _slugify(popup_name)
    taken = db.scalar(
        select(Village.id).where((Village.name == name) | (Village.slug == slug))
    )
    if taken is not None:
        name = f"{name} ({popup_id[:8]})"
        slug = f"{slug}-{popup_id[:8]}"
    village = Village(name=name, slug=slug, edgeos_popup_id=popup_id)
    db.add(village)
    db.flush()  # assign village.id for the membership row
    return village


def assign_villages_from_attendance(
    db: Session, user: User, popups: list[dict]
) -> None:
    """Enroll `user` in one village per attended EdgeOS popup (additive-only; a later
    sync never revokes memberships granted earlier or by other paths). Caller commits.

    Only popups with total_days > 0 count — a 0-day entry in the EdgeOS history (e.g.
    an application/ticket with no checked-in days) grants no membership.
    """
    for popup in popups:
        popup_id = popup.get("popup_id")
        if not popup_id or not (popup.get("total_days") or 0) > 0:
            continue
        village = village_for_popup(
            db, str(popup_id), popup.get("popup_name") or ""
        )
        enroll(db, user, village)


def village_ids_for(db: Session, user_id: int) -> set[int]:
    return set(
        db.scalars(
            select(UserVillage.village_id).where(UserVillage.user_id == user_id)
        )
    )


def village_names_for(db: Session, user_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Village.name)
            .join(UserVillage, UserVillage.village_id == Village.id)
            .where(UserVillage.user_id == user_id)
            .order_by(Village.name)
        )
    )


def is_visible_to(db: Session, target: User, viewer_id: int) -> bool:
    """Can `viewer_id` see `target`? Community profiles: always. Village-only profiles:
    only when the viewer shares ≥1 village with the target."""
    if target.id == viewer_id:
        return True
    if target.visibility != "village":
        return True  # 'community' (the default) is open to everyone
    shared = village_ids_for(db, target.id) & village_ids_for(db, viewer_id)
    return bool(shared)
