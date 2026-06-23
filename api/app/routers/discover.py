"""Discover — escaped ILIKE name search over discoverable users (§7.6)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import case, or_, select

from ..deps import CurrentUser, DbDep
from ..models import ProfileLink, Source, Subscription, User, UserVillage
from ..schemas import DiscoverOut, LinkOut, PlatformPillOut
from ..sources import platform_pills_for
from ..storage import public_url
from ..villages import village_ids_for

router = APIRouter(tags=["discover"])

DISCOVER_PAGE_SIZE = 24  # rows per page; the frontend infinite-scrolls page by page
MAX_PAGE_SIZE = 100


def _like_escape(s: str, esc: str = "\\") -> str:
    """Escape LIKE wildcards so '50%' / 'a_b' match literally."""
    return s.replace(esc, esc + esc).replace("%", esc + "%").replace("_", esc + "_")


@router.get("/discover", response_model=list[DiscoverOut])
def discover(
    user: CurrentUser,
    db: DbDep,
    q: str = Query("", description="name filter; empty = browse all"),
    offset: int = Query(0, ge=0, description="rows to skip (infinite scroll cursor)"),
    limit: int = Query(DISCOVER_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> list[DiscoverOut]:
    term = q.strip()

    # Empty q browses the whole directory (capped); a term ILIKE-filters by name.
    conditions = [User.display_name.is_not(None)]
    if term:
        # A search can surface yourself (so you can find/share your own profile); the
        # default browse view still hides you to keep the focus on other people.
        conditions.append(User.display_name.ilike(f"%{_like_escape(term)}%", escape="\\"))
    else:
        conditions.append(User.id != user.id)  # don't surface yourself in the browse view

    # Visibility gate: a 'village' profile is only listed when it shares a village with the
    # viewer; 'community' profiles are always listed.
    my_village_ids = village_ids_for(db, user.id)
    shares_village = (
        select(UserVillage.user_id)
        .where(UserVillage.village_id.in_(my_village_ids or [-1]))
        .scalar_subquery()
    )
    conditions.append(
        or_(User.visibility != "village", User.id.in_(shares_village))
    )

    # Surface the most useful profiles first: feeders (have sources) > people with profile
    # links > validated (proven-inbox) accounts > everyone else; alphabetical within a tier.
    # Ranked in SQL so it applies *before* the cap, not just within the fetched page.
    has_source = select(Source.id).where(Source.user_id == User.id).exists()
    has_link = select(ProfileLink.id).where(ProfileLink.user_id == User.id).exists()
    rank = case(
        (has_source, 0),
        (has_link, 1),
        (User.verified_at.is_not(None), 2),
        else_=3,
    )

    rows = list(
        db.execute(
            select(
                User.id,
                User.username,
                User.display_name,
                User.bio,
                User.profile_image_path,
                User.tile_image_path,
            )
            .where(*conditions)
            # Stable total order (rank, name, id) so offset paging never skips/repeats rows.
            .order_by(rank, User.display_name, User.id)
            .offset(offset)
            .limit(limit)
        ).all()
    )

    feeder_ids = [r[0] for r in rows]
    pills = platform_pills_for(db, feeder_ids)
    # Non-feeder profile links, grouped per user in display order, shown as pressable pills.
    links: dict[int, list[LinkOut]] = {}
    for link in db.scalars(
        select(ProfileLink)
        .where(ProfileLink.user_id.in_(feeder_ids or [-1]))
        .order_by(ProfileLink.position)
    ):
        links.setdefault(link.user_id, []).append(
            LinkOut(label=link.label, url=link.url)
        )
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
            username=username,
            display_name=name,
            bio=bio,
            platforms=[
                PlatformPillOut(label=label, url=url)
                for label, url in pills.get(fid, [])
            ],
            links=links.get(fid, []),
            is_subscribed=fid in subscribed,
            profile_image_url=public_url(profile_path),
            tile_image_url=public_url(tile_path),
        )
        for fid, username, name, bio, profile_path, tile_path in rows
    ]
