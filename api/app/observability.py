"""Sentry initialization, shared by the web service and the two cron jobs.

The DSN comes from SENTRY_DSN; when it's unset — local dev, tests — init_sentry() is a
no-op and every sentry_sdk call elsewhere degrades to a harmless no-op too. That keeps
dev/test errors out of Sentry; set the var in the Railway environment to enable it.

Each entry point passes its `component` ("web" / "scrape" / "digest") so every event is
tagged with the process it came from — you can tell at a glance whether a failure was a
request, the scrape cron, or the digest cron.

The cron jobs MUST call sentry_sdk.flush() before the process exits: Sentry's transport
sends events from a background thread, and a short-lived `python -m app.jobs.*` process
dies immediately after main(), dropping anything still in flight.
"""

from __future__ import annotations

import os

import sentry_sdk


def init_sentry(component: str) -> None:
    """Initialize Sentry for one process. No-op when SENTRY_DSN is unset."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        # Attach request headers / client IP / user data for debuggability.
        send_default_pii=True,
        # Errors-only by default (cheap). Set SENTRY_TRACES_SAMPLE_RATE=0.1 etc. to
        # sample performance transactions; the FastAPI integration auto-instruments
        # requests once tracing is on.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
    )
    # Applies to every event from this process (the web server or one cron run).
    sentry_sdk.set_tag("component", component)
