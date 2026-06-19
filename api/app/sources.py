"""Real sources for the spike, parsed from `docs/source-list.md`, + a dialect-agnostic
upsert.

The doc is the source of truth: one feeder name per stanza, followed by its URLs. Each
URL is classified to an adapter; URLs with no adapter (X/Twitter, GitHub) are skipped so
per-feeder coverage degrades to whatever *does* resolve rather than failing the feeder.

Deliberately select-then-insert (no SQLite `on_conflict_*`) so the dedup logic
survives the move to Postgres.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import API_DIR
from .models import Source

# docs/ lives at the repo root, one level above the `api/` package dir.
SOURCE_LIST_PATH = API_DIR.parent / "docs" / "source-list.md"


def _classify_url(url: str) -> str | None:
    """Map a URL to its adapter type, or None if we have no adapter for it.

    RSS is the catch-all: it resolves plain blogs, Substack, Medium, Mastodon (via
    autodiscovery), and YouTube/Apple-Podcasts directory pages. X/Twitter and GitHub
    have no feed adapter in the spike, so they're skipped (see mvp-plan deferred list).
    """
    u = url.lower()
    if "bsky.app/profile/" in u:
        return "bluesky"
    if "x.com/" in u or "twitter.com/" in u:
        return None  # X/Twitter — deferred, no public adapter
    if "github.com/" in u:
        return None  # GitHub activity — no feed adapter
    return "rss"


def load_source_specs(path: Path | None = None) -> list[dict[str, str]]:
    """Parse `source-list.md` into {feeder_name, type, url} specs (unsupported URLs dropped)."""
    path = path or SOURCE_LIST_PATH
    specs: list[dict[str, str]] = []
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("http://", "https://")):
            if current is None:
                continue
            type_ = _classify_url(line)
            if type_ is not None:
                specs.append({"feeder_name": current, "type": type_, "url": line})
        else:
            current = line  # a non-URL, non-blank line is the next feeder's name
    return specs


def upsert_sources(session: Session) -> list[Source]:
    """Ensure every spec from `source-list.md` exists, keyed on (feeder_name, input_url)."""
    for spec in load_source_specs():
        existing = session.scalar(
            select(Source).where(
                Source.feeder_name == spec["feeder_name"],
                Source.input_url == spec["url"],
            )
        )
        if existing is None:
            session.add(
                Source(
                    feeder_name=spec["feeder_name"],
                    type=spec["type"],
                    input_url=spec["url"],
                )
            )
    session.commit()
    return list(session.scalars(select(Source)).all())
