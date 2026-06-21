"""SQLAlchemy 2.0 typed models.

Kept dialect-agnostic (plain string columns, no native enums) so these models and the
Alembic migrations carry forward unchanged to Postgres in Slice 4.
"""

from __future__ import annotations

from datetime import datetime, timezone

import secrets

from sqlalchemy import (
    Boolean,
    Date,
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


def new_unsubscribe_token() -> str:
    return secrets.token_urlsafe(24)


class Base(DeclarativeBase):
    pass


# Profile visibility (plain string, no native enum — keeps SQLite/Postgres parity):
#   'community' — discoverable by the whole edge community
#   'village'   — discoverable only by users sharing a village (the "Just my village(s)" toggle)
VISIBILITY_COMMUNITY = "community"
VISIBILITY_VILLAGE = "village"


class User(Base):
    """An account — both feeder and subscriber (one unified account, §2).

    Three independent states (see slice-2-auth.md):
      exists    — this row is present (pre-seeded at import OR lazy at verify)
      verified  — `verified_at` set: proven inbox >= once. NULL = pre-seeded ghost.
      onboarded — explicit flag, decoupled from display_name.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # lowercased
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    digest_frequency: Mapped[str] = mapped_column(
        String, nullable=False, default="weekly"
    )  # 'weekly' | 'monthly'
    digest_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Opaque per-user token embedded in the digest unsubscribe link (Slice 4).
    unsubscribe_token: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, default=new_unsubscribe_token
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Profile (onboarding artifacts) -----------------------------------------------
    bio: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    # Relative media keys (e.g. '12/profile-ab3.png'), not URLs — the public URL is derived
    # from config.MEDIA_URL_PREFIX at serialization time so it survives an origin change.
    profile_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    tile_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, default=VISIBILITY_COMMUNITY
    )

    last_digest_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_covered_through: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    cities: Mapped[list[UserCity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="UserCity.position",
    )
    links: Mapped[list[ProfileLink]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ProfileLink.position",
    )
    villages: Mapped[list[UserVillage]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProfileLink(Base):
    """A user's non-feeder link (portfolio, personal site, etc.) — distinct from `sources`,
    which feed the digest. `position` preserves the order the user arranged them in."""

    __tablename__ = "profile_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="links")


class UserCity(Base):
    """A place the user lives in / is associated with — informational, multiple allowed.
    Independent of `villages` (which gate visibility)."""

    __tablename__ = "user_cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="cities")


class Village(Base):
    """A community grouping used for 'Just my village(s)' visibility. Membership is
    backend-assigned (today: everyone auto-joins 'EE ’26'); third-party verification later."""

    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    members: Mapped[list[UserVillage]] = relationship(
        back_populates="village", cascade="all, delete-orphan"
    )


class UserVillage(Base):
    """Membership: a user belongs to a village. Two users sharing a village can see each
    other even when their visibility is 'village'."""

    __tablename__ = "user_villages"
    __table_args__ = (
        UniqueConstraint("user_id", "village_id", name="uq_user_village"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="villages")
    village: Mapped[Village] = relationship(back_populates="members")


class AllowedEmail(Base):
    """CSV allowlist gate — source of truth for 'valid edge email' (§2)."""

    __tablename__ = "allowed_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # lowercased
    # Abbreviated form only ("Jane S."); full surname is never persisted.
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class MagicLinkToken(Base):
    """Single-use login token. Keyed by EMAIL — the user may not exist yet at request."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False)  # lowercased
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Session(Base):
    """Opaque server-side session token (§2) — revocable, no JWT."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Subscription(Base):
    """A subscriber following a feeder. Both ids are users — 'feeder' is a role, not a
    table. Self-subscription (subscriber_id == feeder_id) is allowed (digest dogfooding).
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("subscriber_id", "feeder_id", name="uq_subscription_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    feeder_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class SentDigest(Base):
    """One row per (subscriber, anchor) digest period — dedup + audit (Slice 4).

    `sent=False, item_count=0` records a skip-empty period so it isn't re-attempted; the
    UNIQUE(subscriber_id, anchor_date) is what makes the digest job idempotent and lets a
    missed cron day self-heal (the anchor simply isn't logged yet).
    """

    __tablename__ = "sent_digests"
    __table_args__ = (
        UniqueConstraint("subscriber_id", "anchor_date", name="uq_sent_digest_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    anchor_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Source(Base):
    """A feeder's content source. Multiple per feeder allowed."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("user_id", "input_url", name="uq_source_user_input"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
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
