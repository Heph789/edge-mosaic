"""Digest cron job — due selection, send, skip-empty, idempotency, paused/unverified."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.jobs.digest import run_digest_job
from app.models import Item, SentDigest, Source, Subscription, utcnow

TODAY = date(2026, 6, 17)  # Wednesday → weekly anchor Monday 2026-06-15, window Jun 8–15


def _subscriber(make_user, email, **kw):
    return make_user(email, "Sub Scriber", verified_at=utcnow(), **kw)


def _feeder_with_item(db, make_user, email, when):
    feeder = make_user(email, "Feeder F.", verified_at=utcnow())
    src = Source(user_id=feeder.id, type="rss", input_url=f"https://{email}")
    db.add(src)
    db.commit()
    db.refresh(src)
    db.add(
        Item(
            source_id=src.id,
            external_id=f"{email}-1",
            kind="long",
            title="In-window post",
            url="https://x/1",
            published_at=when,
            scraped_at=utcnow(),
        )
    )
    db.commit()
    return feeder


def _subscribe(db, sub_id, feeder_id):
    db.add(Subscription(subscriber_id=sub_id, feeder_id=feeder_id))
    db.commit()


def test_sends_and_is_idempotent(db, make_user, sent_emails):
    sub = _subscriber(make_user, "s@example.com")
    feeder = _feeder_with_item(db, make_user, "f@example.com", datetime(2026, 6, 10, tzinfo=timezone.utc))
    _subscribe(db, sub.id, feeder.id)

    stats = run_digest_job(db, today=TODAY)
    assert stats["sent"] == 1
    assert len(sent_emails) == 1
    assert "digest" in sent_emails[0]["subject"].lower()
    assert "List-Unsubscribe" in sent_emails[0]["headers"]

    row = db.scalar(select(SentDigest))
    assert row.sent is True and row.item_count == 1
    assert row.anchor_date == date(2026, 6, 15)

    # Second run on the same day → already logged, no new email.
    stats2 = run_digest_job(db, today=TODAY)
    assert stats2 == {"sent": 0, "skipped_empty": 0, "already": 1, "errors": 0}
    assert len(sent_emails) == 1


def test_skip_empty_logs_but_sends_nothing(db, make_user, sent_emails):
    sub = _subscriber(make_user, "s@example.com")
    feeder = make_user("f@example.com", "Feeder F.", verified_at=utcnow())  # no items
    _subscribe(db, sub.id, feeder.id)

    stats = run_digest_job(db, today=TODAY)
    assert stats["skipped_empty"] == 1
    assert sent_emails == []
    row = db.scalar(select(SentDigest))
    assert row.sent is False and row.item_count == 0  # still logged → not re-attempted


def test_paused_and_unverified_are_skipped(db, make_user, sent_emails):
    paused = _subscriber(make_user, "p@example.com", digest_paused=True)
    unverified = make_user("u@example.com", "Unverified U.")  # verified_at is None
    feeder = _feeder_with_item(db, make_user, "f@example.com", datetime(2026, 6, 10, tzinfo=timezone.utc))
    _subscribe(db, paused.id, feeder.id)
    _subscribe(db, unverified.id, feeder.id)

    stats = run_digest_job(db, today=TODAY)
    assert sent_emails == []
    assert stats["sent"] == 0
    assert db.scalar(select(SentDigest)) is None


def test_out_of_window_items_excluded(db, make_user, sent_emails):
    sub = _subscriber(make_user, "s@example.com")
    # Item published before the window (Jun 8–15) → skip-empty.
    feeder = _feeder_with_item(db, make_user, "f@example.com", datetime(2026, 6, 1, tzinfo=timezone.utc))
    _subscribe(db, sub.id, feeder.id)

    stats = run_digest_job(db, today=TODAY)
    assert stats["skipped_empty"] == 1
    assert sent_emails == []
