"""Render a `DigestData` (from the assembly engine) to the HTML email body (Slice 4).

The same `assemble_digest` output that feeds the JSON preview is rendered here to HTML —
one engine, two sinks.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import SHORT_TEXT_RENDER_CHARS
from .digest import DigestData
from .text import truncate_on_word

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        # Always escape: every value rendered is scraped content (XSS rule). Note the
        # template is named .html.j2, so extension-based select_autoescape would skip it.
        autoescape=True,
    )
    env.filters["truncate_words"] = truncate_on_word
    return env


def render_digest_html(data: DigestData, unsubscribe_url: str) -> str:
    env = _build_env()
    template = env.get_template("digest.html.j2")
    feeders = [
        {"name": f.display_name or "Someone", "longs": f.longs, "shorts": f.shorts}
        for f in data.feeders
    ]
    return template.render(
        feeders=feeders,
        window_start=data.window_start,
        window_end=data.window_end,
        short_text_chars=SHORT_TEXT_RENDER_CHARS,
        unsubscribe_url=unsubscribe_url,
    )
