"""Mirror Railway production data into the local dev database.

Copies every table from a *source* database (prod Postgres) into the *destination*
(the local SQLite file, `config.DATABASE_URL`). The models use only plain
String/Integer/Boolean/DateTime/Date columns — no native enums or JSON — so a
Postgres→SQLite copy goes through SQLAlchemy Core cleanly, with the dialects doing
the type coercion (bool→0/1, tz-aware datetime→stored wall-clock, etc.).

Auth material is skipped by design: `sessions` and `magic_link_tokens` are never
copied (pass --keep-auth to override). Everything else — users, profiles, sources,
items, subscriptions — is mirrored as-is.

The destination schema is (re)built by Alembic (`alembic upgrade head`), the same
mechanism the app uses, so the mirror matches whatever migration head the code is on.

Usage (normally invoked via scripts/mirror-prod-db.sh, which injects the source URL):

    SOURCE_DATABASE_URL=postgresql://user:pass@host:port/db  python -m app.mirror

Options:
    --source URL   source DB (defaults to $SOURCE_DATABASE_URL)
    --keep-auth    also copy sessions + magic_link_tokens (default: skip them)
    --yes / -y     don't prompt for confirmation
    --dest-force   allow a non-SQLite destination (safety off — you almost never want this)
"""

from __future__ import annotations

import argparse
import os
import sys

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import make_url

from .config import API_DIR, DATABASE_URL, _normalize_db_url
from .models import Base

# Auth/secret tables — never mirrored unless --keep-auth. Live login sessions and
# single-use magic-link tokens have no business sitting in a local test copy.
AUTH_TABLES = {"sessions", "magic_link_tokens"}

# Rows per executemany batch. Keeps the `items` table (potentially large) off the heap
# in one giant list-of-dicts and within SQLite's bound-parameter limits.
BATCH = 500


def _rebuild_dest_schema() -> None:
    """Build the local (destination) schema fresh at Alembic head — the app's own mechanism.

    A mirror replaces all local data anyway, so for a SQLite dest we delete the file first
    and migrate from base. That sidesteps a stale/mis-stamped local DB (e.g. schema ahead of
    its alembic_version) and guarantees the mirror's schema matches prod's migration head.
    Alembic reads config.DATABASE_URL, which is this same local DB.
    """
    url = make_url(DATABASE_URL)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).unlink(missing_ok=True)
    cfg = Config(str(API_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")


def mirror(source_url: str, *, keep_auth: bool = False) -> None:
    dest_url = DATABASE_URL  # local dev DB (SQLite by default)

    source_engine = create_engine(source_url, future=True)
    dest_engine = create_engine(dest_url, future=True)

    # Insert parents before children (FK order); delete children before parents.
    tables = list(Base.metadata.sorted_tables)

    copied: dict[str, int] = {}
    with source_engine.connect() as src, dest_engine.begin() as dst:
        # SQLite enforces FKs per-connection; turn them off for the bulk load so table
        # order/self-references (subscriptions, sources→users) can't trip us mid-copy.
        if dest_engine.dialect.name == "sqlite":
            dst.exec_driver_sql("PRAGMA foreign_keys=OFF")

        # Wipe destination first (reverse FK order) so this is a true mirror, not a merge.
        for table in reversed(tables):
            dst.execute(delete(table))

        for table in tables:
            if table.name in AUTH_TABLES and not keep_auth:
                copied[table.name] = 0  # left empty on purpose
                continue

            rows = src.execute(table.select()).mappings().all()
            if not rows:
                copied[table.name] = 0
                continue

            payload = [dict(r) for r in rows]
            for i in range(0, len(payload), BATCH):
                dst.execute(table.insert(), payload[i : i + BATCH])
            copied[table.name] = len(payload)

    print("\nMirror complete (source → local):")
    for table in tables:
        n = copied.get(table.name, 0)
        note = ""
        if table.name in AUTH_TABLES and not keep_auth:
            note = "  (auth — skipped)"
        print(f"  {table.name:<20} {n:>6} row(s){note}")
    total = sum(copied.values())
    print(f"\n{total} row(s) written to {dest_url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror prod DB data into the local dev DB.")
    parser.add_argument("--source", default=os.environ.get("SOURCE_DATABASE_URL", ""))
    parser.add_argument("--keep-auth", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--dest-force", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if not args.source:
        parser.error("no source database — set $SOURCE_DATABASE_URL or pass --source "
                     "(use scripts/mirror-prod-db.sh to pull it from Railway).")

    source_url = _normalize_db_url(args.source)

    # Safety: the destination is the local dev DB and must be SQLite. If someone's .env
    # points DATABASE_URL at a real Postgres, we would otherwise WIPE it — refuse.
    if not DATABASE_URL.startswith("sqlite") and not args.dest_force:
        parser.error(f"destination DATABASE_URL is not SQLite ({DATABASE_URL!r}); refusing "
                     "to overwrite it. Unset DATABASE_URL for the default local SQLite, or "
                     "pass --dest-force if you really mean it.")

    if source_url == _normalize_db_url(DATABASE_URL):
        parser.error("source and destination are the same database — nothing to mirror.")

    # Show the source host (never the password) so the operator can eyeball what they're pulling.
    safe_source = source_url
    if "@" in safe_source:
        creds, tail = safe_source.split("@", 1)
        scheme = creds.split("://", 1)[0] if "://" in creds else creds
        safe_source = f"{scheme}://***@{tail}"

    print(f"Source:      {safe_source}")
    print(f"Destination: {DATABASE_URL}")
    print(f"Auth tables: {'COPIED' if args.keep_auth else 'skipped (sessions, magic_link_tokens)'}")
    print("This REPLACES all data in the local dev DB.")

    if not args.yes:
        if input("Proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1

    _rebuild_dest_schema()
    mirror(source_url, keep_auth=args.keep_auth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
