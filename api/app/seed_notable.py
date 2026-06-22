"""Seed curated *notable speakers* (pre-seeded ghost users) from the notable-speakers roster.

The roster lives under the gitignored `data/` tree (it is not committed to the public repo);
its path is `NOTABLE_PATH` below. Because it isn't baked into the deploy image, production
seeding is run from a local checkout with `DATABASE_URL` pointed at the prod Postgres (see the
operator notes), not from inside the container.

Each entry becomes a **pre-seeded ghost user** (`verified_at` NULL — discoverable in the
Directory via `display_name`, never logged in), flagged `is_notable=True`, populated *as-is*
from the roster: full `display_name`, optional email, and its channels split into:
  - **sources** (scraped feeders) for feed-bearing platforms — Substack, YouTube, Medium,
    Mastodon, blogs, podcasts, Bluesky — routed through `detect_type` like `seed_sources`.
  - **profile_links** (display only) for everything else — X, LinkedIn, GitHub, Instagram, …

Idempotent. Dedup key: `email` when present (and *promote* a pre-existing user to notable),
else (`display_name`, `is_notable`). The roster is the **source of truth** and seeding is fully
declarative, so each run reconciles the DB to the roster:
  - rewrites the notable's `display_name`;
  - **replaces** its `profile_links` wholesale;
  - reconciles its `sources` — kept feeders are left untouched (preserving scrape state:
    `resolved_feed_url`, items), feeders no longer in the roster are deleted (cascading items);
  - **reconciles** notable *ghosts* (`verified_at` NULL) no longer in the roster: a ghost whose
    email is a *named* allowlist entry is **demoted** back to a plain pre-seeded attendee (the
    exact row `import_allowlist` would create — abbreviated `allowed_emails.name`, `is_notable`
    cleared, curated links/sources stripped); any other ghost is **deleted** outright, cascading
    sources→items, links, cities, villages, and subscriptions referencing it. A notable later
    *claimed* by a real person (`verified_at` set) is never touched.

So removing a row/link from the roster + re-running is how a notable (or one of its links) is
removed from a deployed DB — and an attendee who's also on the allowlist survives as a normal
pre-seed rather than vanishing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import config
from .config import API_DIR
from .models import AllowedEmail, ProfileLink, Source, Subscription, User
from .sources import SourceRejected, detect_type
from .villages import assign_default_village

NOTABLE_PATH = (
    API_DIR.parent / "data" / "edge-esmeralda-2026" / "notable-speakers.json"
)

# Channel labels whose URLs are feed-bearing → stored as scraped `sources` (the RSS adapter
# resolves Substack /feed, Medium, Apple/Acast podcasts, Mastodon, plain blogs; Bluesky via
# its adapter). Everything else stays a display-only profile link.
#
# YouTube is intentionally NOT here: YouTube blocks its feeds/videos.xml endpoint from
# datacenter/cloud IPs (returns 404/500 for even valid channels, incl. the scraper's host),
# so a YouTube "feeder" would just fail every scrape. It rides along as a display link.
FEEDER_LABELS = {"Substack", "Medium", "Mastodon", "Blog", "Podcast", "Bluesky"}


@dataclass
class NotableSpec:
    name: str
    email: str | None
    links: list[tuple[str, str]]  # (label, url) in display order


def parse_notable_list(text: str) -> list[NotableSpec]:
    """Parse the JSON roster into specs, normalizing email to lowercase."""
    specs: list[NotableSpec] = []
    for row in json.loads(text):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        email = (row.get("email") or "").strip().lower() or None
        links = [
            (str(l["label"]).strip(), str(l["url"]).strip())
            for l in (row.get("links") or [])
            if l.get("label") and l.get("url")
        ]
        specs.append(NotableSpec(name=name, email=email, links=links))
    return specs


@dataclass
class NotableStats:
    created: int = 0
    promoted: int = 0  # pre-existing user flagged notable
    existing: int = 0
    sources_created: int = 0
    sources_existing: int = 0
    sources_removed: int = 0  # no longer feeders in the roster (e.g. demoted)
    notables_removed: int = 0  # ghost notables deleted (dropped, not on allowlist)
    notables_demoted: int = 0  # ghost notables demoted to a plain pre-seed (on allowlist)
    links_set: int = 0
    links_skipped: int = 0  # over MAX_LINKS
    warnings: list[str] = field(default_factory=list)


def _find_user(session: Session, spec: NotableSpec) -> User | None:
    if spec.email is not None:
        return session.scalar(select(User).where(User.email == spec.email))
    # Email-less: best available stable key is the display name among notables.
    return session.scalar(
        select(User).where(
            User.display_name == spec.name, User.is_notable.is_(True)
        )
    )


def _partition_links(
    spec: NotableSpec,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split a spec's links into (sources, display_links). A feeder-labelled URL that
    `detect_type` rejects (e.g. an X link mislabelled) falls back to a display link."""
    sources: list[tuple[str, str]] = []  # (source_type, url)
    display: list[tuple[str, str]] = []  # (label, url)
    for label, url in spec.links:
        if label in FEEDER_LABELS:
            try:
                sources.append((detect_type(url), url))
                continue
            except SourceRejected:
                pass
        display.append((label, url))
    return sources, display


def _delete_user_deep(session: Session, user: User) -> None:
    """Remove a notable ghost and everything that references it. Sources cascade to their
    items via the ORM relationship; links/cities/villages cascade off the User relationship.
    Subscriptions FK `users.id` on *both* sides with no cascade, so clear them explicitly to
    avoid orphaning a row on Postgres (where the FK is enforced)."""
    for src in session.scalars(select(Source).where(Source.user_id == user.id)):
        session.delete(src)  # cascades items
    session.execute(
        delete(Subscription).where(
            (Subscription.feeder_id == user.id)
            | (Subscription.subscriber_id == user.id)
        )
    )
    session.delete(user)  # cascades links, cities, villages


def _strip_curated_content(session: Session, user: User) -> None:
    """Drop the roster-curated sources (cascading items) and profile links from a notable —
    used when demoting it back to a plain pre-seed, which carries neither."""
    for src in session.scalars(select(Source).where(Source.user_id == user.id)):
        session.delete(src)  # cascades items
    session.execute(delete(ProfileLink).where(ProfileLink.user_id == user.id))


def _prune_orphan_notables(
    session: Session, kept_ids: set[int], stats: NotableStats
) -> None:
    """Reconcile notable *ghosts* (`verified_at` NULL) no longer in the roster. A notable later
    claimed/verified by a real person is never touched. For each dropped ghost:
      - if its email is a *named* allowlist entry → **demote** to a plain pre-seeded attendee
        (abbreviated `allowed_emails.name`, `is_notable` cleared, curated links/sources stripped)
        — exactly the row `import_allowlist` pre-seeds, so the attendee doesn't vanish;
      - otherwise → **delete** outright, cascading everything."""
    orphans = session.scalars(
        select(User).where(
            User.is_notable.is_(True),
            User.verified_at.is_(None),
            User.id.notin_(kept_ids),
        )
    ).all()
    for user in orphans:
        allowed = (
            session.scalar(
                select(AllowedEmail).where(AllowedEmail.email == user.email)
            )
            if user.email
            else None
        )
        if allowed is not None and allowed.name is not None:
            user.is_notable = False
            user.display_name = allowed.name
            _strip_curated_content(session, user)
            stats.notables_demoted += 1
            stats.warnings.append(
                f"demoted notable to pre-seed (on allowlist): {allowed.name} (id={user.id})"
            )
        else:
            stats.warnings.append(
                f"pruned notable no longer in roster: {user.display_name} (id={user.id})"
            )
            _delete_user_deep(session, user)
            stats.notables_removed += 1


def seed_notable_speakers(session: Session, path: Path | None = None) -> NotableStats:
    text = (path or NOTABLE_PATH).read_text(encoding="utf-8")
    specs = parse_notable_list(text)
    stats = NotableStats()
    kept_ids: set[int] = set()

    for spec in specs:
        user = _find_user(session, spec)
        if user is None:
            # Pre-seeded ghost: discoverable by display_name, never logged in (verified_at NULL).
            user = User(email=spec.email, display_name=spec.name, is_notable=True)
            session.add(user)
            session.flush()  # assign user.id for the username + links below
            user.username = f"user-{user.id}"  # canonical placeholder handle
            assign_default_village(session, user)
            stats.created += 1
        else:
            if not user.is_notable:
                user.is_notable = True  # promote a pre-existing (e.g. allowlisted) account
                stats.promoted += 1
            else:
                stats.existing += 1
            # Roster is source of truth: refresh the display name (fixes abbreviated rosters).
            user.display_name = spec.name

        kept_ids.add(user.id)
        source_specs, display_specs = _partition_links(spec)

        # Sources: reconcile to the roster. Kept feeders are left untouched (preserves scrape
        # state — resolved_feed_url, items); feeders no longer in the roster (e.g. demoted from
        # FEEDER_LABELS) are deleted (cascades to their items). Safe because notable accounts'
        # sources are roster-driven and carry no user-authored feeders today.
        desired_urls = {url for _, url in source_specs}
        existing_urls: set[str] = set()
        for src in session.scalars(
            select(Source).where(Source.user_id == user.id)
        ):
            if src.input_url in desired_urls:
                existing_urls.add(src.input_url)
                stats.sources_existing += 1
            else:
                session.delete(src)
                stats.sources_removed += 1
        for source_type, url in source_specs:
            if url not in existing_urls:
                session.add(
                    Source(user_id=user.id, type=source_type, input_url=url)
                )
                stats.sources_created += 1

        # Profile links: declarative — replace wholesale so the roster governs (and prior-run
        # feeder URLs mis-filed as links get cleaned up). Safe because notable accounts are
        # roster-driven and don't carry user-authored links today.
        session.execute(delete(ProfileLink).where(ProfileLink.user_id == user.id))
        for position, (label, url) in enumerate(display_specs):
            if position >= config.MAX_LINKS:
                stats.links_skipped += 1
                stats.warnings.append(
                    f"{spec.name}: '{label}' skipped — over MAX_LINKS={config.MAX_LINKS}"
                )
                continue
            session.add(
                ProfileLink(user_id=user.id, label=label, url=url, position=position)
            )
            stats.links_set += 1

    # Prune notable ghosts dropped from the roster — but only if the roster actually parsed to
    # something, so a missing/empty file can never wipe the whole notable directory.
    if specs:
        _prune_orphan_notables(session, kept_ids, stats)

    session.commit()
    return stats
