# Slice 3 — Multi-user CRUD + API

Detailed build spec for the third slice. Parent: [`mvp-plan.md`](./mvp-plan.md).

## Goal

Turn the authed accounts from Slice 2 into a working multi-user app: feeders **add real
sources**, subscribers **follow feeders**, everyone can **search** and **preview the
digest they'd receive** — all over the API.

**add source → scrape → subscribe → preview the digest** — end to end, backend only.

Deferred to Slice 4: the scrape/digest **cron wrappers**, the **actual email send**, and
calendar-anchored **due-scheduling**. Slice 3 builds the assembly engine and a manual
scrape; sending is next. Frontend is still Slice 5 — exercised with curl/pytest.

## Concurrency model — sync `def` + threadpool

Network-bound endpoints (`/sources/preview`, `/sources`) and the adapters/DB stay
**synchronous**; Starlette offloads each `def` handler to its worker threadpool (default
40), so a blocking ~5s feed fetch parks a worker, never the event loop. Two concurrent
adds run on two threads and overlap fine (blocking socket I/O releases the GIL).

Chosen over full-async for MVP simplicity — zero adapter/ORM rewrite. **Do not** make
these handlers `async def` while the DB driver is sync: an `async def` with `AsyncClient`
fetch but a sync `session.execute()` is *half-async* and blocks the loop on every query.
Migration path if throughput ever demands it: go fully async (`httpx.AsyncClient` +
`atproto.AsyncClient` + SQLAlchemy `AsyncSession` + `aiosqlite`/`asyncpg`), which also
unlocks `asyncio.gather` concurrent scraping. Ceiling to watch: the 40-thread pool is
per-process (Slice 4's multiple uvicorn workers multiply it).

## Schema delta

New `subscriptions` table + migration `0003`:

```
subscriptions
  id · subscriber_id (FK users.id) · feeder_id (FK users.id) · created_at
  UNIQUE(subscriber_id, feeder_id)
```

Both columns FK `users.id` — "feeder" is a *role*, not a table. `items` / `sources` are
unchanged from Slice 2 (`sources` is already `user_id`-keyed).

## Endpoints (all authed via the Slice 2 `current_user` dependency)

| Endpoint | Behaviour |
|---|---|
| `POST /sources/preview {url}` | `detect_type` → validate (resolve feed / DID, fetch) → return `{type, resolved_url, title, found_count, latest:{title, published_at}}`. **No DB write.** `x.com`/`twitter.com` → `400 "coming soon"`; dead feed → `422`. |
| `GET /sources` | the caller's own sources only. |
| `POST /sources {url}` | re-validate → create source → **inline first-scrape** (dedup-insert its items) → return the source. Idempotent on `UNIQUE(user_id, input_url)` (re-add → return existing). |
| `DELETE /sources/{id}` | hard-delete + cascade items. Foreign id → `404` (don't reveal existence). No `PATCH` — "edit" is remove + re-add. |
| `POST /subscriptions {feeder_id}` | subscribe; idempotent (re-sub → existing row). **Self-sub allowed.** `feeder_id` must reference a real user, else `404`. |
| `DELETE /subscriptions/{feeder_id}` | unsubscribe; `204` even if not subscribed (idempotent). |
| `GET /subscriptions` | caller's subscriptions, each with feeder `display_name` + `platforms`. |
| `GET /discover?q=` | escaped `.ilike()` name search; `display_name`-eligible (pre-seeded ghosts included), excludes self; cap 50; empty `q` → `422`. |
| `GET /me/digest/preview` | trailing-window assembled digest, JSON. |
| `PATCH /me` | partial update: `display_name` (sets `onboarded`), `digest_frequency` ∈ {weekly,monthly}, `digest_paused`. |

Onboarding is **not** an action gate — a verified-but-not-onboarded user (no
`display_name`) can add sources and subscribe; they just won't appear in Discover until
they have a name.

## Add-source detail

- **`detect_type(url)`** — one pure function (rewrite of `sources.py`), the single source
  of truth, reused by preview / create / scrape:
  - `x.com` / `twitter.com` → reject (`"coming soon"`)
  - `bsky.app` or `@handle` → `bluesky`
  - else → `rss` (the resolver handles Substack `/feed` + autodiscovery)
- **Validator = the spike's resolution logic**, with a tightened budget: **~5s
  per-request timeout** *and* an **overall resolution deadline** (abort after ~10s total)
  so the worst-case "try URL → fetch HTML → 5 common paths" chain can't hang an
  interactive add. The deadline raises `FeedResolutionError` → `422`.
- **Inline first-scrape** runs in the same (threadpool) call as create, before responding,
  so `GET /me/digest/preview` immediately after shows content. Not backgrounded — a
  `BackgroundTask` would race the preview.

## Discover detail

- **Eligibility:** `display_name IS NOT NULL` and `id != caller`. Includes pre-seeded
  ghosts (pre-subscription) and feeders with no sources yet.
- **Escaped `ILIKE`:** `display_name.ilike(f"%{esc(q)}%", escape="\\")` where `esc`
  doubles `\\` and prefixes `%`/`_` — so `50%` / `a_b` match literally. `.ilike()`
  compiles to `ILIKE` on Postgres, `LIKE` (ASCII-case-insensitive) on SQLite.
- **Response per hit:** `{user_id, display_name, platforms:[...], is_subscribed}`.
  `platforms` = distinct `source.type`s the feeder owns ( `[]` for a contentless ghost).

## Digest assembly engine

- **`assemble_digest(user) -> DigestData`** — the shared engine (rebuild of
  `render.build_feeders` on `user_id` + subscription filter):
  window → join `items → source → feeder` → **filter to the caller's subscriptions** →
  group by feeder → cap → order. Returns a structured object (not HTML).
- **Capping:** longs → top-`LONG_ITEMS_CAP` (5) by recency; shorts → top-`SHORT_ITEMS_CAP`
  (3) by recency; **per-digest safety cap** ~50 feeders (sampled if exceeded, logged).
- **Ordering:** feeders by most-recent activity; within a feeder, longs then shorts.
- **Two sinks:** Slice 3 serializes `DigestData` to **JSON** for `GET /me/digest/preview`;
  Slice 4's email job renders the *same* object to **HTML** (reusing the Jinja template).
- **Preview window = rolling trailing window** sized to frequency (weekly → 7d, monthly →
  ~30d), so a mid-cycle preview is representative, not sparse. The real send (Slice 4) uses
  the calendar-anchored window — same engine, different bounds. Empty preview is fine
  (skip-empty is a *send* concern).

## Ingestion rebuild

`sources.py` → `detect_type` (drop `HARDCODED_SOURCES`); `ingest.py` scrape iterates all
real sources (per-source try/except isolation, unchanged dedup); `render.py` →
`assemble_digest`. `python -m app.cli scrape` is resurrected to populate `items` manually
(the cron wrapper is Slice 4).

## Definition of done

A pytest flow: user A adds a real source (`preview` then `create` → items land) → user B
`/discover?q=` finds A → B subscribes → manual `cli scrape` refreshes → `GET
/me/digest/preview` for B returns A's grouped/capped items → unsubscribe empties it.
Plus unit tests for `detect_type`, escaped `ilike`, ownership 404s, idempotent sub/unsub,
self-sub, and the capping math. Migration `0003` applies clean up and down.

## Carries forward
- `assemble_digest` + the Jinja template → the **email send** (Slice 4).
- Calendar-anchored windowing + `last_covered_through` due-logic → the **digest cron**
  (Slice 4).
- The manual `cli scrape` → the **scrape cron** (Slice 4).
- Every endpoint → the **7 screens** (Slice 5).
