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

# 1) Install dependencies from the lockfile FIRST, as their own Docker layer, so edits to
#    app/ source don't bust the (slow) dependency install. --no-dev drops pytest & friends.
#    --no-cache keeps uv's download cache out of the image layer (no BuildKit cache mount,
#    so Railway's Docker builder accepts this without a syntax directive).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-cache

# 2) Copy the source and install the project itself into the venv.
COPY . .
RUN uv sync --frozen --no-dev --no-cache

# Run as a non-root user. /app is owned by it so config.py can create data/ and data/media/
# at import time (psycopg uses Postgres in prod, but those mkdir() calls still run).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Web server entrypoint. Explicit `sh -c` so ${PORT:-8000} is expanded by a shell — Railway
# runs a no-operator start command WITHOUT a shell, which would pass the literal string to
# uvicorn. Railway injects $PORT; defaults to 8000 for a plain `docker run`. Migrations are NOT
# run here — they run as railway.json's preDeployCommand (`alembic upgrade head`) so a slow/
# unreachable DB on boot can't block the server from binding. The cron services override this
# with their own command (`python -m app.jobs.scrape` / `... digest`).
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
