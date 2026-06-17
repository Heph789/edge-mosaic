"""RSS/Atom adapter. The feed-resolution logic here is reused as the add-time
source validator in Slice 3."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from ..config import EXCERPT_MAX_CHARS, RSS_FETCH_TIMEOUT, USER_AGENT
from ..models import Source
from ..text import classify_kind, strip_html, truncate_on_word
from .base import NormalizedItem

COMMON_FEED_PATHS = ["/feed", "/rss", "/feed.xml", "/atom.xml", "/index.xml"]
FEED_LINK_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


class FeedResolutionError(Exception):
    """Raised when no usable feed can be found for a source URL."""


class RSSAdapter:
    type = "rss"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=RSS_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    # -- public ---------------------------------------------------------------

    def fetch(self, source: Source) -> list[NormalizedItem]:
        feed_url, parsed = self._resolve_feed(source.input_url)
        source.resolved_feed_url = feed_url
        title = parsed.feed.get("title")
        if title:
            source.title = title.strip()
        return [self._normalize(entry) for entry in parsed.entries]

    # -- feed resolution (Slice 1 §RSS adapter) -------------------------------

    def _resolve_feed(self, url: str):
        # 1. Already a feed?
        parsed = self._try_parse(url)
        if parsed is not None:
            return url, parsed

        # 2. HTML autodiscovery via <link rel="alternate" ...>.
        html = self._get_text(url)
        if html:
            discovered = self._discover_in_html(html, url)
            if discovered:
                parsed = self._try_parse(discovered)
                if parsed is not None:
                    return discovered, parsed

        # 3. Common well-known paths.
        base = self._base_url(url)
        for path in COMMON_FEED_PATHS:
            candidate = urljoin(base, path)
            parsed = self._try_parse(candidate)
            if parsed is not None:
                return candidate, parsed

        # 4. Give up.
        raise FeedResolutionError(f"Could not resolve a feed for {url!r}")

    def _try_parse(self, url: str):
        """Fetch + parse; return the parsed feed only if it really is a feed."""
        content = self._get_bytes(url)
        if content is None:
            return None
        parsed = feedparser.parse(content)
        # feedparser leaves `version` empty for non-feed documents (e.g. HTML pages).
        if parsed.get("version"):
            return parsed
        return None

    def _discover_in_html(self, html: str, base_url: str) -> str | None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("link", rel="alternate"):
            link_type = (link.get("type") or "").lower()
            href = link.get("href")
            if href and link_type in FEED_LINK_TYPES:
                return urljoin(base_url, href)
        return None

    # -- entry normalization --------------------------------------------------

    def _normalize(self, entry) -> NormalizedItem:
        link = entry.get("link") or ""
        title = (entry.get("title") or "").strip() or None

        external_id = (
            entry.get("id")
            or link
            or hashlib.sha1(f"{title}{link}".encode()).hexdigest()
        )

        # Length classification uses the fullest body available (Atom <content> when
        # present, else <summary>); the displayed excerpt stays the author's summary.
        body = entry.get("summary") or entry.get("description")
        if entry.get("content"):
            body = entry.content[0].get("value") or body
        stripped_body = strip_html(body)

        raw_excerpt = entry.get("summary") or entry.get("description")
        excerpt = truncate_on_word(strip_html(raw_excerpt), EXCERPT_MAX_CHARS) or None

        return NormalizedItem(
            external_id=external_id,
            kind=classify_kind(stripped_body),
            title=title,
            url=link,
            text=None,
            excerpt=excerpt,
            engagement_count=0,
            published_at=self._entry_datetime(entry),
        )

    def _entry_datetime(self, entry) -> datetime:
        for key in ("published_parsed", "updated_parsed"):
            st: time.struct_time | None = entry.get(key)
            if st is not None:
                try:
                    # feedparser normalizes parsed times to UTC.
                    return datetime(*st[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
        # Missing/garbage date → fall back to scrape time.
        return datetime.now(timezone.utc)

    # -- http helpers ---------------------------------------------------------

    def _get_bytes(self, url: str) -> bytes | None:
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError:
            return None

    def _get_text(self, url: str) -> str | None:
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError:
            return None

    @staticmethod
    def _base_url(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}"
