"""Operator CLI.

    python -m app.cli import-allowlist [csv]  # seed allowed_emails + pre-seed named users
    python -m app.cli scrape    # (dormant since Slice 2 — needs real user_id sources)
    python -m app.cli render    # (dormant since Slice 2)
    python -m app.cli run       # scrape then render
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from alembic import command
from alembic.config import Config

from . import config
from .allowlist import import_allowlist
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
            print(f"  ✓ {r.input_url:<40} {r.new_items:>3} new, {r.seen_items:>3} seen")
        else:
            print(f"  ✗ {r.input_url:<40} FAILED — {r.error}")
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
    parser = argparse.ArgumentParser(prog="app.cli", description="Edge Mosaic ingestion spike")
    sub = parser.add_subparsers(dest="command", required=True)
    imp_p = sub.add_parser("import-allowlist", help="seed allowed_emails + pre-seed named users")
    imp_p.add_argument("csv", nargs="?", default=None, help="path to roster CSV (defaults to api/input/attendees-*.csv)")
    sub.add_parser("scrape", help="(dormant since Slice 2) fetch hardcoded sources")
    render_p = sub.add_parser("render", help="(dormant since Slice 2) render the HTML digest")
    render_p.add_argument("--no-open", action="store_true", help="don't open a browser")
    sub.add_parser("run", help="scrape then render")

    args = parser.parse_args(argv)
    if args.command == "import-allowlist":
        return cmd_import_allowlist(args.csv)
    elif args.command == "scrape":
        cmd_scrape()
    elif args.command == "render":
        cmd_render(open_browser=not args.no_open)
    elif args.command == "run":
        cmd_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
