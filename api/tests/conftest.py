"""Test harness: an isolated temp SQLite DB + an in-process API client.

DATABASE_URL is pointed at a throwaway temp file *before* any app module imports, so the
engine binds to it. Tables are built from the models (fast; the Alembic migrations are
exercised separately by the migration itself).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

from app.db import SessionLocal, engine  # noqa: E402  (after env is set)
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop + recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture emails instead of sending; expose dicts with to/subject/html/text/headers."""
    captured: list[dict] = []

    def fake_send(to, subject, html, text=None, headers=None):
        captured.append(
            {"to": to, "subject": subject, "html": html, "text": text, "headers": headers}
        )

    # Patch the source module (main.py calls `email.send_email`, resolved at call time)
    # plus every module that bound it via `from ..email import send_email`.
    for target in ("app.email.send_email", "app.jobs.digest.send_email"):
        try:
            monkeypatch.setattr(target, fake_send)
        except (AttributeError, ImportError):
            pass
    return captured


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(db):
    """Factory: create a user. Given a display_name → treated as onboarded.

    username is NOT NULL + unique; default it to a valid, unique handle derived from the
    (unique) email when not supplied, so callers that don't care about it still work."""
    import re

    from app.models import User

    def _make(email, display_name=None, **kw):
        kw.setdefault("username", "u" + re.sub(r"[^a-z0-9]", "", email.lower())[:29])
        user = User(
            email=email,
            display_name=display_name,
            onboarded=bool(display_name),
            **kw,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def auth(db):
    """Factory: mint a real session row for a user → return Bearer headers."""
    from datetime import timedelta

    from app.models import Session, utcnow
    from app.security import hash_token, new_token

    def _auth(user):
        raw = new_token()
        db.add(
            Session(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        db.commit()
        return {"Authorization": f"Bearer {raw}"}

    return _auth
