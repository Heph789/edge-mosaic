Mosaic to keep up with friends

## Local development

**API** (FastAPI, port 8000):

```bash
cd api
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Swagger UI available at http://localhost:8000/docs. Magic-link emails are printed to the terminal by default (`EMAIL_BACKEND=console`) — grab the login link from there.

**Web** (Vite, port 5173):

```bash
cd web
pnpm install
pnpm dev
```

The SPA proxies `/api` to port 8000, so both servers need to be running.

## Database migrations

The schema is managed with Alembic. Run from the `api/` directory:

```bash
# Apply all pending migrations (runs automatically on startup too)
uv run alembic upgrade head

# Create a new migration after changing models.py
uv run alembic revision --autogenerate -m "describe the change"
```

See [`api/README.md`](api/README.md) for the full API reference, CLI commands, and deployment notes.
