"""Digest assembly engine + preview endpoint."""

from __future__ import annotations

from datetime import timedelta

from app.config import LONG_ITEMS_CAP, SHORT_ITEMS_CAP
from app.digest import assemble_digest
from app.models import Item, Source, Subscription, utcnow


def _source(db, user_id, stype="rss"):
    # URL keyed on (user_id, stype) so a feeder can have several distinct sources.
    s = Source(user_id=user_id, type=stype, input_url=f"https://{user_id}-{stype}.ex")
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
    assert data.feeders[0].sources[0].longs[0].title == "followed post"


def test_trailing_window_excludes_old(db, make_user):
    sub = make_user("s@example.com", "Sub")  # weekly → 7-day trailing window
    feeder = make_user("f@example.com", "Feeder")
    fs = _source(db, feeder.id)
    _item(db, fs.id, "long", days_ago=2, title="recent")
    _item(db, fs.id, "long", days_ago=20, title="stale")
    _subscribe(db, sub.id, feeder.id)

    data = assemble_digest(db, sub)
    titles = [i.title for i in data.feeders[0].sources[0].longs]
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
    # Caps are per-feeder; this feeder has one source, so the block holds the capped items.
    block = feeder_data.sources[0]
    assert len(block.longs) == LONG_ITEMS_CAP
    assert len(block.shorts) == SHORT_ITEMS_CAP


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
    assert body["feeders"][0]["sources"][0]["longs"][0]["title"] == "Hello"
    assert body["feeders"][0]["selected"]["title"] == "Hello"
    assert body["compact"] is False and body["quiet_feeders"] == []

    # Unsubscribe empties it again.
    client.delete(f"/subscriptions/{feeder.id}", headers=h)
    assert client.get("/me/digest/preview", headers=h).json()["feeders"] == []


def test_groups_by_source_long_form_first(db, make_user):
    sub = make_user("s@example.com", "Sub")
    feeder = make_user("f@example.com", "Feeder")
    blog = _source(db, feeder.id, "rss")
    sky = _source(db, feeder.id, "bluesky")
    blog.title = "The Blog"
    db.commit()
    _item(db, sky.id, "short", days_ago=1, title="toot", ext="sky1")
    _item(db, blog.id, "long", days_ago=2, title="essay", ext="blog1")
    _subscribe(db, sub.id, feeder.id)

    feeder_data = assemble_digest(db, sub).feeders[0]
    labels = [s.label for s in feeder_data.sources]
    # A feeder's sources each get their own labelled block; long-form sorts above short.
    assert labels == ["The Blog", "Bluesky"]
    assert feeder_data.sources[0].longs[0].title == "essay"


def test_selected_prefers_most_recent_long(db, make_user):
    sub = make_user("s@example.com", "Sub")
    feeder = make_user("f@example.com", "Feeder")
    fs = _source(db, feeder.id)
    _item(db, fs.id, "short", days_ago=1, title="fresh short", ext="s1")
    _item(db, fs.id, "long", days_ago=3, title="older long", ext="l1")
    _subscribe(db, sub.id, feeder.id)

    # Representative item is the most-recent LONG even though a short is newer (kind §4).
    assert assemble_digest(db, sub).feeders[0].selected.title == "older long"


def test_quiet_feeders_surfaced(db, make_user):
    sub = make_user("s@example.com", "Sub")
    active = make_user("a@example.com", "Active A")
    quiet = make_user("q@example.com", "Quiet Q")
    a_src = _source(db, active.id)
    q_src = _source(db, quiet.id)
    _item(db, a_src.id, "long", days_ago=1, title="posted", ext="a1")
    _item(db, q_src.id, "long", days_ago=40, title="stale", ext="q1")  # outside window
    _subscribe(db, sub.id, active.id)
    _subscribe(db, sub.id, quiet.id)

    data = assemble_digest(db, sub)
    assert [f.display_name for f in data.feeders] == ["Active A"]
    # Followed, has a source, but nothing in the window → surfaced as quiet, not dropped.
    assert data.quiet_feeders == ["Quiet Q"]


def test_compact_flag_trips_above_threshold(db, make_user):
    from app.config import COMPACT_MODE_FEEDER_THRESHOLD

    sub = make_user("s@example.com", "Sub")
    for n in range(COMPACT_MODE_FEEDER_THRESHOLD):
        f = make_user(f"f{n}@example.com", f"Feeder {n}")
        s = _source(db, f.id)
        _item(db, s.id, "long", days_ago=1, title=f"post {n}", ext=f"p{n}")
        _subscribe(db, sub.id, f.id)

    assert assemble_digest(db, sub).compact is True
