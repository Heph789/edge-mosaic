# Slice 5 — Frontend (Vite/React/TS SPA)

Detailed, self-contained build spec for the final slice. Parent: [`mvp-plan.md`](./mvp-plan.md).
Written to be implementable **from a fresh context** — it restates the API contract and the
exact build steps so you don't need the design conversation.

## Goal

Tie the Slice 1–4 backend together with a **plain functional** SPA: the 3-tab authed app
(Directory · Digest · Profile) plus the public login / verify / unsubscribe pages. This is
the slice that finally gives the magic-link and unsubscribe emails real pages to land on.

Scope reminder: **functional, not polished**; the mosaic UI is explicitly out (§intro).

## Stack & decisions (resolved in the grill — don't re-litigate)

| Concern | Choice |
|---|---|
| Build | **Vite** + **React 18** + **TypeScript** |
| Server state | **TanStack Query** (`@tanstack/react-query`) |
| API client | **hand-written typed `api.ts`** mirrored from `/openapi.json` (no codegen) |
| Routing | **React Router** (`react-router-dom`) |
| Styling | **plain CSS** (one global sheet + small per-component) — no Tailwind / component lib |
| Auth | **localStorage bearer token** (§2), `AuthProvider` context, global 401→login |
| Hosting | **Vercel** (SPA catch-all rewrite), `VITE_API_URL` → Railway API |
| Tests | **Vitest + React Testing Library + MSW**, thin — verify / add-source / subscribe-toggle |

Repo is a monorepo: new **`/web`** beside `/api`.

## Backend change (do this first — one commit in `/api`)

The SPA is a separate origin, so FastAPI needs CORS.

1. `api/app/config.py` — add:
   ```python
   CORS_ORIGINS = [
       o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
   ]
   ```
2. `api/app/main.py` — add the middleware (after `app = FastAPI(...)`):
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(
       CORSMiddleware,
       allow_origins=config.CORS_ORIGINS,
       allow_credentials=False,   # bearer header, not cookies
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```
3. `api/.env.example` — document `CORS_ORIGINS` (prod = the Vercel domain).
4. Quick test: a cross-origin `OPTIONS` preflight to `/me` returns the
   `access-control-allow-origin` header.

## API contract (what the SPA consumes)

All authed endpoints take `Authorization: Bearer <session_token>`. Base = `VITE_API_URL`.

```ts
// shared
type User = { id: number; email: string; display_name: string | null;
              digest_frequency: "weekly" | "monthly"; digest_paused: boolean; onboarded: boolean };

// --- public ---
POST /auth/request-link  { email }            -> 200 { message }            // always generic
POST /auth/verify        { token }            -> 200 { session_token, user } | 400
POST /auth/logout        (bearer)             -> 200 { message }
POST /unsubscribe?token=…                     -> 200 { message }            // generic

// --- me ---
GET   /me                (bearer)             -> User
PATCH /me  { display_name?, digest_frequency?, digest_paused? } -> User     // partial

// --- sources (Profile) ---
POST   /sources/preview  { url }  -> { type, resolved_url, title, found_count,
                                       latest_title, latest_published_at } | 400(x.com) | 422(dead)
GET    /sources                   -> Source[]                               // own only
POST   /sources          { url }  -> Source (201) | 400 | 422               // inline first-scrape
DELETE /sources/{id}              -> 204 | 404
// Source = { id, type, input_url, resolved_feed_url, title,
//            last_checked_at, last_success_at, created_at }

// --- subscriptions (Digest) ---
POST   /subscriptions    { feeder_id } -> Subscription (200) | 404
DELETE /subscriptions/{feeder_id}      -> 204                                // idempotent
GET    /subscriptions                  -> Subscription[]
// Subscription = { feeder_id, display_name, platforms: string[] }

// --- discover (Directory) ---
GET /discover?q=…  -> Discover[]   // q required (422 if empty), cap 50
// Discover = { user_id, display_name, platforms: string[], is_subscribed: boolean }

// --- digest preview (Digest) ---
GET /me/digest/preview -> { window_start, window_end, feeders: Feeder[] }
// Feeder = { feeder_id, display_name, longs: Item[], shorts: Item[] }
// Item   = { title, url, excerpt, text, kind: "long"|"short", published_at }
```

## `/web` file tree

```
web/
  package.json · vite.config.ts · tsconfig.json · index.html
  .env.example                 # VITE_API_URL=http://localhost:8000
  vercel.json                  # SPA rewrite (see Deploy)
  src/
    main.tsx                   # mount + QueryClientProvider + AuthProvider + router
    api.ts                     # typed fetch wrappers + types + 401 handling
    auth.tsx                   # AuthProvider, useAuth(), token storage
    routes.tsx                 # route table + guards (RequireAuth, RequireOnboarded)
    styles.css                 # one global stylesheet
    components/
      AppShell.tsx             # tab nav (Directory · Digest · Profile) + display name + logout
      RequireAuth.tsx · RequireOnboarded.tsx
    pages/
      Login.tsx · Verify.tsx · Unsubscribe.tsx
      Onboarding.tsx
      Directory.tsx · Digest.tsx · Profile.tsx
    hooks/queries.ts           # useSources, useSubscriptions, useDiscover, useDigestPreview, mutations
  src/__tests__/               # verify.test.tsx, add-source.test.tsx, subscribe-toggle.test.tsx
```

## Auth model (`auth.ts` + `api.ts`)

- **Token** in `localStorage["em_token"]`. `api.ts` attaches `Authorization: Bearer` when present.
- **`api.ts` 401 handler:** on any `401`, clear the token and `window.location` to `/login`
  (covers the fixed 30-day expiry — no refresh logic).
- **`AuthProvider`** exposes `{ token, user, login(token,user), logout(), refreshUser() }`.
  On mount with a token but no user, it calls `GET /me` (and logs out on failure).
- **Guards:**
  - `RequireAuth` — no token → `/login`.
  - `RequireOnboarded` — `user.onboarded === false` → `/onboarding`. (Onboarding is a
    *frontend* gate only; the API never blocks on it.)

## Routes

```
/login                     Login              (public)
/auth/verify               Verify             (public; reads ?token, POSTs exchange)
/unsubscribe               Unsubscribe        (public; reads ?token, POSTs)
/onboarding                Onboarding         (RequireAuth)
/  (AppShell layout)       RequireAuth + RequireOnboarded
   index → /directory
   /directory              Directory
   /digest                 Digest
   /profile                Profile
*                          redirect → /directory (or /login)
```

## Screens

- **Login** — email input → `POST /auth/request-link` → always show "If your email is
  eligible, a link is on its way." Never reveal allowlist membership.
- **Verify** — on mount read `?token`, `POST /auth/verify`; on success `login()` + redirect
  (`/onboarding` if `!onboarded`, else `/directory`); on 400 show "link invalid/expired" +
  a link back to `/login`.
- **Unsubscribe** — on mount read `?token`, `POST /unsubscribe?token=…`, show confirmation.
- **Onboarding** — text field prefilled with `user.display_name` (may be the preseeded
  "Jane S."); `PATCH /me { display_name }` → on success refresh user → `/directory`.
- **Directory** — search box (debounce ~300ms) → `GET /discover?q=`; empty query shows a
  prompt, not a dump. Each row: name + platforms + **optimistic** subscribe toggle
  (`POST/DELETE /subscriptions`, rollback on error, invalidate the digest query on success).
- **Digest** — list `GET /subscriptions` (unsubscribe per row); frequency select + pause
  toggle → `PATCH /me`; **live preview** from `GET /me/digest/preview` rendered as a React
  component mirroring the email layout (escaped text only).
- **Profile** — edit display name (`PATCH /me`); **sources**: list `GET /sources`, add via
  two-step (paste → `POST /sources/preview` → confirm card "Found N, latest '<title>'" →
  `POST /sources`), remove (`DELETE /sources/{id}`); surface `400` (x.com "coming soon") and
  `422` (dead feed) inline. Logout button → `POST /auth/logout` + clear token.

## Interaction specifics

- **Optimistic subscribe toggle:** TanStack Query `onMutate` flips the row's
  `is_subscribed` in the cache, `onError` rolls back, `onSettled`/`onSuccess` invalidates
  `["discover", q]` and `["digest-preview"]`.
- **Two-step add-source:** preview result held in local state; "Add" uses it only as
  confirmation — the create call re-validates server-side regardless.
- **XSS rule (§2):** render all scraped strings as text (React escapes by default). **Never**
  `dangerouslySetInnerHTML` on feed/Bluesky content or the digest preview.

## Deploy (Vercel)

- Project root = `web/`. Build `vite build` → output `dist/`.
- `web/vercel.json` SPA rewrite so deep links (`/auth/verify?token=…`) serve `index.html`:
  ```json
  { "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
  ```
- Env: `VITE_API_URL` = Railway API URL. On the API side set `CORS_ORIGINS` = the Vercel domain.

## Tests (thin)

Vitest + React Testing Library + **MSW** (mock the API at the network layer):
- **Verify** — token→session→redirect; expired token → error state.
- **Add-source** — paste → preview card → add → appears in list; x.com → "coming soon".
- **Subscribe toggle** — optimistic flip; server error → rollback.

## Build sequence (ordered milestones)

1. **Backend CORS** commit in `/api` (above) — verify a preflight passes.
2. **Scaffold** `web/` (`npm create vite@latest web -- --template react-ts`), add deps:
   `@tanstack/react-query react-router-dom`; dev: `vitest @testing-library/react
   @testing-library/jest-dom msw jsdom`.
3. **`api.ts`** — types + fetch wrappers + 401 handling. **`auth.tsx`** — provider + storage.
4. **Router + guards + AppShell** — get the empty 3-tab shell rendering behind auth.
5. **Public pages** — Login, Verify, Unsubscribe (the auth loop end-to-end against the
   running API + console-sink link).
6. **Onboarding.**
7. **Directory** (search + optimistic toggle) → **Digest** (subs + settings + preview) →
   **Profile** (display name + sources two-step + logout).
8. **Styling pass** (one `styles.css`).
9. **Tests** (verify / add-source / subscribe-toggle).
10. **Deploy** to Vercel; set `VITE_API_URL` + API `CORS_ORIGINS`; smoke-test the live
    magic-link flow (needs `EMAIL_BACKEND=resend` + verified domain for real delivery).

## Definition of done

A real person can: open the SPA → enter an allowlisted email → click the magic link →
land verified → onboard → add a source → find someone in the Directory and subscribe →
see the live digest preview → adjust frequency/pause → unsubscribe from an email link.
That closes the core loop end-to-end through the UI.

## Done after this
This is the last MVP slice. Post-MVP work lives in [`mvp-plan.md` Deferred / follow-up]
(the mosaic UI, source-health handling, engagement ranking, etc.).
