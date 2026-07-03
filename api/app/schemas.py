"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field

from . import config, storage

if TYPE_CHECKING:
    from .models import Source, User


class RequestLinkIn(BaseModel):
    email: EmailStr


class GenericMessage(BaseModel):
    message: str


class VerifyIn(BaseModel):
    token: str = Field(min_length=1)


class StartLoginOut(BaseModel):
    """Unified login entry response: which second step the UI should render."""

    mode: str  # 'link' — check your inbox for a magic link; 'code' — show the OTP input
    message: str


class EdgeosVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


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
    username: str
    display_name: str | None
    digest_frequency: str
    digest_paused: bool
    onboarded: bool
    # profile artifacts
    bio: str | None
    contact_email: str | None
    contact_phone: str | None
    contact_telegram: str | None
    profile_image_url: str | None
    visibility: str
    cities: list[str]
    links: list[LinkOut]
    villages: list[str]  # village names the user belongs to (backend-assigned)
    # Popups attended per the user's EdgeOS profile (snapshot from the last EdgeOS login;
    # empty for legacy email-only accounts).
    edgeos_popups: list[str]

    @classmethod
    def from_user(cls, user: "User") -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            display_name=user.display_name,
            digest_frequency=user.digest_frequency,
            digest_paused=user.digest_paused,
            onboarded=user.onboarded,
            bio=user.bio,
            contact_email=user.contact_email,
            contact_phone=user.contact_phone,
            contact_telegram=user.contact_telegram,
            profile_image_url=storage.public_url(user.profile_image_path),
            visibility=user.visibility,
            cities=[c.name for c in user.cities],
            links=[LinkOut(label=l.label, url=l.url) for l in user.links],
            villages=[uv.village.name for uv in user.villages],
            edgeos_popups=[a.popup_name for a in user.edgeos_attendances],
        )


class VerifyOut(BaseModel):
    session_token: str
    user: UserOut


class UsernameAvailability(BaseModel):
    valid: bool  # passes the format rules
    available: bool  # well-formed AND not taken by another user


class ProfileSourceOut(BaseModel):
    """A feeder's content source as a clickable directory entry."""

    type: str  # scraping category ('rss' | 'bluesky')
    label: str  # granular display label (Substack/YouTube/Podcast/…)
    url: str
    title: str | None
    status: str  # 'active' | 'unverified' (unverified = couldn't be scraped yet)


class PublicProfileOut(BaseModel):
    """Another user's profile as seen in the Directory (private fields omitted)."""

    id: int
    username: str
    display_name: str | None
    bio: str | None
    contact_email: str | None  # public contact only; phone stays private
    contact_telegram: str | None  # public contact handle
    profile_image_url: str | None
    cities: list[str]
    links: list[LinkOut]
    platforms: list[str]
    sources: list[ProfileSourceOut]  # the feeder's content feeds, as clickable links
    is_subscribed: bool
    verified: bool  # proven-inbox at least once; False = unclaimed, pre-seeded profile
    has_email: bool  # False = pre-seeded ghost with no account email (can't log in yet)

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
            username=user.username,
            display_name=user.display_name,
            bio=user.bio,
            contact_email=user.contact_email,
            contact_telegram=user.contact_telegram,
            profile_image_url=storage.public_url(user.profile_image_path),
            cities=[c.name for c in user.cities],
            links=[LinkOut(label=l.label, url=l.url) for l in user.links],
            platforms=platforms,
            sources=sources,
            is_subscribed=is_subscribed,
            verified=user.verified_at is not None,
            has_email=user.email is not None,
        )


class UpdateMeIn(BaseModel):
    """Partial update — any subset of fields (§7.7). Unset fields are left untouched;
    `cities` / `links` use replace-all semantics when present."""

    display_name: str | None = Field(
        default=None, min_length=1, max_length=config.DISPLAY_NAME_MAX_CHARS
    )
    # Format + uniqueness validated in the endpoint (see app/usernames.py).
    username: str | None = Field(
        default=None, min_length=config.USERNAME_MIN_CHARS, max_length=config.USERNAME_MAX_CHARS
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
    contact_telegram: str | None = Field(
        default=None, max_length=config.CONTACT_TELEGRAM_MAX_CHARS
    )
    visibility: str | None = None
    cities: list[str] | None = Field(default=None, max_length=config.MAX_CITIES)
    links: list[LinkIn] | None = Field(default=None, max_length=config.MAX_LINKS)


# --- sources --------------------------------------------------------------------------
class UrlIn(BaseModel):
    url: str = Field(min_length=1)


class SourcePreviewOut(BaseModel):
    type: str
    label: str
    resolved_url: str | None
    title: str | None
    found_count: int
    latest_title: str | None
    latest_published_at: datetime | None


class SourceOut(BaseModel):
    id: int
    type: str
    label: str  # granular display label (Substack/YouTube/Podcast/…)
    input_url: str
    resolved_feed_url: str | None
    title: str | None
    status: str  # 'active' | 'unverified' (unverified = couldn't be scraped yet)
    last_checked_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime

    @classmethod
    def from_source(cls, source: "Source") -> "SourceOut":
        from .sources import detect_label

        return cls(
            id=source.id,
            type=source.type,
            label=detect_label(source.type, source.input_url, source.resolved_feed_url),
            input_url=source.input_url,
            resolved_feed_url=source.resolved_feed_url,
            title=source.title,
            status=source.status,
            last_checked_at=source.last_checked_at,
            last_success_at=source.last_success_at,
            created_at=source.created_at,
        )


# --- subscriptions / discover ---------------------------------------------------------
class SubscribeIn(BaseModel):
    feeder_id: int


class PlatformPillOut(BaseModel):
    """A directory card pill: a platform label that links out to the feeder's first source
    of that platform."""

    label: str  # Substack/YouTube/Podcast/…
    url: str  # the first source of that platform (the pill's link target)


class SubscriptionOut(BaseModel):
    feeder_id: int
    username: str  # links the row to the feeder's profile (/p/{username})
    display_name: str | None
    platforms: list[PlatformPillOut]  # feeder-source pills, each links out


class DiscoverOut(BaseModel):
    user_id: int
    username: str
    display_name: str | None
    bio: str | None  # short context shown under the name in the directory
    city: str | None  # primary city, shown as the location line in the list view
    platforms: list[PlatformPillOut]  # feeder-source pills, each links out
    links: list[LinkOut]  # non-feeder profile links, shown as pressable pills too
    is_subscribed: bool
    profile_image_url: str | None  # shown circular as avatar, square as the mosaic tile
    verified: bool  # proven-inbox at least once; False = pre-seeded ghost, not yet registered


class MosaicTileOut(BaseModel):
    """Minimal per-user manifest row for the mosaic wall — just what a tile renders.

    The whole directory ships in one response, so this deliberately skips the pills /
    links / is_subscribed hydration that makes DiscoverOut expensive per row.
    """

    user_id: int
    username: str  # gradient seed + profile route
    display_name: str | None
    profile_image_url: str | None
    placeholder: bool  # pre-seeded ghost with nothing attached yet — dimmed in the mosaic


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
