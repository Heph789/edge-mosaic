# Slice 4 — Cron + Postgres + Email

Detailed build spec for the fourth slice. Parent: [`mvp-plan.md`](./mvp-plan.md).

## Goal

Make the digest actually **go out**: move to Postgres in prod, run the scrape + digest as
scheduled jobs, and send real email through Resend — with unsubscribe and a first-subscribe
welcome sample.

**cron scrape → cron digest → Resend send → unsubscribe** — the loop runs itself.

This is the slice that turns the curl/pytest-only app into one that emails real people.
Frontend is still Slice 5; the clickable in-email unsubscribe *page* lands there (the
backend POST endpoint + RFC 8058 headers are here).

## Decisions (from the Slice 4 grill)

- **SQLite local, Postgres prod.** Local dev + the pytest suite stay on SQLite (fast,
  zero-setup); prod is Postgres on Railway. Migrations are validated against a real
  Postgres once (done — all four apply + roundtrip on PG 14). Keeps the standing
  "dev≠prod, avoid SQLite-isms" discipline.
- **`sent_digests` log table** for send idempotency + audit (chosen over a bare cursor).
- **Resend behind the interface, env-flagged.** `EMAIL_BACKEND` defaults to `console`
  (no real delivery) → set to `resend` in prod once a domain is verified.
- **Persistent opaque `unsubscribe_token`** column per user.

Derived (decided during build):
- **Anchor/window math:** `most_recent_anchor(freq, today)` = most recent Monday (weekly)
  / 1st (monthly) on-or-before today; window = `[previous_anchor, anchor)` (the
  just-completed period). Due = that anchor not yet in `sent_digests` → self-heals a
  missed cron day.
- **Unsubscribe is `POST`, not GET** (anti-prefetch, like the magic link), token in the
  query string so it doubles as the RFC 8058 one-click target.
- **Welcome sample is best-effort** on a user's first-ever subscription; failure is logged,
  never fails the subscribe.

## Schema delta (migration 0004)

```
users.unsubscribe_token (unique, NOT NULL)   -- backfilled per-row, then constrained

sent_digests
  id · subscriber_id (FK users.id) · anchor_date (date)
  window_start · window_end · item_count · sent (bool) · created_at
  UNIQUE(subscriber_id, anchor_date)
```

The `unsubscribe_token` backfill runs inside the migration (add nullable → fill each row →
set NOT NULL + UNIQUE) so it's correct on an already-populated prod table too.

## Postgres

- `DATABASE_URL` drives the dialect. `config._normalize_db_url` rewrites Railway's
  `postgres://` / `postgresql://` to the **psycopg3** driver (`postgresql+psycopg://`) so
  we don't silently fall back to psycopg2. Dep: `psycopg[binary]`.
- Alembic's `render_as_batch=True` (set since Slice 1) makes the SQLite ALTERs work; on
  Postgres those compile to plain `ALTER`s. Validated: 0001–0004 apply + full down/up
  roundtrip on real Postgres.

## Email backend (`app/email.py`)

`send_email(to, subject, html, text=None, headers=None)` dispatches on `EMAIL_BACKEND`:
- **`console`** (default) — logs + prints; send-safe, drives curl/pytest.
- **`resend`** — `POST https://api.resend.com/emails` via httpx with `RESEND_API_KEY`;
  `from` = `EMAIL_FROM`. Passes `headers` through (for `List-Unsubscribe`).

Magic-link email (Slice 2) now sends html + text through this same signature.

## Jobs (Railway cron services)

Both run from the same `/api` image as separate Railway services:

```
python -m app.jobs.scrape    # daily ~06:00 UTC
python -m app.jobs.digest    # daily ~07:00 UTC (after scrape)
```

- **scrape** — `ingest.scrape(session)` over every source; per-source try/except isolation.
- **digest** — `run_digest_job(db, today)`:
  - `due_subscribers` = verified, non-paused users with ≥1 subscription.
  - per subscriber: `anchor = most_recent_anchor(freq, today)`; if `(subscriber, anchor)`
    already in `sent_digests` → skip; else assemble window `[prev_anchor, anchor)`,
    render HTML, **send** (or skip-empty), then write the `sent_digests` row + advance
    `last_digest_sent_at` / `last_covered_through`, commit per subscriber.
  - Ordering: assemble → send → log+commit (rare duplicate on mid-send crash accepted; a
    send that raises is isolated and *not* logged, so it retries next run).

## Unsubscribe

- `POST /unsubscribe?token=…` (public) → looks up `unsubscribe_token`, sets
  `digest_paused`. Generic `200` regardless of token validity (don't reveal which tokens
  are real). Idempotent.
- Digest emails carry `List-Unsubscribe: <{API_BASE_URL}/unsubscribe?token=…>` +
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, and a human footer link to the SPA
  (`{APP_BASE_URL}/unsubscribe?token=…`, finished in Slice 5).

## Deploy (Railway)

- `api/railway.json` — web service: build (Nixpacks) + start
  `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- `api/Procfile` documents the three process commands (`web` / `scrape` / `digest`). The
  two cron services are configured in the Railway dashboard pointing at the same image
  with the `scrape` / `digest` start commands + cron expressions; all share one Postgres.
- Env to set in prod: `DATABASE_URL` (Railway Postgres), `EMAIL_BACKEND=resend`,
  `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`, `API_BASE_URL`.

## Definition of done

`run_digest_job` sends one email per due subscriber with content, skips-empty with a logged
row, is idempotent on re-run, and excludes paused/unverified users; unsubscribe flips
`digest_paused`; first subscription sends a welcome sample; migrations apply on real
Postgres. (53 tests pass; digest HTML eyeballed via the console sink.)

## Carries forward
- The in-email unsubscribe + verify links → the **SPA pages** (Slice 5).
- `EMAIL_BACKEND=resend` + a verified domain → **live delivery** (flip the env once ready).
- Per-email send cooldown on `request-link` → drop into the existing choke point when
  abuse becomes real.
