# YouTube feed hardening — investigation brief

Self-contained brief for a **fresh context**. Branch: `prototype-/youtube`. Parent plan:
[`mvp-plan.md`](./mvp-plan.md) (see the "YouTube feed hardening" bullet in Deferred).

> **Task shape:** this is a *spike/investigation*, not a known build. The fix is unknown —
> the first job is to **reproduce and characterize the failure**, then pick the cheapest
> approach that actually works. Don't implement a heavy solution before confirming the
> simple ones fail.

## The problem

YouTube channels are ingested as RSS: a channel/handle URL resolves to YouTube's per-channel
Atom feed `https://www.youtube.com/feeds/videos.xml?channel_id=<UC…>`. Channel→id resolution
works, but the public feed fetch is **throttled / blocked at scale**.

**Observed (live 30-feeder scrape):** 9 of 10 YouTube sources came back as a non-feed
consent/block page (so `feedparser` saw no `version` and we stored nothing); 1
identical-shape URL succeeded. This is **intermittent anti-bot**, not a code bug — the same
code path works for one channel and fails for the next.

Hypotheses to confirm (don't assume): YouTube serves a **cookie-consent interstitial** or a
**bot challenge** to datacenter IPs / cookieless clients, more aggressively under burst
traffic. The "block page" is likely HTML (consent or `/sorry/`), which is why
`_try_parse` correctly rejects it (no feed `version`) and the item count is zero.

## How YouTube ingestion works today (code map)

All in `api/app/adapters/rss.py` (`RSSAdapter`):

- `fetch(source)` → `_platform_feed(url)` detects `youtube.com`/`youtu.be` and routes to
  `_youtube_feed(url)`, forcing `kind="long"` for every entry.
- `_youtube_feed(url)`:
  - if the URL already contains `/channel/UC…`, use that id directly (regex `_YT_CHANNEL_ID_RE`);
  - else `_youtube_channel_id(url)` does **`_get_text(url)`** (fetch the channel HTML) and
    scrapes the channel's *own* id from `"externalId":"UC…"` or the canonical `<link>`
    (`_YT_OWN_ID_RES`) — deliberately not the first `channelId` on the page (that's often a
    recommended channel);
  - returns `https://www.youtube.com/feeds/videos.xml?channel_id=<id>`.
- Back in `fetch`, the feed URL goes through `_try_parse` → `_get_bytes` (httpx GET) →
  `feedparser.parse`; a non-feed document (`version` empty) raises `FeedResolutionError`.

So there are **two** fetches that can be blocked: the channel **HTML** page (for id
resolution) and the **videos.xml** feed itself. The handle forms in our seed data
(`https://www.youtube.com/@AndrejKarpathy`, `/@t3dotgg`, …) hit *both*; a raw
`/channel/UC…` URL would skip the HTML fetch.

HTTP client config: one `httpx.Client`, `follow_redirects=True`, single header
`User-Agent: config.USER_AGENT` (currently
`"Mozilla/5.0 (compatible; edge-mosaic-spike/0.1; +https://github.com/edge-mosaic)"` — an
obvious non-browser UA), `timeout=RSS_FETCH_TIMEOUT` (10s). **No cookies, no retries.**

Scrape orchestration is `api/app/ingest.py` (`scrape` / `scrape_source`): per-source
try/except, records `last_checked_at`/`last_success_at`, dedup-inserts items. A failed
source just returns `SourceResult(ok=False, error=…)` — the run continues.

Runtime context: in prod this runs as a **Railway cron** (`python -m app.jobs.scrape`) —
**headless, datacenter IP**, which is precisely the environment most likely to be blocked.

## Reproduce it first

The dev DB (`api/data/`) is already seeded with YouTube channels via
`python -m app.cli seed-sources` (source: [`source-list.md`](./source-list.md) — e.g. Andrej
Karpathy, Theo Browne, the science YouTubers). From `api/` with `.venv`:

```bash
.venv/bin/python - <<'PY'
from app.db import SessionLocal
from app.models import Source
from app.ingest import scrape_source
from sqlalchemy import select
db = SessionLocal()
yt = [s for s in db.scalars(select(Source)) if "youtube.com" in s.input_url or "youtu.be" in s.input_url]
print(f"{len(yt)} youtube sources")
for s in yt:
    r = scrape_source(db, s)
    print(f"  {'OK ' if r.ok else 'ERR'} {r.new_items:>3} new  {s.input_url}  {r.error or ''}")
PY
```

Then **characterize the block**: fetch a failing channel's HTML and its `videos.xml`
directly with the current UA and capture the actual response — status code, redirects
(`Location`), and the first chunk of the body (consent page? `/sorry/`? `429`?). That
response is what dictates which approach below is needed. Vary: cookieless vs. a
`CONSENT`/`SOCS` cookie; spike UA vs. a real browser UA; back-to-back bursts vs. spaced.

## Candidate approaches (cheapest first — stop when one works)

1. **Browser-like UA + consent cookie.** Set a realistic desktop `User-Agent` and a consent
   cookie (`SOCS` / `CONSENT=YES+…`) on the client. If the block is the EU consent
   interstitial, this alone often fixes both the HTML and feed fetches. Near-zero cost.
2. **Retry with backoff + jitter; throttle concurrency/pacing.** If it's rate/burst-based
   (429 / intermittent), a couple of retries with exponential backoff and spacing YouTube
   requests (vs. hammering all channels at once) may suffice. Cheap, but adds run latency.
3. **Skip the HTML fetch when possible.** Resolve handles to `UC…` ids **once** and persist
   on the `Source` (e.g. store the resolved `videos.xml` in `resolved_feed_url` / the id in
   `external_id`) so steady-state scrapes hit only the feed, halving the block surface.
4. **YouTube Data API v3.** Official, key-based, free tier ~10k units/day (`channels.list`
   for the uploads playlist → `playlistItems.list`). Reliable from datacenter IPs, but adds
   an API key + quota management + a second code path. Reach for this if 1–3 don't hold.
5. **`yt-dlp` (or similar).** Handles consent/extraction robustly but is a heavy dependency,
   slower, and itself subject to breakage/blocking. Last resort.

The per-channel feed only carries ~15 latest videos — fine for the digest window, so we
don't need full history regardless of approach.

## Constraints / non-negotiables

- Must work **headless on a datacenter IP** (Railway cron), ideally **no auth** and **free**.
- Keep the **adapter interface** intact: YouTube stays a `type='rss'` source resolved inside
  `RSSAdapter` (or a cleanly factored helper), still producing `NormalizedItem`s with
  `kind='long'`. Don't fork the scrape orchestration.
- **One dead source must never kill the run** (the `scrape_source` try/except contract).
- Dialect-agnostic if you touch models/migrations (SQLite dev, Postgres prod — see
  `mvp-plan.md` §1); avoid SQLite-isms.
- Don't regress the non-YouTube RSS path or the Apple-Podcasts resolver in the same file.
- Be a polite client; don't build anything that hammers YouTube.

## Definition of done

- The repro script above scrapes the seeded YouTube channels with a **high success rate**
  (target: the previously-failing channels now return items), demonstrated locally and
  reasoned about for the datacenter-IP cron case.
- The fix is the **cheapest approach that actually works**, with a one-paragraph writeup of
  what the block actually was (from the characterization step) and why the chosen approach
  addresses it.
- Tests: a unit test around the resolver/fetch path (mock the HTTP layer — consent-page
  response vs. real feed) so the regression is locked; existing RSS/podcast tests stay green.
- Update the `mvp-plan.md` Deferred bullet (resolve it or narrow what remains).

## Suggested first move

Reproduce → **capture a real failing response body** → only then choose from the ladder
above. The characterization is 80% of the work; the fix is often approach #1.
