"""
Shared deduplication logic used by stream_runner and the maintenance endpoint.

Two entry points:
  - find_duplicate(paper, candidates, ...) — one incoming paper vs a known set
  - find_all_duplicates(items, ...)        — library-wide pairwise grouping
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prisma.utils.text import significant_words

if TYPE_CHECKING:
    from prisma.services.zotero import ZoteroService

_STEM_THRESHOLDS = {
    "low":    (13, 10),
    "medium": (10,  7),
    "high":   ( 7,  5),
}


def _stem_thresholds(sensitivity: str = "medium") -> tuple[int, int]:
    """Return (certain, ambiguous) stem-overlap thresholds for the given sensitivity."""
    return _STEM_THRESHOLDS.get(sensitivity, _STEM_THRESHOLDS["medium"])


def _get_analysis():
    from prisma.agents.analysis_agent import AnalysisAgent
    return AnalysisAgent()


def build_index(items) -> tuple[dict, dict, list[tuple[frozenset, object]]]:
    """Build fast-lookup structures from a list of ZoteroItem."""
    by_doi: dict[str, object] = {}
    by_title: dict[str, object] = {}
    stems: list[tuple[frozenset, object]] = []
    for item in items:
        if item.doi:
            by_doi[item.doi.lower().strip()] = item
        by_title[item.title.lower().strip()] = item
        stems.append((significant_words(item.title), item))
    return by_doi, by_title, stems


def find_duplicate(
    paper,
    by_doi: dict,
    by_title: dict,
    stems: list[tuple[frozenset, object]],
    *,
    zotero: "ZoteroService | None" = None,
    collection_key: str | None = None,
    log: logging.Logger | None = None,
    sensitivity: str = "medium",
) -> object | None:
    """
    Return the first matching item from the index, or None if the paper is new.

    Levels:
      1. DOI exact match (in-memory)
      2. Title exact match (in-memory)
      3. Zotero search via find_by_identifier (optional, requires zotero)
      4. NLTK stem overlap ≥ certain threshold → certain match
      5. NLTK stem overlap ≥ ambiguous threshold → LLM identity check

    sensitivity controls levels 4-5 thresholds:
      low: certain=13 ambiguous=10 | medium: certain=10 ambiguous=7 | high: certain=7 ambiguous=5
    """
    _log = log or logging.getLogger("prisma.dedup")
    _STEM_CERTAIN, _STEM_AMBIGUOUS = _stem_thresholds(sensitivity)

    if paper.doi:
        hit = by_doi.get(paper.doi.lower().strip())
        if hit is not None:
            _log.info("dedup DOI: %r matched %r", paper.title, hit.title)
            return hit

    hit = by_title.get(paper.title.lower().strip())
    if hit is not None:
        _log.info("dedup title: %r matched %r", paper.title, hit.title)
        return hit

    if zotero is not None:
        try:
            hit = zotero.find_by_identifier(
                doi=paper.doi, title=paper.title, collection_key=collection_key
            )
            if hit is not None:
                _log.info("dedup zotero-search: %r matched %r", paper.title, hit.title)
                return hit
        except Exception as exc:
            _log.warning("dedup zotero-search failed: %s — continuing to NLTK", exc)

    incoming = significant_words(paper.title)
    llm_candidates: list[tuple[str, str, object]] = []
    for item_stems, item in stems:
        overlap = len(incoming & item_stems)
        if overlap >= _STEM_CERTAIN:
            _log.info("dedup stem-certain: %r matched %r (overlap=%d)", paper.title, item.title, overlap)
            return item
        if overlap >= _STEM_AMBIGUOUS:
            llm_candidates.append((item.title, getattr(item, "abstract", None) or "", item))

    if not llm_candidates:
        return None

    _log.info("dedup LLM: checking %r against %d candidate(s)", paper.title, len(llm_candidates))
    try:
        results = _get_analysis().check_identity_batch(
            paper.title,
            getattr(paper, "abstract", None) or "",
            [(t, a) for t, a, _ in llm_candidates],
        )
        for identity_result, (_, _, item) in zip(results, llm_candidates):
            if identity_result.are_same:
                _log.info("dedup LLM: %r matched %r (confidence=%.2f)", paper.title, item.title, identity_result.confidence)
                return item
    except Exception as exc:
        _log.warning("dedup LLM failed: %s — treating as new", exc)

    return None


def _authors_match(a, b) -> bool:
    """True if at least one author shares last name + first initial."""
    def _pairs(item):
        pairs = set()
        for creator in (item.creators or []):
            if creator.creator_type != "author":
                continue
            last = (creator.last_name or "").strip().lower()
            first = (creator.first_name or "").strip()
            if last:
                pairs.add((last, first[0].lower() if first else ""))
        return pairs
    return bool(_pairs(a) & _pairs(b))


def find_all_duplicates(
    items: list,
    *,
    zotero: "ZoteroService | None" = None,
    log: logging.Logger | None = None,
    max_level: int = 3,
    sensitivity: str = "medium",
) -> list[list]:
    """
    Find duplicate groups within a flat list of ZoteroItems.

    Levels (stop at max_level):
      1. DOI exact match
      2. Title exact match
      3. Year ±1 + author last name + first initial (Zotero desktop algorithm)
      4. NLTK stem overlap ≥ STEM_CERTAIN → certain match
      5. NLTK stem overlap ≥ STEM_AMBIGUOUS → LLM identity check
    """
    _log = log or logging.getLogger("prisma.dedup")
    _STEM_CERTAIN, _STEM_AMBIGUOUS = _stem_thresholds(sensitivity)

    # Level 1: group by DOI
    by_doi: dict[str, list] = {}
    no_doi: list = []
    for item in items:
        doi = item.doi.lower().strip() if item.doi else None
        if doi:
            by_doi.setdefault(doi, []).append(item)
        else:
            no_doi.append(item)

    groups: list[list] = [g for g in by_doi.values() if len(g) >= 2]
    already_grouped: set[str] = {item.key for g in groups for item in g}

    if max_level < 2:
        return groups

    # Level 2: group by normalized title
    by_title: dict[str, list] = {}
    for item in items:
        if item.key in already_grouped:
            continue
        key = item.title.lower().strip()
        by_title.setdefault(key, []).append(item)

    for g in by_title.values():
        if len(g) >= 2:
            groups.append(g)
            already_grouped.update(item.key for item in g)

    if max_level < 3:
        return groups

    # Level 3: year ±1 + author last name + first initial
    ungrouped = [item for item in items if item.key not in already_grouped]
    visited: set[str] = set()
    for i, item_i in enumerate(ungrouped):
        if item_i.key in visited:
            continue
        year_i = getattr(item_i, "year", None)
        matched: list = []
        for item_j in ungrouped[i + 1:]:
            if item_j.key in visited:
                continue
            year_j = getattr(item_j, "year", None)
            if year_i and year_j and abs(int(year_i) - int(year_j)) > 1:
                continue
            if _authors_match(item_i, item_j):
                matched.append(item_j)
                _log.info("dedup year+author: %r matched %r", item_i.title, item_j.title)
        if matched:
            group = [item_i] + matched
            groups.append(group)
            visited.update(item.key for item in group)
            already_grouped.update(item.key for item in group)

    if max_level < 4:
        return groups

    # Level 4: NLTK stem overlap ≥ STEM_CERTAIN
    ungrouped = [item for item in items if item.key not in already_grouped]
    stems = [(significant_words(item.title), item) for item in ungrouped]
    visited = set()
    for i, (stems_i, item_i) in enumerate(stems):
        if item_i.key in visited:
            continue
        certain_matches: list = []
        llm_candidates: list[tuple[str, str, object]] = []
        for j, (stems_j, item_j) in enumerate(stems):
            if i == j or item_j.key in visited:
                continue
            overlap = len(stems_i & stems_j)
            if overlap >= _STEM_CERTAIN:
                certain_matches.append(item_j)
                _log.info("dedup stem-certain: %r matched %r (overlap=%d)", item_i.title, item_j.title, overlap)
            elif max_level >= 5 and overlap >= _STEM_AMBIGUOUS:
                llm_candidates.append((item_j.title, getattr(item_j, "abstract", None) or "", item_j))

        matched = list(certain_matches)

        if max_level >= 5 and llm_candidates:
            try:
                results = _get_analysis().check_identity_batch(
                    item_i.title,
                    getattr(item_i, "abstract", None) or "",
                    [(t, a) for t, a, _ in llm_candidates],
                )
                for identity_result, (_, _, item_j) in zip(results, llm_candidates):
                    if identity_result.are_same:
                        matched.append(item_j)
                        _log.info("dedup LLM: %r matched %r", item_i.title, item_j.title)
            except Exception as exc:
                _log.warning("dedup LLM failed for %r: %s", item_i.title, exc)

        if matched:
            group = [item_i] + matched
            groups.append(group)
            visited.update(item.key for item in group)

    return groups
