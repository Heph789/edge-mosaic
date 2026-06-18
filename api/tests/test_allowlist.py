"""Allowlist importer — the defensive parse + pre-seed rules."""

from __future__ import annotations

from sqlalchemy import select

from app.allowlist import abbreviate_name, import_allowlist
from app.models import AllowedEmail, User


def test_abbreviate_name_rules():
    assert abbreviate_name("Jane", "Smith") == "Jane S."
    assert abbreviate_name("Jane", None) == "Jane"
    assert abbreviate_name("Jane", "*") == "Jane"
    assert abbreviate_name("*", "Smith") is None  # no first name → no usable name
    assert abbreviate_name(None, None) is None
    assert abbreviate_name("Ana", "-García") == "Ana G."  # first alpha char as initial
    assert abbreviate_name(" Jane ", " smith ") == "Jane S."


ROSTER = """First Name,Last Name,Email,Telegram,Role,Organization,Residence,Age,Gender
Jane,Smith,Jane@Example.com,@jane,Builder,Acme,SF,30,F
*,Doe,bob@example.com,*,*,*,*,*,*
Carol,*,carol@example.com,*,*,*,*,*,*
*,*,*,*,*,*,*,*,*
Jane,Smith,jane@example.com,*,*,*,*,*,*
"""


def _write(tmp_path, text):
    p = tmp_path / "roster.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_import_seeds_named_only_and_skips_no_email(db, tmp_path):
    stats = import_allowlist(db, _write(tmp_path, ROSTER))

    # jane, bob, carol unique emails; the all-* row skipped; duplicate jane ignored.
    assert stats.imported == 3
    assert stats.skipped_no_email == 1
    assert stats.seeded == 2  # jane ("Jane S.") + carol ("Carol"); bob has no name

    emails = set(db.scalars(select(AllowedEmail.email)))
    assert emails == {"jane@example.com", "bob@example.com", "carol@example.com"}

    jane = db.scalar(select(AllowedEmail).where(AllowedEmail.email == "jane@example.com"))
    assert jane.name == "Jane S."  # email lowercased, surname reduced to initial
    bob = db.scalar(select(AllowedEmail).where(AllowedEmail.email == "bob@example.com"))
    assert bob.name is None

    users = {u.email: u for u in db.scalars(select(User))}
    assert set(users) == {"jane@example.com", "carol@example.com"}
    assert users["jane@example.com"].display_name == "Jane S."
    assert users["jane@example.com"].verified_at is None  # pre-seeded ghost
    assert users["jane@example.com"].onboarded is False
    assert "bob@example.com" not in users  # anonymized → gate row only, no user


def test_reimport_is_idempotent_and_non_clobbering(db, tmp_path):
    path = _write(tmp_path, ROSTER)
    import_allowlist(db, path)

    # User edits their display name; a re-import must not overwrite it.
    jane = db.scalar(select(User).where(User.email == "jane@example.com"))
    jane.display_name = "Jane the Great"
    jane.onboarded = True
    db.commit()

    stats = import_allowlist(db, path)
    assert stats.imported == 0
    assert stats.seeded == 0
    assert stats.already_present == 3

    db.refresh(jane)
    assert jane.display_name == "Jane the Great"  # never clobbered
    assert jane.onboarded is True
    assert db.scalar(select(User).where(User.email == "jane@example.com")) is not None
    # still exactly 3 allowlist rows, 2 users
    assert len(list(db.scalars(select(AllowedEmail)))) == 3
    assert len(list(db.scalars(select(User)))) == 2
