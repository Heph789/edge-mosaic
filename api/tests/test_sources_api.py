"""Source endpoints — preview, create (inline first-scrape), idempotency, ownership."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.adapters.base import NormalizedItem
from app.models import Item, Source, utcnow


class FakeAdapter:
    """Stand-in for the network adapters: mutates the source + returns canned items."""

    type = "rss"

    def __init__(self, items):
        self._items = items

    def fetch(self, source):
        source.resolved_feed_url = source.input_url.rstrip("/") + "/feed"
        source.title = "Fake Blog"
        return self._items


@pytest.fixture
def fake_feed(monkeypatch):
    """Patch both adapter seams (preview path + scrape path) with canned items."""
    now = utcnow()
    items = [
        NormalizedItem(
            external_id="post-1",
            kind="long",
            url="https://blog.example/1",
            published_at=now - timedelta(hours=1),  # most recent → the "latest"
            title="A Long Essay",
            excerpt="essay excerpt",
        ),
        NormalizedItem(
            external_id="note-1",
            kind="short",
            url="https://blog.example/2",
            published_at=now - timedelta(hours=2),
            text="a short note",
        ),
    ]
    adapter = FakeAdapter(items)
    monkeypatch.setattr("app.sources._adapter_for", lambda _t: adapter)
    monkeypatch.setattr("app.ingest.get_adapter", lambda _t: adapter)
    return items


def test_preview_does_not_write(client, db, make_user, auth, fake_feed):
    h = auth(make_user("a@example.com", "Ann A."))
    r = client.post("/sources/preview", json={"url": "https://blog.example"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "rss"
    assert body["found_count"] == 2
    assert body["latest_title"] == "A Long Essay"  # most recent of the canned items
    # No DB writes from preview.
    assert db.scalar(select(Source)) is None


def test_preview_accepts_x(client, make_user, auth, fake_feed):
    # X is now a supported platform: it detects as type 'x' and previews like any source.
    h = auth(make_user("a@example.com", "Ann A."))
    r = client.post("/sources/preview", json={"url": "https://x.com/jack"}, headers=h)
    assert r.status_code == 200
    assert r.json()["type"] == "x"


def test_create_runs_inline_first_scrape(client, db, make_user, auth, fake_feed):
    user = make_user("a@example.com", "Ann A.")
    h = auth(user)
    r = client.post("/sources", json={"url": "https://blog.example"}, headers=h)
    assert r.status_code == 201
    src = r.json()
    assert src["type"] == "rss" and src["resolved_feed_url"].endswith("/feed")

    # Items were ingested immediately (inline first-scrape).
    items = list(db.scalars(select(Item)))
    assert {i.external_id for i in items} == {"post-1", "note-1"}
    assert all(i.source_id == src["id"] for i in items)


def test_create_is_idempotent(client, db, make_user, auth, fake_feed):
    h = auth(make_user("a@example.com", "Ann A."))
    first = client.post("/sources", json={"url": "https://blog.example"}, headers=h)
    second = client.post("/sources", json={"url": "https://blog.example"}, headers=h)
    assert first.json()["id"] == second.json()["id"]
    assert len(list(db.scalars(select(Source)))) == 1


def test_list_is_own_only(client, db, make_user, auth, fake_feed):
    ann = make_user("a@example.com", "Ann A.")
    bob = make_user("b@example.com", "Bob B.")
    client.post("/sources", json={"url": "https://ann.example"}, headers=auth(ann))
    bob_h = auth(bob)
    client.post("/sources", json={"url": "https://bob.example"}, headers=bob_h)

    listed = client.get("/sources", headers=bob_h).json()
    assert [s["input_url"] for s in listed] == ["https://bob.example"]


def test_delete_foreign_source_is_404(client, db, make_user, auth, fake_feed):
    ann = make_user("a@example.com", "Ann A.")
    bob = make_user("b@example.com", "Bob B.")
    created = client.post(
        "/sources", json={"url": "https://ann.example"}, headers=auth(ann)
    ).json()
    # Bob can't see or delete Ann's source.
    r = client.delete(f"/sources/{created['id']}", headers=auth(bob))
    assert r.status_code == 404
    assert db.get(Source, created["id"]) is not None


def test_delete_cascades_items(client, db, make_user, auth, fake_feed):
    ann = make_user("a@example.com", "Ann A.")
    h = auth(ann)
    created = client.post(
        "/sources", json={"url": "https://ann.example"}, headers=h
    ).json()
    assert client.delete(f"/sources/{created['id']}", headers=h).status_code == 204
    assert db.scalar(select(Source)) is None
    assert db.scalar(select(Item)) is None  # cascade removed items
