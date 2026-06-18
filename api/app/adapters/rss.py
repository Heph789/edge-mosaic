"""RSS/Atom adapter. The feed-resolution logic here is reused as the add-time
source validator in Slice 3."""

from __future__ import annotations

import hashlib
import re
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

# Platforms whose "page" is just a directory in front of a real RSS feed.
_APPLE_PODCAST_RE = re.compile(r"podcasts\.apple\.com/.*?/id(\d+)")
_YT_CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/(UC[0-9A-Za-z_-]{22})")
_YT_OWN_ID_RES = (
    re.compile(r'"externalId":"(UC[0-9A-Za-z_-]{22})"'),
    re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{22})"'),
)


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
        # Podcasts/YouTube are RSS underneath a directory page: resolve those directly
        # and force kind='long' (a media episode is real content regardless of how long
        # its blurb is, so length-classification doesn't apply).
        platform_feed, force_kind = self._platform_feed(source.input_url)
        if platform_feed is not None:
            parsed = self._try_parse(platform_feed)
            if parsed is None:
                raise FeedResolutionError(f"Resolved feed did not parse: {platform_feed!r}")
            feed_url = platform_feed
        else:
            feed_url, parsed = self._resolve_feed(source.input_url)
            force_kind = None

        source.resolved_feed_url = feed_url
        title = parsed.feed.get("title")
        if title:
            source.title = title.strip()
        return [self._normalize(entry, force_kind) for entry in parsed.entries]

    # -- platform resolution (directory page → real feed) ---------------------

    def _platform_feed(self, url: str) -> tuple[str | None, str | None]:
        """Resolve a known platform URL to its feed + forced kind, else (None, None)."""
        apple = _APPLE_PODCAST_RE.search(url)
        if apple:
            return self._itunes_feed(apple.group(1)), "long"
        if "youtube.com" in url or "youtu.be" in url:
            return self._youtube_feed(url), "long"
        return None, None

    def _itunes_feed(self, podcast_id: str) -> str:
        """Apple Podcasts id → real RSS feed via the iTunes Lookup API."""
        try:
            resp = self._client.get(
                "https://itunes.apple.com/lookup", params={"id": podcast_id}
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            raise FeedResolutionError(f"iTunes lookup failed for id {podcast_id}") from exc
        feed_url = results[0].get("feedUrl") if results else None
        if not feed_url:
            raise FeedResolutionError(f"No feedUrl for Apple podcast id {podcast_id}")
        return feed_url

    def _youtube_feed(self, url: str) -> str:
        """YouTube channel/handle URL → channel RSS feed."""
        direct = _YT_CHANNEL_ID_RE.search(url)
        channel_id = direct.group(1) if direct else self._youtube_channel_id(url)
        if not channel_id:
            raise FeedResolutionError(f"Could not find a YouTube channel id for {url!r}")
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def _youtube_channel_id(self, url: str) -> str | None:
        # The channel's OWN id is in externalId/canonical — not the first "channelId"
        # in the page, which is often a recommended channel.
        html = self._get_text(url)
        if not html:
            return None
        for pattern in _YT_OWN_ID_RES:
            match = pattern.search(html)
            if match:
                return match.group(1)
        return None

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

    def _normalize(self, entry, force_kind: str | None = None) -> NormalizedItem:
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
            kind=force_kind or classify_kind(stripped_body),
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
