# Edge Mosaic — MVP Implementation Plan

Companion to [`initial-frame.md`](./initial-frame.md). That doc is the product vision;
this is the resolved implementation design for the MVP. Decisions here were worked
through deliberately — where something was deferred, it's listed in
[Deferred / follow-up](#deferred--follow-up) rather than dropped.

> **Scope reminder:** the mosaic UI is explicitly *out* of the MVP. The MVP is a
> plain functional app that proves the core loop: feeders connect content →
> subscribers follow people → subscribers get periodic digests.

---

## 1. Stack & topology

| Concern | Choice |
|---|---|
| Frontend | **Vite React SPA**, hosted on a static CDN (Cloudflare Pages / Vercel) |
| Backend | **FastAPI** on **Railway** — one web service + two cron services |
| Database | **Railway Postgres** (prod). Local **SQLite** for the Slice 1 spike — see [`slice-1-ingestion-spike.md`](./slice-1-ingestion-spike.md) |
| Email | **Resend** (behind a `send_email()` interface), authenticated sending domain |
| Repo | **Monorepo**: `/web` (SPA) + `/api` (FastAPI package + job entrypoints) |

- The SPA talks to the API via `VITE_API_URL`; **CORS** is configured on FastAPI to
  allow the CDN origin. Split-origin (SPA on CDN, API on Railway) is intentional — the
  SPA gets a CDN, Railway only runs Python.
- **Railway runs three roles from the same `/api` image**, all sharing one Postgres:
  - **Web service** — `uvicorn app.main:app`
  - **Cron: scrape** — `python -m app.jobs.scrape`, daily (~06:00 UTC)
  - **Cron: digest** — `python -m app.jobs.digest`, daily (~07:00 UTC, *after* scrape)
- Web API and cron jobs share the same models / db / adapters — different entrypoints,
  one package. No duplication.
- Migrations via **Alembic**.
- **Dev vs prod DB:** Slice 1 (the ingestion spike) runs on local **SQLite** for zero-setup
  iteration; the app moves to **Postgres** at Slice 4 (deploy). Keep all SQLAlchemy models
  dialect-agnostic and avoid SQLite-isms (upsert syntax, native enums) so the switch is
  painless. Detail in [`slice-1-ingestion-spike.md`](./slice-1-ingestion-spike.md).

**Why FastAPI over Django:** API-only (the SPA is the UI), async-friendly for
I/O-heavy scraping, OpenAPI for the frontend. Trade-off accepted: no free Django
admin — early data inspection is via `psql`.

**Why Railway:** first-class cron + persistent web service + Postgres from one repo,
near-zero ops. Serverless (Vercel/Lambda) was rejected because scraping and digest
sends are recurring background jobs, not request/response.

---

## 2. Auth & identity

- **Passwordless magic-link** login. Email *is* identity (we send digests to it), so
  the magic link authenticates, proves inbox ownership, and avoids password storage.
- **Edge-email gating = CSV-seeded `allowed_emails` allowlist.** An email must be on
  the list before a link is sent. This *is* the source of truth for "valid edge email"
  — no official Edge API needed; a real check can later slot behind the same gate.
- **One unified account** — a user is both feeder and subscriber. They "become a
  feeder" simply by adding content sources. No separate account types.
- **Display name** (used for search + "From <name>" digest headers) is **preseeded
  from the allowlist roster, then user-editable at onboarding** — there's no classic
  signup form in a magic-link flow. The roster's full name is reduced to **first name +
  last initial** (`"Jane Smith"` → `"Jane S."`) *at import time*; the full surname is
  never persisted. If the roster has no usable name, `display_name` starts `NULL` and
  onboarding collects it.

### User lifecycle & pre-seeding
A `users` row has three **independent** states — don't conflate them:
- **Exists** — a row is present. Created either by **pre-seeding** (at allowlist import,
  for named roster entries only) or **lazily at verify** (for un-pre-seeded / anonymized
  people, in the same transaction as their first login).
- **Verified** (`verified_at`) — has proven inbox ownership ≥ once. `NULL` = a pre-seeded
  ghost nobody's claimed yet (subscribable in Discover, but never logged in). The lazy
  path never yields `NULL` — those rows are born verified.
- **Onboarded** (`onboarded` bool) — explicit flag, **decoupled from `display_name`**
  precisely because a pre-seeded user can already have a preseeded name yet not be
  onboarded.

**Pre-seeding** lets members **pre-subscribe to people who haven't joined yet** (solves
Discover cold-start). For the MVP, allowlist import **auto-creates a pre-seeded user for
every *named* roster entry**; anonymized entries (no name) get only the `allowed_emails`
gate row and a lazily-created user if they ever log in. (Selective opt-in seeding was the
alternative; auto-all was chosen to see the product fully populated pre-release — all
this data is throwaway until launch.)

**User creation at verify is get-or-create** keyed on the normalized email: it finds the
pre-seeded row if present (stamping `verified_at` + `allowed_emails.claimed_by_user_id`),
else creates it. `UNIQUE(email)` makes this collision-free.

### Sessions
- **Opaque server-side session tokens** (random string, row in `sessions`), sent as
  `Authorization: Bearer <token>`. Chosen over JWT because: revocable, no signing-key
  management, no stale claims, and the single-service + Postgres shape makes JWT
  statelessness worthless here.
- Session expiry **fixed ~30 days** from creation, no sliding renewal (low-stakes;
  re-login is just another magic link). `POST /auth/logout` deletes the session row —
  exercising the revocability that was the whole reason for opaque tokens over JWT.
- Magic-link tokens: **single-use, ~15-min expiry**, stored hashed. Verify claims the
  token **atomically** (`UPDATE … SET used_at=now() WHERE token_hash=? AND used_at IS
  NULL AND expires_at>now()`, check rowcount=1) — no TOCTOU window. Each new request
  **invalidates prior unused tokens** for that email, so there's only ever one live link.
- **Token hashing = plain `sha256`**, not bcrypt/argon2: these are 256-bit
  `secrets.token_urlsafe(32)` random strings, so there's nothing to brute-force and a
  fast digest is correct. Raw token lives only in the URL / Bearer header; the DB stores
  `sha256(token)` in `UNIQUE` hash columns. Applies to both magic-link and session tokens.
- **Anti-prefetch:** the email link targets the SPA landing route, and the token exchange
  is a deliberate `POST /auth/verify {token}` (token in **body**, never the query string).
  A bare GET prefetch by an email scanner only loads static JS — it doesn't fire the POST,
  so it can't burn the single-use token. We consciously never expose a GET that consumes a
  token.
- Token stored in localStorage. **XSS rule:** all scraped content is rendered as
  escaped plain text — never `dangerouslySetInnerHTML` on feed/Bluesky content.

### Login privacy
- The login flow **never reveals allowlist membership**. Same "if your email is
  eligible, a link is on its way" response either way — so the app can't be used to
  enumerate who is in the Edge community.

---

## 3. Ingestion

### v1 sources
- **RSS/Atom** — covers Substack *and* any blog that exposes a feed (one adapter).
- **Bluesky** — AT Protocol public API (`getAuthorFeed`), no auth, free.
- Every source is normalized behind a unified **"feed source" adapter interface**, so
  deferred platforms (X, non-feed sites) drop in later without touching the rest of the
  system.

> The v1 dividing line is **"does this URL expose a discoverable feed?"** — not "is it
> a Substack." Feed-having personal blogs are in; non-feed sites are deferred.

### Adding a source
- Feeder pastes any URL. Backend **auto-detects** the type:
  - `x.com` / `twitter.com` → rejected for now ("coming soon").
  - `bsky.app` or `@handle` → Bluesky (resolve handle → DID).
  - `*.substack.com` / custom domain → try `/feed`.
  - anything else → **RSS autodiscovery** (`<link rel="alternate" type="application/rss+xml">`,
    fall back to `/feed`, `/rss`).
- **Validate synchronously** at add-time (fetch + parse, ~5s per-request timeout + an
  overall resolution deadline so pathological autodiscovery can't hang the request).
  Reject dead feeds immediately rather than storing a silently-broken source.
- **Confirm** to the feeder: "✅ Found N recent posts, latest: '<title>' — is this right?"
- **Multiple sources per feeder** allowed (e.g. their Substack *and* their Bluesky).
- **Two endpoints** (Slice 3): `POST /sources/preview` validates + returns the found
  sample with **no DB write** (powers the confirm step); `POST /sources` re-validates,
  creates the source, and runs an **inline first-scrape** (dedup-inserts its items) so a
  freshly added source isn't empty until the next daily scrape. `detect_type(url)` is one
  pure function shared by preview, create, and the scrape orchestrator.

### Scraping
- **Daily global scrape** into a durable `items` table. Decoupled from digest cadence.
  - *Why daily, not at digest time:* RSS feeds are a sliding window (~last 10–20 items).
    Scraping only at digest time would silently lose posts that rolled off the feed.
    Scrape frequently into our own store; digests read from the store, not the live feed.
- **Dedup** via `UNIQUE(source_id, external_id)` upsert (RSS `guid`/`id`, Bluesky
  URI/CID; fall back to canonical-URL hash). Re-scraping an item is a no-op.
- Source failures are **not handled in v1** (dead sources just return nothing) — see
  deferred list. `last_checked_at` / `last_success_at` are recorded for debugging only.

---

## 4. Content model: `kind` (long vs short)

A first-class axis, **orthogonal to platform**:

- `source.type` (`rss` | `bluesky`) = **provenance** (which adapter; debugging).
- `item.kind` (`long` | `short`) = **form factor** (high-value/infrequent vs
  low-value/bursty). This is the significance proxy that operationalizes the doc's
  "filter out insignificant updates."

`kind` lives on the **item**, stamped by the adapter at scrape time (RSS → `long`,
Bluesky → `short`). Modeled per-item (not per-source) and as an enum so future cases —
Substack Notes (short), X threads (long), video/podcast — slot in with no schema change.

---

## 5. Digest assembly

- **Cadence: per-subscriber `weekly` | `monthly`**, **calendar-anchored with global
  anchors** (weekly → Monday, monthly → 1st-of-month).
- Digest cron runs daily; it's a near-no-op off anchor days. A `last_covered_through`
  cursor is kept as a backstop so a *missed* cron run self-heals next day.
- **Window** = items published in the current calendar window for due subscribers,
  joined subscriptions → feeder → sources.
- **Assembly is split from rendering** (Slice 3): one pure `assemble_digest(user) ->
  DigestData` engine produces the grouped/capped structure, serialized as **JSON** for the
  in-app preview and rendered to **HTML** by the Slice 4 email job — one engine, two sinks.
- **Preview window divergence:** the in-app preview uses a **rolling trailing window**
  sized to the subscriber's frequency (weekly → last 7 days, monthly → last ~30) so a
  preview rendered mid-cycle is *representative*, not sparse. The real send uses the
  calendar-anchored window. Same engine, different window bounds.

### Filtering & capping
- **Long items: cap to top-N by recency** (`LONG_ITEMS_CAP`, default 5). (Earlier framing
  was "include all"; a prolific essayist over a *monthly* window can pile up, so longs are
  capped like shorts — just with a higher ceiling. A per-frequency cap is a possible later
  refinement.)
- **Short items: light-filter then cap** — drop Bluesky replies/reposts at scrape time;
  cap to **top-N by recency** (e.g. 3) per feeder.
- **Per-digest safety cap** (~50 feeders, sampled if exceeded) so an email can't explode.
  The real serendipity/sampling design for huge subscription counts is deferred.

### Presentation
- **Organized by feeder** ("From John… From Mike…").
- Per feeder: **long items headlined** (title + author's own excerpt + link), then a
  smaller "also posted" list of **short** items (first ~100 chars + link).
- **No AI summaries.** The author's RSS-provided excerpt *is* allowed (author-written,
  not AI) and is shown for long items to aid the click decision. Users must click
  through for the actual content.

### Send mechanics
- **One personalized email per due subscriber** (not a broadcast).
- **Idempotency + skip-empty via a `sent_digests` log** (Slice 4): one row per
  `(subscriber, anchor)` period, `UNIQUE(subscriber_id, anchor_date)`. Skip-empty still
  writes a row (`sent=false, item_count=0`) so it isn't re-attempted; a missed cron day
  self-heals because the anchor simply isn't logged yet. Assemble → send → log+commit
  (a crash between send and commit can rarely duplicate — accepted; we never log a `sent`
  row for a send that raised, so failures retry rather than drop).
- **First-subscribe experience:** immediate **in-app preview** ("here's what your digest
  will look like") + a **one-off emailed welcome sample** (also serves as a
  deliverability canary; best-effort — never fails the subscribe). Both are clearly
  labeled as samples and don't disturb cadence.
- **Unsubscribe:** every digest carries a one-click **global unsubscribe** token link
  (opaque per-user `unsubscribe_token` column → sets `digest_paused`). It's a **POST**
  (anti-prefetch, like the magic link) and ships **RFC 8058 `List-Unsubscribe` +
  `List-Unsubscribe-Post`** headers. Per-feeder unsubscribe is just removing a
  subscription in-app.

### Email / deliverability notes
- Magic links (transactional, critical-path) and digests (bulk) both go through Resend.
- **Backend is env-flagged behind `send_email()`** (Slice 4): default `console` (logs the
  message, no real delivery — send-safe), flip to `resend` via `EMAIL_BACKEND` once a
  domain is verified. The Resend swap is the one-file change the interface promised.
- Provider choice matters less than a properly **authenticated sending domain
  (SPF/DKIM/DMARC)** — that's what keeps magic links out of spam.
- Watch item: bulk digests attract spam complaints, which can degrade shared sender
  reputation and hurt magic-link delivery. **Postmark** (with transactional/broadcast
  stream separation) is the documented upgrade path if deliverability wobbles —
  swappable in one file thanks to the `send_email()` interface.

---

## 6. Data model

```
users
  id · email (unique, lowercased) · display_name (nullable)
  digest_frequency ('weekly'|'monthly', default 'weekly')
  digest_paused (bool, default false)
  verified_at (nullable)         -- NULL = pre-seeded ghost, never logged in
  onboarded (bool, default false)-- explicit; decoupled from display_name
  unsubscribe_token (unique)     -- opaque; embedded in the digest unsubscribe link (Slice 4)
  last_digest_sent_at · last_covered_through · created_at

allowed_emails            -- CSV allowlist gate
  id · email (unique, lowercased) · name (nullable)   -- name stores abbreviated form only
  claimed_by_user_id (nullable FK users.id)           -- set at first verify
  created_at

magic_link_tokens         -- keyed by EMAIL, not user_id (user may not exist yet at request)
  id · email · token_hash (unique) · expires_at · used_at · created_at

sessions
  id · user_id (FK users.id) · token_hash (unique) · expires_at · created_at

sources                   -- a feeder's content source (multiple per feeder)
  id · user_id (FK users.id)   -- replaces the Slice 1 feeder_name stub
  type ('rss'|'bluesky')
  input_url · resolved_feed_url / external_id · title
  last_checked_at · last_success_at · created_at
  UNIQUE(user_id, input_url)   -- replaces UNIQUE(feeder_name, input_url)
  -- (status / consecutive_failures deferred with source-health handling)

items                     -- scraped content (durable history)
  id · source_id · external_id · kind ('long'|'short')
  title (nullable) · url · text (nullable) · excerpt (nullable)
  engagement_count (default 0) · published_at · scraped_at
  UNIQUE(source_id, external_id)

subscriptions             -- subscriber → feeder (both FK users.id; "feeder" is a role, not a table)
  id · subscriber_id (FK users.id) · feeder_id (FK users.id) · created_at
  UNIQUE(subscriber_id, feeder_id)   -- added in Slice 3 (migration 0003)

sent_digests              -- one row per (subscriber, anchor) period; dedup + audit (Slice 4)
  id · subscriber_id (FK users.id) · anchor_date (date)
  window_start · window_end · item_count · sent (bool) · created_at
  UNIQUE(subscriber_id, anchor_date)   -- idempotency + self-heal key (migration 0004)
```

Notes:
- `published_at` = feed date if present and sane, else falls back to `scraped_at`
  (calendar windowing depends on it).
- Every item is attributed to the **feeder who owns the source** (per-item RSS authors
  on multi-author blogs are ignored — deferred edge case).
- `engagement_count` is stored now (Bluesky likes/reposts) but unused in v1 ranking;
  short items sort by recency for now, by traction later.
- **Self-subscription is allowed** (`feeder_id == subscriber_id`) — a feeder can follow
  themselves to dogfood "what goes out from me" in their own digest preview. The Slice 4
  send will therefore also email a self-subscriber their own posts; they can unsubscribe.

---

## 7. Frontend (Slice 5)

Vite + React + **TypeScript** SPA, **TanStack Query** for server state, hand-written typed
`api.ts` (mirrored from the API's `/openapi.json`), **plain CSS**, **React Router**.
Hosted on **Vercel**; talks to the Railway API via `VITE_API_URL` (CORS configured on
FastAPI, `allow_credentials=False`). **Full spec:** [`slice-5-frontend.md`](./slice-5-frontend.md).

**Public routes**
1. **Login** (`/login`) — enter edge email → "check your inbox" (privacy-preserving, §2).
2. **Verify** (`/auth/verify?token=…`) — POST-exchange landing: store session → redirect
   (to onboarding if not onboarded). Error state if expired. (POST, so a scanner's
   prefetch GET only loads JS, never burning the token.)
3. **Unsubscribe** (`/unsubscribe?token=…`) — POSTs the token, sets `digest_paused`.

**Onboarding** (`/onboarding`, authed, outside the tab shell)
4. Set display name (`PATCH /me`) before entering the app.

**Authenticated app shell — three tabs** (default landing → Directory)
5. **Directory** — search feeders by name (`ILIKE`, debounced); name + platforms +
   **optimistic** subscribe/unsubscribe toggle.
6. **Digest** — manage subscriptions, set frequency (weekly/monthly), pause; **live
   preview** rendered client-side from the `DigestOut` JSON (never `dangerouslySetInnerHTML`).
7. **Profile** — edit display name, manage **your content sources** (paste → preview →
   confirm → add, remove), logout.

---

## 8. Build sequence — walking skeleton (de-risk first)

Ordered to answer the project's only real technical uncertainty (ingestion) *first*,
before sinking time into the large-but-low-risk auth and frontend layers. Each slice is
a runnable milestone.

1. **Slice 1 — Ingestion spike** (backend only, SQLite, hardcoded sources): scrape →
   deduped `items` → rendered HTML digest you eyeball. De-risks the core, locks the
   `items` model. **Full spec:** [`slice-1-ingestion-spike.md`](./slice-1-ingestion-spike.md).
2. **Slice 2 — Auth + allowlist** — CSV import (with auto pre-seeding), magic-link
   request/verify, sessions, onboarding; swap the spike's `feeder_name` stub for the real
   `user_id` FK. Email is a console sink here (Resend lands in Slice 4); no frontend yet
   (Slice 5) — exercised via curl/pytest. **Full spec:** [`slice-2-auth.md`](./slice-2-auth.md).
3. **Slice 3 — Multi-user CRUD + API** — real add-source (preview + create with inline
   first-scrape, reusing the spike's feed validator), subscriptions, `ILIKE` search,
   windowing + capping, in-app preview. Ingestion is resurrected on `user_id` (manual
   `cli scrape`); the cron wrapper + actual send stay Slice 4. API-only — curl/pytest.
   **Full spec:** [`slice-3-crud.md`](./slice-3-crud.md).
4. **Slice 4 — Cron + Postgres + email** — Postgres in prod (SQLite stays local + tests),
   daily scrape + digest cron entrypoints (`app.jobs.scrape` / `app.jobs.digest`),
   calendar-anchored due-scheduling + `sent_digests` idempotency, env-flagged Resend send
   behind `send_email()`, welcome sample, one-click unsubscribe. Migrations validated on
   real Postgres. **Full spec:** [`slice-4-cron-email.md`](./slice-4-cron-email.md).
5. **Slice 5 — Frontend** — the Vite/React/TS SPA: 3-tab shell (Directory · Digest ·
   Profile) + public auth/verify/unsubscribe pages, wired to the API; adds CORS to FastAPI;
   deployed on Vercel. **Full spec:** [`slice-5-frontend.md`](./slice-5-frontend.md).

> Why not auth-first: auth and frontend are well-trodden and certain to work; ingestion
> is where real feeds break assumptions. Validate that in days, not after weeks of
> scaffolding. See `slice-1-ingestion-spike.md` for the rationale in full.

---

## Deferred / follow-up

Consciously punted from the MVP, roughly in priority order:

- **X / Twitter** — adapter stub now; if forced, a hosted **Apify** actor (not
  self-hosted `twscrape` on Railway) — scraping needs auth'd accounts + residential
  proxies and faces bans regardless of frequency.
- **Non-feed personal/company websites** — true HTML scraping (no RSS).
- **Source-health handling** — track consecutive failures, flag broken sources in the
  feeder dashboard, optionally email feeders (options a/b from the design discussion;
  MVP punts with "c": dead sources silently return nothing).
- **Per-digest serendipity / sampling** — real design for subscribers following
  hundreds of feeders (random/exploration rather than mechanical truncation). May
  partly self-resolve if few people publish.
- **"Long-form only" subscriber preference** — trivial given the `kind` axis.
- **Engagement-based ranking of short items** — flip sort from recency to traction.
- **Per-feeder digest priority**, **per-medium subscription granularity** (subscribe to
  a feeder's Substack but not their Bluesky).
- **Category / interest search** — beyond `ILIKE` name search.
- **AI-for-ranking** (not summarizing) — only if X returns and heuristics fall short.
- **Optimizations** — scrape only sources with ≥1 subscriber; prune old `items` data.
- **Mosaic UI** — the tile-per-participant visual design.
- **httpOnly-cookie sessions** — if eliminating the localStorage XSS-token risk becomes
  worth the cross-origin friction.
- **Per-item author attribution** on multi-author blogs.
