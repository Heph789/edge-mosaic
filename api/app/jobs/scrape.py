"""Daily scrape job — fetch every source, dedup-insert items. (Railway cron: scrape.)"""

from __future__ import annotations

import logging

from ..db import SessionLocal
from ..ingest import scrape


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as session:
        results = scrape(session)
    total_new = sum(r.new_items for r in results)
    ok = sum(1 for r in results if r.ok)
    print(
        f"scrape job: {len(results)} sources, {ok} ok, "
        f"{len(results) - ok} failed, {total_new} new items"
    )


if __name__ == "__main__":
    main()
