"""X (Twitter) adapter via the API v2, app-only Bearer auth.

X bills per post read (pay-per-use since 2026-02-06), so this adapter is deliberately frugal:

  * Resolve the @handle → numeric user id ONCE and cache it on ``source.external_id``; every
    later scrape skips the lookup entirely.
  * Pull only tweets newer than the last one seen, via ``since_id`` (stored on ``source.cursor``
    and advanced to ``meta.newest_id`` after each successful pull). A quiet account costs one
    empty-result request; a busy one costs only its genuinely-new tweets.
  * ``exclude=replies,retweets`` and a small ``max_results`` keep each page tight.

No retry/backoff: a transient failure (e.g. 429) just raises, the orchestrator isolates it,
and the next scheduled scrape picks up where ``cursor`` left off — re-hammering a metered API
would only cost money.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from ..config import X_API_BASE, X_BEARER_TOKEN, X_FEED_LIMIT, X_FETCH_TIMEOUT
from ..models import Source
from .base import NormalizedItem

# x.com/<handle> or twitter.com/<handle>, capturing the first path segment (the handle).
_HANDLE_RE = re.compile(r"(?:x|twitter)\.com/(@?[A-Za-z0-9_]{1,15})")


class XFetchError(Exception):
    """Unrecoverable failure talking to the X API (missing token, bad handle, API error)."""


class XAdapter:
    type = "x"

    def __init__(self, timeout: float = X_FETCH_TIMEOUT) -> None:
        # Token is read at construction but only *required* at fetch time, so importing the
        # adapter (and detecting the source type) works even without X configured.
        self._token = X_BEARER_TOKEN
        self._client = httpx.Client(
            base_url=X_API_BASE,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
        )

    def fetch(self, source: Source) -> list[NormalizedItem]:
        if not self._token:
            raise XFetchError("X_BEARER_TOKEN is not configured")

        handle = self._extract_handle(source.input_url)
        # Resolve the username → numeric id once; reuse the cached id on every later scrape.
        user_id = source.external_id or self._resolve_user_id(handle)
        source.external_id = user_id
        source.title = handle

        params = {
            "max_results": X_FEED_LIMIT,
            "exclude": "replies,retweets",
            "tweet.fields": "created_at,public_metrics",
        }
        if source.cursor:
            params["since_id"] = source.cursor  # only tweets newer than the high-water mark

        payload = self._get(f"/users/{user_id}/tweets", params)
        tweets = payload.get("data") or []

        # Advance the high-water mark so the next scrape reads only what's newer still. Present
        # only when this pull returned tweets; an empty result leaves the cursor untouched.
        newest_id = (payload.get("meta") or {}).get("newest_id")
        if newest_id:
            source.cursor = newest_id

        return [self._normalize(tweet, handle) for tweet in tweets]

    # -- helpers --------------------------------------------------------------

    def _resolve_user_id(self, handle: str) -> str:
        payload = self._get(f"/users/by/username/{handle}", params={})
        data = payload.get("data")
        if not data or not data.get("id"):
            raise XFetchError(f"X user not found: @{handle}")
        return data["id"]

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._client.get(path, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise XFetchError(f"X API request failed for {path}: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise XFetchError(f"X API returned non-JSON for {path}") from exc
        # v2 reports app-level problems (suspended/missing user) as a 200 with `errors`.
        if not payload.get("data") and payload.get("errors"):
            detail = payload["errors"][0].get("detail") or payload["errors"][0].get("title")
            raise XFetchError(f"X API error for {path}: {detail}")
        return payload

    def _normalize(self, tweet: dict, handle: str) -> NormalizedItem:
        tweet_id = tweet["id"]
        metrics = tweet.get("public_metrics") or {}
        likes = metrics.get("like_count", 0) or 0
        reposts = metrics.get("retweet_count", 0) or 0

        return NormalizedItem(
            external_id=tweet_id,
            kind="short",
            title=None,
            url=f"https://x.com/{handle}/status/{tweet_id}",
            text=tweet.get("text", "") or "",  # store full; truncate at render
            excerpt=None,
            engagement_count=likes + reposts,  # mirror the bluesky likes+reposts signal
            published_at=self._parse_created_at(tweet.get("created_at")),
        )

    @staticmethod
    def _extract_handle(url: str) -> str:
        value = url.strip()
        match = _HANDLE_RE.search(value)
        if match:
            return match.group(1).lstrip("@")
        # Bare handle fallback (detect_type routes @handles to bluesky, so this is rare).
        return value.lstrip("@").removeprefix("https://").removeprefix("http://").strip("/")

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
