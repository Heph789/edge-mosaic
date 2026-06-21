# Edge Mosaic API — Slice 1 (Ingestion Spike)

Backend-only walking skeleton: **scrape hardcoded real sources → store deduped
`items` → render an HTML digest you can eyeball.** Spec:
[`../docs/slice-1-ingestion-spike.md`](../docs/slice-1-ingestion-spike.md).

## Run

```bash
uv sync
uv run python -m app.cli run        # scrape, then render + open the digest
```

Or step by step:

```bash
uv run python -m app.cli scrape     # upsert sources, fetch, dedup-insert items
uv run python -m app.cli render     # build data/digest.html and open it
uv run python -m app.cli render --no-open
```

Dev DB is SQLite at `data/edge_mosaic.db` (gitignored); the digest is written to
`data/digest.html`. Schema is managed by Alembic (`alembic upgrade head` runs
automatically on each command).

## Local dev: servers + seed data

Run the API and the SPA, then seed a demo database.

```bash
# 1. Backend (FastAPI) — http://localhost:8000  (Swagger at /docs)
cd api && uv sync
uv run uvicorn app.main:app --reload --port 8000

# 2. Frontend (Vite/React) — http://localhost:5173, in a second shell
cd web && npm install && npm run dev
```

### Seeding

Two seeders, both idempotent (re-running is safe):

```bash
cd api

# Feeders (ghost users) + their sources, from the canonical source list.
# Filter out YouTube: pipe the doc through grep so the filtered copy is always
# regenerated from docs/source-list.md (never goes stale). Re-run after editing the doc.
grep -vi 'youtube.com' ../docs/source-list.md > /tmp/source-list-no-youtube.md
uv run python -m app.cli seed-sources /tmp/source-list-no-youtube.md
# (drop the grep step / arg to include YouTube)

# Real login users + allowlist gate, from a roster CSV in api/input/ (gitignored).
# With no path arg it auto-discovers api/input/attendees-*.csv.
uv run python -m app.cli import-allowlist
```

`api/input/attendees-chase.csv` is the committed-locally roster (gitignored — it
holds real emails). Add a row to add a login user; the CSV headers are
`First Name, Last Name, Email, Telegram, Role, Organization, Residence, Age, Gender`
(use `*` for any cell you want treated as absent). A *named* row both opens the
allowlist gate and pre-seeds a user. Login is gated on `allowed_emails`, so an
email must be imported here before it can request a magic link.

With `EMAIL_BACKEND=console` (the default) magic links are printed to the API log
instead of being emailed — grab the link from there to log in.

> **Stale DB note:** a Slice 1 `data/edge_mosaic.db` predates the `sources.user_id`
> column and fails the auth migration. The DB is gitignored throwaway data — delete
> (or rename) `data/edge_mosaic.db` and let Alembic rebuild it before seeding.

## Layout

```
app/
  config.py            settings (DB url, timeouts, render/cap knobs)
  db.py                engine + session factory
  models.py            SQLAlchemy 2.0 models: Source, Item
  sources.py           hardcoded source list + dialect-agnostic upsert
  adapters/
    base.py            FeedAdapter Protocol + NormalizedItem
    rss.py             feed resolution (→ Slice 3 validator) + entry normalization
    bluesky.py         handle→DID, getAuthorFeed, drop replies/reposts
  ingest.py            scrape orchestration (per-source error isolation)
  render.py            group by feeder, cap shorts, order; Jinja → HTML
  text.py              HTML-strip + word-boundary truncation
  templates/digest.html.j2
  cli.py               throwaway entrypoint (the only disposable file)
alembic/               migrations (carry forward to Postgres in Slice 4)
```

## What carries forward

- RSS feed-resolution → add-time source validator (Slice 3)
- SQLAlchemy models + Alembic migrations → real schema on Postgres (Slice 4)
- `digest.html.j2` → real digest email template (Slice 4)
- `feeder_name` stub → real `user_id` FK (Slice 2)
