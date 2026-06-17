"""Source adapters — one per provenance (`rss`, `bluesky`) behind a shared interface."""

from .base import FeedAdapter, NormalizedItem
from .bluesky import BlueskyAdapter
from .rss import RSSAdapter

__all__ = ["FeedAdapter", "NormalizedItem", "RSSAdapter", "BlueskyAdapter"]


def get_adapter(source_type: str) -> FeedAdapter:
    if source_type == "rss":
        return RSSAdapter()
    if source_type == "bluesky":
        return BlueskyAdapter()
    raise ValueError(f"Unknown source type: {source_type!r}")
