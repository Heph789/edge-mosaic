"""Spike configuration. Dev uses a local SQLite file; prod becomes Postgres in Slice 4."""

from __future__ import annotations

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Dialect-agnostic URL. Swap to Postgres in Slice 4 via the same env var.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'edge_mosaic.db'}")

DIGEST_OUTPUT_PATH = DATA_DIR / "digest.html"

# Polite identifier; some sites reject obvious non-browser agents outright.
USER_AGENT = "Mozilla/5.0 (compatible; edge-mosaic-spike/0.1; +https://github.com/edge-mosaic)"

RSS_FETCH_TIMEOUT = 10.0
BLUESKY_FEED_LIMIT = 30

# Render / capping knobs (Slice 1 §Render).
DIGEST_WINDOW_DAYS = 30
SHORT_ITEMS_CAP = 3
LONG_ITEMS_CAP = 5  # even genuine essays pile up for prolific bloggers; cap by recency
EXCERPT_MAX_CHARS = 200
SHORT_TEXT_RENDER_CHARS = 100

# kind classification for RSS (no post-type/engagement signal exists — length is the
# only proxy). Body in [MIN, MAX] chars → 'short'; outside → 'long'. The MIN floor keeps
# truncated/paywalled stubs (e.g. a 9-char excerpt of a real essay) classified 'long'.
KIND_SHORT_MIN_CHARS = 50
KIND_SHORT_MAX_CHARS = 1500
