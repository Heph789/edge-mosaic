"""Scrape orchestration: upsert sources → fetch each → dedup-insert items.

Per-source try/except is the whole point — one dead source must not kill the run.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import get_adapter
from .models import Item, Source, utcnow
from .sources import upsert_sources


@dataclass
class SourceResult:
    feeder_name: str
    input_url: str
    ok: bool
    new_items: int = 0
    seen_items: int = 0
    error: str | None = None


def scrape(session: Session) -> list[SourceResult]:
    sources = upsert_sources(session)
    results: list[SourceResult] = []

    for source in sources:
        results.append(_scrape_one(session, source))

    return results


def _scrape_one(session: Session, source: Source) -> SourceResult:
    source.last_checked_at = utcnow()
    result = SourceResult(feeder_name=source.feeder_name, input_url=source.input_url, ok=False)

    try:
        adapter = get_adapter(source.type)
        normalized = adapter.fetch(source)
    except Exception as exc:  # isolate: a dead source returns nothing, run continues
        result.error = f"{type(exc).__name__}: {exc}"
        session.commit()  # still persist last_checked_at + any resolution side effects
        return result

    for ni in normalized:
        already = session.scalar(
            select(Item.id).where(
                Item.source_id == source.id, Item.external_id == ni.external_id
            )
        )
        if already is not None:
            result.seen_items += 1
            continue
        session.add(
            Item(
                source_id=source.id,
                external_id=ni.external_id,
                kind=ni.kind,
                title=ni.title,
                url=ni.url,
                text=ni.text,
                excerpt=ni.excerpt,
                engagement_count=ni.engagement_count,
                published_at=ni.published_at,
                scraped_at=utcnow(),
            )
        )
        result.new_items += 1

    source.last_success_at = utcnow()
    result.ok = True
    session.commit()
    return result
