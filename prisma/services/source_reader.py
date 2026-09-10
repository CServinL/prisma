"""Bounded, addressable reads of a single vault document's own raw text.

No Kùzu/graph involvement at all — this is the "read the actual file"
counterpart to the graph-derived retrieval in `kg_queries.py`. Every mode
returns a bounded slice, never the whole file (the flat whole-file dump
TODO.md's 2026-07-02 note rejected).

Modes:
  - summary  — leading excerpt, same shape `ChatToolbox._search_vault` uses,
               just addressable by exact slug instead of via a ChromaDB hit.
  - section  — naive heading-split of the markdown body; returns the section
               whose heading contains `query` (case-insensitive).
  - literal  — literal, case-insensitive line search within the raw text,
               matching lines with a few lines of context each — a grep
               scoped to one file. Literal-only, not a regex engine: `query`
               is REST-caller-controlled (see GET /notes/{slug}/read), and
               Python's stdlib `re` has no execution timeout, so a
               catastrophic-backtracking pattern (e.g. "(a+)+$") run against
               every line could hang a server worker. Not worth the risk
               for what this mode is for.
"""
from __future__ import annotations

import re

from prisma.services.vault import VaultService
from prisma.storage.models.kg_models import ReadSourceResponse

_EXCERPT_CHARS = 2000
# section/literal read the whole document -- cap it so a large imported
# PDF->MD can't load tens of MB into a worker. A match/heading past this is
# treated as absent (the modes are best-effort, not exhaustive).
_MAX_SCAN_CHARS = 2_000_000
_SECTION_MAX_CHARS = 4000
_LITERAL_CONTEXT_LINES = 2
_LITERAL_MAX_MATCHES = 20
# Bounds on top of _LITERAL_MAX_MATCHES -- that caps how many blocks are
# considered, not their size. A single arbitrarily long line (a minified
# blob, a data URI) could otherwise still make the joined `text` return
# megabytes despite the match-count cap.
_LITERAL_MAX_LINE_CHARS = 500
_LITERAL_MAX_TOTAL_CHARS = 8000

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")


def read_source(
    vault: VaultService, slug: str, mode: str = "summary", query: str | None = None,
) -> ReadSourceResponse:
    path = vault.find_file(slug)
    if path is None:
        raise FileNotFoundError(slug)

    if mode == "summary":
        # Bounded read straight from disk -- summary is a leading excerpt by
        # definition, so it shouldn't load the whole file into memory first
        # (matters for a large vault document). A text-mode file object's
        # .read(n) reads at most n *characters*, decoding as it goes, not n
        # raw bytes -- exactly what _EXCERPT_CHARS means here.
        with path.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read(_EXCERPT_CHARS)
        return ReadSourceResponse(slug=slug, mode="summary", text=text)

    # section/literal genuinely need the whole document -- a heading or a
    # match can be anywhere in it -- but bounded (see _MAX_SCAN_CHARS).
    with path.open("r", encoding="utf-8", errors="replace") as f:
        raw = f.read(_MAX_SCAN_CHARS)
    if mode == "section":
        return _read_section(slug, raw, (query or "").strip())
    if mode == "literal":
        return _read_literal(slug, raw, query or "")
    raise ValueError(f"unknown read mode: {mode!r}")


def _strip_frontmatter(raw: str) -> str:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            nl = raw.find("\n", end + 1)
            return raw[nl + 1:] if nl != -1 else ""
    return raw


def _read_section(slug: str, raw: str, query: str) -> ReadSourceResponse:
    lines = _strip_frontmatter(raw).splitlines()
    sections: list[tuple[str, list[str]]] = []
    heading: str | None = None
    buf: list[str] = []
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            if heading is not None:
                sections.append((heading, buf))
            heading = m.group(1).strip()
            buf = [line]
        else:
            buf.append(line)
    if heading is not None:
        sections.append((heading, buf))

    headings = [h for h, _ in sections]
    if query:
        for h, body_lines in sections:
            if query.lower() in h.lower():
                return ReadSourceResponse(
                    slug=slug, mode="section", query=query,
                    text="\n".join(body_lines)[:_SECTION_MAX_CHARS],
                    available_sections=headings,
                )
    return ReadSourceResponse(
        slug=slug, mode="section", query=query or None, text="", available_sections=headings,
    )


def _read_literal(slug: str, raw: str, query: str) -> ReadSourceResponse:
    if not query:
        return ReadSourceResponse(slug=slug, mode="literal", query=None, text="", match_count=0)
    needle = query.lower()
    lines = raw.splitlines()
    hit_indices = [i for i, line in enumerate(lines) if needle in line.lower()]
    truncated = len(hit_indices) > _LITERAL_MAX_MATCHES
    blocks: list[str] = []
    used = 0
    for i in hit_indices[:_LITERAL_MAX_MATCHES]:
        lo = max(0, i - _LITERAL_CONTEXT_LINES)
        hi = min(len(lines), i + _LITERAL_CONTEXT_LINES + 1)
        block_lines = []
        for j in range(lo, hi):
            line = lines[j]
            if len(line) > _LITERAL_MAX_LINE_CHARS:
                truncated = True
                line = line[:_LITERAL_MAX_LINE_CHARS]
            block_lines.append(f"{j + 1}{':' if j == i else '-'}{line}")
        block = "\n".join(block_lines)
        if used + len(block) > _LITERAL_MAX_TOTAL_CHARS:
            truncated = True
            break
        blocks.append(block)
        used += len(block)
    return ReadSourceResponse(
        slug=slug, mode="literal", query=query,
        text="\n--\n".join(blocks), match_count=len(hit_indices), truncated=truncated,
    )
