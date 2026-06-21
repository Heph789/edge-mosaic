"""Profile artifacts: PATCH /me extras, image upload/delete, village auto-assign,
visibility-gated discover + public profile."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app import config, storage
from app.models import User, UserVillage
from app.villages import assign_default_village


@pytest.fixture(autouse=True)
def isolated_media(tmp_path, monkeypatch):
    """Redirect image storage to a throwaway dir so tests never touch api/data/media."""
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(config, "MEDIA_DIR", media)
    monkeypatch.setattr(storage.config, "MEDIA_DIR", media)
    yield

# A 1x1 transparent PNG (smallest valid file the upload path will accept).
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f600000000049454e44ae426082"
)


def _png_file(name="a.png"):
    return {"file": (name, io.BytesIO(PNG_1PX), "image/png")}


def test_patch_me_profile_fields(client, make_user, auth):
    user = make_user("a@example.com", display_name="A")
    h = auth(user)

    r = client.patch(
        "/me",
        json={
            "bio": "  hi there  ",
            "contact_email": "pub@example.com",
            "contact_phone": "555-1234",
            "cities": ["Austin", " ", "Lisbon"],  # blank dropped
            "links": [
                {"label": "Site", "url": "https://ex.com"},
                {"label": " ", "url": " "},  # blank dropped
            ],
            "visibility": "village",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bio"] == "hi there"  # trimmed
    assert body["contact_email"] == "pub@example.com"
    assert body["cities"] == ["Austin", "Lisbon"]
    assert body["links"] == [{"label": "Site", "url": "https://ex.com"}]
    assert body["visibility"] == "village"


def test_patch_me_replace_all_and_clear(client, make_user, auth):
    user = make_user("b@example.com", display_name="B")
    h = auth(user)
    client.patch("/me", json={"cities": ["X", "Y"], "bio": "first"}, headers=h)

    # Replace-all: a new list overwrites; empty list clears; "" clears free text.
    r = client.patch("/me", json={"cities": ["Z"], "bio": ""}, headers=h)
    assert r.json()["cities"] == ["Z"]
    assert r.json()["bio"] is None
    r = client.patch("/me", json={"cities": []}, headers=h)
    assert r.json()["cities"] == []


def test_patch_me_rejects_bad_visibility(client, make_user, auth):
    user = make_user("c@example.com", display_name="C")
    r = client.patch("/me", json={"visibility": "secret"}, headers=auth(user))
    assert r.status_code == 422


def test_image_upload_replace_and_delete(client, make_user, auth):
    user = make_user("d@example.com", display_name="D")
    h = auth(user)

    r = client.post("/me/images/profile", files=_png_file(), headers=h)
    assert r.status_code == 200, r.text
    url1 = r.json()["profile_image_url"]
    assert url1 and url1.endswith(".png")

    # Replacing yields a different key (old file is cleaned up).
    r = client.post("/me/images/profile", files=_png_file("b.png"), headers=h)
    assert r.json()["profile_image_url"] != url1

    r = client.delete("/me/images/profile", headers=h)
    assert r.status_code == 200
    assert r.json()["profile_image_url"] is None


def test_image_upload_rejects_bad_type_and_kind(client, make_user, auth):
    user = make_user("e@example.com", display_name="E")
    h = auth(user)
    r = client.post(
        "/me/images/profile",
        files={"file": ("x.txt", io.BytesIO(b"nope"), "text/plain")},
        headers=h,
    )
    assert r.status_code == 422
    r = client.post("/me/images/banner", files=_png_file(), headers=h)
    assert r.status_code == 404


def test_verify_assigns_default_village(client, db, sent_emails):
    import re

    from app.models import AllowedEmail

    db.add(AllowedEmail(email="newbie@example.com", name="New B."))
    db.commit()
    client.post("/auth/request-link", json={"email": "newbie@example.com"})
    token = re.search(r"token=([^\s&\"]+)", sent_emails[-1]["text"]).group(1)

    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    # The freshly-created user is enrolled in the default village, surfaced on /me.
    assert r.json()["user"]["villages"] == ["EE '26"]

    user = db.scalar(select(User).where(User.email == "newbie@example.com"))
    members = db.scalars(
        select(UserVillage).where(UserVillage.user_id == user.id)
    ).all()
    assert len(members) == 1


def test_assign_default_village_is_idempotent(db, make_user):
    user = make_user("f@example.com", display_name="F")
    assign_default_village(db, user)
    assign_default_village(db, user)
    db.commit()
    count = len(
        db.scalars(select(UserVillage).where(UserVillage.user_id == user.id)).all()
    )
    assert count == 1


def test_discover_hides_village_only_strangers(client, make_user, auth):
    me = make_user("me@example.com", display_name="Me")
    village_only = make_user(
        "v@example.com", display_name="Villager", visibility="village"
    )
    community = make_user("o@example.com", display_name="Opener", visibility="community")
    h = auth(me)

    names = {row["display_name"] for row in client.get("/discover", headers=h).json()}
    # No shared village → the village-only profile is hidden; community is visible.
    assert "Opener" in names
    assert "Villager" not in names


def test_discover_shows_shared_village_member(client, db, make_user, auth):
    me = make_user("me2@example.com", display_name="Me2")
    villager = make_user("v2@example.com", display_name="V2", visibility="village")
    assign_default_village(db, me)
    assign_default_village(db, villager)
    db.commit()

    names = {row["display_name"] for row in client.get("/discover", headers=auth(me)).json()}
    assert "V2" in names


def test_public_profile_gating(client, db, make_user, auth):
    me = make_user("me3@example.com", display_name="Me3")
    hidden = make_user("h@example.com", display_name="Hidden", visibility="village")
    shown = make_user("s@example.com", display_name="Shown", visibility="community")
    h = auth(me)

    assert client.get(f"/users/{shown.id}", headers=h).status_code == 200
    # village-only stranger → 404 (don't reveal existence)
    assert client.get(f"/users/{hidden.id}", headers=h).status_code == 404

    # Share a village → now visible, and phone stays private.
    hidden.contact_phone = "555"
    assign_default_village(db, me)
    assign_default_village(db, hidden)
    db.commit()
    r = client.get(f"/users/{hidden.id}", headers=h)
    assert r.status_code == 200
    assert "contact_phone" not in r.json()
