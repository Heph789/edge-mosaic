"""Polite retry/backoff on the RSS fetch path: retry transient throttling (429/5xx,
timeouts), honor Retry-After, never retry permanent failures, and stay snappy on the
interactive add-time path. See docs/youtube-feed-hardening.md (approach #2).
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.rss import RSSAdapter


def _make_adapter(monkeypatch, handler, **kwargs):
    """Real RSSAdapter wired to a mock transport, with sleep captured (no real waits)."""
    real_client = httpx.Client

    def mock_client(*args, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kw)

    monkeypatch.setattr("app.adapters.rss.httpx.Client", mock_client)
    sleeps: list[float] = []
    monkeypatch.setattr("app.adapters.rss.time.sleep", sleeps.append)
    return RSSAdapter(**kwargs), sleeps


def test_retries_transient_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    adapter, sleeps = _make_adapter(monkeypatch, handler)
    assert adapter._get_text("https://example.com/feed") == "ok"
    assert calls["n"] == 2
    assert len(sleeps) == 1  # backed off once between attempts


def test_no_retry_on_permanent_404(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    adapter, sleeps = _make_adapter(monkeypatch, handler)
    assert adapter._get_bytes("https://example.com/feed") is None
    assert calls["n"] == 1  # not retried
    assert sleeps == []


def test_gives_up_after_retry_budget(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429)

    adapter, sleeps = _make_adapter(monkeypatch, handler)  # default 2 retries
    assert adapter._get_text("https://example.com/feed") is None
    assert calls["n"] == 3  # initial + 2 retries
    assert len(sleeps) == 2


def test_honors_retry_after_header(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text="ok")

    adapter, sleeps = _make_adapter(monkeypatch, handler)
    assert adapter._get_text("https://example.com/feed") == "ok"
    assert sleeps == [2.0]  # exact server-requested wait, not jittered backoff


def test_retries_transport_errors(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="ok")

    adapter, sleeps = _make_adapter(monkeypatch, handler)
    assert adapter._get_text("https://example.com/feed") == "ok"
    assert calls["n"] == 2


def test_interactive_add_path_does_not_retry(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503)

    # deadline_seconds set → add-time validator → no retries, stays snappy.
    adapter, sleeps = _make_adapter(monkeypatch, handler, deadline_seconds=10.0)
    assert adapter._get_text("https://example.com/feed") is None
    assert calls["n"] == 1
    assert sleeps == []
