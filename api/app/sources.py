"""Source type detection + add-time validation (Slice 3).

`detect_type` is the single source of truth for "what kind of source is this URL",
reused by the preview endpoint, the create endpoint, and the scrape orchestrator.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import NormalizedItem
from .adapters.bluesky import BlueskyAdapter
from .adapters.rss import RSSAdapter
from .adapters.x import XAdapter
from .config import ADD_SOURCE_DEADLINE, ADD_SOURCE_TIMEOUT
from .models import Source

# Hosts routed to the X adapter (the various Twitter/X domains all serve the same profiles).
X_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com"}


class SourceRejected(Exception):
    """The URL is a platform we don't support yet."""


def detect_type(url: str) -> str:
    """'rss' | 'bluesky' | 'x'. Raises SourceRejected for unsupported platforms."""
    raw = url.strip()
    if raw.startswith("@"):
        return "bluesky"  # a bare @handle is always Bluesky

    host = (urlparse(raw if "://" in raw else f"https://{raw}").hostname or "").lower()
    host = host.removeprefix("www.")

    if host in X_HOSTS:
        return "x"
    if host == "bsky.app":
        return "bluesky"
    return "rss"  # Substack (/feed) + general RSS autodiscovery handled by the resolver


@dataclass
class SourcePreview:
    type: str
    resolved_url: str | None
    title: str | None
    found_count: int
    latest_title: str | None
    latest_published_at: datetime | None


def _adapter_for(source_type: str):
    """Interactive adapter instances — tight timeout + overall deadline (Slice 3)."""
    if source_type == "rss":
        return RSSAdapter(timeout=ADD_SOURCE_TIMEOUT, deadline_seconds=ADD_SOURCE_DEADLINE)
    if source_type == "bluesky":
        return BlueskyAdapter()
    if source_type == "x":
        return XAdapter()
    raise ValueError(f"Unknown source type: {source_type!r}")


def validate_source(url: str) -> tuple[str, Source, list[NormalizedItem]]:
    """Detect + fetch against a *transient* Source (no DB write). Raises on bad feeds."""
    source_type = detect_type(url)
    transient = Source(type=source_type, input_url=url)  # not added to any session
    items = _adapter_for(source_type).fetch(transient)
    return source_type, transient, items


def preview_source(url: str) -> SourcePreview:
    """Validate a URL and summarize what was found — the §3 confirm step. No writes."""
    source_type, transient, items = validate_source(url)
    latest = max(items, key=lambda i: i.published_at) if items else None
    return SourcePreview(
        type=source_type,
        resolved_url=transient.resolved_feed_url or transient.input_url,
        title=transient.title,
        found_count=len(items),
        latest_title=latest.title if latest else None,
        latest_published_at=latest.published_at if latest else None,
    )


def platforms_for(session: Session, user_ids: Iterable[int]) -> dict[int, list[str]]:
    """{user_id: sorted distinct source types}. Feeders with no sources are absent."""
    ids = list(user_ids)
    out: dict[int, set[str]] = {}
    if not ids:
        return {}
    rows = session.execute(
        select(Source.user_id, Source.type).where(Source.user_id.in_(ids)).distinct()
    ).all()
    for uid, stype in rows:
        out.setdefault(uid, set()).add(stype)
    return {uid: sorted(types) for uid, types in out.items()}
