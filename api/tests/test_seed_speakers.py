"""Speaker seeding — focused on the `user-{id}` placeholder staying collision-safe.

A DB whose id-space was rebuilt/mirrored can carry a *stale* `user-N` handle on a row whose id
is not N (in prod: a real verified user at id 636 still holding `user-697`). As the seed inserts
new ghosts and their ids march through N, a naive `user-{id}` assignment hits a UNIQUE violation
on users.username and wedges the whole run. These tests pin the fallback that prevents that.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models import User, utcnow
from app.seed_speakers import seed_speakers


def _roster(tmp_path, rows):
    path = tmp_path / "speakers.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_new_ghost_gets_id_aligned_placeholder(db, tmp_path):
    """Happy path: with no drift, a created ghost's placeholder is the plain `user-{id}`."""
    seed_speakers(db, _roster(tmp_path, [{"name": "Fresh Speaker"}]))

    user = db.scalar(select(User).where(User.display_name == "Fresh Speaker"))
    assert user is not None
    assert user.username == f"user-{user.id}"


def test_stale_placeholder_does_not_wedge_seed(db, tmp_path):
    """A stale `user-N` handle sitting on the id the next ghost will take must not crash the
    seed: the new ghost falls back to a suffixed slug, and the stale row is left untouched."""
    # Decoy real user at id 1 squatting on `user-2` — the slug the next-inserted ghost wants.
    decoy = User(
        email="real@example.com",
        display_name="Real Person",
        username="user-2",
    )
    db.add(decoy)
    db.commit()
    assert decoy.id == 1

    seed_speakers(db, _roster(tmp_path, [{"name": "New Speaker"}]))

    ghost = db.scalar(select(User).where(User.display_name == "New Speaker"))
    assert ghost is not None
    assert ghost.id == 2  # would-be `user-2`, but that's taken…
    assert ghost.username == "user-2-2"  # …so it fell back to a suffixed slug

    # The squatter is untouched — same handle, no accidental rename.
    db.refresh(decoy)
    assert decoy.username == "user-2"


def test_emailless_entry_does_not_duplicate_real_user(db, tmp_path):
    """An email-less roster entry sharing a real emailed user's display_name (a missed name→email
    match) must be skipped, not created as a shadow ghost."""
    real = User(
        email="julieann.nepo@gmail.com",
        display_name="Julie Ann Nepomuceno",
        username="julieann-nepo",
        verified_at=utcnow(),  # a real signed-up account
    )
    db.add(real)
    db.commit()

    stats = seed_speakers(db, _roster(tmp_path, [{"name": "Julie Ann Nepomuceno"}]))

    # No duplicate: still exactly one row with that name — the real one.
    rows = db.scalars(
        select(User).where(User.display_name == "Julie Ann Nepomuceno")
    ).all()
    assert len(rows) == 1 and rows[0].id == real.id
    assert stats.created == 0
    assert stats.skipped_name_collision == 1
    assert any("shadows real user" in w for w in stats.warnings)


def test_emailless_entry_still_creates_when_no_real_collision(db, tmp_path):
    """The guard is narrow: with no same-named real user, an email-less entry is created normally."""
    stats = seed_speakers(db, _roster(tmp_path, [{"name": "Brand New Speaker"}]))

    assert stats.created == 1
    assert stats.skipped_name_collision == 0
    assert db.scalar(select(User).where(User.display_name == "Brand New Speaker")) is not None
