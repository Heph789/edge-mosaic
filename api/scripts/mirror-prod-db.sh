#!/usr/bin/env bash
# Mirror Railway production data into the local dev database (SQLite).
#
# Pulls the Postgres service's PUBLIC connection URL from Railway (TLS proxy — the pull
# is encrypted in transit) and hands it to `python -m app.mirror`, which copies every
# table into the local dev DB. Auth tables (sessions, magic_link_tokens) are skipped by
# default. See app/mirror.py for the details and flags.
#
# Requirements: the Railway CLI (`railway login` + this repo linked via `railway link`).
#
# Usage:
#   scripts/mirror-prod-db.sh            # prompts before overwriting the local DB
#   scripts/mirror-prod-db.sh --yes      # no prompt (pass-through to app.mirror)
#   scripts/mirror-prod-db.sh --keep-auth
#
# Env overrides:
#   RAILWAY_PG_SERVICE   Railway service name of the Postgres DB (default: Postgres)

set -euo pipefail

PG_SERVICE="${RAILWAY_PG_SERVICE:-Postgres}"
API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v railway >/dev/null 2>&1; then
  echo "error: railway CLI not found. Install it and run 'railway login' + 'railway link'." >&2
  exit 1
fi

echo "Fetching prod connection URL from Railway service '${PG_SERVICE}'..."
SOURCE_DATABASE_URL="$(railway variables --service "${PG_SERVICE}" --kv 2>/dev/null | sed -n 's/^DATABASE_PUBLIC_URL=//p')"

if [ -z "${SOURCE_DATABASE_URL}" ]; then
  echo "error: could not read DATABASE_PUBLIC_URL from service '${PG_SERVICE}'." >&2
  echo "       Check 'railway status' is linked, and set RAILWAY_PG_SERVICE if the DB" >&2
  echo "       service has a different name. The public URL is required to reach prod" >&2
  echo "       from your laptop (the internal *.railway.internal host is not routable)." >&2
  exit 1
fi

export SOURCE_DATABASE_URL
cd "${API_DIR}"
exec uv run python -m app.mirror "$@"
