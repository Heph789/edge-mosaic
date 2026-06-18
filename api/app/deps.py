"""FastAPI dependencies — DB session + the authenticated user."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from .auth import user_for_session_token
from .db import SessionLocal
from .models import User


def get_db() -> Iterator[DbSession]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(
    db: Annotated[DbSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve `Authorization: Bearer <token>` → live user, else 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization[7:].strip()
    user = user_for_session_token(db, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired session")
    return user


DbDep = Annotated[DbSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
