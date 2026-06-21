"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field

from . import config, storage

if TYPE_CHECKING:
    from .models import User


class RequestLinkIn(BaseModel):
    email: EmailStr


class GenericMessage(BaseModel):
    message: str


class VerifyIn(BaseModel):
    token: str = Field(min_length=1)


class LinkIn(BaseModel):
    label: str = Field(min_length=1, max_length=config.LINK_LABEL_MAX_CHARS)
    url: str = Field(min_length=1, max_length=config.LINK_URL_MAX_CHARS)


class LinkOut(BaseModel):
    label: str
    url: str


class UserOut(BaseModel):
    """The authenticated user's own full profile (private fields included)."""

    id: int
    email: str
    display_name: str | None
    digest_frequency: str
    digest_paused: bool
    onboarded: bool
    # profile artifacts
    bio: str | None
    contact_email: str | None
    contact_phone: str | None
    profile_image_url: str | None
    tile_image_url: str | None
    visibility: str
    cities: list[str]
    links: list[LinkOut]
    villages: list[str]  # village names the user belongs to (backend-assigned)

    @classmethod
    def from_user(cls, user: "User") -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            digest_frequency=user.digest_frequency,
            digest_paused=user.digest_paused,
            onboarded=user.onboarded,
            bio=user.bio,
            contact_email=user.contact_email,
            contact_phone=user.contact_phone,
            profile_image_url=storage.public_url(user.profile_image_path),
            tile_image_url=storage.public_url(user.tile_image_path),
            visibility=user.visibility,
            cities=[c.name for c in user.cities],
            links=[LinkOut(label=l.label, url=l.url) for l in user.links],
            villages=[uv.village.name for uv in user.villages],
        )


class VerifyOut(BaseModel):
    session_token: str
    user: UserOut


class ProfileSourceOut(BaseModel):
    """A feeder's content source as a clickable directory entry."""

    type: str
    url: str
    title: str | None


class PublicProfileOut(BaseModel):
    """Another user's profile as seen in the Directory (private fields omitted)."""

    id: int
    display_name: str | None
    bio: str | None
    contact_email: str | None  # public contact only; phone stays private
    profile_image_url: str | None
    tile_image_url: str | None
    cities: list[str]
    links: list[LinkOut]
    platforms: list[str]
    sources: list[ProfileSourceOut]  # the feeder's content feeds, as clickable links
    is_subscribed: bool

    @classmethod
    def from_user(
        cls,
        user: "User",
        *,
        platforms: list[str],
        sources: list[ProfileSourceOut],
        is_subscribed: bool,
    ) -> "PublicProfileOut":
        return cls(
            id=user.id,
            display_name=user.display_name,
            bio=user.bio,
            contact_email=user.contact_email,
            profile_image_url=storage.public_url(user.profile_image_path),
            tile_image_url=storage.public_url(user.tile_image_path),
            cities=[c.name for c in user.cities],
            links=[LinkOut(label=l.label, url=l.url) for l in user.links],
            platforms=platforms,
            sources=sources,
            is_subscribed=is_subscribed,
        )


class UpdateMeIn(BaseModel):
    """Partial update — any subset of fields (§7.7). Unset fields are left untouched;
    `cities` / `links` use replace-all semantics when present."""

    display_name: str | None = Field(
        default=None, min_length=1, max_length=config.DISPLAY_NAME_MAX_CHARS
    )
    digest_frequency: str | None = None
    digest_paused: bool | None = None
    bio: str | None = Field(default=None, max_length=config.BIO_MAX_CHARS)
    contact_email: str | None = Field(
        default=None, max_length=config.CONTACT_EMAIL_MAX_CHARS
    )
    contact_phone: str | None = Field(
        default=None, max_length=config.CONTACT_PHONE_MAX_CHARS
    )
    visibility: str | None = None
    cities: list[str] | None = Field(default=None, max_length=config.MAX_CITIES)
    links: list[LinkIn] | None = Field(default=None, max_length=config.MAX_LINKS)


# --- sources --------------------------------------------------------------------------
class UrlIn(BaseModel):
    url: str = Field(min_length=1)


class SourcePreviewOut(BaseModel):
    type: str
    resolved_url: str | None
    title: str | None
    found_count: int
    latest_title: str | None
    latest_published_at: datetime | None


class SourceOut(BaseModel):
    id: int
    type: str
    input_url: str
    resolved_feed_url: str | None
    title: str | None
    last_checked_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- subscriptions / discover ---------------------------------------------------------
class SubscribeIn(BaseModel):
    feeder_id: int


class SubscriptionOut(BaseModel):
    feeder_id: int
    display_name: str | None
    platforms: list[str]


class DiscoverOut(BaseModel):
    user_id: int
    display_name: str | None
    platforms: list[str]
    is_subscribed: bool
    profile_image_url: str | None
    tile_image_url: str | None  # the mosaic cell image (future mosaic UI)


# --- digest preview -------------------------------------------------------------------
class DigestItemOut(BaseModel):
    title: str | None
    url: str
    excerpt: str | None
    text: str | None
    kind: str
    published_at: datetime


class DigestSourceOut(BaseModel):
    label: str
    longs: list[DigestItemOut]
    shorts: list[DigestItemOut]


class DigestFeederOut(BaseModel):
    feeder_id: int
    display_name: str | None
    sources: list[DigestSourceOut]
    selected: DigestItemOut  # representative item the compact view shows for this feeder


class DigestOut(BaseModel):
    window_start: datetime
    window_end: datetime
    feeders: list[DigestFeederOut]
    quiet_feeders: list[str]  # followed feeders with sources but nothing in the window
    compact: bool  # one-line-per-feeder format (many active feeders)
