"""CSV allowlist import (§2 / slice-2-auth.md).

Defensive parse of a roster we don't own. Fixed headers:
  First Name, Last Name, Email, Telegram, Role, Organization, Residence, Age, Gender
Any cell may be `*` (anonymity marker) — treated as absent.

Behaviour:
  - read only First Name / Last Name / Email (ignore the rest)
  - `*` or blank → None everywhere
  - no email → skip the row (email is identity + the gate), count it
  - name → "Jane S." (full surname never persisted); first-only → "Jane"; no first → None
  - auto pre-seed a users row for every *named* entry; anonymized → gate row only
  - idempotent: insert-missing (no ON CONFLICT), never delete, never clobber claims/names
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .auth import normalize_email
from .models import AllowedEmail, User


def _clean(value: str | None) -> str | None:
    """Trim; treat '' and the '*' anonymity marker as absent."""
    if value is None:
        return None
    v = value.strip()
    return None if v in ("", "*") else v


def abbreviate_name(first: str | None, last: str | None) -> str | None:
    """('Jane','Smith') -> 'Jane S.'  ('Jane',None) -> 'Jane'  (None,*) -> None."""
    first = _clean(first)
    last = _clean(last)
    if first is None:
        return None  # a lone surname isn't a usable display name (and we won't leak it)
    if last is None:
        return first
    initial = next((c for c in last if c.isalpha()), None)
    return f"{first} {initial.upper()}." if initial else first


@dataclass
class ImportStats:
    imported: int = 0  # new allowed_emails rows
    seeded: int = 0  # new pre-seeded users
    skipped_no_email: int = 0
    already_present: int = 0


def import_allowlist(db: DbSession, csv_path: Path) -> ImportStats:
    stats = ImportStats()
    seen_in_file: set[str] = set()

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            raw_email = _clean(row.get("Email"))
            if raw_email is None:
                stats.skipped_no_email += 1
                continue
            email = normalize_email(raw_email)
            if email in seen_in_file:
                continue  # first-wins within the file
            seen_in_file.add(email)

            name = abbreviate_name(row.get("First Name"), row.get("Last Name"))

            allowed = db.scalar(
                select(AllowedEmail).where(AllowedEmail.email == email)
            )
            if allowed is None:
                db.add(AllowedEmail(email=email, name=name))
                stats.imported += 1
            else:
                stats.already_present += 1
                # Backfill a name only if still missing; never clobber existing data.
                if allowed.name is None and name is not None:
                    allowed.name = name

            # Auto pre-seed a user for named entries (get-or-create, never clobber).
            if name is not None:
                user = db.scalar(select(User).where(User.email == email))
                if user is None:
                    db.add(User(email=email, display_name=name))
                    stats.seeded += 1

    db.commit()
    return stats
