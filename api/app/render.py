"""Render the digest: items from the last ~30 days, grouped + capped per feeder.

This Jinja template is the seed of the real digest email template (Slice 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    DIGEST_OUTPUT_PATH,
    DIGEST_WINDOW_DAYS,
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


def build_feeders(session: Session) -> list[dict]:
    """Group last-window items by feeder, cap shorts, order everything (Slice 1 §Render)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_WINDOW_DAYS)
    rows = session.execute(
        select(Item, Source.feeder_name)
        .join(Source, Item.source_id == Source.id)
        .where(Item.published_at >= cutoff)
    ).all()

    grouped: dict[str, dict[str, list[Item]]] = {}
    for item, feeder_name in rows:
        bucket = grouped.setdefault(feeder_name, {"long": [], "short": []})
        bucket.setdefault(item.kind, []).append(item)

    feeders: list[dict] = []
    for name, buckets in grouped.items():
        longs = sorted(buckets.get("long", []), key=lambda i: i.published_at, reverse=True)
        shorts = sorted(buckets.get("short", []), key=lambda i: i.published_at, reverse=True)
        shorts = shorts[:SHORT_ITEMS_CAP]  # cap shorts to top-N by recency
        recency = [i.published_at for i in (*longs, *shorts)]
        feeders.append(
            {
                "name": name,
                "longs": longs,  # all long items, recency-ordered
                "shorts": shorts,
                "last_activity": max(recency) if recency else cutoff,
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
