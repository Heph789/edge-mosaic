"""Hardcoded real sources for the spike + a dialect-agnostic upsert.

Deliberately select-then-insert (no SQLite `on_conflict_*`) so the dedup logic
survives the move to Postgres.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Source

# A couple Substacks (custom domains), feed-having blogs, and a Bluesky handle.
HARDCODED_SOURCES: list[dict[str, str]] = [
    {"feeder_name": "Scott Alexander", "type": "rss", "url": "https://www.astralcodexten.com"},
    {"feeder_name": "Casey Newton", "type": "rss", "url": "https://www.platformer.news"},
    {"feeder_name": "Simon Willison", "type": "rss", "url": "https://simonwillison.net/"},
    # Same feeder, second source — exercises grouping a blog + Bluesky under one feeder.
    {"feeder_name": "Simon Willison", "type": "bluesky", "url": "@simonwillison.net"},
    {"feeder_name": "Julia Evans", "type": "rss", "url": "https://jvns.ca"},
    {"feeder_name": "Bluesky Team", "type": "bluesky", "url": "@bsky.app"},
    # Podcast + YouTube — both are RSS underneath a directory page (the RSS adapter
    # resolves Apple Podcasts via the iTunes Lookup API and YouTube via the channel feed).
    {"feeder_name": "Amanda Cassatt", "type": "rss", "url": "https://podcasts.apple.com/us/podcast/endgame-with-amanda-cassatt/id1801809440"},
    {"feeder_name": "Bankless", "type": "rss", "url": "https://www.youtube.com/@Bankless"},
]


def upsert_sources(session: Session) -> list[Source]:
    """Ensure every hardcoded source exists, keyed on (feeder_name, input_url)."""
    for spec in HARDCODED_SOURCES:
        existing = session.scalar(
            select(Source).where(
                Source.feeder_name == spec["feeder_name"],
                Source.input_url == spec["url"],
            )
        )
        if existing is None:
            session.add(
                Source(
                    feeder_name=spec["feeder_name"],
                    type=spec["type"],
                    input_url=spec["url"],
                )
            )
    session.commit()
    return list(session.scalars(select(Source)).all())
