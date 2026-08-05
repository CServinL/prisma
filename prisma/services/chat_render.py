"""Renders a chat message's raw markdown content (tables, code blocks,
links -- same docu_craft pipeline services/renderer.py already gives Notes/
Sources) to sanitized HTML, with ADR-017 footnote markers (`[^N]`) converted
to a real element the UI can attach click-to-jump/color-by-relation behavior
to after {@html} mounts it -- see ADR-017's 2026-08-04 rendering addendum
and docs/concepts/chat.md.

Kept separate from renderer.render() rather than folded into it: Notes/
Sources have no concept of a footnote marker, and this substitution has to
happen on the raw markdown *before* rendering (so the marker survives as
real HTML, not a client-side string-surgery pass on already-rendered HTML,
which risks corrupting tag structure if a marker lands somewhere awkward).
"""
from __future__ import annotations

import re

from prisma.services.renderer import render
from prisma.services.vault import VaultService

_FOOTNOTE_MARKER_RE = re.compile(r"\[\^(\d+)\]")


def _footnote_marker_span(match: re.Match) -> str:
    n = match.group(1)
    return f'<span class="footnote-marker" data-footnote-index="{n}">{n}</span>'


def render_chat_message(content: str, vault: VaultService) -> str:
    marked = _FOOTNOTE_MARKER_RE.sub(_footnote_marker_span, content)
    html, _, _ = render(marked, vault)
    return html
