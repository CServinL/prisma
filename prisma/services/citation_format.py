"""APA 7th-edition citation formatting for Source nodes (ADR-020).

Two directions: `format_apa()` renders a `Source` as an APA-formatted
reference string; `find_source_by_apa()` (companion module work, see
`validate_apa_format`/`find_source_by_apa` below) goes the other way,
resolving an APA-shaped string back to a vault slug. `missing_fields_for_apa()`
is what both `format_apa()` (to degrade gracefully) and a future vault-health
view (to flag under-cited sources) use to know what's absent, keyed off
`Source.item_type` -- a journal article's requirements differ from a book's
or a webpage's, not just "does it have authors and a year."
"""
from __future__ import annotations

import re

from prisma.storage.models.vault_models import Source

_JOURNAL_LIKE_TYPES = {"journalArticle", "conferencePaper", "magazineArticle", "newspaperArticle"}
_BOOK_LIKE_TYPES = {"book", "bookSection", "thesis", "report"}
_WEB_LIKE_TYPES = {"webpage"}


def _apa_kind(item_type: str | None) -> str:
    if item_type in _JOURNAL_LIKE_TYPES:
        return "journal"
    if item_type in _BOOK_LIKE_TYPES:
        return "book"
    if item_type in _WEB_LIKE_TYPES:
        return "web"
    return "generic"  # unknown/missing item_type -- author/year/title only, no type-specific tail


def missing_fields_for_apa(source: Source) -> list[str]:
    """Which fields are missing for a *correct*, complete APA citation of
    this source's specific item_type -- not just "does it have authors and
    a year." A generic/unrecognized item_type only ever requires the
    always-required fields, since there's no type-specific template to
    hold it to."""
    missing: list[str] = []
    if not source.authors:
        missing.append("authors")
    if not source.title:
        missing.append("title")
    kind = _apa_kind(source.item_type)
    if kind == "journal" and not source.journal:
        missing.append("journal")
    if kind == "book" and not source.publisher:
        missing.append("publisher")
    if kind == "web" and not source.url:
        missing.append("url")
    return missing


def _apa_author(name: str) -> str:
    """'Jane Smith' -> 'Smith, J.'; 'Jane Q. Smith' -> 'Smith, J. Q.'.
    Best-effort -- a single-token name (an organization/collective author,
    or a name this can't parse) is returned unchanged rather than mangled."""
    parts = name.split()
    if len(parts) < 2:
        return name
    *given, family = parts
    initials = " ".join(f"{p[0]}." for p in given if p)
    return f"{family}, {initials}" if initials else family


def _apa_author_list(authors: list[str]) -> str:
    """APA 7th: an '&' before the last author, 1-20 authors. The
    21+-authors ellipsis-plus-final-author rule is deliberately not
    implemented -- not a case this codebase's academic-paper/book sources
    realistically hit."""
    formatted = [_apa_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def format_apa(source: Source) -> str:
    """Render `source` as an APA 7th-edition-formatted citation string.
    Degrades gracefully when fields are missing (omits volume/issue/etc.
    rather than raising) -- call `missing_fields_for_apa()` first if a
    caller needs to know ahead of time whether the result will be
    incomplete."""
    year = str(source.year) if source.year else "n.d."
    kind = _apa_kind(source.item_type)
    if source.authors:
        lead = f"{_apa_author_list(source.authors)} ({year}). {source.title}."
    else:
        # APA: no author -> the title moves into the author position,
        # not repeated -- e.g. a webpage with no byline.
        lead = f"{source.title} ({year})."
    parts = [lead]
    if kind == "journal" and source.journal:
        tail = source.journal
        if source.volume:
            tail += f", {source.volume}"
            if source.issue:
                tail += f"({source.issue})"
        if source.pages:
            tail += f", {source.pages}"
        parts.append(f"{tail}.")
    elif kind == "book" and source.publisher:
        parts.append(f"{source.publisher}.")
    if source.doi:
        parts.append(f"https://doi.org/{source.doi}")
    elif source.url:
        parts.append(source.url)
    return " ".join(parts)


# ── APA validator + reverse lookup (ADR-020 phases 4-5) ───────────────────────

# Structural, not semantic: some author/title lead-in followed by
# "(Year)." or "(n.d.)." -- matches the shape format_apa() itself always
# produces (`"{lead} ({year})."`), and is permissive enough to accept
# hand-written/pasted APA text that follows the same convention.
_APA_STRUCTURE_RE = re.compile(r"^.+?\((\d{4}|n\.d\.)\)\.")


def validate_apa_format(text: str) -> bool:
    """Structural check only -- does `text` start with an author/title
    lead-in followed by a (Year). or (n.d.). marker, the way format_apa()'s
    own output always does. Not a semantic/correctness check (a
    well-formed but factually wrong citation still passes)."""
    return bool(_APA_STRUCTURE_RE.match(text.strip()))


_YEAR_RE = re.compile(r"\((\d{4}|n\.d\.)\)")
_SURNAME_RE = re.compile(r"^([A-Z][\w'-]*)")


def find_source_by_apa(text: str, sources: list[Source]) -> list[Source]:
    """Reverse of format_apa(): given an APA-shaped string, find which
    `sources` it most likely refers to. Inherently fuzzy, unlike the
    `[[@citekey]]` DSL's exact match -- parses a leading surname and a
    year out of `text`, filters by both, and (if more than one source
    still matches) ranks by title word overlap. Returns candidates
    best-match-first; empty if `text` doesn't parse or nothing matches."""
    text = text.strip()
    year_match = _YEAR_RE.search(text)
    surname_match = _SURNAME_RE.match(text)
    if not year_match or not surname_match:
        return []
    year_str = year_match.group(1)
    surname = surname_match.group(1).lower()

    def _year_matches(s: Source) -> bool:
        return s.year is None if year_str == "n.d." else str(s.year) == year_str

    candidates = [
        s for s in sources
        if any(surname in a.lower() for a in s.authors) and _year_matches(s)
    ]
    if len(candidates) <= 1:
        return candidates

    title_words = set(re.findall(r"\w+", text.lower()))

    def _overlap(source: Source) -> int:
        return len(title_words & set(re.findall(r"\w+", source.title.lower())))

    return sorted(candidates, key=_overlap, reverse=True)
