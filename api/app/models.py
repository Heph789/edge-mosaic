"""SQLAlchemy 2.0 typed models — only the two tables Slice 1 needs.

Kept dialect-agnostic (plain string columns, no native enums) so these models and the
Alembic migration carry forward unchanged to Postgres in Slice 4.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    """A feeder's content source. Multiple per feeder allowed."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("feeder_name", "input_url", name="uq_source_feeder_input"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Temporary stub — becomes a user_id FK in Slice 2.
    feeder_name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # 'rss' | 'bluesky'
    input_url: Mapped[str] = mapped_column(String, nullable=False)
    resolved_feed_url: Mapped[str | None] = mapped_column(String, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)  # bluesky DID
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    items: Mapped[list[Item]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Item(Base):
    """Scraped content. `UNIQUE(source_id, external_id)` is the dedup key."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_item_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'long' | 'short'
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str | None] = mapped_column(String, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String, nullable=True)
    engagement_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="items")
