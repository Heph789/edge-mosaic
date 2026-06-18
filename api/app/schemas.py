"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from . import config


class RequestLinkIn(BaseModel):
    email: EmailStr


class GenericMessage(BaseModel):
    message: str


class VerifyIn(BaseModel):
    token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    digest_frequency: str
    digest_paused: bool
    onboarded: bool

    model_config = {"from_attributes": True}


class VerifyOut(BaseModel):
    session_token: str
    user: UserOut


class UpdateMeIn(BaseModel):
    """Partial update — any subset of fields (§7.7)."""

    display_name: str | None = Field(
        default=None, min_length=1, max_length=config.DISPLAY_NAME_MAX_CHARS
    )
    digest_frequency: str | None = None
    digest_paused: bool | None = None


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


# --- digest preview -------------------------------------------------------------------
class DigestItemOut(BaseModel):
    title: str | None
    url: str
    excerpt: str | None
    text: str | None
    kind: str
    published_at: datetime


class DigestFeederOut(BaseModel):
    feeder_id: int
    display_name: str | None
    longs: list[DigestItemOut]
    shorts: list[DigestItemOut]


class DigestOut(BaseModel):
    window_start: datetime
    window_end: datetime
    feeders: list[DigestFeederOut]
