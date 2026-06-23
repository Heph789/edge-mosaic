"""Source adapters — one per provenance (`rss`, `bluesky`, `x`) behind a shared interface."""

from .base import FeedAdapter, NormalizedItem
from .bluesky import BlueskyAdapter
from .rss import RSSAdapter
from .x import XAdapter

__all__ = ["FeedAdapter", "NormalizedItem", "RSSAdapter", "BlueskyAdapter", "XAdapter"]


def get_adapter(source_type: str) -> FeedAdapter:
    if source_type == "rss":
        return RSSAdapter()
    if source_type == "bluesky":
        return BlueskyAdapter()
    if source_type == "x":
        return XAdapter()
    raise ValueError(f"Unknown source type: {source_type!r}")
