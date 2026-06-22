"""Username rules — the single source of truth shared by the PATCH /me validator, the
availability check, and the by-username profile lookup.

A username is the handle in the public profile URL (/p/{username}). Stored lowercased, so
case-insensitive uniqueness falls out of normalizing on input. The 'user-{id}' placeholder
assigned at account creation deliberately matches this pattern.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import config
from .models import User

# 3–30 chars, must start with a letter/digit, then letters/digits/'_'/'-'.
USERNAME_RE = re.compile(
    rf"^[a-z0-9][a-z0-9_-]{{{config.USERNAME_MIN_CHARS - 1},{config.USERNAME_MAX_CHARS - 1}}}$"
)


def normalize(raw: str) -> str:
    """Trim + lowercase — the canonical form stored and compared against."""
    return raw.strip().lower()


def is_valid(username: str) -> bool:
    """Format check on an already-normalized value."""
    return USERNAME_RE.match(username) is not None


def is_available(db: DbSession, username: str, *, exclude_id: int | None = None) -> bool:
    """True if no other user holds this (normalized) username."""
    stmt = select(User.id).where(User.username == username)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) is None
