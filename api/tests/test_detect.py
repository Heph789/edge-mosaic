"""detect_type — the single source-type classifier."""

from __future__ import annotations

import pytest

from app.sources import detect_type


@pytest.mark.parametrize(
    "url,expected",
    [
        ("@simonwillison.net", "bluesky"),
        ("https://bsky.app/profile/jay.bsky.team", "bluesky"),
        ("https://jvns.ca", "rss"),
        ("https://www.astralcodexten.com", "rss"),
        ("foo.substack.com", "rss"),
        ("https://example.com/blog", "rss"),
        ("https://x.com/jack", "x"),
        ("twitter.com/x", "x"),
        ("https://www.x.com/y", "x"),
        ("https://mobile.twitter.com/z", "x"),
    ],
)
def test_detect_type(url, expected):
    assert detect_type(url) == expected
