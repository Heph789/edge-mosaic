"""Operator CLI.

    python -m app.cli import-allowlist [csv]  # seed allowed_emails + pre-seed named users
    python -m app.cli seed-sources [md]       # pre-seed feeders + sources from source-list.md
    python -m app.cli seed-notable [json]     # pre-seed notable speakers + their profile links
    python -m app.cli scrape                  # fetch all real sources, dedup-insert items

The digest send runs as a job entrypoint, not here: `python -m app.jobs.digest`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from . import config
from .allowlist import import_allowlist
from .config import API_DIR
from .db import SessionLocal
from .ingest import scrape
from .seed import SOURCE_LIST_PATH, seed_sources
from .seed_notable import NOTABLE_PATH, seed_notable_speakers


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
            print(f"  ✓ {r.input_url:<40} {r.new_items:>3} new, {r.seen_items:>3} seen")
        else:
            print(f"  ✗ {r.input_url:<40} FAILED — {r.error}")
    print(f"\n{total_new} new item(s) stored.")


def cmd_seed_sources(md_arg: str | None) -> int:
    ensure_schema()
    md_path = Path(md_arg) if md_arg else SOURCE_LIST_PATH
    if not md_path.exists():
        print(f"source list not found: {md_path}", file=sys.stderr)
        return 1

    with SessionLocal() as session:
        stats = seed_sources(session, md_path)

    print(f"Seeded from {md_path.name}:")
    print(f"  {stats.feeders_created} feeders created ({stats.feeders_existing} already present)")
    print(f"  {stats.sources_created} sources created ({stats.sources_existing} already present)")
    print(f"  {stats.urls_skipped} URLs skipped (X/Twitter, GitHub — no adapter)")
    return 0


def cmd_seed_notable(json_arg: str | None) -> int:
    ensure_schema()
    json_path = Path(json_arg) if json_arg else NOTABLE_PATH
    if not json_path.exists():
        print(f"notable list not found: {json_path}", file=sys.stderr)
        return 1

    with SessionLocal() as session:
        stats = seed_notable_speakers(session, json_path)

    print(f"Seeded from {json_path.name}:")
    print(
        f"  {stats.created} notables created, {stats.promoted} promoted, "
        f"{stats.existing} already present"
    )
    print(
        f"  {stats.sources_created} sources created ({stats.sources_existing} already "
        f"present, {stats.sources_removed} removed)"
    )
    print(f"  {stats.links_set} profile links set ({stats.links_skipped} skipped)")
    for w in stats.warnings:
        print(f"  ! {w}", file=sys.stderr)
    return 0


def cmd_import_allowlist(csv_arg: str | None) -> int:
    ensure_schema()
    csv_path = Path(csv_arg) if csv_arg else config.ALLOWLIST_CSV_DEFAULT
    if csv_path is None:
        print("No CSV given and none found in api/input/. Pass a path.", file=sys.stderr)
        return 1
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    with SessionLocal() as session:
        stats = import_allowlist(session, csv_path)

    print(f"Imported from {csv_path.name}:")
    print(f"  {stats.imported} new allowlist entries ({stats.already_present} already present)")
    print(f"  {stats.seeded} users pre-seeded")
    print(f"  {stats.skipped_no_email} rows skipped (no email)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Edge Mosaic operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    imp_p = sub.add_parser("import-allowlist", help="seed allowed_emails + pre-seed named users")
    imp_p.add_argument("csv", nargs="?", default=None, help="path to roster CSV (defaults to api/input/attendees-*.csv)")
    seed_p = sub.add_parser("seed-sources", help="pre-seed feeders + sources from source-list.md")
    seed_p.add_argument("md", nargs="?", default=None, help="path to source list (defaults to docs/source-list.md)")
    notable_p = sub.add_parser("seed-notable", help="pre-seed notable speakers + their profile links")
    notable_p.add_argument("json", nargs="?", default=None, help="path to notable list (defaults to docs/notable-speakers.json)")
    sub.add_parser("scrape", help="fetch all real sources and store deduped items")

    args = parser.parse_args(argv)
    if args.command == "import-allowlist":
        return cmd_import_allowlist(args.csv)
    elif args.command == "seed-sources":
        return cmd_seed_sources(args.md)
    elif args.command == "seed-notable":
        return cmd_seed_notable(args.json)
    elif args.command == "scrape":
        cmd_scrape()
    return 0


if __name__ == "__main__":
    sys.exit(main())
