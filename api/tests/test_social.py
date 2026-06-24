"""Subscriptions + Discover."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Source, Subscription


def _add_source(db, user_id, stype="rss", url=None):
    db.add(Source(user_id=user_id, type=stype, input_url=url or f"https://{stype}.ex"))
    db.commit()


# --- subscriptions --------------------------------------------------------------------
def test_subscribe_unsubscribe_idempotent(client, db, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    bob = make_user("b@example.com", "Bob B.")
    h = auth(ann)

    r = client.post("/subscriptions", json={"feeder_id": bob.id}, headers=h)
    assert r.status_code == 200 and r.json()["feeder_id"] == bob.id
    # Re-subscribe → still one row.
    client.post("/subscriptions", json={"feeder_id": bob.id}, headers=h)
    assert len(list(db.scalars(select(Subscription)))) == 1

    assert client.delete(f"/subscriptions/{bob.id}", headers=h).status_code == 204
    assert db.scalar(select(Subscription)) is None
    # Unsubscribe again → still 204 (idempotent).
    assert client.delete(f"/subscriptions/{bob.id}", headers=h).status_code == 204


def test_self_subscription_allowed(client, db, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    r = client.post("/subscriptions", json={"feeder_id": ann.id}, headers=auth(ann))
    assert r.status_code == 200
    assert db.scalar(select(Subscription)).feeder_id == ann.id


def test_subscribe_to_ghost_allowed(client, db, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    ghost = make_user("g@example.com", "Ghost G.")  # verified_at is None
    assert ghost.verified_at is None
    r = client.post("/subscriptions", json={"feeder_id": ghost.id}, headers=auth(ann))
    assert r.status_code == 200


def test_subscribe_unknown_feeder_404(client, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    r = client.post("/subscriptions", json={"feeder_id": 99999}, headers=auth(ann))
    assert r.status_code == 404


def test_subscription_list_has_platforms(client, db, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    bob = make_user("b@example.com", "Bob B.")
    _add_source(db, bob.id, "rss")
    _add_source(db, bob.id, "bluesky")
    h = auth(ann)
    client.post("/subscriptions", json={"feeder_id": bob.id}, headers=h)

    listed = client.get("/subscriptions", headers=h).json()
    # platforms are granular display labels now: rss(https://rss.ex) → "Blog", bluesky → "Bluesky".
    assert listed == [
        {"feeder_id": bob.id, "display_name": "Bob B.", "platforms": ["Blog", "Bluesky"]}
    ]


# --- discover -------------------------------------------------------------------------
def test_discover_eligibility_and_self_in_search(client, db, make_user, auth):
    searcher = make_user("s@example.com", "Search Person")
    visible = make_user("v@example.com", "Visible Person")  # ghost, no sources
    make_user("n@example.com", display_name=None)  # no display_name → excluded

    hits = client.get("/discover?q=Person", headers=auth(searcher)).json()
    names = {h["display_name"] for h in hits}
    assert "Visible Person" in names  # ghost is discoverable
    assert "Search Person" in names  # you can find your own profile in a search
    assert next(h for h in hits if h["display_name"] == "Visible Person")["platforms"] == []


def test_discover_is_subscribed_flag_and_platforms(client, db, make_user, auth):
    ann = make_user("a@example.com", "Ann A.")
    bob = make_user("b@example.com", "Bob Builder")
    _add_source(db, bob.id, "rss")
    h = auth(ann)
    client.post("/subscriptions", json={"feeder_id": bob.id}, headers=h)

    hit = client.get("/discover?q=Builder", headers=h).json()[0]
    assert hit["is_subscribed"] is True
    # Discover pills now link out: each platform label carries the first source's URL.
    assert hit["platforms"] == [{"label": "Blog", "url": "https://rss.ex"}]


def test_discover_escapes_like_wildcards(client, db, make_user, auth):
    searcher = make_user("s@example.com", "Searcher")
    make_user("a@example.com", "50% Off Deals")
    make_user("b@example.com", "5000 Steps")

    # "50%" must match literally — not as a wildcard that also catches "5000 Steps".
    hits = client.get("/discover?q=50%25", headers=auth(searcher)).json()  # %25 = '%'
    names = {h["display_name"] for h in hits}
    assert names == {"50% Off Deals"}
