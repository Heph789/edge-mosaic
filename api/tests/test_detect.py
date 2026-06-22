"""detect_type — the single source-type classifier."""

from __future__ import annotations

import pytest

from app.sources import (
    SourceRejected,
    detect_label,
    detect_type,
    normalize_source_url,
)


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


@pytest.mark.parametrize(
    "stype,input_url,resolved,expected",
    [
        ("bluesky", "@simonwillison.net", None, "Bluesky"),
        ("rss", "https://foo.substack.com", "https://foo.substack.com/feed", "Substack"),
        ("rss", "https://www.youtube.com/@channel", "https://youtube.com/feeds/videos.xml", "YouTube"),
        ("rss", "https://youtu.be/abc", None, "YouTube"),
        ("rss", "https://medium.com/@writer", None, "Medium"),
        ("rss", "https://feeds.megaphone.fm/show", None, "Podcast"),
        ("rss", "https://example.com/podcast/feed", None, "Podcast"),
        ("rss", "https://jvns.ca", "https://jvns.ca/atom.xml", "Blog"),
    ],
)
def test_detect_label(stype, input_url, resolved, expected):
    assert detect_label(stype, input_url, resolved) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("chaselb.substack.com", "https://chaselb.substack.com"),  # bare host → https
        ("  foo.com/feed ", "https://foo.com/feed"),               # trimmed + schemed
        ("https://jvns.ca", "https://jvns.ca"),                     # already schemed
        ("@jay.bsky.social", "@jay.bsky.social"),                   # Bluesky handle untouched
        ("", ""),                                                    # empty untouched
    ],
)
def test_normalize_source_url(raw, expected):
    assert normalize_source_url(raw) == expected
