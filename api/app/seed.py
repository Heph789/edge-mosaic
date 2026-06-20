"""Seed pre-seeded feeders + their sources from `docs/source-list.md` (dev/demo data).

The doc is the source of truth: a feeder name on its own line, followed by its URLs, one
per line, blank-line separated. Each URL is classified to an adapter; URLs we have no
adapter for (X/Twitter, GitHub) are skipped so a feeder degrades to whatever *does*
resolve rather than failing.

Each feeder becomes a **pre-seeded ghost user** (`verified_at` NULL — discoverable in the
Directory, never logged in; §2 pre-seeding), with one `sources` row per supported URL.
Idempotent: get-or-create on `email` (feeder) and `(user_id, input_url)` (source).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import API_DIR
from .models import Source, User

SOURCE_LIST_PATH = API_DIR.parent / "docs" / "source-list.md"

# Synthetic email domain for pre-seeded demo feeders (never receives real mail).
SEED_EMAIL_DOMAIN = "seed.edge-mosaic.local"


def classify_url(url: str) -> str | None:
    """Map a URL to its adapter type, or None if we have no adapter for it.

    RSS is the catch-all (plain blogs, Substack, Medium, Mastodon via autodiscovery,
    YouTube/Apple-Podcasts directory pages — resolved by the RSS adapter's platform
    handlers). X/Twitter and GitHub have no feed adapter, so they're dropped.
    """
    u = url.lower()
    if "bsky.app/profile/" in u:
        return "bluesky"
    if "x.com/" in u or "twitter.com/" in u:
        return None  # X/Twitter — deferred, no public adapter
    if "github.com/" in u:
        return None  # GitHub activity — no feed adapter
    return "rss"


def _slug(name: str) -> str:
    """'Kent C. Dodds' -> 'kent-c-dodds' (for a stable synthetic email)."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "feeder"


@dataclass
class FeederSpec:
    name: str
    urls: list[tuple[str, str]]  # (type, url) for supported URLs only


def parse_source_list(text: str) -> list[FeederSpec]:
    """Parse the name/URLs stanzas into specs, dropping unsupported URLs."""
    feeders: list[FeederSpec] = []
    current: FeederSpec | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("http://", "https://")):
            if current is None:
                continue  # a stray URL before any name
            type_ = classify_url(line)
            if type_ is not None:
                current.urls.append((type_, line))
        else:
            current = FeederSpec(name=line, urls=[])
            feeders.append(current)
    return feeders


@dataclass
class SeedStats:
    feeders_created: int = 0
    feeders_existing: int = 0
    sources_created: int = 0
    sources_existing: int = 0
    urls_skipped: int = 0  # unsupported (X/Twitter, GitHub)


def seed_sources(session: Session, path: Path | None = None) -> SeedStats:
    text = (path or SOURCE_LIST_PATH).read_text(encoding="utf-8")
    specs = parse_source_list(text)
    stats = SeedStats()

    for spec in specs:
        # Count URLs we dropped for visibility (total lines minus the kept ones).
        email = f"{_slug(spec.name)}@{SEED_EMAIL_DOMAIN}"
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            # Pre-seeded ghost: discoverable by name, never logged in (verified_at NULL).
            user = User(email=email, display_name=spec.name)
            session.add(user)
            session.flush()  # assign user.id for the sources below
            stats.feeders_created += 1
        else:
            stats.feeders_existing += 1

        for source_type, url in spec.urls:
            exists = session.scalar(
                select(Source).where(
                    Source.user_id == user.id, Source.input_url == url
                )
            )
            if exists is None:
                session.add(Source(user_id=user.id, type=source_type, input_url=url))
                stats.sources_created += 1
            else:
                stats.sources_existing += 1

    session.commit()
    # urls_skipped = supported-or-not difference, recomputed from the raw doc.
    total_urls = sum(
        1
        for line in text.splitlines()
        if line.strip().startswith(("http://", "https://"))
    )
    kept = stats.sources_created + stats.sources_existing
    stats.urls_skipped = total_urls - kept
    return stats
