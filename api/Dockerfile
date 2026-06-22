# Edge Mosaic API — production image for Railway.
# Base image ships Python 3.11 + uv (https://github.com/astral-sh/uv), matching
# requires-python = ">=3.11" in pyproject.toml.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Unbuffered logs (so Railway captures them live), no .pyc clutter, copy into the venv
# (hardlinks don't survive the cache-mount boundary), and precompile bytecode for faster
# cold starts. Put the venv on PATH so `alembic`/`uvicorn` resolve without `uv run`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Install dependencies from the lockfile FIRST, as their own cached layer, so edits to
#    app/ source don't bust the (slow) dependency install. --no-dev drops pytest & friends.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2) Copy the source and install the project itself into the venv.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run as a non-root user. /app is owned by it so config.py can create data/ and data/media/
# at import time (psycopg uses Postgres in prod, but those mkdir() calls still run).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Railway injects $PORT at runtime; default to 8000 for a plain `docker run`. Alembic runs
# on boot so a fresh Postgres is migrated before the server accepts traffic. Railway's
# startCommand (railway.json) overrides this for the web service; the cron services set
# their own (`python -m app.jobs.scrape` / `... digest`).
EXPOSE 8000
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
