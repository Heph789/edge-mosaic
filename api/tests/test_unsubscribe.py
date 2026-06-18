"""Public one-click unsubscribe."""

from __future__ import annotations


def test_unsubscribe_pauses_digests(client, db, make_user):
    user = make_user("u@example.com", "User U.")
    token = user.unsubscribe_token
    assert user.digest_paused is False

    r = client.post(f"/unsubscribe?token={token}")
    assert r.status_code == 200
    db.refresh(user)
    assert user.digest_paused is True


def test_unsubscribe_bad_token_is_generic_200(client, db, make_user):
    user = make_user("u@example.com", "User U.")
    r = client.post("/unsubscribe?token=not-a-real-token")
    assert r.status_code == 200  # generic — doesn't reveal token validity
    db.refresh(user)
    assert user.digest_paused is False  # untouched


def test_unsubscribe_is_idempotent(client, db, make_user):
    user = make_user("u@example.com", "User U.", digest_paused=True)
    r = client.post(f"/unsubscribe?token={user.unsubscribe_token}")
    assert r.status_code == 200
    db.refresh(user)
    assert user.digest_paused is True
