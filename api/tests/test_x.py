"""X adapter: frugal-by-design reads (resolve-once, since_id) + normalization.

All HTTP is mocked — these tests never touch the metered X API.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.x import XAdapter, XFetchError
from app.models import Source

USER_RESP = {"data": {"id": "44196397", "name": "Jack", "username": "jack"}}

TWEETS_RESP = {
    "data": [
        {
            "id": "1002",
            "text": "second post",
            "created_at": "2026-06-20T10:00:00.000Z",
            "public_metrics": {"like_count": 5, "retweet_count": 2, "reply_count": 1},
        },
        {
            "id": "1001",
            "text": "first post",
            "created_at": "2026-06-19T10:00:00.000Z",
            "public_metrics": {"like_count": 3, "retweet_count": 0, "reply_count": 0},
        },
    ],
    "meta": {"newest_id": "1002", "oldest_id": "1001", "result_count": 2},
}

EMPTY_RESP = {"meta": {"result_count": 0}}

# X's exclude=replies drops replies to *others* but not self-replies (threads), which come back
# with in_reply_to_user_id == the author's own id. This page mixes a self-reply (newest), a
# reply-to-other that somehow leaked, a quote tweet (top-level, kept), and a plain post.
AUTHOR_ID = "44196397"
TWEETS_WITH_REPLIES_RESP = {
    "data": [
        {
            "id": "1004",
            "text": "@ggraham continuing my own thread",
            "created_at": "2026-06-22T10:00:00.000Z",
            "public_metrics": {"like_count": 1, "retweet_count": 0},
            "in_reply_to_user_id": AUTHOR_ID,  # self-reply — must be dropped
        },
        {
            "id": "1003",
            "text": "@someone reply to another user",
            "created_at": "2026-06-21T10:00:00.000Z",
            "public_metrics": {"like_count": 1, "retweet_count": 0},
            "in_reply_to_user_id": "99999",  # reply to other — must be dropped
        },
        {
            "id": "1002",
            "text": "quote-tweeting something worth sharing",
            "created_at": "2026-06-20T10:00:00.000Z",
            "public_metrics": {"like_count": 5, "retweet_count": 2},
            # quote tweet: no in_reply_to_user_id — top-level, kept
        },
        {
            "id": "1001",
            "text": "plain top-level post",
            "created_at": "2026-06-19T10:00:00.000Z",
            "public_metrics": {"like_count": 3, "retweet_count": 0},
        },
    ],
    "meta": {"newest_id": "1004", "oldest_id": "1001", "result_count": 4},
}


def test_self_replies_are_filtered_but_cursor_advances(monkeypatch):
    """Replies (self or other) are dropped; quote tweets + plain posts survive. The cursor still
    advances to the API's newest_id even though that newest tweet was a filtered self-reply."""
    seen_params: list[dict] = []

    def handler(request):
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=TWEETS_WITH_REPLIES_RESP)

    source = Source(
        type="x", input_url="https://x.com/jack", external_id=AUTHOR_ID, cursor="1000"
    )
    items = _adapter(monkeypatch, handler).fetch(source)

    # Only the two non-replies remain, in returned order.
    assert [i.external_id for i in items] == ["1002", "1001"]
    # We asked X for the reply field so we can filter on it.
    assert "in_reply_to_user_id" in seen_params[0]["tweet.fields"]
    # Cursor advanced past the dropped self-reply — it won't be re-fetched next run.
    assert source.cursor == "1004"


def _adapter(monkeypatch, handler, token="test-token"):
    """Real XAdapter wired to a mock transport, with a deterministic token."""
    real_client = httpx.Client

    def mock_client(*args, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kw)

    monkeypatch.setattr("app.adapters.x.X_BEARER_TOKEN", token)
    monkeypatch.setattr("app.adapters.x.httpx.Client", mock_client)
    return XAdapter()


def test_resolves_then_fetches_and_normalizes(monkeypatch):
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        if "by/username" in request.url.path:
            return httpx.Response(200, json=USER_RESP)
        return httpx.Response(200, json=TWEETS_RESP)

    source = Source(type="x", input_url="https://x.com/jack")
    items = _adapter(monkeypatch, handler).fetch(source)

    # Resolve happened, id + title cached, cursor advanced to newest tweet.
    assert any("by/username/jack" in p for p in seen)
    assert source.external_id == "44196397"
    assert source.title == "jack"
    assert source.cursor == "1002"

    assert [i.external_id for i in items] == ["1002", "1001"]
    top = items[0]
    assert top.kind == "short"
    assert top.url == "https://x.com/jack/status/1002"
    assert top.text == "second post"
    assert top.engagement_count == 7  # 5 likes + 2 retweets (replies ignored)
    assert top.published_at.year == 2026


def test_cached_id_skips_resolve_and_passes_since_id(monkeypatch):
    """The expensive lookup is skipped once external_id is cached, and since_id bounds reads."""
    seen_paths: list[str] = []
    seen_params: list[dict] = []

    def handler(request):
        seen_paths.append(request.url.path)
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=TWEETS_RESP)

    source = Source(
        type="x", input_url="https://x.com/jack", external_id="44196397", cursor="999"
    )
    _adapter(monkeypatch, handler).fetch(source)

    assert not any("by/username" in p for p in seen_paths)  # no resolve call
    assert len(seen_paths) == 1  # exactly one (timeline) request
    params = seen_params[0]
    assert params["since_id"] == "999"
    assert params["exclude"] == "replies,retweets"


def test_empty_result_leaves_cursor_untouched(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=EMPTY_RESP)

    source = Source(
        type="x", input_url="https://x.com/jack", external_id="44196397", cursor="1002"
    )
    items = _adapter(monkeypatch, handler).fetch(source)

    assert items == []
    assert source.cursor == "1002"  # unchanged — nothing newer to advance to


def test_missing_token_raises(monkeypatch):
    def handler(request):  # never called
        raise AssertionError("should not hit the network without a token")

    source = Source(type="x", input_url="https://x.com/jack")
    with pytest.raises(XFetchError, match="not configured"):
        _adapter(monkeypatch, handler, token="").fetch(source)


def test_unknown_user_raises(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"errors": [{"detail": "Could not find user", "title": "Not Found"}]}
        )

    source = Source(type="x", input_url="https://x.com/ghost")
    with pytest.raises(XFetchError):
        _adapter(monkeypatch, handler).fetch(source)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/jack", "jack"),
        ("https://twitter.com/Jack_Dorsey", "Jack_Dorsey"),
        ("https://www.x.com/jack/", "jack"),
        ("x.com/@jack", "jack"),
    ],
)
def test_extract_handle(url, expected):
    assert XAdapter._extract_handle(url) == expected
