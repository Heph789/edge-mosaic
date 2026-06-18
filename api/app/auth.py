"""Auth service — the magic-link + session state machine (§2).

All email sends funnel through `request_magic_link()`, the single choke point where a
per-email cooldown drops in at Slice 4 (when real sends cost money + reputation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from . import config
from .email import send_email
from .models import AllowedEmail, MagicLinkToken, Session, User, utcnow
from .security import hash_token, new_token


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_allowed(db: DbSession, email: str) -> bool:
    return (
        db.scalar(select(AllowedEmail.id).where(AllowedEmail.email == email))
        is not None
    )


def request_magic_link(db: DbSession, raw_email: str) -> None:
    """Gate-check, then mint + 'send' a single-use link. Silent no-op if not allowed.

    The caller always returns the same generic response either way (§2 login privacy).
    """
    email = normalize_email(raw_email)
    if not is_allowed(db, email):
        return  # never reveal allowlist membership; do no work

    now = utcnow()
    # One live link per email: invalidate any prior unused tokens.
    db.execute(
        update(MagicLinkToken)
        .where(MagicLinkToken.email == email, MagicLinkToken.used_at.is_(None))
        .values(used_at=now)
    )

    raw = new_token()
    db.add(
        MagicLinkToken(
            email=email,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(minutes=config.MAGIC_LINK_TTL_MINUTES),
        )
    )
    db.commit()

    link = f"{config.APP_BASE_URL}/auth/verify?token={raw}"
    mins = config.MAGIC_LINK_TTL_MINUTES
    text = (
        f"Click to log in (expires in {mins} min):\n{link}\n\n"
        f"[dev] exchange it directly:\n"
        f"  curl -s -X POST localhost:8000/auth/verify "
        f"-H 'content-type: application/json' -d '{{\"token\": \"{raw}\"}}'\n"
    )
    html = (
        f'<p>Click to log in (expires in {mins} min):</p>'
        f'<p><a href="{link}">Log in to Edge Mosaic</a></p>'
    )
    send_email(to=email, subject="Your Edge Mosaic login link", html=html, text=text)


@dataclass
class VerifyResult:
    user: User
    session_token: str


def verify_token(db: DbSession, raw_token: str) -> VerifyResult | None:
    """Atomically claim a magic-link token, get-or-create the user, mint a session.

    Returns None if the token is missing / expired / already used.
    """
    now = utcnow()
    token_hash = hash_token(raw_token)

    # Atomic single-use claim — no SELECT-then-UPDATE TOCTOU window.
    claimed = db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        return None

    tok = db.scalar(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash)
    )
    assert tok is not None  # just claimed it
    email = tok.email

    user = db.scalar(select(User).where(User.email == email))
    allowed = db.scalar(select(AllowedEmail).where(AllowedEmail.email == email))
    if user is None:
        # Lazy creation — born verified, display_name preseeded from the roster if any.
        user = User(
            email=email,
            display_name=allowed.name if allowed else None,
            verified_at=now,
        )
        db.add(user)
        db.flush()  # assign user.id
    elif user.verified_at is None:
        user.verified_at = now  # pre-seeded ghost logging in for the first time

    if allowed is not None and allowed.claimed_by_user_id is None:
        allowed.claimed_by_user_id = user.id

    session_token = _create_session(db, user, now)
    db.commit()
    return VerifyResult(user=user, session_token=session_token)


def _create_session(db: DbSession, user: User, now: datetime) -> str:
    raw = new_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(days=config.SESSION_TTL_DAYS),
        )
    )
    return raw


def user_for_session_token(db: DbSession, raw_token: str) -> User | None:
    """Resolve a bearer token → live user, or None (expired / unknown)."""
    row = db.scalar(
        select(Session).where(
            Session.token_hash == hash_token(raw_token),
            Session.expires_at > utcnow(),
        )
    )
    if row is None:
        return None
    return db.get(User, row.user_id)


def logout(db: DbSession, raw_token: str) -> None:
    """Delete the current session row — revocation, the point of opaque tokens."""
    db.execute(
        Session.__table__.delete().where(
            Session.token_hash == hash_token(raw_token)
        )
    )
    db.commit()
