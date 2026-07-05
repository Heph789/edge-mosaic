"""Auth service — the magic-link + session state machine (§2).

All email sends funnel through `request_magic_link()`, the single choke point where a
per-email cooldown drops in at Slice 4 (when real sends cost money + reputation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from . import config, edgeos
from .models import (
    AllowedEmail,
    AuthThrottleEvent,
    EdgeosAttendance,
    MagicLinkToken,
    Session,
    User,
    utcnow,
)
from .security import hash_token, new_token
from .villages import (
    assign_default_village,
    assign_villages_from_attendance,
    village_ids_for,
)


class _EmailParams(TypedDict):
    to: str
    subject: str
    html: str
    text: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


class ThrottledError(Exception):
    """This email hit a per-window auth rate limit — respond 429, do no auth work."""


def _throttle_events(db: DbSession, email: str, kind: str) -> int:
    """Prune expired throttle rows, then count this email's live events of `kind`."""
    cutoff = utcnow() - timedelta(minutes=config.AUTH_THROTTLE_WINDOW_MINUTES)
    # Global prune (all emails) — keeps the table bounded to one window of activity.
    db.execute(
        AuthThrottleEvent.__table__.delete().where(
            AuthThrottleEvent.created_at < cutoff
        )
    )
    return db.scalar(
        select(func.count())
        .select_from(AuthThrottleEvent)
        .where(AuthThrottleEvent.email == email, AuthThrottleEvent.kind == kind)
    )


def throttle_start(db: DbSession, raw_email: str) -> None:
    """Gate + record one login-start (magic-link or EdgeOS-code request) for this email.

    Caps how fast a single address can trigger sends — our Resend emails or, worse,
    OTP emails relayed to arbitrary EdgeOS members through /auth/start.
    """
    email = normalize_email(raw_email)
    if _throttle_events(db, email, "start") >= config.AUTH_START_MAX_PER_WINDOW:
        db.commit()  # keep the prune
        raise ThrottledError(email)
    db.add(AuthThrottleEvent(email=email, kind="start"))
    db.commit()


def is_allowed(db: DbSession, email: str) -> bool:
    return (
        db.scalar(select(AllowedEmail.id).where(AllowedEmail.email == email))
        is not None
    )


def request_magic_link(db: DbSession, raw_email: str) -> _EmailParams | None:
    """Gate-check, then mint a single-use link. Returns email params for the caller to
    send asynchronously, or None if the address is not on the allowlist.

    The caller always returns the same generic response either way (§2 login privacy).
    Returning the params (rather than calling send_email inline) keeps the DB connection
    free before the Resend HTTP call happens.
    """
    email = normalize_email(raw_email)
    if not is_allowed(db, email):
        return None  # never reveal allowlist membership; do no work

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
    return _EmailParams(
        to=email,
        subject="Your Edge Mosaic login link",
        html=html,
        text=text,
    )


@dataclass
class StartLoginResult:
    mode: str  # 'link' (legacy magic link) | 'code' (EdgeOS 6-digit OTP)
    email_params: _EmailParams | None = None  # link mode only; None = not allowlisted


def start_login(db: DbSession, raw_email: str) -> StartLoginResult:
    """Route the unified login entry (§2).

    Legacy email accounts (verified before EdgeOS wiring, never EdgeOS-linked) keep the
    magic-link flow. Everyone else — new users included — goes through the EdgeOS OTP,
    whose existing-human check replaces the CSV allowlist as the eligibility gate.

    Raises EdgeosUnavailableError when EdgeOS can't be reached (retryable, not a verdict).
    """
    email = normalize_email(raw_email)
    user = db.scalar(select(User).where(User.email == email))
    legacy_email_user = (
        not config.EDGEOS_ONLY_LOGIN
        and user is not None
        and user.verified_at is not None
        and user.edgeos_human_id is None
    )
    if legacy_email_user:
        return StartLoginResult(mode="link", email_params=request_magic_link(db, email))
    # Result deliberately ignored: unknown-to-EdgeOS emails get the same generic "code on
    # its way" response as known ones (login privacy — no existence oracle).
    edgeos.request_login_code(email)
    return StartLoginResult(mode="code")


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
        db.flush()  # assign user.id (and the default temp username)
        user.username = f"user-{user.id}"  # placeholder; user picks a real one at onboarding
        assign_default_village(db, user)  # every new user joins the default village
    elif user.verified_at is None:
        user.verified_at = now  # pre-seeded ghost logging in for the first time

    if allowed is not None and allowed.claimed_by_user_id is None:
        allowed.claimed_by_user_id = user.id

    session_token = _create_session(db, user, now)
    db.commit()
    return VerifyResult(user=user, session_token=session_token)


def verify_edgeos_code(db: DbSession, raw_email: str, code: str) -> VerifyResult | None:
    """Exchange an EdgeOS OTP for a local session: verify with EdgeOS, get-or-create the
    user, snapshot their EdgeOS profile + popup attendance, mint a session.

    Returns None if EdgeOS rejects the code. Raises ThrottledError once this email has
    burned its failed-attempt budget (brute-force cap on the 6-digit space — EdgeOS's own
    lockout behavior is unknown, so don't rely on it). Raises EdgeosUnavailableError if
    EdgeOS is unreachable for the verification step itself (enrichment failures are
    swallowed — they must never block a successful login).
    """
    # Local import: allowlist.py imports normalize_email from this module.
    from .allowlist import abbreviate_name

    email = normalize_email(raw_email)
    if _throttle_events(db, email, "verify_fail") >= config.AUTH_VERIFY_MAX_FAILURES:
        db.commit()  # keep the prune
        raise ThrottledError(email)
    access_token = edgeos.verify_login_code(email, code)
    if access_token is None:
        db.add(AuthThrottleEvent(email=email, kind="verify_fail"))
        db.commit()
        return None

    now = utcnow()
    profile = edgeos.fetch_profile(access_token)
    stats = edgeos.fetch_profile_stats(access_token)
    edgeos_name = (
        abbreviate_name(profile.get("first_name"), profile.get("last_name"))
        if profile
        else None
    )

    user = db.scalar(select(User).where(User.email == email))
    allowed = db.scalar(select(AllowedEmail).where(AllowedEmail.email == email))
    if user is None:
        # Lazy creation, mirroring verify_token(): born verified, display_name preseeded
        # from the EdgeOS profile (falling back to the roster name if any).
        user = User(
            email=email,
            display_name=edgeos_name or (allowed.name if allowed else None),
            verified_at=now,
        )
        db.add(user)
        db.flush()  # assign user.id (and the default temp username)
        user.username = f"user-{user.id}"  # placeholder; user picks a real one at onboarding
    else:
        if user.verified_at is None:
            user.verified_at = now  # pre-seeded ghost logging in for the first time
        if user.display_name is None and edgeos_name is not None:
            user.display_name = edgeos_name

    if profile and profile.get("id"):
        user.edgeos_human_id = str(profile["id"])
    if allowed is not None and allowed.claimed_by_user_id is None:
        allowed.claimed_by_user_id = user.id

    # Villages are derived from attendance on this path (one per attended popup) — the
    # blanket default is only a fallback when stats couldn't be fetched, so a user isn't
    # left village-less (invisible to / blind to every visibility='village' profile).
    if stats is not None:
        _sync_attendance(db, user, stats, now)
        assign_villages_from_attendance(db, user, stats.get("popups", []))
    elif not village_ids_for(db, user.id):
        # Query, don't touch user.villages: expire_on_commit=False would serialize the
        # relationship's stale pre-enroll cache into the login response.
        assign_default_village(db, user)

    session_token = _create_session(db, user, now)
    db.commit()
    return VerifyResult(user=user, session_token=session_token)


def _parse_edgeos_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sync_attendance(db: DbSession, user: User, stats: dict, now: datetime) -> None:
    """Replace the user's attendance snapshot with EdgeOS's current profile stats."""
    db.execute(
        EdgeosAttendance.__table__.delete().where(
            EdgeosAttendance.user_id == user.id
        )
    )
    for popup in stats.get("popups", []):
        popup_id = popup.get("popup_id")
        if not popup_id:
            continue
        db.add(
            EdgeosAttendance(
                user_id=user.id,
                popup_id=str(popup_id),
                popup_name=popup.get("popup_name") or "",
                start_date=_parse_edgeos_dt(popup.get("start_date")),
                end_date=_parse_edgeos_dt(popup.get("end_date")),
                location=popup.get("location"),
                image_url=popup.get("image_url"),
                total_days=popup.get("total_days") or 0,
                synced_at=now,
            )
        )


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
