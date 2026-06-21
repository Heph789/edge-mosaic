"""Village membership + visibility helpers.

Villages are a community grouping (separate from `user_cities`). Membership is
backend-assigned: today every new user auto-joins `config.DEFAULT_VILLAGE_NAME`
('EE '26'); third-party verification will replace this later. A user with
visibility='village' is only discoverable by users who share at least one village.
"""

from __future__ import annotations

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


def assign_default_village(db: Session, user: User) -> None:
    """Idempotently enroll `user` in the default village. Caller commits."""
    village = get_or_create_default_village(db)
    exists = db.scalar(
        select(UserVillage).where(
            UserVillage.user_id == user.id, UserVillage.village_id == village.id
        )
    )
    if exists is None:
        db.add(UserVillage(user_id=user.id, village_id=village.id))


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
