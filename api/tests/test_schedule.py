"""Calendar anchor + window math."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schedule import most_recent_anchor, previous_anchor, window_for


def test_weekly_anchor_is_most_recent_monday():
    # 2026-06-17 is a Wednesday → anchor is Monday 2026-06-15.
    assert most_recent_anchor("weekly", date(2026, 6, 17)) == date(2026, 6, 15)
    # On the Monday itself, the anchor is that day.
    assert most_recent_anchor("weekly", date(2026, 6, 15)) == date(2026, 6, 15)


def test_monthly_anchor_is_first_of_month():
    assert most_recent_anchor("monthly", date(2026, 6, 17)) == date(2026, 6, 1)


def test_previous_anchor_handles_year_boundary():
    assert previous_anchor("weekly", date(2026, 6, 15)) == date(2026, 6, 8)
    assert previous_anchor("monthly", date(2026, 1, 1)) == date(2025, 12, 1)


def test_window_for_is_completed_period():
    start, end = window_for("weekly", date(2026, 6, 15))
    assert start == datetime(2026, 6, 8, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 15, tzinfo=timezone.utc)
