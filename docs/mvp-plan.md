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
- **Display name** is typed by the user at signup (used for search + "From <name>"
  digest headers).

### Sessions
- **Opaque server-side session tokens** (random string, row in `sessions`), sent as
  `Authorization: Bearer <token>`. Chosen over JWT because: revocable, no signing-key
  management, no stale claims, and the single-service + Postgres shape makes JWT
  statelessness worthless here.
- Session expiry ~30 days (low-stakes; re-login is just another magic link).
- Magic-link tokens: **single-use, ~15-min expiry**, stored hashed.
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
- **Validate synchronously** at add-time (fetch + parse, ~5s timeout). Reject dead
  feeds immediately rather than storing a silently-broken source.
- **Confirm** to the feeder: "✅ Found N recent posts, latest: '<title>' — is this right?"
- **Multiple sources per feeder** allowed (e.g. their Substack *and* their Bluesky).
- **Publication vs. profile URLs (UI nudge):** a `substack.com/@handle` URL points at a
  *person*, not a publication feed, so `/feed` resolution 404s (seen live with
  `substack.com/@pragmaticengineer`). The add-source UI should detect this shape and steer
  the feeder to paste their **publication** URL (`<name>.substack.com`) instead of failing
  silently. (Longer term that same profile handle is the key a Substack **Notes** adapter
  would use — see deferred — so detect-and-nudge now, branch-by-type later.)

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

### Filtering & capping
- **Long items: include all** (rare, high-value).
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

### Density formats (spacious vs. compact)

The presentation above is the **spacious** format and assumes a handful of active feeders.
A subscriber following many people who all post in a window would get a wall of excerpts,
so the digest **hard-switches to a compact format** above a threshold:

- **Trigger:** the *active-feeder count* (feeders with ≥1 item in the window), **not**
  subscription count — a user following 40 mostly-dormant feeders still gets the spacious
  format. One mode for the whole email, so it stays visually coherent. Threshold is a
  single tunable knob (`COMPACT_MODE_FEEDER_THRESHOLD`, starts at 10).
- **Compact layout:** **one line per feeder**, each carrying a single representative item
  (`Name — <title|text> · <date>`, the line linking to the item). The other items in the
  window are dropped silently for now — a `+N more` affordance is a later add once the
  in-app digest view (screen #7) is a place to click through to.
- **Which item represents a feeder:** **most-recent `long`; fall back to most-recent
  `short` only if the feeder has no long** in the window — reusing `kind` (§4) as the
  significance proxy so an essay always beats a throwaway reply. (In the spacious format
  selection barely matters because everything is shown; in compact it *is* the product.)
- **Relation to sampling:** this is a *presentation* tier, orthogonal to the deferred
  serendipity/sampling work below — formatting decides how densely to show what made the
  cut; sampling decides *which* feeders make the cut when there are too many even for one
  line each. A genuinely huge digest eventually wants both.

### Send mechanics
- **One personalized email per due subscriber** (not a broadcast).
- **Skip empty sends** — no email if nothing is new (avoids training people to ignore
  digests / spam-complaints). Advance the cutoff on every run, send or skip (the
  empty-period edge case where this matters is negligible at MVP scale).
- **First-subscribe experience:** immediate **in-app preview** ("here's what your digest
  will look like") + a **one-off emailed welcome sample** (also serves as a
  deliverability canary). Both are clearly labeled as samples and don't disturb cadence.
- **Unsubscribe:** every digest carries a one-click **global unsubscribe** token link
  (sets `digest_paused`). Per-feeder unsubscribe is just removing a subscription in-app.

### Email / deliverability notes
- Magic links (transactional, critical-path) and digests (bulk) both go through Resend.
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
  id · email (unique) · display_name
  digest_frequency ('weekly'|'monthly', default 'weekly')
  digest_paused (bool) · last_digest_sent_at · last_covered_through · created_at

allowed_emails            -- CSV allowlist gate
  email (unique) · name (nullable) · claimed_by_user_id (nullable)

magic_link_tokens
  id · email · token_hash · expires_at · used_at · created_at

sessions
  id · user_id · token_hash · expires_at · created_at

sources                   -- a feeder's content source (multiple per feeder)
  id · user_id (feeder) · type ('rss'|'bluesky')
  input_url · resolved_feed_url / external_id · title
  last_checked_at · last_success_at · created_at
  -- (status / consecutive_failures deferred with source-health handling)

items                     -- scraped content (durable history)
  id · source_id · external_id · kind ('long'|'short')
  title (nullable) · url · text (nullable) · excerpt (nullable)
  engagement_count (default 0) · published_at · scraped_at
  UNIQUE(source_id, external_id)

subscriptions             -- subscriber → feeder
  id · subscriber_id · feeder_id · created_at
  UNIQUE(subscriber_id, feeder_id)
```

Notes:
- `published_at` = feed date if present and sane, else falls back to `scraped_at`
  (calendar windowing depends on it).
- Every item is attributed to the **feeder who owns the source** (per-item RSS authors
  on multi-author blogs are ignored — deferred edge case).
- `engagement_count` is stored now (Bluesky likes/reposts) but unused in v1 ranking;
  short items sort by recency for now, by traction later.

---

## 7. Frontend (7 screens / ~4 routes)

**Public**
1. **Login** — enter edge email → "check your inbox" (privacy-preserving, see §2).
2. **Verify** — `/auth/verify?token=…`, invisible: exchange token → store session →
   redirect. Error state if expired.
3. **Unsubscribe** — public token link target from digest emails.

**Authenticated app shell** (tabs)
4. **First-login onboarding** — set display name; nudge toward add-content / find-people.
5. **My Content** — list sources, add source (paste → validate → confirm), remove.
6. **Discover** — search feeders by name (`ILIKE`), shows name + platforms +
   subscribe/unsubscribe toggle.
7. **My Digest** — manage subscriptions, set frequency (weekly/monthly), pause digests,
   and a **live digest preview**.

---

## 8. Build sequence — walking skeleton (de-risk first)

Ordered to answer the project's only real technical uncertainty (ingestion) *first*,
before sinking time into the large-but-low-risk auth and frontend layers. Each slice is
a runnable milestone.

1. **Slice 1 — Ingestion spike** (backend only, SQLite, hardcoded sources): scrape →
   deduped `items` → rendered HTML digest you eyeball. De-risks the core, locks the
   `items` model. **Full spec:** [`slice-1-ingestion-spike.md`](./slice-1-ingestion-spike.md).
2. **Slice 2 — Auth + allowlist** — CSV import, magic-link send/verify, sessions,
   display name; swap the spike's `feeder_name` stub for the real `user_id` FK.
3. **Slice 3 — Multi-user CRUD + API** — real add-source (reusing the spike's feed
   validator), subscriptions, `ILIKE` search, calendar windowing + capping, in-app preview.
4. **Slice 4 — Cron + Postgres + email** — migrate SQLite→Postgres on Railway, daily
   scrape + digest crons, Resend send, welcome sample, unsubscribe.
5. **Slice 5 — Frontend** — the 7 screens tied together.

> Why not auth-first: auth and frontend are well-trodden and certain to work; ingestion
> is where real feeds break assumptions. Validate that in days, not after weeks of
> scaffolding. See `slice-1-ingestion-spike.md` for the rationale in full.

---

## Deferred / follow-up

Consciously punted from the MVP, roughly in priority order:

- **X / Twitter** — adapter stub now; if forced, a hosted **Apify** actor (not
  self-hosted `twscrape` on Railway) — scraping needs auth'd accounts + residential
  proxies and faces bans regardless of frequency.
- **LinkedIn** — walled garden, harder than X. No public feed (RSS long dead), all
  content behind a login wall, and bots get HTTP 999. No scraping fallback worth the
  ToS/anti-bot risk. The only official read path is the **Community Management API**,
  which is org/brand-**Page**-scoped, commercial-only, and partner-approval-gated
  (low approval rate, weeks–months) — there is *no* product for reading individuals'
  personal posts, which is what the Edge community actually publishes. Realistic
  post-MVP shape if pursued: member-authorized OAuth, not a URL resolver.
- **YouTube feed hardening** — channel→feed resolution works, but the public
  `feeds/videos.xml?channel_id=…` fetch is **throttled/blocked at scale**: in a 30-feeder
  live run, 9 of 10 YouTube sources came back as a non-feed consent/block page while one
  identical-shape URL succeeded — intermittent anti-bot, not a code bug. Options:
  retry-with-backoff, a browser-like User-Agent + consent cookie, or resolve via
  `yt-dlp` / the **YouTube Data API** instead of the public XML feed.
- **Substack Notes ingestion (short-form)** — publication RSS (`/feed`) carries **posts
  only**; Notes (Substack's short-form, Twitter-like feed) appear in *no* RSS. Capturing
  them needs a dedicated adapter producing `kind='short'` items — directly analogous to
  the Bluesky adapter — via one of: the **undocumented JSON endpoint**
  (`<pub>.substack.com/api/v1/notes` / profile reader feed; public reads appear possible
  but it's unstable, ToS-grey, and *read*-Notes is poorly trodden — even the leading
  unofficial wrapper `NHagar/substack_api` covers posts but **not** Notes, so expect real
  reverse-engineering), or a **third-party scraper** (e.g. Apify, paid, adds a dependency).
  **Ruled out — the official Developer API:** it's profile-metadata only (subscriber
  counts, bestseller/leaderboard, LinkedIn-linked profile data, keyed off a LinkedIn
  handle), exposes **no** posts/Notes/comments, and gates on a form + ToS + 7–10 business
  day approval — useless for content ingestion (checked 2026-06). Keys on the
  `substack.com/@handle` profile URL the add-source flow currently rejects (§3) — same
  thread, opposite end.
- **Non-feed personal/company websites** — true HTML scraping (no RSS).
- **Source-health handling** — track consecutive failures, flag broken sources in the
  feeder dashboard, optionally email feeders (options a/b from the design discussion;
  MVP punts with "c": dead sources silently return nothing).
- **Per-digest serendipity / sampling** — real design for subscribers following
  hundreds of feeders (random/exploration rather than mechanical truncation). May
  partly self-resolve if few people publish. *Note:* the compact density format
  (§5 → Density formats) raises how many feeders a digest can show before sampling is
  needed, but is orthogonal to it — formatting ≠ which feeders make the cut.
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
