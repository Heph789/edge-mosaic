"""Throwaway CLI entrypoint for the spike (only this file is disposable).

    python -m app.cli scrape    # upsert sources, fetch, dedup-insert items
    python -m app.cli render    # build the HTML digest and open it
    python -m app.cli run       # scrape then render
"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from alembic import command
from alembic.config import Config

from .config import API_DIR
from .db import SessionLocal
from .ingest import scrape
from .render import render_digest


def ensure_schema() -> None:
    """Bring the DB up to head. Alembic is the single source of truth for schema."""
    cfg = Config(str(API_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")


def cmd_scrape() -> None:
    ensure_schema()
    with SessionLocal() as session:
        results = scrape(session)

    print("\nScrape complete:")
    total_new = 0
    for r in results:
        total_new += r.new_items
        if r.ok:
            print(f"  ✓ {r.feeder_name:<18} {r.new_items:>3} new, {r.seen_items:>3} seen  ({r.input_url})")
        else:
            print(f"  ✗ {r.feeder_name:<18} FAILED — {r.error}")
    print(f"\n{total_new} new item(s) stored.")


def cmd_render(open_browser: bool = True) -> None:
    ensure_schema()
    with SessionLocal() as session:
        path = render_digest(session)
    print(f"Digest written to {path}")
    if open_browser:
        webbrowser.open(path.as_uri())


def cmd_run() -> None:
    cmd_scrape()
    cmd_render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Edge Mosaic ingestion spike")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scrape", help="fetch hardcoded sources and store deduped items")
    render_p = sub.add_parser("render", help="render the HTML digest")
    render_p.add_argument("--no-open", action="store_true", help="don't open a browser")
    sub.add_parser("run", help="scrape then render")

    args = parser.parse_args(argv)
    if args.command == "scrape":
        cmd_scrape()
    elif args.command == "render":
        cmd_render(open_browser=not args.no_open)
    elif args.command == "run":
        cmd_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
