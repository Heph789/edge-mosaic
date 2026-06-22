# Deploying Edge Mosaic to Railway

This is the operator runbook for standing up Edge Mosaic in production. It covers the
**API** (FastAPI, deployed from `api/Dockerfile`), its **Postgres** database, the two
**cron jobs** (scrape + digest), and the **frontend** SPA.

Architecture is split-origin:

```
                ┌──────────────────────── Railway project ────────────────────────┐
                │                                                                  │
  browser ──▶   │   web  (Vercel or Railway static)                                │
                │     │ VITE_API_URL                                               │
                │     ▼                                                            │
                │   api  (Dockerfile)  ──▶  Postgres (Railway plugin)              │
                │     ▲                                                            │
                │     │ shares the SAME image + DATABASE_URL                       │
                │   cron: scrape  (daily — fetch RSS/Bluesky into items)           │
                │   cron: digest  (daily — assemble + email per-subscriber digest) │
                │                                                                  │
                └──────────────────────────────────────────────────────────────────┘
```

Everything runs from the **same Docker image** built from `api/`. The web, scrape, and
digest services differ only in their start command.

---

## 0. Prerequisites

- A [Railway](https://railway.app) account, and the repo pushed to GitHub (Railway deploys
  from a connected repo).
- A [Resend](https://resend.com) account with a **verified sending domain** (SPF/DKIM/DMARC)
  if you want real email delivery. Without it the app runs in `console` mode and just logs
  digests — safe, but no mail goes out.
- *(Optional)* the [Railway CLI](https://docs.railway.com/develop/cli): `npm i -g @railway/cli`.

The repo already contains everything Railway needs:

- `api/Dockerfile` — the production image (Python 3.11 + uv, installs from `uv.lock`).
- `api/.dockerignore` — keeps local DB/media/secrets out of the build.
- `api/railway.json` — pins the builder to `DOCKERFILE` and sets the web start command.

---

## 1. Create the project and provision Postgres

1. **New Project → Deploy from GitHub repo**, and select this repository.
2. In the project, **+ New → Database → Add PostgreSQL**. Railway provisions it and exposes
   a `DATABASE_URL` reference variable.
   - The app normalizes Railway's `postgres://` / `postgresql://` URL to the `psycopg3`
     driver automatically (see `api/app/config.py`), so paste it as-is.

---

## 2. Configure the API service

Railway will have created a service from the repo. Configure it:

1. **Settings → Root Directory:** set to `api`.
   This makes `api/` the build context, so `Dockerfile`, `pyproject.toml`, `uv.lock`, and
   `alembic/` are all visible to the build. (Railway auto-detects `api/railway.json`.)
2. **Settings → Build:** confirm the builder is **Dockerfile** (`railway.json` already pins
   this; if you ever see Nixpacks, it's because the root dir isn't `api/`).
3. **Networking → Generate Domain** to get a public URL, e.g.
   `https://edge-mosaic-api.up.railway.app`. You'll need it for `API_BASE_URL` and the
   frontend's `VITE_API_URL`.
4. Add the environment variables below.

### API environment variables

| Variable        | Required? | Value                                                                                  |
| --------------- | --------- | -------------------------------------------------------------------------------------- |
| `DATABASE_URL`  | yes       | Reference the Postgres plugin: `${{Postgres.DATABASE_URL}}`                             |
| `APP_BASE_URL`  | yes       | The deployed SPA origin, e.g. `https://edge-mosaic.vercel.app` (magic-link target)      |
| `API_BASE_URL`  | yes       | This API's own public origin, e.g. `https://edge-mosaic-api.up.railway.app`             |
| `CORS_ORIGINS`  | yes       | Comma-separated SPA origins allowed to call the API, e.g. `https://edge-mosaic.vercel.app` |
| `EMAIL_BACKEND` | no        | `console` (default, logs only) or `resend` for real delivery                           |
| `RESEND_API_KEY`| if resend | Your Resend API key (`re_...`)                                                          |
| `EMAIL_FROM`    | if resend | Sender on the verified domain, e.g. `Edge Mosaic <digest@yourdomain.com>`               |

> `PORT` is injected by Railway — **do not set it.** The Dockerfile/start command bind to it.
> All other settings have sensible defaults in `api/app/config.py`; only override what's above.

On deploy, the start command runs `alembic upgrade head` before the server starts, so the
schema is created/migrated automatically against the fresh Postgres. No manual migration step.

**Verify:** open `https://<your-api-domain>/docs` — the Swagger UI should load.

---

## 3. Add the cron services (scrape + digest)

Both daily jobs run as separate services that **reuse the same image and database** but run a
one-shot command instead of the web server. Create each one:

1. **+ New → GitHub Repo** (same repo) → **Settings → Root Directory:** `api`.
   (Or duplicate the API service.)
2. Add the same `DATABASE_URL` (and, for the digest job, the `EMAIL_*` vars).
3. **Settings → Cron Schedule:** set a cron expression (UTC).
4. **Settings → Deploy → Custom Start Command:** override the default with the job entrypoint.

| Service  | Start command                | Suggested cron (UTC) | Needs                                   |
| -------- | ---------------------------- | -------------------- | --------------------------------------- |
| `scrape` | `python -m app.jobs.scrape`  | `0 6 * * *` (06:00)  | `DATABASE_URL`                          |
| `digest` | `python -m app.jobs.digest`  | `0 13 * * *` (13:00) | `DATABASE_URL`, `EMAIL_*`, `APP/API_BASE_URL` |

Schedule **scrape before digest** so each day's digest reflects the morning's fresh items.
The digest job is idempotent (`UNIQUE(subscriber_id, anchor_date)`), so an accidental
re-run won't double-send.

> Railway cron services run the start command on schedule and then exit — that's expected;
> they are not long-running. Keep their restart policy default.

---

## 4. Email (Resend) setup

1. In Resend, add and verify your sending domain (DNS: SPF, DKIM, DMARC).
2. Create an API key.
3. On the **API service** and the **digest** cron service, set:
   - `EMAIL_BACKEND=resend`
   - `RESEND_API_KEY=re_...`
   - `EMAIL_FROM=Edge Mosaic <digest@yourdomain.com>` (must be on the verified domain)

Until then, leave `EMAIL_BACKEND=console`: digests are rendered and logged but not sent, which
is the safe default for a first deploy.

---

## 5. Seed the user allowlist (admin only)

Login is gated on the `allowed_emails` table: an email must be on the allowlist before it can
request a magic link, and a *named* roster entry also pre-seeds that person's `users` row. So
**seeding the allowlist is how the proper users get into the system.** This is the existing
operator CLI — `app/allowlist.py`, run via `python -m app.cli import-allowlist`. It is:

- **Idempotent** — re-running only inserts what's missing; it never deletes, never clobbers a
  claimed account or an existing name. Safe to run repeatedly as the roster grows.
- **Privacy-preserving** — persists only the email and an abbreviated name (`"Jane S."`); full
  surnames, phone, age, etc. from the CSV are ignored.

**Why this is admin-only:** the roster CSV is real attendee PII. It is gitignored *and* excluded
from the Docker image (`.dockerignore` drops `input/`), so it is **never baked into the deploy**.
The only people who can seed are those with Railway project access who supply the roster at run
time. There is no public endpoint.

### Procedure (Railway one-off command)

Run the CLI inside the live API container — it already has the code, the DB connection
(`DATABASE_URL` → prod Postgres), and runs `alembic upgrade head` first. You provide the roster
CSV at run time so the PII never lands in git or the image.

```bash
# 1. SSH into the running API service (requires Railway project access).
railway ssh -s api

# 2. In the container shell, paste the roster CSV into a temp file:
cat > /tmp/roster.csv      # paste CSV contents, then Ctrl-D
#    Only three columns are read: First Name, Last Name, Email (exact header names).
#    Email is required per row; a row with a First Name also pre-seeds that user. Any other
#    columns are ignored, and `*` in a cell is treated as absent. Minimal roster:
#        First Name,Last Name,Email
#        Jane,Smith,jane@example.com

# 3. Seed. Prints a summary: imported / pre-seeded / already-present / skipped.
python -m app.cli import-allowlist /tmp/roster.csv

# 4. The temp file lives only in the ephemeral container; it's gone on the next restart.
#    To be explicit: rm /tmp/roster.csv
```

> Verified: this exact command runs cleanly inside the production image and is idempotent
> (a second run reports `0 new`).

**Adding people later:** re-run the same command with an updated CSV — only the new rows are
inserted. **Removing access** is intentionally *not* part of import (it never deletes); to revoke
someone, delete their `allowed_emails` row directly (e.g. via `railway connect` to a psql shell).

> Alternatives if SSH-paste is awkward (e.g. a large roster): point a local
> `python -m app.cli import-allowlist <csv>` at the Postgres **public** proxy URL
> (`railway variables` → `DATABASE_PUBLIC_URL`), or run it as a one-off via `railway run`. Same
> command, same idempotent result — the SSH-paste flow above just keeps the PII off your laptop's
> shell history and avoids exposing the DB publicly.

---

## 6. Frontend (SPA)

The SPA is a static Vite build that just needs `VITE_API_URL` pointed at the Railway API.
It's a **build-time** variable, so changing it requires a rebuild.

**Option A — Vercel (already configured).** `web/vercel.json` has the SPA rewrite. Import the
repo into Vercel with **Root Directory = `web`**, set `VITE_API_URL=https://<your-api-domain>`,
and deploy. Then set the API's `APP_BASE_URL` / `CORS_ORIGINS` to the Vercel domain.

**Option B — Railway static site.** Add another service (Root Directory `web`), build with
`npm install && npm run build`, and serve the `dist/` folder with a static server (e.g.
`npx serve -s dist -l $PORT`). Set `VITE_API_URL` in its build environment. If you go this
route, ask and I'll add a `web/Dockerfile` (nginx or `serve`) to match.

Either way, the API's `CORS_ORIGINS` and `APP_BASE_URL` must list the final SPA origin, or
authed calls and magic links will break.

---

## 7. Going live — checklist

- [ ] Postgres provisioned; `DATABASE_URL` referenced on api + both cron services.
- [ ] API deployed, `/docs` loads, logs show `alembic upgrade head` ran clean.
- [ ] `APP_BASE_URL`, `API_BASE_URL`, `CORS_ORIGINS` all point at the real prod domains.
- [ ] Allowlist seeded (`import-allowlist`); a roster email can request a magic link.
- [ ] Frontend deployed with `VITE_API_URL` → API domain; a magic-link login round-trips.
- [ ] `scrape` cron runs and inserts items (check logs / the discover feed).
- [ ] `digest` cron runs; with `EMAIL_BACKEND=resend`, a test subscriber receives mail.

---

## Notes & gotchas

- **Migrations:** run automatically on every API boot (`alembic upgrade head`). New migrations
  ship by adding files under `api/alembic/versions/` — no separate deploy step.
- **Local media is ephemeral.** Uploaded profile/tile images are written to the container's
  `data/media/` (the `app/storage.py` seam) and are **lost on every redeploy/restart**, and
  not shared across the api + cron containers. For durable images, swap `storage.py` to object
  storage (S3/R2) before relying on uploads in prod. Fine to defer for an early launch.
- **Secrets:** `.env` is gitignored and excluded by `.dockerignore` — set all secrets in the
  Railway dashboard, never bake them into the image.
- **One image, three roles:** api/scrape/digest share the build. A code change redeploys all
  three; keep their env vars in sync (Railway shared variables help here).
- **Builder switched to Docker:** `railway.json` now uses `DOCKERFILE` (was Nixpacks). The
  `api/Procfile` is now only a local/Heroku-style convenience and is unused by Railway.
