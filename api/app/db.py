"""Engine + session factory. Dialect-agnostic so the SQLite→Postgres switch is painless."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, future=True)
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, future=True, expire_on_commit=False
)
