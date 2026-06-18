"""Spike configuration. Dev uses a local SQLite file; prod becomes Postgres in Slice 4."""

from __future__ import annotations

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Dialect-agnostic URL. Local dev defaults to SQLite; prod (Railway) sets DATABASE_URL to
# Postgres. Railway hands out `postgres://` / `postgresql://` — normalize to the psycopg3
# driver so we don't silently fall back to psycopg2.
def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_db_url(
    os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'edge_mosaic.db'}")
)

DIGEST_OUTPUT_PATH = DATA_DIR / "digest.html"

# Polite identifier; some sites reject obvious non-browser agents outright.
USER_AGENT = "Mozilla/5.0 (compatible; edge-mosaic-spike/0.1; +https://github.com/edge-mosaic)"

RSS_FETCH_TIMEOUT = 10.0
BLUESKY_FEED_LIMIT = 30

# Add-time validation (Slice 3): tighter than the background scrape since it's interactive.
# Per-request timeout AND an overall resolution deadline, so the worst-case
# "try URL → fetch HTML → 5 common paths" chain can't hang the request.
ADD_SOURCE_TIMEOUT = 5.0
ADD_SOURCE_DEADLINE = 10.0

# Render / capping knobs (Slice 1 §Render).
DIGEST_WINDOW_DAYS = 30
SHORT_ITEMS_CAP = 3
LONG_ITEMS_CAP = 5  # even genuine essays pile up for prolific bloggers; cap by recency

# Preview trailing-window sizes by frequency (Slice 3 §assembly). The real send (Slice 4)
# passes a calendar-anchored window instead; same engine, different bounds.
WEEKLY_WINDOW_DAYS = 7
MONTHLY_WINDOW_DAYS = 30
# Per-digest safety cap so a huge subscription list can't explode the payload (§5).
DIGEST_FEEDER_CAP = 50
EXCERPT_MAX_CHARS = 200
SHORT_TEXT_RENDER_CHARS = 100

# kind classification for RSS (no post-type/engagement signal exists — length is the
# only proxy). Body in [MIN, MAX] chars → 'short'; outside → 'long'. The MIN floor keeps
# truncated/paywalled stubs (e.g. a 9-char excerpt of a real essay) classified 'long'.
KIND_SHORT_MIN_CHARS = 50
KIND_SHORT_MAX_CHARS = 1500

# --- Slice 2: auth (§2) ---------------------------------------------------------------
# Token lifetimes. Magic links are short-lived + single-use; sessions are long + revocable.
MAGIC_LINK_TTL_MINUTES = 15
SESSION_TTL_DAYS = 30
DISPLAY_NAME_MAX_CHARS = 50

# Where the magic link points in prod (the SPA verify route). Slice 2 only logs it.
# Overridable so Slice 5 can point at the real CDN origin.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")

# The API's own public origin (split-origin from the SPA). Used for the RFC 8058
# one-click unsubscribe POST target in List-Unsubscribe headers.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# Default allowlist roster (real attendee PII — gitignored, never read into the repo).
ALLOWLIST_CSV_DEFAULT = next(
    iter(sorted((API_DIR / "input").glob("attendees-*.csv"))), None
)

# --- Slice 4: cron + email (§5) -------------------------------------------------------
# Email backend behind the send_email() seam. Default 'console' (no real delivery) so the
# app stays send-safe until a verified domain is wired; set EMAIL_BACKEND=resend in prod.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Edge Mosaic <digest@edgemosaic.example>")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_API_URL = "https://api.resend.com/emails"
