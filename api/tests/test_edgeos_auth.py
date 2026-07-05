"""EdgeOS OTP login: /auth/start routing + /auth/edgeos/verify state machine.

The EdgeOS HTTP client (app.edgeos) is monkeypatched — these tests exercise our side of
the flow: routing legacy vs EdgeOS users, get-or-create/claim semantics, the attendance
snapshot sync, and the privacy posture (identical responses for unknown emails).
"""

from __future__ import annotations

from sqlalchemy import select

from app.edgeos import EdgeosUnavailableError
from app.models import AllowedEmail, EdgeosAttendance, User, utcnow

PROFILE = {
    "id": "5b45e2f8-0000-0000-0000-000000000001",
    "email": "jane@example.com",
    "first_name": "Jane",
    "last_name": "Smith",
}

STATS = {
    "total_days": 24,
    "popups": [
        {
            "popup_id": "aaaa0000-0000-0000-0000-000000000001",
            "popup_name": "Edge Esmeralda 2025",
            "start_date": "2025-05-24T00:00:00Z",
            "end_date": "2025-06-21T00:00:00Z",
            "location": "Healdsburg, CA",
            "image_url": None,
            "total_days": 24,
        },
        {
            "popup_id": "aaaa0000-0000-0000-0000-000000000002",
            "popup_name": "Edge City Lanna",
            "start_date": None,
            "end_date": None,
            "location": None,
            "image_url": None,
            "total_days": 0,
        },
    ],
}


def _mock_edgeos(
    monkeypatch,
    *,
    known=True,
    code="123456",
    profile=PROFILE,
    stats=STATS,
):
    """Wire app.edgeos to a fake EdgeOS that knows one human + one valid code."""
    calls = {"login": [], "authenticate": []}

    def request_login_code(email):
        calls["login"].append(email)
        return known

    def verify_login_code(email, submitted):
        calls["authenticate"].append((email, submitted))
        return "edgeos-jwt" if known and submitted == code else None

    monkeypatch.setattr("app.edgeos.request_login_code", request_login_code)
    monkeypatch.setattr("app.edgeos.verify_login_code", verify_login_code)
    monkeypatch.setattr("app.edgeos.fetch_profile", lambda token: profile)
    monkeypatch.setattr("app.edgeos.fetch_profile_stats", lambda token: stats)
    return calls


# --- /auth/start routing ----------------------------------------------------------------


def test_start_routes_legacy_email_user_to_magic_link(
    client, sent_emails, db, monkeypatch
):
    calls = _mock_edgeos(monkeypatch)
    db.add(AllowedEmail(email="old@example.com"))
    db.add(User(email="old@example.com", verified_at=utcnow()))
    db.commit()

    r = client.post("/auth/start", json={"email": "old@example.com"})
    assert r.status_code == 200
    assert r.json()["mode"] == "link"
    assert len(sent_emails) == 1  # magic link went out, EdgeOS untouched
    assert calls["login"] == []


def test_start_routes_new_email_to_edgeos_code(client, sent_emails, db, monkeypatch):
    calls = _mock_edgeos(monkeypatch)
    r = client.post("/auth/start", json={"email": "  Jane@Example.COM "})
    assert r.status_code == 200
    assert r.json()["mode"] == "code"
    assert calls["login"] == ["jane@example.com"]  # normalized
    assert sent_emails == []  # EdgeOS sends the code, not us


def test_start_response_identical_for_unknown_email(client, db, monkeypatch):
    """Privacy: an email EdgeOS doesn't know gets the same mode + message."""
    _mock_edgeos(monkeypatch, known=True)
    known = client.post("/auth/start", json={"email": "jane@example.com"}).json()
    _mock_edgeos(monkeypatch, known=False)
    unknown = client.post("/auth/start", json={"email": "stranger@example.com"}).json()
    assert known == unknown


def test_start_routes_edgeos_user_back_to_code(client, sent_emails, db, monkeypatch):
    """A user who first signed in via EdgeOS keeps the OTP flow, not the magic link."""
    calls = _mock_edgeos(monkeypatch)
    db.add(
        User(
            email="jane@example.com",
            verified_at=utcnow(),
            edgeos_human_id=PROFILE["id"],
        )
    )
    db.commit()

    r = client.post("/auth/start", json={"email": "jane@example.com"})
    assert r.json()["mode"] == "code"
    assert calls["login"] == ["jane@example.com"]
    assert sent_emails == []


def test_start_503_when_edgeos_unreachable(client, db, monkeypatch):
    def boom(email):
        raise EdgeosUnavailableError("down")

    monkeypatch.setattr("app.edgeos.request_login_code", boom)
    r = client.post("/auth/start", json={"email": "jane@example.com"})
    assert r.status_code == 503


# --- /auth/edgeos/verify ----------------------------------------------------------------


def test_verify_code_creates_user_with_profile_and_attendance(
    client, db, monkeypatch
):
    _mock_edgeos(monkeypatch)
    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["user"]["display_name"] == "Jane S."  # abbreviated, never full surname
    # Villages are derived from attendance — one per popup with total_days > 0, NOT the
    # blanket default. Lanna (0 days) is snapshotted below but grants no membership.
    assert payload["user"]["villages"] == ["Edge Esmeralda 2025"]
    assert payload["user"]["onboarded"] is False
    # Set-compare: NULL start_date sorts differently on SQLite vs Postgres.
    assert set(payload["user"]["edgeos_popups"]) == {
        "Edge Esmeralda 2025",
        "Edge City Lanna",
    }

    user = db.scalar(select(User).where(User.email == "jane@example.com"))
    assert user.verified_at is not None  # born verified
    assert user.edgeos_human_id == PROFILE["id"]
    assert user.username == f"user-{user.id}"

    rows = list(db.scalars(select(EdgeosAttendance)))
    assert {r.popup_name for r in rows} == {"Edge Esmeralda 2025", "Edge City Lanna"}
    ee = next(r for r in rows if r.popup_name == "Edge Esmeralda 2025")
    assert ee.total_days == 24 and ee.location == "Healdsburg, CA"
    assert ee.start_date is not None

    # The minted session is a working bearer token.
    auth_h = {"Authorization": f"Bearer {payload['session_token']}"}
    assert client.get("/me", headers=auth_h).status_code == 200


def test_verify_wrong_code_rejected_generically(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "999999"}
    )
    assert r.status_code == 400
    assert db.scalar(select(User)) is None  # no user materialized on failure


def test_verify_malformed_code_is_422(client):
    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "12ab56"}
    )
    assert r.status_code == 422


def test_verify_claims_preseeded_ghost(client, db, monkeypatch):
    """An allowlist-seeded ghost row is claimed (same row, now verified) — no duplicate."""
    _mock_edgeos(monkeypatch)
    db.add(AllowedEmail(email="jane@example.com", name="Jane S."))
    db.add(User(email="jane@example.com", display_name="Jane S."))
    db.commit()

    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
    )
    assert r.status_code == 200

    users = list(db.scalars(select(User)))
    assert len(users) == 1
    assert users[0].verified_at is not None
    assert users[0].edgeos_human_id == PROFILE["id"]
    allowed = db.scalar(select(AllowedEmail))
    assert allowed.claimed_by_user_id == users[0].id


def test_repeat_login_resyncs_attendance_without_duplicates(client, db, monkeypatch):
    _mock_edgeos(monkeypatch)
    assert (
        client.post(
            "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
        ).status_code
        == 200
    )

    shrunk = {"total_days": 24, "popups": [STATS["popups"][0]]}
    _mock_edgeos(monkeypatch, stats=shrunk)
    assert (
        client.post(
            "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
        ).status_code
        == 200
    )

    assert len(list(db.scalars(select(User)))) == 1
    rows = list(db.scalars(select(EdgeosAttendance)))
    assert [r.popup_name for r in rows] == ["Edge Esmeralda 2025"]  # replaced, not appended

    # Village memberships are additive-only and undated: no membership row is duplicated
    # by the resync.
    user = db.scalar(select(User))
    assert [uv.village.name for uv in user.villages] == ["Edge Esmeralda 2025"]


def test_verify_survives_enrichment_failure(client, db, monkeypatch):
    """Profile/stats fetches are best-effort — login must still succeed without them,
    falling back to the default village so the user isn't left village-less."""
    _mock_edgeos(monkeypatch, profile=None, stats=None)
    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
    )
    assert r.status_code == 200
    assert r.json()["user"]["display_name"] is None
    assert r.json()["user"]["edgeos_popups"] == []
    assert r.json()["user"]["villages"] == ["EE '26"]  # fallback, not attendance-derived
    user = db.scalar(select(User))
    assert user.verified_at is not None and user.edgeos_human_id is None


def test_aliased_popup_claims_preexisting_village(client, db, monkeypatch):
    """A popup listed in EDGEOS_POPUP_VILLAGE_SLUGS enrolls into the pre-existing local
    village (claiming it) instead of minting a duplicate."""
    from app.models import Village

    _mock_edgeos(monkeypatch)
    db.add(Village(name="EE '26", slug="ee-26"))
    db.commit()
    monkeypatch.setattr(
        "app.config.EDGEOS_POPUP_VILLAGE_SLUGS",
        {STATS["popups"][0]["popup_id"]: "ee-26"},
    )

    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
    )
    assert r.status_code == 200
    assert r.json()["user"]["villages"] == ["EE '26"]

    villages = list(db.scalars(select(Village)))
    assert len(villages) == 1  # no "Edge Esmeralda 2025" duplicate minted
    assert villages[0].edgeos_popup_id == STATS["popups"][0]["popup_id"]


def test_unrelated_name_collision_gets_suffixed_village(client, db, monkeypatch):
    """A local village that happens to share the popup's name is NOT hijacked — the
    popup's village is created with a popup-id suffix."""
    from app.models import Village

    _mock_edgeos(monkeypatch)
    db.add(Village(name="Edge Esmeralda 2025", slug="edge-esmeralda-2025"))
    db.commit()

    r = client.post(
        "/auth/edgeos/verify", json={"email": "jane@example.com", "code": "123456"}
    )
    assert r.status_code == 200

    local = db.scalar(select(Village).where(Village.slug == "edge-esmeralda-2025"))
    assert local.edgeos_popup_id is None  # untouched
    suffix = STATS["popups"][0]["popup_id"][:8]
    assert f"Edge Esmeralda 2025 ({suffix})" in r.json()["user"]["villages"]


def test_legacy_magic_link_flow_still_works_end_to_end(
    client, sent_emails, db, monkeypatch
):
    """Backwards compat: the pre-EdgeOS endpoints are untouched for existing users."""
    import re

    _mock_edgeos(monkeypatch)
    db.add(AllowedEmail(email="old@example.com"))
    db.add(User(email="old@example.com", verified_at=utcnow()))
    db.commit()

    assert (
        client.post("/auth/request-link", json={"email": "old@example.com"}).status_code
        == 200
    )
    token = re.search(r"token=([^\s&\"]+)", sent_emails[-1]["text"]).group(1)
    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "old@example.com"
