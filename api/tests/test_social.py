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
    assert hit["platforms"] == ["Blog"]  # rss(https://rss.ex) → "Blog" display label


def test_discover_escapes_like_wildcards(client, db, make_user, auth):
    searcher = make_user("s@example.com", "Searcher")
    make_user("a@example.com", "50% Off Deals")
    make_user("b@example.com", "5000 Steps")

    # "50%" must match literally — not as a wildcard that also catches "5000 Steps".
    hits = client.get("/discover?q=50%25", headers=auth(searcher)).json()  # %25 = '%'
    names = {h["display_name"] for h in hits}
    assert names == {"50% Off Deals"}


def test_discover_empty_query_browses_all(client, make_user, auth):
    # Empty / whitespace / absent q browses the whole directory (Slice 5: the Directory
    # shows a list by default), excluding the searcher; it no longer 422s.
    searcher = make_user("s@example.com", "Searcher")
    make_user("a@example.com", "Alice A")
    make_user("b@example.com", "Bob B")

    for url in ("/discover?q=%20", "/discover"):
        resp = client.get(url, headers=auth(searcher))
        assert resp.status_code == 200
        names = {h["display_name"] for h in resp.json()}
        assert names == {"Alice A", "Bob B"}  # all discoverable users, self excluded


def test_discover_pagination_offset_limit(client, make_user, auth):
    # Infinite scroll fetches the directory page by page via offset/limit; the slices must
    # tile the full ordered list without gaps or repeats.
    searcher = make_user("s@example.com", "Searcher")
    for i in range(5):
        make_user(f"u{i}@example.com", f"Person {i}")

    h = auth(searcher)
    page1 = client.get("/discover?limit=2&offset=0", headers=h).json()
    page2 = client.get("/discover?limit=2&offset=2", headers=h).json()
    page3 = client.get("/discover?limit=2&offset=4", headers=h).json()
    assert [len(page1), len(page2), len(page3)] == [2, 2, 1]  # 5 people, 2 per page

    ids = [r["user_id"] for r in (*page1, *page2, *page3)]
    assert len(ids) == len(set(ids)) == 5  # no gaps, no repeats
