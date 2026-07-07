"""Digest assembly engine (Slice 3, + prototype digest-format work folded in at Slice 5).

`assemble_digest` is the single engine behind both the in-app preview (serialized to JSON)
and the Slice 4 email (rendered to HTML from the same `DigestData`). It filters items to
the subscriber's feeders, then shapes them the way the digest presents them:

- **grouped by source within each feeder** (a feeder's Substack and their Bluesky get their
  own labelled blocks; long-form sources sort above short-form);
- **per-feeder caps** (≤LONG_ITEMS_CAP long, ≤SHORT_ITEMS_CAP short) applied across all of
  a feeder's sources, then partitioned back out by source for display;
- a **representative item** per feeder (most-recent long, else most-recent short) that the
  compact format collapses each feeder to;
- a **compact** flag (set once enough feeders are active) and a list of **quiet feeders**
  (followed, have sources, but nothing in the window) so they're surfaced, not dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    COMPACT_MODE_FEEDER_THRESHOLD,
    DIGEST_FEEDER_CAP,
    LONG_ITEMS_CAP,
    MONTHLY_WINDOW_DAYS,
    SHORT_ITEMS_CAP,
    WEEKLY_WINDOW_DAYS,
)
from .models import SOURCE_STATUS_ACTIVE, Item, Source, Subscription, User, utcnow


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
class DigestSource:
    """One source's slice of a feeder's digest (its own labelled block)."""

    label: str
    longs: list[DigestItem]
    shorts: list[DigestItem]


@dataclass
class DigestFeeder:
    feeder_id: int
    display_name: str | None
    username: str | None
    sources: list[DigestSource]
    selected: DigestItem  # representative item — what compact mode shows for this feeder
    last_activity: datetime


@dataclass
class DigestData:
    user_id: int
    window_start: datetime
    window_end: datetime
    feeders: list[DigestFeeder]
    quiet_feeders: list[str]  # display names of followed feeders with sources but no items
    compact: bool


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


def _source_label(source: Source) -> str:
    """Subheading for a source block: its pulled publication name (`sources.title`),
    'Bluesky' for Bluesky, falling back to the feed host if a feed carried no title."""
    if source.type == "bluesky":
        return "Bluesky"
    if source.title:
        return source.title
    host = urlparse(source.resolved_feed_url or source.input_url).netloc
    return host or source.input_url


def _published(item: Item) -> datetime:
    return item.published_at


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
            select(Subscription.feeder_id).where(Subscription.subscriber_id == user.id)
        )
    )
    if not feeder_ids:
        return DigestData(user.id, window_start, now, [], [], False)

    rows = session.execute(
        select(Item, Source)
        .join(Source, Item.source_id == Source.id)
        .where(
            Source.user_id.in_(feeder_ids),
            Source.status == SOURCE_STATUS_ACTIVE,  # 'unverified' feeds never enter a digest
            Item.published_at >= window_start,
            Item.published_at <= now,
        )
    ).all()

    # feeder_id -> source_id -> {"source": Source, "long": [Item], "short": [Item]}
    grouped: dict[int, dict[int, dict]] = {}
    for item, source in rows:
        by_source = grouped.setdefault(source.user_id, {})
        bucket = by_source.setdefault(
            source.id, {"source": source, "long": [], "short": []}
        )
        bucket.setdefault(item.kind, []).append(item)

    feeder_rows = session.execute(
        select(User.id, User.display_name, User.username).where(User.id.in_(feeder_ids))
    ).all()
    names = {row.id: row.display_name for row in feeder_rows}
    usernames = {row.id: row.username for row in feeder_rows}

    feeders: list[DigestFeeder] = []
    for feeder_id, by_source in grouped.items():
        # Caps are per-feeder, applied across all the feeder's sources, then the kept
        # items are partitioned back out by source for display.
        all_long = [i for b in by_source.values() for i in b["long"]]
        all_short = [i for b in by_source.values() for i in b["short"]]
        keep_long = {
            i.id for i in sorted(all_long, key=_published, reverse=True)[:LONG_ITEMS_CAP]
        }
        keep_short = {
            i.id for i in sorted(all_short, key=_published, reverse=True)[:SHORT_ITEMS_CAP]
        }

        source_blocks: list[tuple[bool, datetime, DigestSource]] = []
        for bucket in by_source.values():
            longs = sorted(
                (i for i in bucket["long"] if i.id in keep_long),
                key=_published,
                reverse=True,
            )
            shorts = sorted(
                (i for i in bucket["short"] if i.id in keep_short),
                key=_published,
                reverse=True,
            )
            if not longs and not shorts:
                continue
            recency = max(_published(i) for i in (*longs, *shorts))
            source_blocks.append(
                (
                    bool(longs),  # long-form sources sort above short-form
                    recency,
                    DigestSource(
                        label=_source_label(bucket["source"]),
                        longs=[_to_item(i) for i in longs],
                        shorts=[_to_item(i) for i in shorts],
                    ),
                )
            )

        if not source_blocks:
            continue
        source_blocks.sort(key=lambda b: (b[0], b[1]), reverse=True)

        # Representative item: most-recent long, else most-recent short (kind §4 as the
        # significance proxy) — barely matters in the spacious format, *is* the product in
        # compact. Chosen from the capped, kept items so it always appears in a block too.
        kept = [i for i in all_long if i.id in keep_long] or [
            i for i in all_short if i.id in keep_short
        ]
        selected = max(kept, key=_published)

        feeders.append(
            DigestFeeder(
                feeder_id=feeder_id,
                display_name=names.get(feeder_id),
                username=usernames.get(feeder_id),
                sources=[block for _, _, block in source_blocks],
                selected=_to_item(selected),
                last_activity=max(recency for _, recency, _ in source_blocks),
            )
        )

    # Order by most-recent activity, then apply the per-digest safety cap.
    feeders.sort(key=lambda f: f.last_activity, reverse=True)
    feeders = feeders[:DIGEST_FEEDER_CAP]

    # Followed feeders that have sources but produced nothing in the window — surfaced as
    # a "No updates" list rather than silently dropped.
    active_ids = {f.feeder_id for f in feeders}
    feeders_with_sources = set(
        session.scalars(
            select(Source.user_id).where(Source.user_id.in_(feeder_ids)).distinct()
        )
    )
    quiet_feeders = sorted(
        names.get(fid) or "Someone" for fid in feeders_with_sources - active_ids
    )

    # One mode for the whole digest: many active feeders → compact, else spacious.
    compact = len(feeders) >= COMPACT_MODE_FEEDER_THRESHOLD

    return DigestData(user.id, window_start, now, feeders, quiet_feeders, compact)
