"""Notable-speaker seeding — declarative reconcile of links/sources and pruning of ghosts.

The roster (`docs/notable-speakers.json`) is the source of truth: re-running rebuilds each
notable's links, reconciles its sources, and prunes ghosts dropped from the roster — which is
how a notable or one of its links gets deleted from a deployed DB.
"""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select

from app.models import (
    AllowedEmail,
    Item,
    ProfileLink,
    Source,
    Subscription,
    User,
    utcnow,
)
from app.seed_notable import seed_notable_speakers


def _roster(tmp_path, rows):
    path = tmp_path / "notable.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


ALICE = {
    "name": "Alice Example",
    "email": "alice@example.com",
    "links": [
        {"label": "Substack", "url": "https://alice.substack.com"},  # feeder → source
        {"label": "X", "url": "https://x.com/alice"},  # feeder → source (X adapter)
        {"label": "GitHub", "url": "https://github.com/alice"},  # display link
    ],
}


def test_seed_creates_notable_with_source_and_links(db, tmp_path):
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    assert user.is_notable and user.verified_at is None
    # Substack + X route to scraped sources; only GitHub stays a display link.
    sources = {
        s.input_url: s.type
        for s in db.scalars(select(Source).where(Source.user_id == user.id))
    }
    assert sources == {
        "https://alice.substack.com": "rss",
        "https://x.com/alice": "x",
    }
    assert {l.url for l in db.scalars(select(ProfileLink).where(ProfileLink.user_id == user.id))} == {
        "https://github.com/alice",
    }


def test_rerun_drops_removed_link_and_source(db, tmp_path):
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))

    # Drop everything but the GitHub display link → both scraped sources are removed.
    trimmed = {**ALICE, "links": [{"label": "GitHub", "url": "https://github.com/alice"}]}
    stats = seed_notable_speakers(db, _roster(tmp_path, [trimmed]))

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert stats.sources_removed == 2  # substack + x
    assert db.scalar(select(func.count()).select_from(Source).where(Source.user_id == user.id)) == 0
    assert [l.url for l in db.scalars(select(ProfileLink).where(ProfileLink.user_id == user.id))] == [
        "https://github.com/alice"
    ]


def test_prune_removes_ghost_dropped_from_roster(db, tmp_path):
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))
    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    src = db.scalar(select(Source).where(Source.user_id == user.id))
    db.add(
        Item(
            source_id=src.id,
            external_id="x1",
            kind="long",
            url="https://alice.substack.com/p/1",
            published_at=utcnow(),
        )
    )
    db.commit()

    # Roster no longer lists Alice (but is non-empty) → she is pruned, cascading everything.
    keeper = {"name": "Bob", "email": "bob@example.com", "links": []}
    stats = seed_notable_speakers(db, _roster(tmp_path, [keeper]))

    assert stats.notables_removed == 1
    assert db.scalar(select(User).where(User.email == "alice@example.com")) is None
    assert db.scalar(select(func.count()).select_from(Source)) == 0  # cascaded
    assert db.scalar(select(func.count()).select_from(Item)) == 0  # cascaded
    assert db.scalar(select(func.count()).select_from(ProfileLink)) == 0  # cascaded


def test_demote_dropped_notable_on_allowlist(db, tmp_path):
    """A dropped notable who is also a named allowlist attendee is demoted to a plain
    pre-seed (initials, curated content stripped), not deleted."""
    db.add(AllowedEmail(email="alice@example.com", name="Alice E."))
    db.commit()
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))

    stats = seed_notable_speakers(db, _roster(tmp_path, [{"name": "Bob", "email": "bob@x.co", "links": []}]))

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert stats.notables_demoted == 1 and stats.notables_removed == 0
    assert user is not None and user.is_notable is False
    assert user.display_name == "Alice E."  # reverted to allowlist initials
    # Curated links/sources are stripped — a pre-seed carries neither.
    assert db.scalar(select(func.count()).select_from(Source).where(Source.user_id == user.id)) == 0
    assert db.scalar(select(func.count()).select_from(ProfileLink).where(ProfileLink.user_id == user.id)) == 0


def test_prune_keeps_claimed_notable(db, tmp_path):
    """A notable later verified by a real person must survive being dropped from the roster."""
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))
    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    user.verified_at = utcnow()
    db.commit()

    stats = seed_notable_speakers(db, _roster(tmp_path, [{"name": "Bob", "email": "bob@x.co", "links": []}]))

    assert stats.notables_removed == 0
    assert db.scalar(select(User).where(User.email == "alice@example.com")) is not None


def test_prune_clears_subscriptions_to_pruned_feeder(db, tmp_path, make_user):
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))
    alice = db.scalar(select(User).where(User.email == "alice@example.com"))
    fan = make_user("fan@example.com")
    db.add(Subscription(subscriber_id=fan.id, feeder_id=alice.id))
    db.commit()

    seed_notable_speakers(db, _roster(tmp_path, [{"name": "Bob", "email": "bob@x.co", "links": []}]))

    assert db.scalar(select(User).where(User.email == "alice@example.com")) is None
    assert db.scalar(select(func.count()).select_from(Subscription)) == 0


def test_empty_roster_never_prunes(db, tmp_path):
    """A roster that parses to nothing must not wipe the existing notable directory."""
    seed_notable_speakers(db, _roster(tmp_path, [ALICE]))
    stats = seed_notable_speakers(db, _roster(tmp_path, []))

    assert stats.notables_removed == 0
    assert db.scalar(select(User).where(User.email == "alice@example.com")) is not None
