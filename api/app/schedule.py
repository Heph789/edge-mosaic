"""Calendar-anchored digest scheduling (Slice 4 §5).

Global anchors: weekly → Monday, monthly → 1st-of-month. On (or after) an anchor, a
subscriber is due for the period that just *completed*: window = [previous_anchor, anchor).
Dedup/self-heal is handled by the caller via `sent_digests` keyed on (subscriber, anchor)
— a missed cron day simply leaves the anchor unlogged, so it fires next run.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def most_recent_anchor(frequency: str, today: date) -> date:
    """The latest anchor on-or-before `today`."""
    if frequency == "monthly":
        return today.replace(day=1)
    return today - timedelta(days=today.weekday())  # weekday()==0 is Monday


def previous_anchor(frequency: str, anchor: date) -> date:
    """The anchor one period before `anchor` (start of the window)."""
    if frequency == "monthly":
        if anchor.month == 1:
            return anchor.replace(year=anchor.year - 1, month=12, day=1)
        return anchor.replace(month=anchor.month - 1, day=1)
    return anchor - timedelta(days=7)


def window_for(frequency: str, anchor: date) -> tuple[datetime, datetime]:
    """[start, end) UTC datetimes for the just-completed period ending at `anchor`."""
    start = datetime.combine(previous_anchor(frequency, anchor), time.min, tzinfo=timezone.utc)
    end = datetime.combine(anchor, time.min, tzinfo=timezone.utc)
    return start, end
