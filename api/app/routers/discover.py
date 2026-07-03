"""Discover — escaped ILIKE name search over discoverable users (§7.6)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import case, or_, select

from ..deps import CurrentUser, DbDep
from ..models import ProfileLink, Source, Subscription, User, UserCity, UserVillage
from ..schemas import DiscoverOut, LinkOut, MosaicTileOut, PlatformPillOut
from ..sources import platform_pills_for
from ..storage import public_url
from ..villages import village_ids_for

router = APIRouter(tags=["discover"])

DISCOVER_PAGE_SIZE = 24  # rows per page; the frontend infinite-scrolls page by page
MAX_PAGE_SIZE = 100

# Shared row-level expressions (correlated to User) used by both /discover endpoints.
_HAS_SOURCE = select(Source.id).where(Source.user_id == User.id).exists()
_HAS_LINK = select(ProfileLink.id).where(ProfileLink.user_id == User.id).exists()
# Surface the most useful profiles first: feeders (have sources) > people with profile
# links > validated (proven-inbox) accounts > everyone else.
_RANK = case(
    (_HAS_SOURCE, 0),
    (_HAS_LINK, 1),
    (User.verified_at.is_not(None), 2),
    else_=3,
)


def _like_escape(s: str, esc: str = "\\") -> str:
    """Escape LIKE wildcards so '50%' / 'a_b' match literally."""
    return s.replace(esc, esc + esc).replace("%", esc + "%").replace("_", esc + "_")


def _visibility_gate(db: DbDep, user: User):
    """A 'village' profile is only listed when it shares a village with the viewer;
    'community' profiles are always listed."""
    my_village_ids = village_ids_for(db, user.id)
    shares_village = (
        select(UserVillage.user_id)
        .where(UserVillage.village_id.in_(my_village_ids or [-1]))
        .scalar_subquery()
    )
    return or_(User.visibility != "village", User.id.in_(shares_village))


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
        conditions.append(User.display_name.ilike(f"%{_like_escape(term)}%", escape="\\"))

    conditions.append(_visibility_gate(db, user))

    # Primary city (lowest position) shown as the list-view location line.
    primary_city = (
        select(UserCity.name)
        .where(UserCity.user_id == User.id)
        .order_by(UserCity.position)
        .limit(1)
        .scalar_subquery()
    )

    rows = list(
        db.execute(
            select(
                User.id,
                User.username,
                User.display_name,
                User.bio,
                User.profile_image_path,
                primary_city.label("city"),
                User.verified_at,
            )
            .where(*conditions)
            # Stable total order (rank, name, id) so offset paging never skips/repeats rows.
            .order_by(_RANK, User.display_name, User.id)
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
            city=city,
            platforms=[
                PlatformPillOut(label=label, url=url)
                for label, url in pills.get(fid, [])
            ],
            links=links.get(fid, []),
            is_subscribed=fid in subscribed,
            profile_image_url=public_url(profile_path),
            verified=verified_at is not None,
        )
        for fid, username, name, bio, profile_path, city, verified_at in rows
    ]


@router.get("/discover/mosaic", response_model=list[MosaicTileOut])
def discover_mosaic(user: CurrentUser, db: DbDep) -> list[MosaicTileOut]:
    """Whole-directory manifest for the mosaic wall in a single round trip.

    One flat query, no per-user pills/links/subscription hydration — a tile only renders
    a name, a photo (or generated gradient), and a dim flag for empty pre-seeded ghosts.
    The list view still uses paged /discover for its richer rows.
    """
    placeholder = (
        (~_HAS_SOURCE) & (~_HAS_LINK) & User.verified_at.is_(None)
    ).label("placeholder")

    rows = db.execute(
        select(
            User.id,
            User.username,
            User.display_name,
            User.profile_image_path,
            placeholder,
        )
        .where(User.display_name.is_not(None), _visibility_gate(db, user))
        # Same rank order as /discover so the wall clusters the most useful profiles
        # (which the client then re-sorts photo-first for the innermost cells).
        .order_by(_RANK, User.display_name, User.id)
    ).all()

    return [
        MosaicTileOut(
            user_id=uid,
            username=username,
            display_name=name,
            profile_image_url=public_url(image_path),
            placeholder=bool(is_placeholder),
        )
        for uid, username, name, image_path, is_placeholder in rows
    ]
