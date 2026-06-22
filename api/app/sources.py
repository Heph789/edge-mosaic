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
from .config import ADD_SOURCE_DEADLINE, ADD_SOURCE_TIMEOUT
from .models import Source

# Hosts we deliberately reject for now (X adapter is deferred — see mvp-plan Deferred).
REJECTED_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com"}


class SourceRejected(Exception):
    """The URL is a platform we don't support yet (e.g. X / Twitter)."""


def _host(url: str | None) -> str:
    """Lower-cased, www-stripped hostname for a (possibly scheme-less) URL."""
    if not url:
        return ""
    raw = url.strip()
    host = (urlparse(raw if "://" in raw else f"https://{raw}").hostname or "").lower()
    return host.removeprefix("www.")


def normalize_source_url(url: str) -> str:
    """Default a scheme-less feed URL to https:// so 'chaselb.substack.com' is fetched as a
    URL rather than treated as a path (which fails with 'unknown url type'). Bluesky
    @handles and already-schemed URLs pass through untouched."""
    raw = url.strip()
    if not raw or raw.startswith("@") or "://" in raw:
        return raw
    return f"https://{raw}"


def detect_type(url: str) -> str:
    """'rss' | 'bluesky' — the scraping category. Raises SourceRejected for deferred
    platforms. This is intentionally coarse; see `detect_label` for the display name."""
    raw = url.strip()
    if raw.startswith("@"):
        return "bluesky"  # a bare @handle is always Bluesky

    host = _host(raw)
    if host in REJECTED_HOSTS:
        raise SourceRejected("X / Twitter sources are coming soon.")
    if host == "bsky.app":
        return "bluesky"
    return "rss"  # Substack (/feed) + general RSS autodiscovery handled by the resolver


# Podcast-hosting domains whose feeds we want to surface as "Podcast" rather than "Blog".
_PODCAST_HOSTS = frozenset(
    {
        "anchor.fm", "podbean.com", "libsyn.com", "redcircle.com", "acast.com",
        "captivate.fm", "fireside.fm", "pinecast.com", "buzzsprout.com",
        "transistor.fm", "simplecast.com", "megaphone.fm", "omny.fm", "rss.com",
    }
)


def detect_label(
    source_type: str,
    input_url: str,
    resolved_feed_url: str | None = None,
) -> str:
    """Granular, human-facing label for a source — finer than `type` (the scraping
    category). One of: 'Bluesky' | 'YouTube' | 'Substack' | 'Medium' | 'Podcast' | 'Blog'.
    Derived from the URL host(s), so it needs no extra storage."""
    if source_type == "bluesky":
        return "Bluesky"

    hosts = [h for h in (_host(resolved_feed_url), _host(input_url)) if h]

    def host_matches(suffixes: frozenset[str] | set[str]) -> bool:
        return any(
            h == s or h.endswith(f".{s}") for h in hosts for s in suffixes
        )

    if host_matches({"youtube.com", "youtu.be"}):
        return "YouTube"
    if host_matches({"substack.com"}):
        return "Substack"
    if host_matches({"medium.com"}):
        return "Medium"
    if host_matches(_PODCAST_HOSTS) or any(
        "podcast" in (u or "").lower() for u in (input_url, resolved_feed_url)
    ):
        return "Podcast"
    return "Blog"


@dataclass
class SourcePreview:
    type: str
    label: str
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
        label=detect_label(source_type, url, transient.resolved_feed_url),
        resolved_url=transient.resolved_feed_url or transient.input_url,
        title=transient.title,
        found_count=len(items),
        latest_title=latest.title if latest else None,
        latest_published_at=latest.published_at if latest else None,
    )


def platforms_for(session: Session, user_ids: Iterable[int]) -> dict[int, list[str]]:
    """{user_id: sorted distinct display labels}. Labels are the granular, human-facing
    names (Substack/YouTube/Podcast/…) — see `detect_label`. Feeders with no sources are
    absent."""
    ids = list(user_ids)
    out: dict[int, set[str]] = {}
    if not ids:
        return {}
    rows = session.execute(
        select(
            Source.user_id, Source.type, Source.input_url, Source.resolved_feed_url
        ).where(Source.user_id.in_(ids))
    ).all()
    for uid, stype, input_url, resolved in rows:
        out.setdefault(uid, set()).add(detect_label(stype, input_url, resolved))
    return {uid: sorted(labels) for uid, labels in out.items()}
