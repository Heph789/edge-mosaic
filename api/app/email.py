"""The `send_email()` interface (§5) with swappable backends.

Default backend is the console sink (no real delivery) so the app is send-safe until a
verified domain is wired. Set EMAIL_BACKEND=resend (+ RESEND_API_KEY, EMAIL_FROM) in prod.
The Resend swap is exactly the one-file change the plan promised.
"""

from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("edge_mosaic.email")


def send_email(
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Deliver an email via the configured backend. Raises on a hard delivery failure."""
    if config.EMAIL_BACKEND == "resend":
        _send_resend(to, subject, html, text, headers)
    else:
        _send_console(to, subject, html, text, headers)


def _send_console(to, subject, html, text, headers) -> None:
    log.info("EMAIL → %s | %s", to, subject)
    body = text or html
    extra = f"\nheaders: {headers}" if headers else ""
    print(
        f"\n--- EMAIL (console sink) ---\nTo: {to}\nSubject: {subject}{extra}\n\n{body}\n--- end ---\n",
        flush=True,
    )


def _send_resend(to, subject, html, text, headers) -> None:
    if not config.RESEND_API_KEY:
        raise RuntimeError("EMAIL_BACKEND=resend but RESEND_API_KEY is unset")
    payload: dict = {
        "from": config.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if headers:
        payload["headers"] = headers
    resp = httpx.post(
        config.RESEND_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
        timeout=15.0,
    )
    resp.raise_for_status()
    log.info("EMAIL sent via Resend → %s | %s", to, subject)
