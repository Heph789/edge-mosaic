"""End-to-end auth state machine: request → verify → me → logout, plus edge cases."""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select

from app.models import AllowedEmail, MagicLinkToken, User, utcnow


def _allow(db, email, name=None, preseed=False):
    db.add(AllowedEmail(email=email, name=name))
    if preseed:
        db.add(User(email=email, display_name=name))
    db.commit()


def _token_from(text: str) -> str:
    m = re.search(r"token=([^\s&\"]+)", text)
    assert m, f"no token in email body:\n{text}"
    return m.group(1)


def _request_and_get_token(client, sent_emails, email) -> str:
    r = client.post("/auth/request-link", json={"email": email})
    assert r.status_code == 200
    assert "eligible" in r.json()["message"].lower()
    return _token_from(sent_emails[-1]["text"])


def test_request_link_privacy_no_enumeration(client, sent_emails, db):
    _allow(db, "yes@example.com")
    # Non-allowlisted email: identical response, but no email + no token.
    r = client.post("/auth/request-link", json={"email": "stranger@example.com"})
    assert r.status_code == 200
    assert "eligible" in r.json()["message"].lower()
    assert sent_emails == []
    assert db.scalar(select(MagicLinkToken)) is None


def test_full_flow_preseeded_user(client, sent_emails, db):
    _allow(db, "jane@example.com", name="Jane S.", preseed=True)
    token = _request_and_get_token(client, sent_emails, "jane@example.com")

    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    payload = r.json()
    session_token = payload["session_token"]
    assert payload["user"]["email"] == "jane@example.com"
    assert payload["user"]["display_name"] == "Jane S."
    assert payload["user"]["onboarded"] is False

    # The pre-seeded ghost is now verified, same row (claimed).
    user = db.scalar(select(User).where(User.email == "jane@example.com"))
    assert user.verified_at is not None
    allowed = db.scalar(select(AllowedEmail).where(AllowedEmail.email == "jane@example.com"))
    assert allowed.claimed_by_user_id == user.id

    auth_h = {"Authorization": f"Bearer {session_token}"}
    me = client.get("/me", headers=auth_h)
    assert me.status_code == 200 and me.json()["email"] == "jane@example.com"

    # Onboard: set display name → onboarded flips true.
    patched = client.patch("/me", json={"display_name": "Jane Smith"}, headers=auth_h)
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Jane Smith"
    assert patched.json()["onboarded"] is True

    # Logout revokes the session.
    assert client.post("/auth/logout", headers=auth_h).status_code == 200
    assert client.get("/me", headers=auth_h).status_code == 401


def test_lazy_user_creation_for_anonymized_email(client, sent_emails, db):
    _allow(db, "ghost@example.com", name=None, preseed=False)  # gate row only, no user
    assert db.scalar(select(User).where(User.email == "ghost@example.com")) is None

    token = _request_and_get_token(client, sent_emails, "ghost@example.com")
    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["user"]["display_name"] is None  # nothing to preseed

    user = db.scalar(select(User).where(User.email == "ghost@example.com"))
    assert user is not None and user.verified_at is not None  # born verified


def test_token_is_single_use(client, sent_emails, db):
    _allow(db, "jane@example.com")
    token = _request_and_get_token(client, sent_emails, "jane@example.com")
    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/auth/verify", json={"token": token}).status_code == 400


def test_expired_token_rejected(client, sent_emails, db):
    _allow(db, "jane@example.com")
    token = _request_and_get_token(client, sent_emails, "jane@example.com")
    # Force the token into the past.
    tok = db.scalar(select(MagicLinkToken))
    tok.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.post("/auth/verify", json={"token": token}).status_code == 400


def test_new_request_invalidates_prior_token(client, sent_emails, db):
    _allow(db, "jane@example.com")
    first = _request_and_get_token(client, sent_emails, "jane@example.com")
    second = _request_and_get_token(client, sent_emails, "jane@example.com")
    assert first != second
    assert client.post("/auth/verify", json={"token": first}).status_code == 400
    assert client.post("/auth/verify", json={"token": second}).status_code == 200


def test_me_requires_auth(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_email_is_normalized_on_request(client, sent_emails, db):
    _allow(db, "jane@example.com", name="Jane S.", preseed=True)
    # Mixed-case + whitespace must still resolve to the same allowlisted identity.
    token = _request_and_get_token(client, sent_emails, "  Jane@Example.COM ")
    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    assert len(list(db.scalars(select(User)))) == 1  # no duplicate user created
