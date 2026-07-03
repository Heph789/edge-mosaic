"""Seed pre-seeded *event speakers* (Edge Esmeralda directory).

Each roster entry becomes (or augments) a pre-seeded ghost user flagged `speaker=True`, with its
links split — feed-bearing platforms → `sources`, the rest → `profile_links` (like `seed_notable`).

Behaviour (per the operator's constraints):
  - **Tied to allowlist emails where possible.** A roster entry may carry an `email` (matched from
    the attendees export). If that email is actually in `allowed_emails`, the speaker is tied to it
    — found-or-created on that real inbox so the person *claims* the pre-seeded account on signup
    (same idea as the notables). An email not in the allowlist is ignored and the speaker is seeded
    email-less. No email → an email-less ghost matched by display name.
  - **Verified users are skipped entirely.** A row with `verified_at` set (a real person who logged
    in and set up what they wanted) is never touched — no flag, link, name, or visibility change.
    That `verified_at` gate *is* the "don't overwrite real user data" guarantee.
  - **Ghosts carry no user-authored data**, so a matched ghost is brought in line with the roster:
    `speaker` flag and full `display_name` (upgrading an abbreviated allowlist name like "Jess L."
    to "Jess Luibrand"). Bios are intentionally NOT seeded right now.
  - **Links only when the ghost has none.** Curated links/sources are added only to a content-less
    ghost; one that already has links/sources is left alone (not duplicated, not replaced).
  - **Ghosts are village-scoped.** A ghost this seed *initializes* (creates, or first populates) is
    set to `village` visibility — not edge-wide/community.
  - **Non-pruning.** Re-running with a different roster never drops speakers seeded earlier.

Matching: by `email` (when allowlisted) else by `display_name` among speaker/notable/email-less
ghosts only — so a speaker sharing a name with a *real emailed attendee* is never hijacked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from . import config
from .config import API_DIR
from .models import VISIBILITY_VILLAGE, AllowedEmail, ProfileLink, Source, User
from .seed_notable import FEEDER_LABELS
from .sources import SourceRejected, detect_type
from .usernames import is_available
from .villages import assign_default_village

SPEAKER_PATH = (
    API_DIR.parent
    / "data"
    / "edge-esmeralda-2026"
    / "june-25-bulk-speaker-add"
    / "speakers-loft.json"  # loft-only subset of speakers-final.json (spoke at The Loft venue)
)


@dataclass
class SpeakerSpec:
    name: str
    email: str | None
    bio: str | None
    links: list[tuple[str, str]]  # (label, url) in display order


def parse_speaker_list(text: str) -> list[SpeakerSpec]:
    specs: list[SpeakerSpec] = []
    for row in json.loads(text):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        email = (row.get("email") or "").strip().lower() or None
        bio = (row.get("bio") or row.get("one_line_bio") or "").strip() or None
        links = [
            (str(l["label"]).strip(), str(l["url"]).strip())
            for l in (row.get("links") or [])
            if l.get("label") and l.get("url")
        ]
        specs.append(SpeakerSpec(name=name, email=email, bio=bio, links=links))
    return specs


@dataclass
class SpeakerStats:
    created: int = 0
    created_with_email: int = 0  # of the created, how many tied to an allowlist inbox
    filled: int = 0  # existing content-less ghost populated as a speaker
    flagged_only: int = 0  # existing ghost already had content — only ensured speaker flag
    skipped_verified: int = 0  # matched a real (verified) user — left untouched
    skipped_name_collision: int = 0  # email-less entry shadowed a real emailed user — not created
    notables_flagged: int = 0  # is_notable rows set speaker=true (backfill)
    email_not_allowlisted: int = 0  # roster email absent from allowed_emails — seeded email-less
    sources_added: int = 0
    links_added: int = 0
    links_skipped: int = 0  # over MAX_LINKS
    warnings: list[str] = field(default_factory=list)


def _partition_links(
    spec: SpeakerSpec,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Same split as seed_notable: feeder-labelled URLs that `detect_type` accepts become sources;
    everything else (and feeder labels detect_type rejects) becomes a display link."""
    sources: list[tuple[str, str]] = []
    display: list[tuple[str, str]] = []
    for label, url in spec.links:
        if label in FEEDER_LABELS:
            try:
                sources.append((detect_type(url), url))
                continue
            except SourceRejected:
                pass
        display.append((label, url))
    return sources, display


def _email_allowlisted(session: Session, email: str) -> bool:
    return (
        session.scalar(select(AllowedEmail.email).where(AllowedEmail.email == email))
        is not None
    )


def _placeholder_username(session: Session, user_id: int) -> str:
    """The `user-{id}` placeholder, made collision-safe. Normally the id-aligned slug is free
    and returned as-is (preserving the `user-N == id` convention). But a DB whose id-space was
    rebuilt/mirrored can carry a *stale* `user-N` handle on some other row (e.g. a real user at
    id 636 still holding `user-697`); marching new ids through N would then hit a UNIQUE
    violation on users.username. When that happens, fall back to a suffixed slug so the seed
    can't be wedged by pre-existing username drift."""
    base = f"user-{user_id}"
    if is_available(session, base, exclude_id=user_id):
        return base
    suffix = 2
    while not is_available(session, f"{base}-{suffix}", exclude_id=user_id):
        suffix += 1
    return f"{base}-{suffix}"


def _real_emailed_user_with_name(session: Session, name: str) -> User | None:
    """A user with this display_name who owns an email — i.e. a real/claimable account (a
    verified sign-up or an allowlist pre-seed). The email-less branch of `_find_user` skips
    these on purpose (a shared name mustn't hijack a real inbox), so an email-less roster entry
    for the *same* person — one whose name→email match we missed — would otherwise create a
    duplicate ghost shadowing them. This lets the caller detect that and skip+warn instead."""
    return session.scalar(
        select(User)
        .where(User.display_name == name, User.email.is_not(None))
        .order_by(User.id)
        .limit(1)
    )


def _find_user(session: Session, email: str | None, name: str) -> User | None:
    if email is not None:
        return session.scalar(select(User).where(User.email == email))
    # Email-less: only match a prior speaker/notable ghost or an email-less ghost — never a real
    # emailed attendee who merely shares this name.
    return session.scalar(
        select(User)
        .where(
            User.display_name == name,
            or_(User.speaker.is_(True), User.is_notable.is_(True), User.email.is_(None)),
        )
        .order_by(User.id)
        .limit(1)
    )


def _has_curated_content(session: Session, user: User) -> bool:
    has_source = session.scalar(
        select(Source.id).where(Source.user_id == user.id).limit(1)
    )
    has_link = session.scalar(
        select(ProfileLink.id).where(ProfileLink.user_id == user.id).limit(1)
    )
    return has_source is not None or has_link is not None


def _add_links(session: Session, user: User, spec: SpeakerSpec, stats: SpeakerStats) -> None:
    """Add a spec's links — sources for feeders, profile_links for the rest. Only called for a
    content-less user, so it never duplicates or replaces."""
    source_specs, display_specs = _partition_links(spec)
    for source_type, url in source_specs:
        session.add(Source(user_id=user.id, type=source_type, input_url=url))
        stats.sources_added += 1
    for position, (label, url) in enumerate(display_specs):
        if position >= config.MAX_LINKS:
            stats.links_skipped += 1
            stats.warnings.append(
                f"{spec.name}: '{label}' skipped — over MAX_LINKS={config.MAX_LINKS}"
            )
            continue
        session.add(ProfileLink(user_id=user.id, label=label, url=url, position=position))
        stats.links_added += 1


def seed_speakers(session: Session, path: Path | None = None) -> SpeakerStats:
    specs = parse_speaker_list((path or SPEAKER_PATH).read_text(encoding="utf-8"))
    stats = SpeakerStats()

    # Invariant: every notable is also a speaker. One blanket backfill (idempotent).
    res = session.execute(
        update(User).where(User.is_notable.is_(True), User.speaker.is_(False)).values(speaker=True)
    )
    stats.notables_flagged = res.rowcount or 0

    for spec in specs:
        # Only tie to an email that's actually in the allowlist; otherwise seed email-less.
        email = spec.email
        if email is not None and not _email_allowlisted(session, email):
            stats.email_not_allowlisted += 1
            stats.warnings.append(
                f"{spec.name}: roster email {email} not in allowlist — seeding email-less"
            )
            email = None

        user = _find_user(session, email, spec.name)

        if user is not None and user.verified_at is not None:
            stats.skipped_verified += 1  # real user — never changed
            continue

        if user is None:
            # Safety net: an email-less entry about to be created as a fresh ghost, while a real
            # emailed user already holds this exact display_name, almost always means we failed to
            # capture this person's email (see match_speaker_emails.py) — creating would duplicate
            # them. Skip and surface it for a human rather than polluting the directory. (When the
            # entry HAS an email we don't guard: that's a legitimate new tie, and a same-named real
            # user would be a genuinely different person.)
            if email is None:
                shadowed = _real_emailed_user_with_name(session, spec.name)
                if shadowed is not None:
                    stats.skipped_name_collision += 1
                    stats.warnings.append(
                        f"{spec.name}: email-less entry shadows real user {shadowed.email} "
                        f"(id {shadowed.id}) — skipped to avoid a duplicate; fix the name→email match"
                    )
                    continue
            user = User(
                email=email,
                display_name=spec.name,
                speaker=True,
                visibility=VISIBILITY_VILLAGE,  # ghosts are village-scoped, not edge-wide
            )
            session.add(user)
            session.flush()  # assign id for username + links
            user.username = _placeholder_username(session, user.id)
            assign_default_village(session, user)
            _add_links(session, user, spec, stats)
            stats.created += 1
            if email is not None:
                stats.created_with_email += 1
            continue

        # Existing pre-seeded ghost (allowlist pre-seed or prior speaker) — never verified, so it
        # carries no user-authored data. Bring its metadata in line with the roster (this upgrades
        # an abbreviated allowlist name to the full speaker name).
        user.speaker = True
        user.display_name = spec.name
        if _has_curated_content(session, user):
            stats.flagged_only += 1  # already has links — leave its content untouched (no dupes)
        else:
            # Initializing a content-less ghost as a speaker: village-scope it and add its links.
            user.visibility = VISIBILITY_VILLAGE
            _add_links(session, user, spec, stats)
            stats.filled += 1

    session.commit()
    return stats


__all__ = ["seed_speakers", "SpeakerStats", "SPEAKER_PATH", "parse_speaker_list"]
