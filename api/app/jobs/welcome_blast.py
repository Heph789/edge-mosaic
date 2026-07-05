"""One-time welcome blast to all verified users.

Usage:
    python -m app.jobs.welcome_blast email.html [--subject "..."] [--dry-run]

Reads the HTML file, sends it to every verified (verified_at IS NOT NULL) user
via the configured email backend. Pass --dry-run to print recipients without sending.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from ..db import SessionLocal
from ..email import send_email
from ..models import User
from ..observability import init_sentry

log = logging.getLogger("edge_mosaic.welcome_blast")

DEFAULT_SUBJECT = "Welcome to Edge Mosaic"


def run_blast(html: str, subject: str, dry_run: bool, to: str | None = None) -> dict[str, int]:
    stats = {"sent": 0, "skipped_no_email": 0, "errors": 0}
    with SessionLocal() as db:
        query = select(User).where(User.verified_at.is_not(None))
        if to:
            query = query.where(User.email == to.lower())
        users = list(db.scalars(query))
    log.info("%d verified user(s) found", len(users))
    for user in users:
        if not user.email:
            stats["skipped_no_email"] += 1
            continue
        if dry_run:
            print(f"  [dry-run] would send → {user.email} ({user.display_name})")
            stats["sent"] += 1
            continue
        try:
            send_email(to=user.email, subject=subject, html=html)
            stats["sent"] += 1
            log.info("sent → %s", user.email)
        except Exception as exc:
            stats["errors"] += 1
            log.error("failed → %s: %s", user.email, exc)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_sentry("welcome_blast")

    parser = argparse.ArgumentParser(description="One-time welcome blast")
    parser.add_argument("html_file", help="Path to HTML email body")
    parser.add_argument("--subject", default=DEFAULT_SUBJECT, help="Email subject line")
    parser.add_argument("--to", default=None, help="Send only to this email address")
    parser.add_argument("--dry-run", action="store_true", help="Print recipients, do not send")
    args = parser.parse_args()

    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f"error: file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    html = html_path.read_text()
    if args.dry_run:
        print(f"DRY RUN — subject: {args.subject}")

    stats = run_blast(html, args.subject, args.dry_run, to=args.to)
    label = "dry-run" if args.dry_run else "blast"
    print(f"welcome {label}: {stats}")


if __name__ == "__main__":
    main()
