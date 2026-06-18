"""Unit tests for prisma.services.dedup — all levels of find_duplicate and find_all_duplicates."""
from unittest.mock import MagicMock

import pytest

from prisma.services.dedup import (
    _authors_match,
    _stem_thresholds,
    build_index,
    find_all_duplicates,
    find_duplicate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(key, title, doi=None, authors=None, year=None):
    item = MagicMock()
    item.key = key
    item.title = title
    item.doi = doi
    item.abstract = ""
    item.year = year
    creators = []
    for name in (authors or []):
        last, _, first = name.partition(",")
        c = MagicMock()
        c.creator_type = "author"
        c.last_name = last.strip()
        c.first_name = first.strip()
        creators.append(c)
    item.creators = creators
    item.authors = [f"{c.first_name} {c.last_name}".strip() for c in creators]
    return item


def _paper(title, doi=None, abstract=""):
    p = MagicMock()
    p.title = title
    p.doi = doi
    p.abstract = abstract
    return p


# ---------------------------------------------------------------------------
# _stem_thresholds
# ---------------------------------------------------------------------------

def test_stem_thresholds_known_values():
    assert _stem_thresholds("low") == (13, 10)
    assert _stem_thresholds("medium") == (10, 7)
    assert _stem_thresholds("high") == (7, 5)


def test_stem_thresholds_unknown_falls_back_to_medium():
    assert _stem_thresholds("unknown") == _stem_thresholds("medium")


# ---------------------------------------------------------------------------
# _authors_match
# ---------------------------------------------------------------------------

def test_authors_match_same_last_first_initial():
    a = _item("A", "T1", authors=["Smith, John"])
    b = _item("B", "T2", authors=["Smith, Jane"])
    assert _authors_match(a, b)


def test_authors_match_different_first_initial():
    a = _item("A", "T1", authors=["Smith, John"])
    b = _item("B", "T2", authors=["Smith, Alice"])
    # Different first initials — no match
    assert not _authors_match(a, b)


def test_authors_match_no_authors():
    a = _item("A", "T1")
    b = _item("B", "T2")
    assert not _authors_match(a, b)


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------

def test_build_index_populates_all_structures():
    items = [
        _item("K1", "Deep Learning Survey", doi="10.1/abc"),
        _item("K2", "Neural Networks Overview"),
    ]
    by_doi, by_title, stems = build_index(items)
    assert "10.1/abc" in by_doi
    assert "deep learning survey" in by_title
    assert "neural networks overview" in by_title
    assert len(stems) == 2


# ---------------------------------------------------------------------------
# find_duplicate — level 1: DOI
# ---------------------------------------------------------------------------

def test_find_duplicate_doi_match():
    items = [_item("K1", "Some Title", doi="10.1/xyz")]
    by_doi, by_title, stems = build_index(items)
    paper = _paper("Different Title", doi="10.1/xyz")
    hit = find_duplicate(paper, by_doi, by_title, stems)
    assert hit is not None
    assert hit.key == "K1"


# ---------------------------------------------------------------------------
# find_duplicate — level 2: title
# ---------------------------------------------------------------------------

def test_find_duplicate_title_match():
    items = [_item("K1", "Attention Is All You Need")]
    by_doi, by_title, stems = build_index(items)
    paper = _paper("Attention Is All You Need")
    hit = find_duplicate(paper, by_doi, by_title, stems)
    assert hit is not None
    assert hit.key == "K1"


def test_find_duplicate_no_match():
    items = [_item("K1", "Completely Unrelated Work on Chemistry")]
    by_doi, by_title, stems = build_index(items)
    paper = _paper("Deep Learning for Vision Tasks")
    hit = find_duplicate(paper, by_doi, by_title, stems)
    assert hit is None


# ---------------------------------------------------------------------------
# find_all_duplicates — level 1
# ---------------------------------------------------------------------------

def test_find_all_duplicates_doi_group():
    items = [
        _item("K1", "Paper A", doi="10.1/same"),
        _item("K2", "Paper A (preprint)", doi="10.1/same"),
        _item("K3", "Unrelated", doi="10.1/other"),
    ]
    groups = find_all_duplicates(items, max_level=1)
    assert len(groups) == 1
    keys = {i.key for i in groups[0]}
    assert keys == {"K1", "K2"}


# ---------------------------------------------------------------------------
# find_all_duplicates — level 2
# ---------------------------------------------------------------------------

def test_find_all_duplicates_title_group():
    items = [
        _item("K1", "Attention Is All You Need"),
        _item("K2", "attention is all you need"),
        _item("K3", "BERT: Pre-training of Deep Bidirectional Transformers"),
    ]
    groups = find_all_duplicates(items, max_level=2)
    assert len(groups) == 1
    keys = {i.key for i in groups[0]}
    assert keys == {"K1", "K2"}


# ---------------------------------------------------------------------------
# find_all_duplicates — level 3: year + author
# ---------------------------------------------------------------------------

def test_find_all_duplicates_year_author_match():
    items = [
        _item("K1", "A Study on Transformers", year=2020, authors=["Vaswani, Ashish"]),
        _item("K2", "A Study of Transformers", year=2020, authors=["Vaswani, Anna"]),
        _item("K3", "Completely Different Work", year=2018, authors=["LeCun, Yann"]),
    ]
    groups = find_all_duplicates(items, max_level=3)
    assert len(groups) == 1
    keys = {i.key for i in groups[0]}
    assert keys == {"K1", "K2"}


def test_find_all_duplicates_year_mismatch_no_group():
    items = [
        _item("K1", "A Survey on Deep Learning", year=2018, authors=["Smith, John"]),
        _item("K2", "A Survey on Deep Learning", year=2022, authors=["Smith, Jane"]),
    ]
    # Title exact match at level 2 would catch this, so use only level 3 data
    # by giving them distinct titles but same author+year
    items2 = [
        _item("K1", "Unique Title Alpha", year=2018, authors=["Smith, John"]),
        _item("K2", "Unique Title Beta", year=2022, authors=["Smith, Jane"]),
    ]
    groups = find_all_duplicates(items2, max_level=3)
    assert len(groups) == 0


# ---------------------------------------------------------------------------
# find_all_duplicates — max_level stops early
# ---------------------------------------------------------------------------

def test_find_all_duplicates_max_level_1_skips_title():
    items = [
        _item("K1", "Same Title Here"),
        _item("K2", "Same Title Here"),
    ]
    groups = find_all_duplicates(items, max_level=1)
    assert len(groups) == 0  # DOI grouping only — no DOIs set


def test_find_all_duplicates_empty_input():
    assert find_all_duplicates([]) == []
