"""Daily digest job (Railway cron: digest).

For each due subscriber, assemble the calendar-anchored window, send (or skip-empty), and
record a `sent_digests` row. The UNIQUE(subscriber_id, anchor_date) makes the run
idempotent and lets a missed day self-heal. A near-no-op off anchor days.

Ordering note: we assemble → send → log+commit. A crash between send and commit can
duplicate (accepted per §5 / the design decision); we never log a `sent` row for a send
that raised, so failures retry next run rather than silently drop.
"""

from __future__ import annotations

import logging
from datetime import date

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from ..digest import assemble_digest
from ..email import send_email
from ..models import SentDigest, Subscription, User, utcnow
from ..observability import init_sentry
from ..render import render_digest_html
from ..schedule import most_recent_anchor, window_for

log = logging.getLogger("edge_mosaic.digest")


def _unsub_url(token: str, base: str) -> str:
    return f"{base}/unsubscribe?token={token}"


def _list_unsubscribe_headers(user: User) -> dict[str, str]:
    # RFC 8058: the https URI is the one-click POST target (token in the query string).
    return {
        "List-Unsubscribe": f"<{_unsub_url(user.unsubscribe_token, config.API_BASE_URL)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def due_subscribers(db: Session) -> list[User]:
    """Verified, non-paused users with at least one subscription."""
    return list(
        db.scalars(
            select(User)
            .join(Subscription, Subscription.subscriber_id == User.id)
            .where(User.verified_at.is_not(None), User.digest_paused.is_(False))
            .distinct()
        )
    )


def send_one(db: Session, user: User, anchor: date) -> bool | None:
    """Send (or skip-empty) one subscriber's digest for `anchor`.

    Returns True if an email was sent, False if skipped-empty, None if already logged.
    """
    already = db.scalar(
        select(SentDigest).where(
            SentDigest.subscriber_id == user.id, SentDigest.anchor_date == anchor
        )
    )
    if already is not None:
        return None

    start, end = window_for(user.digest_frequency, anchor)
    data = assemble_digest(db, user, window_start=start, now=end)
    has_content = bool(data.feeders)

    if has_content:
        html = render_digest_html(
            data, _unsub_url(user.unsubscribe_token, config.APP_BASE_URL)
        )
        send_email(
            to=user.email,
            subject="Your Edge Mosaic digest",
            html=html,
            headers=_list_unsubscribe_headers(user),
        )

    item_count = sum(
        len(s.longs) + len(s.shorts) for f in data.feeders for s in f.sources
    )
    db.add(
        SentDigest(
            subscriber_id=user.id,
            anchor_date=anchor,
            window_start=start,
            window_end=end,
            item_count=item_count,
            sent=has_content,
        )
    )
    if has_content:
        user.last_digest_sent_at = utcnow()
    user.last_covered_through = end
    db.commit()
    return has_content


def send_welcome_sample(db: Session, user: User) -> None:
    """One-off sample on first subscribe (§5) — also a deliverability canary. Best-effort;
    sends even when empty (the canary still validates delivery). Does NOT touch cadence."""
    data = assemble_digest(db, user)  # trailing preview window
    html = render_digest_html(
        data, _unsub_url(user.unsubscribe_token, config.APP_BASE_URL)
    )
    sample_note = (
        "<p><em>This is a one-off sample so you can see what your digests will look "
        "like. It doesn't change your weekly/monthly schedule.</em></p>"
    )
    send_email(
        to=user.email,
        subject="Welcome to Edge Mosaic — a sample digest",
        html=sample_note + html,
        headers=_list_unsubscribe_headers(user),
    )


def run_digest_job(db: Session, today: date | None = None) -> dict[str, int]:
    today = today or utcnow().date()
    stats = {"sent": 0, "skipped_empty": 0, "already": 0, "errors": 0}
    for user in due_subscribers(db):
        anchor = most_recent_anchor(user.digest_frequency, today)
        try:
            result = send_one(db, user, anchor)
        except Exception as exc:  # isolate: one bad send can't kill the run
            db.rollback()
            stats["errors"] += 1
            log.error("digest send failed for user %s: %s", user.id, exc)
            # Surface the swallowed failure — a subscriber silently not getting their
            # digest is exactly the thing we want an alert on.
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("job", "digest")
                scope.set_context(
                    "subscriber", {"id": user.id, "anchor_date": str(anchor)}
                )
                sentry_sdk.capture_exception(exc)
            continue
        if result is True:
            stats["sent"] += 1
        elif result is False:
            stats["skipped_empty"] += 1
        else:
            stats["already"] += 1
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_sentry("digest")
    with SessionLocal() as db:
        stats = run_digest_job(db)
    print(f"digest job: {stats}")
    # Cron process exits immediately; flush the background transport so captured per-user
    # failures aren't dropped.
    sentry_sdk.flush()


if __name__ == "__main__":
    main()
