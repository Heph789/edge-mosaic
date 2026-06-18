"""detect_type — the single source-type classifier."""

from __future__ import annotations

import pytest

from app.sources import SourceRejected, detect_type


@pytest.mark.parametrize(
    "url,expected",
    [
        ("@simonwillison.net", "bluesky"),
        ("https://bsky.app/profile/jay.bsky.team", "bluesky"),
        ("https://jvns.ca", "rss"),
        ("https://www.astralcodexten.com", "rss"),
        ("foo.substack.com", "rss"),
        ("https://example.com/blog", "rss"),
    ],
)
def test_detect_type(url, expected):
    assert detect_type(url) == expected


@pytest.mark.parametrize("url", ["https://x.com/jack", "twitter.com/x", "https://www.x.com/y"])
def test_x_is_rejected(url):
    with pytest.raises(SourceRejected):
        detect_type(url)
