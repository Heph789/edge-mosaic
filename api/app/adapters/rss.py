"""RSS/Atom adapter. The feed-resolution logic here is reused as the add-time
source validator in Slice 3."""

from __future__ import annotations

import hashlib
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from ..config import (
    EXCERPT_MAX_CHARS,
    RSS_FETCH_RETRIES,
    RSS_FETCH_TIMEOUT,
    RSS_RETRY_BACKOFF_BASE,
    RSS_RETRY_MAX_DELAY,
    USER_AGENT,
    YOUTUBE_CONSENT_COOKIES,
)
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

# Transient throttling/server errors worth a polite retry; 4xx like 404/403 are not.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

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

    def __init__(
        self,
        timeout: float = RSS_FETCH_TIMEOUT,
        deadline_seconds: float | None = None,
    ) -> None:
        # deadline_seconds bounds *total* resolution wall-clock (interactive add); the
        # background scrape leaves it None and relies on the per-request timeout only.
        self._deadline_seconds = deadline_seconds
        # Polite retry only on the background scrape — the interactive add path has a
        # deadline to honor, so it opts out and stays snappy.
        self._retries = 0 if deadline_seconds is not None else RSS_FETCH_RETRIES
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        # Pre-accept YouTube's cookie-consent gate so the channel page + videos.xml feed
        # return real content instead of a consent interstitial (the failure mode on the
        # cookieless, datacenter-IP Railway cron). Domain-scoped → never sent elsewhere.
        for name, value in YOUTUBE_CONSENT_COOKIES.items():
            self._client.cookies.set(name, value, domain="youtube.com")

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
        start = time.monotonic()

        def check_deadline() -> None:
            if (
                self._deadline_seconds is not None
                and time.monotonic() - start > self._deadline_seconds
            ):
                raise FeedResolutionError(
                    f"Feed resolution for {url!r} exceeded {self._deadline_seconds}s"
                )

        # 1. Already a feed?
        parsed = self._try_parse(url)
        if parsed is not None:
            return url, parsed

        # 2. HTML autodiscovery via <link rel="alternate" ...>.
        check_deadline()
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
            check_deadline()
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
        resp = self._get_response(url)
        return resp.content if resp is not None else None

    def _get_text(self, url: str) -> str | None:
        resp = self._get_response(url)
        return resp.text if resp is not None else None

    def _get_response(self, url: str) -> httpx.Response | None:
        """GET with a polite retry on transient throttling (429/5xx) and transport
        errors (timeouts, connection resets). Honors Retry-After, backs off with jitter,
        and gives up — returning None — on permanent failures (404/403) or last attempt."""
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status in _RETRYABLE_STATUS or isinstance(
                    exc, httpx.TransportError
                )
                if not retryable or attempt == self._retries:
                    return None
                response = getattr(exc, "response", None)
                time.sleep(self._retry_delay(attempt, response))
        return None

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = self._parse_retry_after(response)
        if retry_after is not None:
            return min(retry_after, RSS_RETRY_MAX_DELAY)
        # Exponential backoff with full jitter, capped — polite spacing under load.
        ceiling = min(RSS_RETRY_BACKOFF_BASE * (2**attempt), RSS_RETRY_MAX_DELAY)
        return random.uniform(0, ceiling)

    @staticmethod
    def _parse_retry_after(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))  # delta-seconds form
        except ValueError:
            return None  # HTTP-date form: fall back to backoff

    @staticmethod
    def _base_url(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}"
