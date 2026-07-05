"""EdgeOS third-party auth client (§2).

Two steps of ONE OTP flow (EdgeOS's "Third Party Human Login" / "... Authenticate"):
  1. POST /auth/human/third-party/login        — EdgeOS emails the human a 6-digit code
     (201). Unknown email → 401 and NO email sent; the endpoint never creates a human, so
     "EdgeOS knows this email" is the eligibility gate that replaces the CSV allowlist.
  2. POST /auth/human/third-party/authenticate — verify the code → EdgeOS JWT (scoped to
     portal:profile/applications/directory reads for our app).

The JWT is used transiently to pull the human's profile + popup-attendance stats and is
then discarded — our own opaque Session rows stay the app's only credential.

All functions are synchronous (called from sync FastAPI endpoints, like the Resend email
backend). Network failures / EdgeOS 5xx raise EdgeosUnavailableError so endpoints can
return 503 instead of silently eating a login.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import sentry_sdk

from . import config

logger = logging.getLogger(__name__)


class EdgeosUnavailableError(Exception):
    """EdgeOS couldn't be reached (network error / 5xx) — retryable, not an auth verdict."""


def _unavailable(message: str, exc: Exception | None = None) -> EdgeosUnavailableError:
    """Build the error AND report it: endpoints translate it into an intentional 503,
    which Sentry's FastAPI integration won't capture — without this, a broken key or an
    EdgeOS outage would only surface through user reports."""
    logger.warning("EdgeOS unavailable: %s", message)
    err = EdgeosUnavailableError(message)
    sentry_sdk.capture_exception(err if exc is None else exc)  # no-op without a DSN
    return err


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        resp = httpx.request(
            method,
            f"{config.EDGEOS_API_BASE}{path}",
            timeout=config.EDGEOS_TIMEOUT,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise _unavailable(f"EdgeOS request failed: {exc}", exc) from exc
    if resp.status_code >= 500:
        raise _unavailable(f"EdgeOS returned {resp.status_code} for {path}")
    return resp


def _key_header() -> dict[str, str]:
    return {"X-Third-Party-Api-Key": config.EDGEOS_API_KEY}


def request_login_code(email: str) -> bool:
    """Ask EdgeOS to email `email` a 6-digit login code.

    True → code sent (EdgeOS knows this human). False → 401: unknown email (or bad API
    key), nothing sent. Callers must respond identically either way (login privacy).
    """
    resp = _request(
        "POST",
        "/auth/human/third-party/login",
        headers=_key_header(),
        json={"email": email},
    )
    return resp.status_code == 201


def verify_login_code(email: str, code: str) -> str | None:
    """Exchange the emailed 6-digit code for an EdgeOS access token, or None if rejected."""
    resp = _request(
        "POST",
        "/auth/human/third-party/authenticate",
        headers=_key_header(),
        json={"email": email, "code": code},
    )
    if resp.status_code != 200:
        return None  # wrong/expired code (EdgeOS answers 401 for all rejections)
    return resp.json().get("access_token")


def _fetch_json(access_token: str, path: str) -> dict[str, Any] | None:
    """Best-effort authed GET — profile enrichment must never block a successful login."""
    try:
        resp = _request(
            "GET", path, headers={"Authorization": f"Bearer {access_token}"}
        )
    except EdgeosUnavailableError:
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data if isinstance(data, dict) else None


def fetch_profile(access_token: str) -> dict[str, Any] | None:
    """GET /humans/me — id, first_name, last_name, picture_url, telegram, residence, …"""
    return _fetch_json(access_token, "/humans/me")


def fetch_profile_stats(access_token: str) -> dict[str, Any] | None:
    """GET /humans/me/profile-stats — {popups: [{popup_id, popup_name, start_date,
    end_date, location, image_url, total_days}], total_days}."""
    return _fetch_json(access_token, "/humans/me/profile-stats")
