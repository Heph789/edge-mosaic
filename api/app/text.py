"""Small text helpers shared by adapters and the renderer."""

from __future__ import annotations

from bs4 import BeautifulSoup


def strip_html(value: str | None) -> str:
    """Render HTML to plain text (feeds love to dump full HTML bodies into summaries)."""
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text(separator=" ").strip()


def truncate_on_word(value: str | None, max_chars: int) -> str:
    """Truncate to ~max_chars on a word boundary, appending an ellipsis if cut."""
    if not value:
        return ""
    text = " ".join(value.split())  # collapse whitespace
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut + "…"
