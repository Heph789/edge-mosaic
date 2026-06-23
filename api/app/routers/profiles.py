"""Public profile view — another user's profile, gated by visibility (§ onboarding)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import usernames
from ..deps import CurrentUser, DbDep
from ..models import Source, Subscription, User
from ..schemas import ProfileSourceOut, PublicProfileOut
from ..sources import detect_label, platforms_for
from ..villages import is_visible_to

router = APIRouter(tags=["profiles"])


def _profile_sources(db, user_id: int) -> list[ProfileSourceOut]:
    """A feeder's sources as clickable entries — the human-facing input_url, labelled by
    its pulled title (falling back to the platform type)."""
    rows = db.scalars(
        select(Source).where(Source.user_id == user_id).order_by(Source.created_at)
    ).all()
    return [
        ProfileSourceOut(
            type=s.type,
            label=detect_label(s.type, s.input_url, s.resolved_feed_url),
            url=s.input_url,
            title=s.title,
            status=s.status,
        )
        for s in rows
    ]


def _public_profile(db, target: User | None, viewer: User) -> PublicProfileOut:
    """Shared gating + assembly for the id- and username-keyed profile routes.
    404 (not 403) when the target is missing OR hidden from the viewer — don't reveal
    that a village-only profile exists."""
    if target is None or target.display_name is None or not is_visible_to(
        db, target, viewer.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")

    platforms = platforms_for(db, [target.id]).get(target.id, [])
    is_subscribed = (
        db.scalar(
            select(Subscription.id).where(
                Subscription.subscriber_id == viewer.id,
                Subscription.feeder_id == target.id,
            )
        )
        is not None
    )
    return PublicProfileOut.from_user(
        target,
        platforms=platforms,
        sources=_profile_sources(db, target.id),
        is_subscribed=is_subscribed,
    )


@router.get("/users/by-username/{username}", response_model=PublicProfileOut)
def get_profile_by_username(
    username: str, user: CurrentUser, db: DbDep
) -> PublicProfileOut:
    target = db.scalar(
        select(User).where(User.username == usernames.normalize(username))
    )
    return _public_profile(db, target, user)


@router.get("/users/{user_id}", response_model=PublicProfileOut)
def get_profile(user_id: int, user: CurrentUser, db: DbDep) -> PublicProfileOut:
    return _public_profile(db, db.get(User, user_id), user)
