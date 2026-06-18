"""Token generation + hashing.

Tokens are 256-bit `secrets.token_urlsafe(32)` random strings, so a fast `sha256` digest
is the correct storage form — bcrypt/argon2 exist to slow brute-forcing of *low-entropy*
passwords, of which there are none here. The raw token lives only in the URL / Bearer
header; the DB stores `sha256(token)`.
"""

from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    """A fresh URL-safe random token (raw — return to the caller, never store)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Stable hash for DB storage + lookup. Same input → same hash (not salted)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
