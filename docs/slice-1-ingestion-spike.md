# Slice 1 — Ingestion Spike (Walking Skeleton)

Detailed build spec for the first slice. Parent: [`mvp-plan.md`](./mvp-plan.md).

## Goal

De-risk the only part of the project with real technical uncertainty — **ingestion** —
before investing in auth or frontend. Prove, end-to-end and backend-only, that we can:

**scrape hardcoded real sources → store deduped `items` → render a digest you can eyeball.**

When the rendered digest looks right against real Edge content, the riskiest part is
solved and the `items` data model is validated. No auth, no frontend, no real
subscribers in this slice.

## Tooling

| Concern | Choice | Notes |
|---|---|---|
| Package manager | **`uv`** | venv + deps + lockfile |
| Dev database | **SQLite** (file) | zero-setup, fast loop. **Prod is Postgres from Slice 4** |
| ORM / migrations | **SQLAlchemy 2.0 (typed) + Alembic** | models/migrations carry forward; only the CLI entrypoint is throwaway |
| RSS | **`feedparser`** + **`httpx`** (fetch) + **`beautifulsoup4`** (autodiscovery + HTML-strip) | |
| Bluesky | **`atproto`** SDK | handles handle→DID + `getAuthorFeed` |
| Render | **Jinja2** → HTML file | seed of the real digest email template |

### Avoid SQLite-isms (dev SQLite → prod Postgres)
- **Upsert:** no dialect-specific `sqlite.insert(...).on_conflict_*`. Isolate the upsert
  behind one swappable helper, or use select-then-insert dedup.
- **`items.kind`:** plain string column (SQLAlchemy `Enum`/`String`), not a native PG enum.
- Keep all models dialect-agnostic. (`ILIKE` search is Slice 3, not here.)

## Schema subset (build only these two tables)

```
sources
  id · feeder_name (TEXT, temporary stub — becomes user_id FK in Slice 2)
  type ('rss'|'bluesky') · input_url · resolved_feed_url / external_id
  title · last_checked_at · last_success_at · created_at

items
  id · source_id · external_id · kind ('long'|'short')
  title (nullable) · url · text (nullable) · excerpt (nullable)
  engagement_count (default 0) · published_at · scraped_at
  UNIQUE(source_id, external_id)
```

Hardcoded sources live in a small Python/YAML list of `{feeder_name, url}` that the
spike upserts into `sources` (a couple Substacks, one feed-having blog, a Bluesky handle).

## Adapter interface

```python
class FeedAdapter(Protocol):
    def fetch(self, source: Source) -> list[NormalizedItem]: ...

# NormalizedItem fields:
#   external_id · kind · title? · url · text? · excerpt?
#   engagement_count · published_at
```
Wrap each source's fetch in try/except so one dead source can't kill the run.

### RSS adapter (`url → list[NormalizedItem]`)
**Resolve the feed** (this logic is reused as the add-time validator in Slice 3):
1. If the URL already parses as a feed, use it.
2. Else fetch HTML, read `<link rel="alternate" type="application/rss+xml|atom+xml">`,
   resolve relative→absolute.
3. Else try common paths: `/feed`, `/rss`, `/feed.xml`, `/atom.xml`, `/index.xml`.
4. Else fail.

**Per entry → NormalizedItem:**
- `external_id` = `entry.id`/guid → fallback `entry.link` → fallback `hash(title+link)`
- `kind = 'long'`, `title = entry.title`, `url = entry.link`
- `excerpt` = `entry.summary`/description, **HTML-stripped** (bs4 `get_text`),
  **truncated to ~200 chars on a word boundary**
- `text = None`, `engagement_count = 0`
- `published_at` = `published_parsed`/`updated_parsed` → tz-aware datetime;
  **fallback to `scraped_at`** if missing/garbage

### Bluesky adapter (`handle | profile URL → list[NormalizedItem]`)
- Extract handle → **resolve to DID** → `getAuthorFeed(actor=did, limit=N)`.
- **Filter at scrape:** drop replies (`post.reply` present) and reposts
  (feed `reason` = repost).
- **Per post → NormalizedItem:**
  - `external_id` = post AT-URI (`at://…/post/<rkey>`)
  - `kind = 'short'`, `title = None`
  - `url` = `https://bsky.app/profile/<handle>/post/<rkey>`
  - `text` = full `record.text` (truncate to ~100 chars at *render*, store full)
  - `excerpt = None`, `published_at = record.createdAt`
  - `engagement_count` = **likes + reposts** combined

## Render step

- **Output:** Jinja2 template → **HTML file**, opened in the browser. This is the seed
  of the real digest email template. (Console text optional as a quick secondary.)
- **What:** all `items` from the **last ~30 days, grouped by `feeder_name`** (no
  subscription filtering — that's Slice 3).
- **Within each feeder, group items by source** under a source subheading, so every
  link is attributed to where it came from:
  - Subheading = the source's **publication name** (`sources.title`); for Bluesky use
    `"Bluesky"`; fall back to platform/domain if a feed has no title.
  - **Long-form sources listed above short-form** sources within the feeder.
  ```
  From John
    Astral Codex Ten                 ← source subheading (sources.title)
      • <long post title> — <excerpt>
      • <long post title> — <excerpt>
    Bluesky
      • <short post text…>
  ```
- **Capping (the real behavior, so you judge it for real):**
  - **All long items** (ordered by recency).
  - **Short capped to top-3 by recency** per feeder.
  - Per long item show title + excerpt + link; per short item show ~100-char text + link.
  - Feeders ordered by most-recent-activity.

## Definition of done

Run a CLI entrypoint against the ~5 hardcoded real sources → deduped rows land in SQLite
→ a render command produces the grouped/capped HTML digest → open it and eyeball it
against the real content. If it reads like a useful digest, Slice 1 is complete.

## Known risky bits to watch (expected first breakages)
- **Substack custom domains** — does `/feed` resolve? (autodiscovery `<link>` should catch it)
- **Feeds dumping full HTML body into `summary`** — truncation handles it
- **Timezone-naive / garbage dates** — the `scraped_at` fallback handles it
- **Per-source error isolation** — one dead source must not kill the run

## Carries forward into later slices
- RSS feed-resolution logic → add-time **source validator** (Slice 3)
- SQLAlchemy models + Alembic migrations → real schema (Postgres, Slice 4)
- Jinja HTML template → real **digest email** template (Slice 4)
- `feeder_name` stub → real `user_id` FK (Slice 2)
