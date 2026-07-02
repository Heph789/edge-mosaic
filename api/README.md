# Edge Mosaic API

FastAPI backend for Edge Mosaic. Feeders register content sources (RSS, Bluesky);
subscribers receive a periodic email digest of new items from the feeders they follow.

## Stack

- Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Alembic
- SQLite for local dev, Postgres in production (set `DATABASE_URL`)

## Local development

```bash
cd api
uv sync
uv run uvicorn app.main:app --reload --port 8000   # http://localhost:8000  (Swagger at /docs)
```

The SPA lives in [`../web`](../web):

```bash
cd web && npm install && npm run dev               # http://localhost:5173
```

Configuration is read from environment variables — see [`.env.example`](.env.example); all
have local-dev defaults. The schema is managed by Alembic and brought to head automatically on
startup and on each CLI command.

With `EMAIL_BACKEND=console` (the default) magic links and digests are written to the API log
instead of being emailed — grab the login link from there.

## Operator CLI

```bash
uv run python -m app.cli import-allowlist <csv>   # open the login allowlist from a roster
uv run python -m app.cli seed-sources [md]        # pre-seed feeders + their sources
uv run python -m app.cli scrape                   # fetch all sources, store deduped items
```

The daily jobs are their own entrypoints (these are what the production cron runs):

```bash
uv run python -m app.jobs.scrape                  # ingest new items
uv run python -m app.jobs.digest                  # assemble + send due digests
```

## Mirror production data locally

Pull a fresh copy of the production data into your local SQLite DB for testing. Requires the
Railway CLI (`railway login` + `railway link`); the pull runs over Railway's TLS Postgres proxy.

```bash
scripts/mirror-prod-db.sh                          # prompts before replacing the local DB
scripts/mirror-prod-db.sh --yes                    # no prompt
scripts/mirror-prod-db.sh --keep-auth              # also copy sessions + magic-link tokens
```

It rebuilds the local schema from base to Alembic head, then copies every table. Auth tables
(`sessions`, `magic_link_tokens`) are skipped by default. The destination is always the local
SQLite DB — it refuses to run if `DATABASE_URL` points at a non-SQLite database. See
[`app/mirror.py`](app/mirror.py).

## Deployment

See [`../deploy-instructions.md`](../deploy-instructions.md) for the Railway deployment and the
admin allowlist-seeding procedure.
