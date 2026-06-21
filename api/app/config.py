"""App configuration. Dev uses a local SQLite file; prod is Postgres (Slice 4)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load api/.env if present, so the server *and* the cron jobs pick up local config/secrets.
# Real environment variables (e.g. Railway's) always win — load_dotenv never overrides them.
load_dotenv(API_DIR / ".env")

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

# Realistic desktop UA. The earlier "edge-mosaic-spike/0.1" identifier was an obvious
# non-browser agent; YouTube (and some other sites) reject those, and combined with a
# cookieless datacenter IP it triggered YouTube's consent interstitial instead of the feed.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cookies that pre-accept YouTube's EU cookie-consent gate. Without them a cookieless
# client (our Railway cron, datacenter IP) is bounced to a consent HTML page for both the
# channel page and the videos.xml feed — feedparser then sees no feed `version` and we
# store nothing. Scoped to youtube.com only (see RSSAdapter) so other feeds are untouched.
# SOCS=CAI is the modern acceptance value; CONSENT=YES+ covers the legacy gate.
YOUTUBE_CONSENT_COOKIES = {"SOCS": "CAI", "CONSENT": "YES+"}

RSS_FETCH_TIMEOUT = 10.0
BLUESKY_FEED_LIMIT = 30

# Polite retry on transient throttling (429/5xx, timeouts) during the background scrape.
# Honors Retry-After; backs off exponentially with jitter rather than re-hammering. The
# interactive add-time validator (which sets a deadline) opts out to stay snappy.
RSS_FETCH_RETRIES = 2  # extra attempts after the first
RSS_RETRY_BACKOFF_BASE = 0.5  # seconds; doubled per attempt, then jittered
RSS_RETRY_MAX_DELAY = 8.0  # cap on any single backoff / Retry-After wait

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

# Compact digest: once this many feeders have window activity, the spacious format (full
# excerpts, ≤5 long + ≤3 short each) becomes a wall, so the whole digest hard-switches to
# one line per feeder — a single representative item each (mvp-plan §5). Tune against data.
COMPACT_MODE_FEEDER_THRESHOLD = 10

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

# --- Profile (onboarding artifacts) ---------------------------------------------------
BIO_MAX_CHARS = 280
CONTACT_EMAIL_MAX_CHARS = 254  # RFC 5321 max email length
CONTACT_PHONE_MAX_CHARS = 40
CITY_MAX_CHARS = 80
MAX_CITIES = 5
LINK_LABEL_MAX_CHARS = 60
LINK_URL_MAX_CHARS = 2000
MAX_LINKS = 10
VALID_VISIBILITIES = {"community", "village"}
# Backend-assigned village every new user joins for now (third-party verification later).
DEFAULT_VILLAGE_NAME = "EE '26"
DEFAULT_VILLAGE_SLUG = "ee-26"

# --- Uploaded media (profile + tile images) -------------------------------------------
# Local-filesystem store for dev, served by the API at MEDIA_URL_PREFIX. The storage seam
# in app/storage.py is the one-file swap point for object storage in prod (cf. app/email.py).
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)
MEDIA_URL_PREFIX = "/media"
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
# content-type -> file extension for the formats we accept.
ALLOWED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
VALID_IMAGE_KINDS = {"profile", "tile"}

# Where the magic link points in prod (the SPA verify route). Slice 2 only logs it.
# Overridable so Slice 5 can point at the real CDN origin.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")

# The API's own public origin (split-origin from the SPA). Used for the RFC 8058
# one-click unsubscribe POST target in List-Unsubscribe headers.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# CORS (Slice 5): the SPA is a separate origin, so the browser preflights authed calls.
# Comma-separated allowlist; local dev defaults to the Vite dev server. Prod sets this to
# the Vercel domain. allow_credentials stays False — auth is a bearer header, not cookies.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

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
