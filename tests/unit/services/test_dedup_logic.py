"""Unit tests for prisma.services.dedup — all levels of find_duplicate and find_all_duplicates."""
from unittest.mock import MagicMock, patch

import pytest

from prisma.services.dedup import (
    _authors_match,
    _stem_thresholds,
    build_index,
    find_all_duplicates,
    find_duplicate,
)

# Two titles engineered (via prisma.utils.text.significant_words) to overlap
# by exactly 11 significant stems -- above medium sensitivity's "certain"
# threshold (10), so they trigger level 4 without any DOI/exact-title match.
_STEM_CERTAIN_TITLE_A = (
    "Deep Learning Methods For Image Classification Using Convolutional "
    "Neural Network Architectures And Transfer Learning Techniques For Medical Diagnosis"
)
_STEM_CERTAIN_TITLE_B = (
    "Deep Learning Approaches For Image Classification Using Convolutional "
    "Neural Network Architectures And Transfer Learning Systems For Clinical Diagnosis"
)

# Overlap by exactly 7 stems -- medium sensitivity's "ambiguous" threshold
# (7 <= overlap < 10), triggering the LLM identity check (level 5) instead
# of an automatic certain match.
_STEM_AMBIGUOUS_TITLE_A = (
    "Deep Learning Methods For Image Classification Using Convolutional "
    "Neural Network Architectures And Transfer Learning Techniques For Medical Diagnosis"
)
_STEM_AMBIGUOUS_TITLE_B = (
    "Statistical Regression Techniques For Signal Processing Using Convolutional "
    "Filters And Network Diagnosis Applications In Medical Imaging Systems"
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
# find_duplicate — level 3: Zotero find_by_identifier
# ---------------------------------------------------------------------------

def test_find_duplicate_zotero_search_match():
    items = [_item("K1", "Something Unrelated To The Paper Title")]
    by_doi, by_title, stems = build_index(items)
    paper = _paper("A Totally Different Title Not In The Index", doi="10.1/only-in-zotero")
    zotero_hit = _item("ZK1", "Found Via Zotero Search")
    zotero = MagicMock()
    zotero.find_by_identifier.return_value = zotero_hit

    hit = find_duplicate(paper, by_doi, by_title, stems, zotero=zotero)

    assert hit is zotero_hit
    zotero.find_by_identifier.assert_called_once_with(
        doi=paper.doi, title=paper.title, collection_key=None
    )


def test_find_duplicate_zotero_search_exception_continues_to_nltk():
    items = [_item("K1", _STEM_CERTAIN_TITLE_B)]
    by_doi, by_title, stems = build_index(items)
    paper = _paper(_STEM_CERTAIN_TITLE_A)
    zotero = MagicMock()
    zotero.find_by_identifier.side_effect = RuntimeError("zotero unreachable")

    # Must not propagate the exception -- falls through to the stem-overlap
    # levels below and still finds the real match there.
    hit = find_duplicate(paper, by_doi, by_title, stems, zotero=zotero)

    assert hit is not None
    assert hit.key == "K1"


# ---------------------------------------------------------------------------
# find_duplicate — level 4: NLTK stem-certain match
# ---------------------------------------------------------------------------

def test_find_duplicate_stem_certain_match():
    items = [_item("K1", _STEM_CERTAIN_TITLE_B)]
    by_doi, by_title, stems = build_index(items)
    paper = _paper(_STEM_CERTAIN_TITLE_A)

    hit = find_duplicate(paper, by_doi, by_title, stems)

    assert hit is not None
    assert hit.key == "K1"


# ---------------------------------------------------------------------------
# find_duplicate — level 5: NLTK stem-ambiguous -> LLM identity check
# ---------------------------------------------------------------------------

def test_find_duplicate_stem_ambiguous_llm_confirms_match():
    items = [_item("K1", _STEM_AMBIGUOUS_TITLE_B)]
    by_doi, by_title, stems = build_index(items)
    paper = _paper(_STEM_AMBIGUOUS_TITLE_A)

    identity_result = MagicMock(are_same=True, confidence=0.9)
    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.return_value = [identity_result]

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        hit = find_duplicate(paper, by_doi, by_title, stems)

    assert hit is not None
    assert hit.key == "K1"
    mock_analysis.check_identity_batch.assert_called_once()


def test_find_duplicate_stem_ambiguous_llm_rejects_match():
    items = [_item("K1", _STEM_AMBIGUOUS_TITLE_B)]
    by_doi, by_title, stems = build_index(items)
    paper = _paper(_STEM_AMBIGUOUS_TITLE_A)

    identity_result = MagicMock(are_same=False, confidence=0.2)
    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.return_value = [identity_result]

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        hit = find_duplicate(paper, by_doi, by_title, stems)

    assert hit is None


def test_find_duplicate_llm_exception_treated_as_new():
    items = [_item("K1", _STEM_AMBIGUOUS_TITLE_B)]
    by_doi, by_title, stems = build_index(items)
    paper = _paper(_STEM_AMBIGUOUS_TITLE_A)

    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.side_effect = RuntimeError("LLM unavailable")

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
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


# ---------------------------------------------------------------------------
# find_all_duplicates — level 4: NLTK stem-certain match
# ---------------------------------------------------------------------------

def test_find_all_duplicates_stem_certain_group():
    items = [
        _item("K1", _STEM_CERTAIN_TITLE_A),
        _item("K2", _STEM_CERTAIN_TITLE_B),
        _item("K3", "Something Entirely Unrelated About Cooking Recipes"),
    ]
    groups = find_all_duplicates(items, max_level=4)
    assert len(groups) == 1
    keys = {i.key for i in groups[0]}
    assert keys == {"K1", "K2"}


def test_find_all_duplicates_max_level_3_skips_stem_matching():
    items = [
        _item("K1", _STEM_CERTAIN_TITLE_A),
        _item("K2", _STEM_CERTAIN_TITLE_B),
    ]
    groups = find_all_duplicates(items, max_level=3)
    assert groups == []


# ---------------------------------------------------------------------------
# find_all_duplicates — level 5: NLTK stem-ambiguous -> LLM identity check
# ---------------------------------------------------------------------------

def test_find_all_duplicates_stem_ambiguous_llm_confirms_group():
    items = [
        _item("K1", _STEM_AMBIGUOUS_TITLE_A),
        _item("K2", _STEM_AMBIGUOUS_TITLE_B),
    ]
    identity_result = MagicMock(are_same=True, confidence=0.9)
    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.return_value = [identity_result]

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        groups = find_all_duplicates(items, max_level=5)

    assert len(groups) == 1
    keys = {i.key for i in groups[0]}
    assert keys == {"K1", "K2"}


def test_find_all_duplicates_stem_ambiguous_llm_rejects_group():
    items = [
        _item("K1", _STEM_AMBIGUOUS_TITLE_A),
        _item("K2", _STEM_AMBIGUOUS_TITLE_B),
    ]
    identity_result = MagicMock(are_same=False, confidence=0.1)
    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.return_value = [identity_result]

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        groups = find_all_duplicates(items, max_level=5)

    assert groups == []


def test_find_all_duplicates_llm_exception_skips_group_not_whole_run():
    items = [
        _item("K1", _STEM_AMBIGUOUS_TITLE_A),
        _item("K2", _STEM_AMBIGUOUS_TITLE_B),
    ]
    mock_analysis = MagicMock()
    mock_analysis.check_identity_batch.side_effect = RuntimeError("LLM unavailable")

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        groups = find_all_duplicates(items, max_level=5)

    assert groups == []


def test_find_all_duplicates_max_level_4_skips_llm_entirely():
    items = [
        _item("K1", _STEM_AMBIGUOUS_TITLE_A),
        _item("K2", _STEM_AMBIGUOUS_TITLE_B),
    ]
    mock_analysis = MagicMock()

    with patch("prisma.services.dedup._get_analysis", return_value=mock_analysis):
        groups = find_all_duplicates(items, max_level=4)

    mock_analysis.check_identity_batch.assert_not_called()
    assert groups == []
