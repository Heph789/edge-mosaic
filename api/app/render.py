"""Render the digest: items from the last ~30 days, grouped + capped per feeder.

This Jinja template is the seed of the real digest email template (Slice 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    DIGEST_OUTPUT_PATH,
    DIGEST_WINDOW_DAYS,
    LONG_ITEMS_CAP,
    SHORT_ITEMS_CAP,
    SHORT_TEXT_RENDER_CHARS,
)
from .models import Item, Source
from .text import truncate_on_word

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        # Always escape: every value rendered is scraped content (XSS rule). Note the
        # template is named .html.j2, so extension-based select_autoescape would skip it.
        autoescape=True,
    )
    env.filters["truncate_words"] = truncate_on_word
    return env


def _published(item: Item) -> datetime:
    return item.published_at


def source_label(source: Source) -> str:
    """Subheading for a source: its pulled publication name (sources.title), 'Bluesky'
    for Bluesky, falling back to the host if a feed had no title."""
    if source.type == "bluesky":
        return "Bluesky"
    if source.title:
        return source.title
    host = urlparse(source.resolved_feed_url or source.input_url).netloc
    return host or source.input_url


def build_feeders(session: Session) -> list[dict]:
    """Group last-window items by feeder → by source, capping per feeder (Slice 1 §Render).

    Caps stay per-feeder (≤N long, ≤3 short across all of a feeder's sources); the kept
    items are then partitioned by source for display, with each source's pulled title as a
    subheading and long-form sources listed above short-form ones.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_WINDOW_DAYS)
    rows = session.execute(
        select(Item, Source)
        .join(Source, Item.source_id == Source.id)
        .where(Item.published_at >= cutoff)
    ).all()

    # feeder_name -> source_id -> {"source", "long"[], "short"[]}
    grouped: dict[str, dict[int, dict]] = {}
    for item, source in rows:
        by_source = grouped.setdefault(source.feeder_name, {})
        bucket = by_source.setdefault(
            source.id, {"source": source, "long": [], "short": []}
        )
        bucket[item.kind].append(item)

    feeders: list[dict] = []
    for name, by_source in grouped.items():
        # Per-feeder caps applied across all the feeder's sources.
        all_long = [i for b in by_source.values() for i in b["long"]]
        all_short = [i for b in by_source.values() for i in b["short"]]
        keep_long = {i.id for i in sorted(all_long, key=_published, reverse=True)[:LONG_ITEMS_CAP]}
        keep_short = {i.id for i in sorted(all_short, key=_published, reverse=True)[:SHORT_ITEMS_CAP]}

        source_blocks: list[dict] = []
        for bucket in by_source.values():
            longs = sorted(
                (i for i in bucket["long"] if i.id in keep_long), key=_published, reverse=True
            )
            shorts = sorted(
                (i for i in bucket["short"] if i.id in keep_short), key=_published, reverse=True
            )
            if not longs and not shorts:
                continue
            source_blocks.append(
                {
                    "label": source_label(bucket["source"]),
                    "longs": longs,
                    "shorts": shorts,
                    "has_long": bool(longs),
                    "recency": max(_published(i) for i in (*longs, *shorts)),
                }
            )

        if not source_blocks:
            continue
        # Long-form sources above short-form; ties broken by recency.
        source_blocks.sort(key=lambda s: (s["has_long"], s["recency"]), reverse=True)
        feeders.append(
            {
                "name": name,
                "sources": source_blocks,
                "last_activity": max(s["recency"] for s in source_blocks),
            }
        )

    # Feeders ordered by most-recent activity.
    feeders.sort(key=lambda f: f["last_activity"], reverse=True)
    return feeders


def render_digest(session: Session, output_path: Path | None = None) -> Path:
    output_path = output_path or DIGEST_OUTPUT_PATH
    env = _build_env()
    template = env.get_template("digest.html.j2")
    html = template.render(
        feeders=build_feeders(session),
        generated_at=datetime.now(timezone.utc),
        window_days=DIGEST_WINDOW_DAYS,
        short_text_chars=SHORT_TEXT_RENDER_CHARS,
    )
    output_path.write_text(html, encoding="utf-8")
    return output_path
