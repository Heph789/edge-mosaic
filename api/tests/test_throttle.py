"""Per-email login throttling: start-request caps and OTP brute-force caps.

DB-backed (auth_throttle_events) so limits hold across workers/restarts. Both the new
/auth/start entry and the legacy /auth/request-link draw from the same 'start' budget.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from app import config
from app.models import AuthThrottleEvent, User, utcnow

EMAIL = "jane@example.com"


def _mock_edgeos(monkeypatch, code="123456"):
    monkeypatch.setattr("app.edgeos.request_login_code", lambda email: True)
    monkeypatch.setattr(
        "app.edgeos.verify_login_code",
        lambda email, submitted: "edgeos-jwt" if submitted == code else None,
    )
    monkeypatch.setattr("app.edgeos.fetch_profile", lambda token: None)
    monkeypatch.setattr("app.edgeos.fetch_profile_stats", lambda token: None)


def _backdate_events(db, minutes):
    db.execute(
        update(AuthThrottleEvent).values(
            created_at=utcnow() - timedelta(minutes=minutes)
        )
    )
    db.commit()


def test_start_throttled_after_cap_then_window_reopens(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    for _ in range(config.AUTH_START_MAX_PER_WINDOW):
        assert client.post("/auth/start", json={"email": EMAIL}).status_code == 200

    r = client.post("/auth/start", json={"email": EMAIL})
    assert r.status_code == 429
    # Another address is unaffected — the budget is per email.
    assert client.post("/auth/start", json={"email": "other@example.com"}).status_code == 200

    # Once the window passes (rows pruned), the same email may start again.
    _backdate_events(db, config.AUTH_THROTTLE_WINDOW_MINUTES + 1)
    assert client.post("/auth/start", json={"email": EMAIL}).status_code == 200


def test_legacy_request_link_shares_the_start_budget(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    for _ in range(config.AUTH_START_MAX_PER_WINDOW):
        assert client.post("/auth/start", json={"email": EMAIL}).status_code == 200
    assert client.post("/auth/request-link", json={"email": EMAIL}).status_code == 429


def test_verify_failures_throttled_even_for_the_right_code(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    for _ in range(config.AUTH_VERIFY_MAX_FAILURES):
        r = client.post("/auth/edgeos/verify", json={"email": EMAIL, "code": "999999"})
        assert r.status_code == 400

    # Budget burned: even the correct code is refused until the window passes.
    r = client.post("/auth/edgeos/verify", json={"email": EMAIL, "code": "123456"})
    assert r.status_code == 429
    assert db.scalar(select(User)) is None

    _backdate_events(db, config.AUTH_THROTTLE_WINDOW_MINUTES + 1)
    r = client.post("/auth/edgeos/verify", json={"email": EMAIL, "code": "123456"})
    assert r.status_code == 200


def test_start_and_verify_budgets_are_independent(client, db, monkeypatch):
    """Burning the start budget must not block verifying a code already sent."""
    _mock_edgeos(monkeypatch)
    for _ in range(config.AUTH_START_MAX_PER_WINDOW + 1):
        client.post("/auth/start", json={"email": EMAIL})

    r = client.post("/auth/edgeos/verify", json={"email": EMAIL, "code": "123456"})
    assert r.status_code == 200


def test_successful_verify_does_not_consume_failure_budget(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    assert (
        client.post("/auth/edgeos/verify", json={"email": EMAIL, "code": "123456"}).status_code
        == 200
    )
    assert (
        db.scalar(
            select(AuthThrottleEvent).where(AuthThrottleEvent.kind == "verify_fail")
        )
        is None
    )
