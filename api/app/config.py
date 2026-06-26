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

# --- X / Twitter (paid, metered) ------------------------------------------------------
# As of 2026-02-06 X charges pay-per-use ($0.005 per post read), so the adapter is built
# to read as little as possible: resolve the username→id ONCE (cached on source.external_id),
# then pull only tweets newer than the last seen one (since_id, stored on source.cursor).
# X_FEED_LIMIT caps the page size — the only knob that bounds the first pull for a new source
# and any catch-up after a quiet stretch. X requires max_results in [5, 100].
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")
X_API_BASE = os.environ.get("X_API_BASE", "https://api.twitter.com/2")
X_FEED_LIMIT = int(os.environ.get("X_FEED_LIMIT", "10"))
X_FETCH_TIMEOUT = 10.0

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
# Public-profile handle (/p/{username}). See app/usernames.py for the format rules.
USERNAME_MIN_CHARS = 3
USERNAME_MAX_CHARS = 30

# --- Profile (onboarding artifacts) ---------------------------------------------------
BIO_MAX_CHARS = 280
CONTACT_EMAIL_MAX_CHARS = 254  # RFC 5321 max email length
CONTACT_PHONE_MAX_CHARS = 40
CONTACT_TELEGRAM_MAX_CHARS = 33  # '@' + Telegram's 32-char handle max
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
# Two backends behind the app/storage.py seam (cf. app/email.py):
#   * dev  -> local filesystem under MEDIA_DIR, served by the API's StaticFiles mount.
#   * prod -> S3-compatible object storage (Cloudflare R2 / AWS S3), selected automatically
#             when MEDIA_S3_BUCKET is set. Railway's container FS is ephemeral *and*
#             root-owned-volume hostile (uid 10001 can't write a mounted volume), so the
#             local backend can't run there — object storage is the prod path.
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)
MEDIA_URL_PREFIX = "/media"
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

# S3/R2 backend. When MEDIA_S3_BUCKET is non-empty, storage.py uses object storage and
# ignores MEDIA_DIR. The bucket stays PRIVATE: image URLs are short-lived presigned GET URLs
# generated at serialization time (boto3, local HMAC — no network call), so nothing is
# publicly readable and links expire after MEDIA_URL_TTL_SECONDS. The URL is only ever
# returned to viewers who already pass the directory's visibility checks. For Cloudflare R2,
# MEDIA_S3_ENDPOINT_URL is https://<account-id>.r2.cloudflarestorage.com and the region is
# "auto"; for AWS S3 leave the endpoint empty and set the real region.
MEDIA_S3_BUCKET = os.environ.get("MEDIA_S3_BUCKET", "")
MEDIA_S3_ENDPOINT_URL = os.environ.get("MEDIA_S3_ENDPOINT_URL", "") or None
MEDIA_S3_REGION = os.environ.get("MEDIA_S3_REGION", "auto")
MEDIA_S3_ACCESS_KEY_ID = os.environ.get("MEDIA_S3_ACCESS_KEY_ID", "")
MEDIA_S3_SECRET_ACCESS_KEY = os.environ.get("MEDIA_S3_SECRET_ACCESS_KEY", "")
# Lifetime of a presigned image URL. Short enough that a leaked link soon dies; long enough
# to outlast a page session. SigV4 caps this at 7 days (604800s).
MEDIA_URL_TTL_SECONDS = int(os.environ.get("MEDIA_URL_TTL_SECONDS", "3600"))
# content-type -> file extension for the formats we accept.
ALLOWED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
# One image per user (the profile photo, also rendered as the square mosaic tile). The
# {kind} route param is kept as a seam for future image kinds (e.g. a banner).
VALID_IMAGE_KINDS = {"profile"}

# Where the magic link points in prod (the SPA verify route). Slice 2 only logs it.
# Overridable so Slice 5 can point at the real CDN origin.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")

# The API's own public origin (split-origin from the SPA). Used for the RFC 8058
# one-click unsubscribe POST target in List-Unsubscribe headers.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# CORS (Slice 5): the SPA is a separate origin, so the browser preflights authed calls.
# Comma-separated exact allowlist; local dev defaults to the Vite dev server. allow_credentials
# stays False — auth is a bearer header, not cookies. An origin is allowed if it's in this exact
# list OR matches CORS_ORIGIN_REGEX below, so prod usually needs neither override.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# Pattern form of the allowlist (Starlette `allow_origin_regex`) so we don't have to enumerate
# every origin: localhost/127.0.0.1 on any port (dev), the edge-mosaic.com apex and any
# subdomain (www, etc.), and this project's Vercel prod/preview URLs. Matched with `fullmatch`,
# so each alternative must consume the whole origin — `…edge-mosaic.com.evil.com` won't match.
# Override via CORS_ORIGIN_REGEX (set it empty to disable regex matching and use the list only).
CORS_ORIGIN_REGEX = os.environ.get(
    "CORS_ORIGIN_REGEX",
    r"http://(localhost|127\.0\.0\.1)(:\d+)?"
    r"|https://([a-z0-9-]+\.)*edge-mosaic\.com"
    r"|https://edge-mosaic[a-z0-9-]*\.vercel\.app",
) or None

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
