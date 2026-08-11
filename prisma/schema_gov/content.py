"""Typed multi-format text content -- markdown today, with room for HTML/
SVG/LaTeX later (tables, code blocks, math, diagrams) without a field
reshape each time a new format is added, replacing a flat `content: str` +
`html: str | None` field pair."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

__all__ = ["ContentFormat", "RichContent"]


class ContentFormat(str, Enum):
    markdown = "md"
    html = "html"
    svg = "svg"      # schema support only -- no rendering pipeline yet
    latex = "latex"  # schema support only -- no rendering pipeline yet


class RichContent(BaseModel):
    format: ContentFormat = ContentFormat.markdown
    value: str
    # Populated only in API responses, never persisted raw -- same
    # "computed at read time" convention prisma's own Chat.context_tokens_used
    # already uses for response-only fields.
    rendered_html: str | None = None
