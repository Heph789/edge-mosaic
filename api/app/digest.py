"""Digest assembly engine (Slice 3).

`assemble_digest` is the single engine behind both the in-app preview (serialized to JSON
here) and the Slice 4 email (rendered to HTML from the same `DigestData`). It filters items
to the subscriber's feeders, groups by feeder, caps, and orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    DIGEST_FEEDER_CAP,
    LONG_ITEMS_CAP,
    MONTHLY_WINDOW_DAYS,
    SHORT_ITEMS_CAP,
    WEEKLY_WINDOW_DAYS,
)
from .models import Item, Source, Subscription, User, utcnow


@dataclass
class DigestItem:
    title: str | None
    url: str
    excerpt: str | None
    text: str | None
    kind: str
    published_at: datetime
    engagement_count: int


@dataclass
class DigestFeeder:
    feeder_id: int
    display_name: str | None
    longs: list[DigestItem]
    shorts: list[DigestItem]
    last_activity: datetime


@dataclass
class DigestData:
    user_id: int
    window_start: datetime
    window_end: datetime
    feeders: list[DigestFeeder]


def trailing_window_start(frequency: str, now: datetime) -> datetime:
    """Preview window: a rolling trailing window sized to the subscriber's frequency."""
    days = MONTHLY_WINDOW_DAYS if frequency == "monthly" else WEEKLY_WINDOW_DAYS
    return now - timedelta(days=days)


def _to_item(item: Item) -> DigestItem:
    return DigestItem(
        title=item.title,
        url=item.url,
        excerpt=item.excerpt,
        text=item.text,
        kind=item.kind,
        published_at=item.published_at,
        engagement_count=item.engagement_count,
    )


def assemble_digest(
    session: Session,
    user: User,
    window_start: datetime | None = None,
    now: datetime | None = None,
) -> DigestData:
    """Build the digest `user` would receive. Defaults to the trailing preview window."""
    now = now or utcnow()
    if window_start is None:
        window_start = trailing_window_start(user.digest_frequency, now)

    feeder_ids = set(
        session.scalars(
            select(Subscription.feeder_id).where(
                Subscription.subscriber_id == user.id
            )
        )
    )
    if not feeder_ids:
        return DigestData(user.id, window_start, now, [])

    rows = session.execute(
        select(Item, Source.user_id)
        .join(Source, Item.source_id == Source.id)
        .where(
            Source.user_id.in_(feeder_ids),
            Item.published_at >= window_start,
            Item.published_at <= now,
        )
    ).all()

    grouped: dict[int, list[Item]] = {}
    for item, feeder_id in rows:
        grouped.setdefault(feeder_id, []).append(item)

    names = dict(
        session.execute(
            select(User.id, User.display_name).where(User.id.in_(feeder_ids))
        ).all()
    )

    feeders: list[DigestFeeder] = []
    for feeder_id, items in grouped.items():
        longs = sorted(
            (i for i in items if i.kind == "long"),
            key=lambda i: i.published_at,
            reverse=True,
        )[:LONG_ITEMS_CAP]
        shorts = sorted(
            (i for i in items if i.kind == "short"),
            key=lambda i: i.published_at,
            reverse=True,
        )[:SHORT_ITEMS_CAP]
        if not longs and not shorts:
            continue
        recency = [i.published_at for i in (*longs, *shorts)]
        feeders.append(
            DigestFeeder(
                feeder_id=feeder_id,
                display_name=names.get(feeder_id),
                longs=[_to_item(i) for i in longs],
                shorts=[_to_item(i) for i in shorts],
                last_activity=max(recency),
            )
        )

    # Order by most-recent activity, then apply the per-digest safety cap.
    feeders.sort(key=lambda f: f.last_activity, reverse=True)
    feeders = feeders[:DIGEST_FEEDER_CAP]

    return DigestData(user.id, window_start, now, feeders)
