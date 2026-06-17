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
