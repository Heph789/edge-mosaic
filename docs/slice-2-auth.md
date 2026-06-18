# Slice 2 — Auth + Allowlist

Detailed build spec for the second slice. Parent: [`mvp-plan.md`](./mvp-plan.md).

## Goal

Stand up real identity for the app: turn the Slice 1 anonymous `feeder_name` stub into
real `users`, gated by the **CSV allowlist**, reached by **passwordless magic links**, and
held by **opaque server-side sessions**.

**request a link → verify → session → call an authed endpoint** — end to end, backend
only.

Two MVP dependencies are deliberately *not* here yet:
- **Email** is a **console sink** (the link is logged, not sent). Resend lands in Slice 4
  behind the same `send_email()` interface.
- **Frontend** is Slice 5. This slice is exercised with **curl / pytest**, not a UI.

When you can drive the whole auth state machine from a terminal and the `sources` table is
re-keyed to `user_id`, Slice 2 is done.

## Tooling (additions to Slice 1)

| Concern | Choice | Notes |
|---|---|---|
| Web framework | **FastAPI** + **uvicorn** | `app.main:app`; the real web role from §1 |
| Validation | **Pydantic v2** | request/response schemas (ships with FastAPI) |
| Tests | **pytest** + **httpx** `ASGITransport` | in-process client, no live server |
| Hashing | **`hashlib.sha256`** (stdlib) | tokens are 256-bit random — no bcrypt needed |
| Tokens | **`secrets.token_urlsafe(32)`** (stdlib) | magic-link + session tokens |
| CSV | **`csv.DictReader`** (stdlib) | defensive parse of a roster we don't own |

Still SQLite in dev; still dialect-agnostic models; Postgres at Slice 4.

## Schema (full set after this slice)

New tables `users`, `allowed_emails`, `magic_link_tokens`, `sessions`; `sources`
restructured. See [`mvp-plan.md` §6](./mvp-plan.md#6-data-model) for the canonical block.
Key columns specific to this slice:

```
users
  id · email (unique, lowercased) · display_name (nullable)
  digest_frequency ('weekly'|'monthly', default 'weekly') · digest_paused (default false)
  verified_at (nullable)          -- NULL = pre-seeded ghost, never logged in
  onboarded (bool, default false) -- explicit; NOT derived from display_name
  last_digest_sent_at · last_covered_through · created_at

allowed_emails
  id · email (unique, lowercased) · name (nullable, abbreviated form only)
  claimed_by_user_id (nullable FK users.id) · created_at

magic_link_tokens
  id · email (NOT user_id) · token_hash (unique) · expires_at · used_at · created_at

sessions
  id · user_id (FK users.id) · token_hash (unique) · expires_at · created_at
```

### Migration 0002 — the `feeder_name → user_id` swap
- Create the four new tables.
- `batch_alter_table("sources")`: drop `feeder_name` + `uq_source_feeder_input`, add
  `user_id` (FK → `users.id`, NOT NULL) + `UNIQUE(user_id, input_url)`.
- **No backfill.** Slice 1 `sources`/`items` rows are throwaway local SQLite; wipe the dev
  DB and re-run. In prod (Slice 4) `sources` is empty when this first runs, so
  assume-empty is correct.
- **Consequence:** the Slice 1 scrape/render CLI goes **dormant** (it can't key on
  `feeder_name` anymore). Slice 3 rebuilds source-adding on the real `user_id` model.
  Don't resurrect it now.

## User lifecycle (three independent states)

| State | Carried by | Meaning |
|---|---|---|
| **Exists** | a `users` row | created by pre-seed *or* lazily at verify |
| **Verified** | `verified_at` | proven inbox ≥ once. `NULL` ⇒ pre-seeded ghost, never logged in |
| **Onboarded** | `onboarded` bool | explicit; a pre-seeded user can have a name yet be un-onboarded |

The **lazy** path (verify creates the row) stamps `verified_at` in the same transaction —
so a lazily-created user is *never* `NULL`. Only **pre-seeded** users dwell at
`verified_at IS NULL`.

## Allowlist import (`python -m app.cli import-allowlist <csv>`)

Operator-run CLI (no admin HTTP surface in the MVP). Default path:
`api/input/attendees-Edge Esmeralda 2026-*.csv` (the real roster — PII, not in git).

The roster headers are fixed and **not ours to change**:
`First Name, Last Name, Email, Telegram, Role, Organization, Residence, Age, Gender`.
Any cell may be `*` (anonymity marker).

Rules:
1. **Read only `First Name`, `Last Name`, `Email`** via `DictReader` (ignore the rest — a
   column reorder/addition won't break us).
2. **`*` (or blank) → `None`** everywhere — it's a redaction marker, never literal data.
3. **Email `None` → skip the row and count it.** Email *is* identity and the gate; an
   anonymized email is unusable. Print `imported N, skipped M (no email)`.
4. **Name transform → abbreviated, full surname never persisted:**
   - first + last → `f"{first} {last_initial}."` → `"Jane S."` (initial = first
     *alphabetic* char of last name, upper-cased)
   - first only → `"Jane"`
   - first `None` → `name = None` (don't derive from email local-part — would leak a surname)
5. **Auto pre-seed named entries:** if `name` is non-null, get-or-create a `users` row
   (`display_name = name`, `verified_at = NULL`, `onboarded = False`). Anonymized entries
   get the `allowed_emails` gate row **only**.
6. **Idempotent, never destructive:** lowercase+trim emails; insert-missing via
   select-then-insert (**no `ON CONFLICT`** — SQLite-ism); **never delete** rows absent
   from the CSV; **never clobber** an existing `claimed_by_user_id` or a user's
   (possibly edited) `display_name`. Dedup within the file (first-wins).

## Auth flow & endpoints

`send_email(to, subject, body)` is an interface; Slice 2's impl logs to stdout and prints
a ready-to-curl line with the raw token.

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /auth/request-link {email}` | public | Always `200 {"message": "if eligible…"}` (no allowlist enumeration). If on the allowlist: invalidate prior unused tokens for the email, mint a single-use token (~15 min), `send_email` the link. |
| `POST /auth/verify {token}` | public | **Atomic claim** (`UPDATE … used_at WHERE unused AND unexpired`, rowcount=1). **Get-or-create** user by normalized email; set `verified_at` + `allowed_emails.claimed_by_user_id`; preseed `display_name` from the roster name if creating. Mint a 30-day session. Return `{session_token, user}`. Invalid/expired/used → generic `400`. |
| `GET /me` | bearer | Current user `{id, email, display_name, digest_frequency, digest_paused, onboarded}`. |
| `PATCH /me {display_name}` | bearer | Trim, reject empty/whitespace/`*`-only, cap ~50 chars; set `display_name`, flip `onboarded = True`. |
| `POST /auth/logout` | bearer | Delete the current session row (exercises revocation — the reason for opaque tokens). |

### Tokens & sessions
- **`secrets.token_urlsafe(32)`**, stored only as **`sha256(token)`** in `UNIQUE` hash
  columns. Raw token lives in the URL / `Authorization: Bearer` header only.
- **Magic link:** single-use, ~15-min expiry; new request invalidates priors → one live
  link per email.
- **Session:** fixed ~30-day expiry, no sliding renewal.
- **`current_user` dependency:** `sha256` the bearer → look up `sessions` (unexpired) →
  join `users` → else `401`.
- **Anti-prefetch:** verify is a **POST with token in the body** — a scanner's bare GET of
  the SPA landing link only loads JS, never burning the token. Never expose a
  token-consuming GET.

### Abuse protection
- **No real rate limiter in Slice 2** (console sink — no email cost). The one-live-token
  rule + gate-check-before-work already bound the blast radius.
- All sends funnel through **one `request_magic_link()` choke point** so a per-email
  cooldown (DB-count on `magic_link_tokens.created_at`) drops in at Slice 4 when Resend
  makes sends cost money + reputation.

## Definition of done

1. `import-allowlist <roster.csv>` populates `allowed_emails` + pre-seeds named users,
   idempotently (re-run = no dupes, no clobbers).
2. A pytest flow drives **request-link → (grab token from the email sink) → verify →
   `GET /me` → `PATCH /me` → `POST /auth/logout`**, asserting: privacy-preserving
   request response, single-use enforcement, expiry rejection, get-or-create (pre-seeded
   *and* lazy), 401 after logout.
3. Migration 0002 applies cleanly to a fresh SQLite DB; `sources` is `user_id`-keyed.

## Carries forward
- `send_email()` console sink → **Resend** (Slice 4); the cooldown choke point goes live then.
- `users` / sessions / `current_user` → every authed endpoint in Slice 3 (CRUD, search).
- Pre-seeded users → **Discover** + **pre-subscription** (Slice 3 / Slice 5).
- The roster `name`-abbreviation + preseed → **onboarding** screen (Slice 5).
