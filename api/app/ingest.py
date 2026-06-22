"""Scrape orchestration: fetch each real source → dedup-insert items.

Per-source try/except is the whole point — one dead source must not kill the run.
Slice 3: sources are real `user_id`-owned rows (no more hardcoded list).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import get_adapter
from .models import Item, Source, utcnow


@dataclass
class SourceResult:
    source_id: int | None
    input_url: str
    ok: bool
    new_items: int = 0
    seen_items: int = 0
    error: str | None = None
    # The original exception, retained so the scrape *cron* can report it to Sentry with a
    # real traceback. Deliberately not captured here: scrape_source also runs inline on
    # `POST /sources`, where a failure is an expected, user-facing 422 — not an alert.
    exception: BaseException | None = field(default=None, repr=False, compare=False)


def scrape(session: Session) -> list[SourceResult]:
    """Global scrape over every source. (Slice 4 wraps this in the daily cron.)"""
    sources = list(session.scalars(select(Source)).all())
    return [scrape_source(session, source) for source in sources]


def scrape_source(session: Session, source: Source) -> SourceResult:
    """Fetch one source and dedup-insert its items. Also the inline first-scrape on add."""
    source.last_checked_at = utcnow()
    result = SourceResult(source_id=source.id, input_url=source.input_url, ok=False)

    try:
        adapter = get_adapter(source.type)
        normalized = adapter.fetch(source)
    except Exception as exc:  # isolate: a dead source returns nothing, run continues
        result.error = f"{type(exc).__name__}: {exc}"
        result.exception = exc
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
