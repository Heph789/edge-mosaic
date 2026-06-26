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
    """Redirect image storage to a throwaway dir so tests never touch api/data/media.

    Also force the local-filesystem backend by clearing MEDIA_S3_BUCKET, so a developer's
    local .env (which may point at a real R2 bucket) can't leak into the test run. The one
    S3-backend test opts back in by setting MEDIA_S3_BUCKET itself.
    """
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(config, "MEDIA_DIR", media)
    monkeypatch.setattr(storage.config, "MEDIA_DIR", media)
    monkeypatch.setattr(config, "MEDIA_S3_BUCKET", "")
    yield

# A 1x1 transparent PNG (smallest valid file the upload path will accept).
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360606060000000050001a5f645400000000049454e44"
    "ae426082"
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
    assert url1 and url1.endswith(".webp")

    # Replacing yields a different key (old file is cleaned up).
    r = client.post("/me/images/profile", files=_png_file("b.png"), headers=h)
    assert r.json()["profile_image_url"] != url1

    r = client.delete("/me/images/profile", headers=h)
    assert r.status_code == 200
    assert r.json()["profile_image_url"] is None


def test_image_upload_s3_backend(client, make_user, auth, monkeypatch):
    """When MEDIA_S3_BUCKET is set, uploads put objects into a private bucket and URLs are
    presigned (the prod path). A fake boto3 client stands in for R2/S3."""
    puts: list[dict] = []
    deletes: list[dict] = []
    signed: list[dict] = []

    class FakeS3:
        def put_object(self, **kw):
            puts.append(kw)

        def delete_object(self, **kw):
            deletes.append(kw)

        def generate_presigned_url(self, op, Params, ExpiresIn):
            signed.append({"op": op, "Params": Params, "ExpiresIn": ExpiresIn})
            return f"https://r2.example.com/{Params['Key']}?X-Amz-Signature=deadbeef"

    monkeypatch.setattr(config, "MEDIA_S3_BUCKET", "test-bucket")
    monkeypatch.setattr(config, "MEDIA_URL_TTL_SECONDS", 1800)
    monkeypatch.setattr(storage, "_s3_client", FakeS3())  # skip real boto3 client build

    user = make_user("s3@example.com", display_name="S")
    h = auth(user)

    r = client.post("/me/images/profile", files=_png_file(), headers=h)
    assert r.status_code == 200, r.text
    url = r.json()["profile_image_url"]
    # URL is a presigned GET (private bucket), not a static public URL.
    assert "X-Amz-Signature=" in url
    assert len(puts) == 1
    assert puts[0]["Bucket"] == "test-bucket"
    assert puts[0]["ContentType"] == "image/webp"
    # Body is re-encoded WebP; verify it round-trips as a valid image.
    from PIL import Image
    img = Image.open(io.BytesIO(puts[0]["Body"]))
    assert img.size == (1, 1)
    # The signed key matches what was stored, and the configured TTL is honored.
    assert signed[-1]["op"] == "get_object"
    assert signed[-1]["Params"]["Bucket"] == "test-bucket"
    assert signed[-1]["ExpiresIn"] == 1800

    # Replacing deletes the old object.
    r = client.post("/me/images/profile", files=_png_file("b.png"), headers=h)
    assert r.status_code == 200
    assert len(deletes) == 1
    assert deletes[0]["Bucket"] == "test-bucket"


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


def test_verify_assigns_placeholder_username(client, db, sent_emails):
    import re

    from app.models import AllowedEmail

    db.add(AllowedEmail(email="handle@example.com", name="Han D."))
    db.commit()
    client.post("/auth/request-link", json={"email": "handle@example.com"})
    token = re.search(r"token=([^\s&\"]+)", sent_emails[-1]["text"]).group(1)

    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    user = db.scalar(select(User).where(User.email == "handle@example.com"))
    # Born with the canonical 'user-{id}' placeholder, surfaced on the user payload.
    assert r.json()["user"]["username"] == f"user-{user.id}"


def test_patch_me_sets_and_normalizes_username(client, make_user, auth):
    user = make_user("u1@example.com", display_name="U1")
    r = client.patch("/me", json={"username": "  CoolHandle  "}, headers=auth(user))
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "coolhandle"  # trimmed + lowercased


def test_patch_me_rejects_taken_username(client, make_user, auth):
    make_user("taken@example.com", display_name="T", username="taken")
    me = make_user("u2@example.com", display_name="U2")
    r = client.patch("/me", json={"username": "Taken"}, headers=auth(me))
    assert r.status_code == 409


def test_patch_me_rejects_invalid_username(client, make_user, auth):
    me = make_user("u3@example.com", display_name="U3")
    # Too short / bad chars / leading hyphen all fail the format rules.
    for bad in ["ab", "has space", "-leads", "way" * 20]:
        r = client.patch("/me", json={"username": bad}, headers=auth(me))
        assert r.status_code == 422, f"{bad!r} -> {r.status_code}"


def test_username_availability(client, make_user, auth):
    make_user("owner@example.com", display_name="Owner", username="owner")
    me = make_user("u4@example.com", display_name="U4", username="myhandle")
    h = auth(me)

    assert client.get("/usernames/owner/available", headers=h).json() == {
        "valid": True,
        "available": False,
    }
    assert client.get("/usernames/freeone/available", headers=h).json() == {
        "valid": True,
        "available": True,
    }
    # The caller's own handle reads as available (re-saving it isn't a conflict).
    assert client.get("/usernames/myhandle/available", headers=h).json()["available"] is True
    # Malformed → not valid (and therefore not available).
    assert client.get("/usernames/ab/available", headers=h).json() == {
        "valid": False,
        "available": False,
    }


def test_public_profile_by_username(client, db, make_user, auth):
    me = make_user("viewer@example.com", display_name="Viewer", username="viewer")
    shown = make_user(
        "shown2@example.com", display_name="Shown", username="shown", visibility="community"
    )
    hidden = make_user(
        "hidden2@example.com", display_name="Hidden", username="hidden", visibility="village"
    )
    h = auth(me)

    r = client.get("/users/by-username/shown", headers=h)
    assert r.status_code == 200
    assert r.json()["username"] == "shown"
    # village-only stranger → 404 (don't reveal existence), same gating as the id route
    assert client.get("/users/by-username/hidden", headers=h).status_code == 404
    assert client.get("/users/by-username/nobody", headers=h).status_code == 404

    assign_default_village(db, me)
    assign_default_village(db, hidden)
    db.commit()
    assert client.get("/users/by-username/hidden", headers=h).status_code == 200


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
