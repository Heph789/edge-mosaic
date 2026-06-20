"""Source-list seeding — URL classification, parsing, idempotent feeder/source creation."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Source, User
from app.seed import classify_url, parse_source_list, seed_sources

SAMPLE = """\
Simon Willison
https://simonwillison.net/
https://bsky.app/profile/simonwillison.net
https://github.com/simonw
https://x.com/simonw

Theo Browne
https://t3.gg/
https://twitter.com/theo
"""


def test_classify_url():
    assert classify_url("https://bsky.app/profile/b0rk.jvns.ca") == "bluesky"
    assert classify_url("https://x.com/jack") is None
    assert classify_url("https://twitter.com/theo") is None
    assert classify_url("https://github.com/simonw") is None
    assert classify_url("https://simonwillison.net/") == "rss"  # RSS is the catch-all


def test_parse_drops_unsupported_urls():
    specs = parse_source_list(SAMPLE)
    assert [s.name for s in specs] == ["Simon Willison", "Theo Browne"]
    # X/Twitter + GitHub dropped; blog + Bluesky kept.
    assert specs[0].urls == [
        ("rss", "https://simonwillison.net/"),
        ("bluesky", "https://bsky.app/profile/simonwillison.net"),
    ]
    assert specs[1].urls == [("rss", "https://t3.gg/")]


def test_seed_creates_ghosts_and_is_idempotent(db, tmp_path):
    md = tmp_path / "source-list.md"
    md.write_text(SAMPLE, encoding="utf-8")

    stats = seed_sources(db, md)
    assert stats.feeders_created == 2
    assert stats.sources_created == 3  # 2 for Simon, 1 for Theo
    assert stats.urls_skipped == 3  # 2 GitHub/X + 1 Twitter

    simon = db.scalar(select(User).where(User.display_name == "Simon Willison"))
    assert simon is not None and simon.verified_at is None  # pre-seeded ghost

    # Re-running creates nothing new.
    again = seed_sources(db, md)
    assert again.feeders_created == 0 and again.sources_created == 0
    assert again.feeders_existing == 2 and again.sources_existing == 3
    assert db.scalar(select(func.count()).select_from(Source)) == 3
