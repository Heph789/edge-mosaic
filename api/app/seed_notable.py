"""Seed curated *notable speakers* (pre-seeded ghost users) from `docs/notable-speakers.json`.

Each entry becomes a **pre-seeded ghost user** (`verified_at` NULL — discoverable in the
Directory via `display_name`, never logged in), flagged `is_notable=True`, populated *as-is*
from the roster: full `display_name`, optional email, and its channels split into:
  - **sources** (scraped feeders) for feed-bearing platforms — Substack, YouTube, Medium,
    Mastodon, blogs, podcasts, Bluesky — routed through `detect_type` like `seed_sources`.
  - **profile_links** (display only) for everything else — X, LinkedIn, GitHub, Instagram, …

Idempotent. Dedup key: `email` when present (and *promote* a pre-existing user to notable),
else (`display_name`, `is_notable`). The roster is the source of truth, so each run rewrites
the notable's `display_name` and **replaces** its `profile_links` declaratively; `sources` are
added idempotently (never dropped) so scrape state (`resolved_feed_url`, items) is preserved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import config
from .config import API_DIR
from .models import ProfileLink, Source, User
from .sources import SourceRejected, detect_type
from .villages import assign_default_village

NOTABLE_PATH = API_DIR.parent / "docs" / "notable-speakers.json"

# Channel labels whose URLs are feed-bearing → stored as scraped `sources` (the RSS adapter
# resolves Substack /feed, Medium, Apple/Acast podcasts, Mastodon, plain blogs; Bluesky via
# its adapter). Everything else stays a display-only profile link.
#
# YouTube is intentionally NOT here: YouTube blocks its feeds/videos.xml endpoint from
# datacenter/cloud IPs (returns 404/500 for even valid channels, incl. the scraper's host),
# so a YouTube "feeder" would just fail every scrape. It rides along as a display link.
FEEDER_LABELS = {"Substack", "Medium", "Mastodon", "Blog", "Podcast", "Bluesky"}


@dataclass
class NotableSpec:
    name: str
    email: str | None
    links: list[tuple[str, str]]  # (label, url) in display order


def parse_notable_list(text: str) -> list[NotableSpec]:
    """Parse the JSON roster into specs, normalizing email to lowercase."""
    specs: list[NotableSpec] = []
    for row in json.loads(text):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        email = (row.get("email") or "").strip().lower() or None
        links = [
            (str(l["label"]).strip(), str(l["url"]).strip())
            for l in (row.get("links") or [])
            if l.get("label") and l.get("url")
        ]
        specs.append(NotableSpec(name=name, email=email, links=links))
    return specs


@dataclass
class NotableStats:
    created: int = 0
    promoted: int = 0  # pre-existing user flagged notable
    existing: int = 0
    sources_created: int = 0
    sources_existing: int = 0
    sources_removed: int = 0  # no longer feeders in the roster (e.g. demoted)
    links_set: int = 0
    links_skipped: int = 0  # over MAX_LINKS
    warnings: list[str] = field(default_factory=list)


def _find_user(session: Session, spec: NotableSpec) -> User | None:
    if spec.email is not None:
        return session.scalar(select(User).where(User.email == spec.email))
    # Email-less: best available stable key is the display name among notables.
    return session.scalar(
        select(User).where(
            User.display_name == spec.name, User.is_notable.is_(True)
        )
    )


def _partition_links(
    spec: NotableSpec,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split a spec's links into (sources, display_links). A feeder-labelled URL that
    `detect_type` rejects (e.g. an X link mislabelled) falls back to a display link."""
    sources: list[tuple[str, str]] = []  # (source_type, url)
    display: list[tuple[str, str]] = []  # (label, url)
    for label, url in spec.links:
        if label in FEEDER_LABELS:
            try:
                sources.append((detect_type(url), url))
                continue
            except SourceRejected:
                pass
        display.append((label, url))
    return sources, display


def seed_notable_speakers(session: Session, path: Path | None = None) -> NotableStats:
    text = (path or NOTABLE_PATH).read_text(encoding="utf-8")
    specs = parse_notable_list(text)
    stats = NotableStats()

    for spec in specs:
        user = _find_user(session, spec)
        if user is None:
            # Pre-seeded ghost: discoverable by display_name, never logged in (verified_at NULL).
            user = User(email=spec.email, display_name=spec.name, is_notable=True)
            session.add(user)
            session.flush()  # assign user.id for the username + links below
            user.username = f"user-{user.id}"  # canonical placeholder handle
            assign_default_village(session, user)
            stats.created += 1
        else:
            if not user.is_notable:
                user.is_notable = True  # promote a pre-existing (e.g. allowlisted) account
                stats.promoted += 1
            else:
                stats.existing += 1
            # Roster is source of truth: refresh the display name (fixes abbreviated rosters).
            user.display_name = spec.name

        source_specs, display_specs = _partition_links(spec)

        # Sources: reconcile to the roster. Kept feeders are left untouched (preserves scrape
        # state — resolved_feed_url, items); feeders no longer in the roster (e.g. demoted from
        # FEEDER_LABELS) are deleted (cascades to their items). Safe because notable accounts'
        # sources are roster-driven and carry no user-authored feeders today.
        desired_urls = {url for _, url in source_specs}
        existing_urls: set[str] = set()
        for src in session.scalars(
            select(Source).where(Source.user_id == user.id)
        ):
            if src.input_url in desired_urls:
                existing_urls.add(src.input_url)
                stats.sources_existing += 1
            else:
                session.delete(src)
                stats.sources_removed += 1
        for source_type, url in source_specs:
            if url not in existing_urls:
                session.add(
                    Source(user_id=user.id, type=source_type, input_url=url)
                )
                stats.sources_created += 1

        # Profile links: declarative — replace wholesale so the roster governs (and prior-run
        # feeder URLs mis-filed as links get cleaned up). Safe because notable accounts are
        # roster-driven and don't carry user-authored links today.
        session.execute(delete(ProfileLink).where(ProfileLink.user_id == user.id))
        for position, (label, url) in enumerate(display_specs):
            if position >= config.MAX_LINKS:
                stats.links_skipped += 1
                stats.warnings.append(
                    f"{spec.name}: '{label}' skipped — over MAX_LINKS={config.MAX_LINKS}"
                )
                continue
            session.add(
                ProfileLink(user_id=user.id, label=label, url=url, position=position)
            )
            stats.links_set += 1

    session.commit()
    return stats
