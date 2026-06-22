"""Daily scrape job — fetch every source, dedup-insert items. (Railway cron: scrape.)"""

from __future__ import annotations

import logging

import sentry_sdk

from ..db import SessionLocal
from ..ingest import scrape
from ..observability import init_sentry


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_sentry("scrape")
    with SessionLocal() as session:
        results = scrape(session)

    # Each source's per-source try/except swallows failures so one dead feed can't kill the
    # run — which also means nothing ever surfaces them. Report them to Sentry here (cron
    # context only; the inline add-time scrape handles its own failure as a 422).
    for r in results:
        if not r.ok and r.exception is not None:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("job", "scrape")
                scope.set_context(
                    "source", {"id": r.source_id, "input_url": r.input_url}
                )
                sentry_sdk.capture_exception(r.exception)

    total_new = sum(r.new_items for r in results)
    ok = sum(1 for r in results if r.ok)
    print(
        f"scrape job: {len(results)} sources, {ok} ok, "
        f"{len(results) - ok} failed, {total_new} new items"
    )
    # Cron process exits immediately after main(); flush the background transport first so
    # captured events aren't dropped.
    sentry_sdk.flush()


if __name__ == "__main__":
    main()
