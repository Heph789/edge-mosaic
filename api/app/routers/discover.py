"""Discover — escaped ILIKE name search over discoverable users (§7.6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..deps import CurrentUser, DbDep
from ..models import Subscription, User
from ..schemas import DiscoverOut
from ..sources import platforms_for

router = APIRouter(tags=["discover"])

DISCOVER_LIMIT = 50


def _like_escape(s: str, esc: str = "\\") -> str:
    """Escape LIKE wildcards so '50%' / 'a_b' match literally."""
    return s.replace(esc, esc + esc).replace("%", esc + "%").replace("_", esc + "_")


@router.get("/discover", response_model=list[DiscoverOut])
def discover(
    user: CurrentUser,
    db: DbDep,
    q: str = Query(min_length=1),
) -> list[DiscoverOut]:
    term = q.strip()
    if not term:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty query")

    pattern = f"%{_like_escape(term)}%"
    rows = list(
        db.execute(
            select(User.id, User.display_name)
            .where(
                User.display_name.is_not(None),
                User.display_name.ilike(pattern, escape="\\"),
                User.id != user.id,  # don't surface yourself
            )
            .order_by(User.display_name)
            .limit(DISCOVER_LIMIT)
        ).all()
    )

    feeder_ids = [fid for fid, _ in rows]
    platforms = platforms_for(db, feeder_ids)
    subscribed = set(
        db.scalars(
            select(Subscription.feeder_id).where(
                Subscription.subscriber_id == user.id,
                Subscription.feeder_id.in_(feeder_ids or [-1]),
            )
        )
    )
    return [
        DiscoverOut(
            user_id=fid,
            display_name=name,
            platforms=platforms.get(fid, []),
            is_subscribed=fid in subscribed,
        )
        for fid, name in rows
    ]
