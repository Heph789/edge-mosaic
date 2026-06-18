"""Digest assembly engine + preview endpoint."""

from __future__ import annotations

from datetime import timedelta

from app.config import LONG_ITEMS_CAP, SHORT_ITEMS_CAP
from app.digest import assemble_digest
from app.models import Item, Source, Subscription, utcnow


def _source(db, user_id, stype="rss"):
    s = Source(user_id=user_id, type=stype, input_url=f"https://{user_id}.ex")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _item(db, source_id, kind="long", days_ago=1, ext=None, title=None):
    db.add(
        Item(
            source_id=source_id,
            external_id=ext or f"{source_id}-{kind}-{days_ago}-{title}",
            kind=kind,
            title=title,
            url=f"https://x/{ext or title}",
            published_at=utcnow() - timedelta(days=days_ago),
            scraped_at=utcnow(),
        )
    )
    db.commit()


def _subscribe(db, subscriber_id, feeder_id):
    db.add(Subscription(subscriber_id=subscriber_id, feeder_id=feeder_id))
    db.commit()


def test_assemble_filters_to_subscriptions(db, make_user):
    sub = make_user("s@example.com", "Sub")
    followed = make_user("f@example.com", "Followed")
    other = make_user("o@example.com", "Other")
    fs = _source(db, followed.id)
    os_ = _source(db, other.id)
    _item(db, fs.id, "long", days_ago=1, title="followed post")
    _item(db, os_.id, "long", days_ago=1, title="other post")
    _subscribe(db, sub.id, followed.id)

    data = assemble_digest(db, sub)
    assert [f.feeder_id for f in data.feeders] == [followed.id]
    assert data.feeders[0].longs[0].title == "followed post"


def test_trailing_window_excludes_old(db, make_user):
    sub = make_user("s@example.com", "Sub")  # weekly → 7-day trailing window
    feeder = make_user("f@example.com", "Feeder")
    fs = _source(db, feeder.id)
    _item(db, fs.id, "long", days_ago=2, title="recent")
    _item(db, fs.id, "long", days_ago=20, title="stale")
    _subscribe(db, sub.id, feeder.id)

    data = assemble_digest(db, sub)
    titles = [i.title for i in data.feeders[0].longs]
    assert titles == ["recent"]


def test_capping(db, make_user):
    sub = make_user("s@example.com", "Sub")
    feeder = make_user("f@example.com", "Feeder")
    fs = _source(db, feeder.id)
    for n in range(LONG_ITEMS_CAP + 3):
        _item(db, fs.id, "long", days_ago=1, ext=f"long-{n}", title=f"L{n}")
    for n in range(SHORT_ITEMS_CAP + 3):
        _item(db, fs.id, "short", days_ago=1, ext=f"short-{n}", title=f"S{n}")
    _subscribe(db, sub.id, feeder.id)

    feeder_data = assemble_digest(db, sub).feeders[0]
    assert len(feeder_data.longs) == LONG_ITEMS_CAP
    assert len(feeder_data.shorts) == SHORT_ITEMS_CAP


def test_feeders_ordered_by_recent_activity(db, make_user):
    sub = make_user("s@example.com", "Sub")
    older = make_user("o@example.com", "Older")
    newer = make_user("n@example.com", "Newer")
    for u, days in [(older, 5), (newer, 1)]:
        s = _source(db, u.id)
        _item(db, s.id, "long", days_ago=days, title=f"{u.display_name} post")
        _subscribe(db, sub.id, u.id)

    order = [f.display_name for f in assemble_digest(db, sub).feeders]
    assert order == ["Newer", "Older"]  # most-recent activity first


def test_preview_endpoint(client, db, make_user, auth):
    sub = make_user("s@example.com", "Sub")
    feeder = make_user("f@example.com", "Feeder F.")
    fs = _source(db, feeder.id)
    _item(db, fs.id, "long", days_ago=1, title="Hello", ext="p1")
    h = auth(sub)

    # Before subscribing: empty.
    empty = client.get("/me/digest/preview", headers=h).json()
    assert empty["feeders"] == []

    client.post("/subscriptions", json={"feeder_id": feeder.id}, headers=h)
    body = client.get("/me/digest/preview", headers=h).json()
    assert len(body["feeders"]) == 1
    assert body["feeders"][0]["display_name"] == "Feeder F."
    assert body["feeders"][0]["longs"][0]["title"] == "Hello"

    # Unsubscribe empties it again.
    client.delete(f"/subscriptions/{feeder.id}", headers=h)
    assert client.get("/me/digest/preview", headers=h).json()["feeders"] == []
