"""Bluesky adapter via the AT Protocol public AppView (no auth required)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from atproto import Client

from ..config import BLUESKY_FEED_LIMIT
from ..models import Source
from .base import NormalizedItem

# Unauthenticated reads go through the public AppView.
PUBLIC_API = "https://public.api.bsky.app"

_PROFILE_RE = re.compile(r"bsky\.app/profile/([^/?#]+)")


class BlueskyAdapter:
    type = "bluesky"

    def __init__(self) -> None:
        self._client = Client(base_url=PUBLIC_API)

    def fetch(self, source: Source) -> list[NormalizedItem]:
        handle = self._extract_handle(source.input_url)
        did = self._resolve_did(handle)
        source.external_id = did
        source.title = handle

        resp = self._client.app.bsky.feed.get_author_feed(
            params={"actor": did, "limit": BLUESKY_FEED_LIMIT}
        )

        items: list[NormalizedItem] = []
        for view in resp.feed:
            # Filter at scrape: drop replies and reposts.
            if getattr(view, "reply", None) is not None:
                continue
            if getattr(view, "reason", None) is not None:
                continue
            items.append(self._normalize(view.post, handle))
        return items

    # -- helpers --------------------------------------------------------------

    def _resolve_did(self, handle: str) -> str:
        resp = self._client.com.atproto.identity.resolve_handle(
            params={"handle": handle}
        )
        return resp.did

    def _normalize(self, post, handle: str) -> NormalizedItem:
        record = post.record
        uri = post.uri  # at://<did>/app.bsky.feed.post/<rkey>
        rkey = uri.rsplit("/", 1)[-1]

        likes = getattr(post, "like_count", 0) or 0
        reposts = getattr(post, "repost_count", 0) or 0

        return NormalizedItem(
            external_id=uri,
            kind="short",
            title=None,
            url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            text=getattr(record, "text", "") or "",  # store full; truncate at render
            excerpt=None,
            engagement_count=likes + reposts,
            published_at=self._parse_created_at(getattr(record, "created_at", None)),
        )

    @staticmethod
    def _extract_handle(url: str) -> str:
        value = url.strip()
        if value.startswith("@"):
            return value[1:]
        match = _PROFILE_RE.search(value)
        if match:
            return match.group(1)
        return value.removeprefix("https://").removeprefix("http://").strip("/")

    @staticmethod
    def _parse_created_at(value: str | None) -> datetime:
        if value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
