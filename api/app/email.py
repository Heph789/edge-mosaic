"""The `send_email()` interface (§5).

Slice 2 ships only the console sink: it logs the message and, for magic links, prints a
ready-to-curl line so the whole auth flow is drivable from a terminal with no real email.
Slice 4 swaps in a Resend-backed `send_email` behind this same signature — a one-file
change.
"""

from __future__ import annotations

import logging

log = logging.getLogger("edge_mosaic.email")


def send_email(to: str, subject: str, body: str) -> None:
    """Deliver an email. Console-sink implementation for Slice 2."""
    log.info("EMAIL → %s | %s\n%s", to, subject, body)
    # Also print (flushed, so it appears immediately even when stdout is piped to a file)
    # so the link shows up without logging configured — curl-driven dev.
    print(
        f"\n--- EMAIL (console sink) ---\nTo: {to}\nSubject: {subject}\n\n{body}\n--- end ---\n",
        flush=True,
    )
