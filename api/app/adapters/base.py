"""Unified adapter interface. Deferred platforms (X, non-feed sites) slot in here later."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..models import Source


@dataclass
class NormalizedItem:
    """Adapter output — the platform-agnostic shape that maps onto `items`."""

    external_id: str
    kind: str  # 'long' | 'short'
    url: str
    published_at: datetime
    title: str | None = None
    text: str | None = None
    excerpt: str | None = None
    engagement_count: int = 0


class FeedAdapter(Protocol):
    type: str

    def fetch(self, source: "Source") -> list[NormalizedItem]:
        """Resolve the source (mutating resolved_feed_url/external_id/title) and
        return its current items. Raises on unrecoverable failure; the orchestrator
        isolates that so one dead source can't kill the run."""
        ...
