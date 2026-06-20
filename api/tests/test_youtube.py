"""YouTube feed resolution: the consent-cookie path that survives YouTube's
cookie-consent interstitial (the datacenter-IP failure mode — see
docs/youtube-feed-hardening.md).

The HTTP layer is mocked: requests carrying the consent cookie get the real channel
page / Atom feed; cookieless requests get the consent interstitial (HTML, no feed
`version`) exactly as YouTube serves it to our Railway cron. This locks in that the
consent cookie is load-bearing.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.rss import FeedResolutionError, RSSAdapter
from app.models import Source

CHANNEL_ID = "UCAAAAAAAAAAAAAAAAAAAAAA"  # UC + 22 chars

CONSENT_HTML = (
    '<!DOCTYPE html><html><head><title>Before you continue to YouTube</title></head>'
    "<body>We use cookies… consent interstitial, not a feed.</body></html>"
)
CHANNEL_HTML = f'<!DOCTYPE html><html><body>{{"externalId":"{CHANNEL_ID}"}}</body></html>'
FEED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<title>Test Channel</title>"
    "<entry>"
    "<id>yt:video:abc123</id>"
    "<title>Hello Video</title>"
    '<link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>'
    "<published>2026-06-01T00:00:00+00:00</published>"
    "<summary>A summary</summary>"
    "</entry>"
    "</feed>"
)


def _handler(request: httpx.Request) -> httpx.Response:
    """Stand in for YouTube: serve real content only to consent-cookied requests."""
    has_consent = "SOCS=CAI" in request.headers.get("cookie", "")
    if not has_consent:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=CONSENT_HTML)
    if request.url.path == "/feeds/videos.xml":
        return httpx.Response(200, headers={"content-type": "text/xml"}, text=FEED_XML)
    return httpx.Response(200, headers={"content-type": "text/html"}, text=CHANNEL_HTML)


@pytest.fixture
def adapter(monkeypatch):
    """A real RSSAdapter (consent cookies set in __init__) wired to a mock transport."""
    real_client = httpx.Client

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.adapters.rss.httpx.Client", mock_client)
    return RSSAdapter()


def _source() -> Source:
    return Source(user_id=1, type="rss", input_url="https://www.youtube.com/@chan")


def test_consent_cookie_resolves_handle_feed(adapter):
    """Handle URL → channel HTML (id scrape) → videos.xml, all past the consent gate."""
    source = _source()
    items = adapter.fetch(source)

    assert source.resolved_feed_url == (
        f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
    )
    assert source.title == "Test Channel"
    assert len(items) == 1
    assert items[0].title == "Hello Video"
    assert items[0].kind == "long"  # YouTube entries are always forced long


def test_without_consent_cookie_hits_interstitial(adapter):
    """Regression guard: strip the cookie and the same transport returns the consent
    page, so resolution fails exactly as it did on the datacenter-IP cron."""
    adapter._client.cookies.clear()
    with pytest.raises(FeedResolutionError):
        adapter.fetch(_source())
