"""Unit tests for APA 7th-edition citation formatting (ADR-020)."""
from pathlib import Path

from prisma.services.citation_format import (
    find_source_by_apa, format_apa, missing_fields_for_apa, validate_apa_format,
)
from prisma.storage.models.vault_models import Source


def _source(**overrides) -> Source:
    defaults = dict(slug="smith2024", title="A Great Paper", path=Path("/tmp/smith2024.md"), citekey="smith2024")
    defaults.update(overrides)
    return Source(**defaults)


# ── missing_fields_for_apa ────────────────────────────────────────────────────

def test_missing_fields_journal_article_complete():
    source = _source(authors=["Jane Smith"], year=2024, item_type="journalArticle", journal="J")
    assert missing_fields_for_apa(source) == []


def test_missing_fields_journal_article_missing_journal():
    source = _source(authors=["Jane Smith"], year=2024, item_type="journalArticle")
    assert "journal" in missing_fields_for_apa(source)


def test_missing_fields_book_missing_publisher():
    source = _source(authors=["Jane Smith"], year=2024, item_type="book")
    assert "publisher" in missing_fields_for_apa(source)


def test_missing_fields_webpage_missing_url():
    source = _source(authors=["Jane Smith"], year=2024, item_type="webpage")
    assert "url" in missing_fields_for_apa(source)


def test_missing_fields_no_authors():
    source = _source(authors=[], year=2024)
    assert "authors" in missing_fields_for_apa(source)


def test_missing_fields_unknown_item_type_only_needs_base_fields():
    source = _source(authors=["Jane Smith"], year=2024, item_type="artwork")
    assert missing_fields_for_apa(source) == []


# ── format_apa ────────────────────────────────────────────────────────────────

def test_format_apa_single_author():
    source = _source(authors=["Jane Smith"], year=2024)
    assert format_apa(source) == "Smith, J. (2024). A Great Paper."


def test_format_apa_two_authors_joined_with_ampersand():
    source = _source(authors=["Jane Smith", "John Doe"], year=2024)
    assert format_apa(source).startswith("Smith, J., & Doe, J. (2024).")


def test_format_apa_three_authors():
    source = _source(authors=["Jane Smith", "John Doe", "Amy Lee"], year=2024)
    assert format_apa(source).startswith("Smith, J., Doe, J., & Lee, A. (2024).")


def test_format_apa_no_authors_puts_title_first():
    source = _source(authors=[], year=2024, title="Untitled Report")
    assert format_apa(source) == "Untitled Report (2024)."


def test_format_apa_no_year_uses_nd():
    source = _source(authors=["Jane Smith"], year=None)
    assert "(n.d.)" in format_apa(source)


def test_format_apa_journal_article_full_tail():
    source = _source(
        authors=["Jane Smith"], year=2024, item_type="journalArticle",
        journal="Journal of Examples", volume="12", issue="3", pages="45-67",
    )
    assert format_apa(source) == (
        "Smith, J. (2024). A Great Paper. Journal of Examples, 12(3), 45-67."
    )


def test_format_apa_journal_article_without_issue():
    source = _source(
        authors=["Jane Smith"], year=2024, item_type="journalArticle",
        journal="Journal of Examples", volume="12",
    )
    assert "Journal of Examples, 12." in format_apa(source)


def test_format_apa_book_uses_publisher():
    source = _source(authors=["Jane Smith"], year=2024, item_type="book", publisher="Example Press")
    assert format_apa(source) == "Smith, J. (2024). A Great Paper. Example Press."


def test_format_apa_prefers_doi_over_url():
    source = _source(authors=["Jane Smith"], year=2024, doi="10.1/xyz", url="https://example.com")
    assert format_apa(source).endswith("https://doi.org/10.1/xyz")


def test_format_apa_falls_back_to_url_without_doi():
    source = _source(authors=["Jane Smith"], year=2024, url="https://example.com")
    assert format_apa(source).endswith("https://example.com")


def test_format_apa_degrades_gracefully_with_nothing_but_title():
    source = _source(authors=[], year=None, title="Mystery Document")
    assert format_apa(source) == "Mystery Document (n.d.)."


# ── validate_apa_format ────────────────────────────────────────────────────────

def test_validate_apa_format_accepts_format_apas_own_output():
    source = _source(authors=["Jane Smith"], year=2024, item_type="journalArticle", journal="J")
    assert validate_apa_format(format_apa(source)) is True


def test_validate_apa_format_accepts_no_date_output():
    source = _source(authors=[], year=None)
    assert validate_apa_format(format_apa(source)) is True


def test_validate_apa_format_rejects_plain_prose():
    assert validate_apa_format("just some random text with no citation shape") is False


def test_validate_apa_format_rejects_empty_string():
    assert validate_apa_format("") is False


# ── find_source_by_apa ────────────────────────────────────────────────────────

def test_find_source_by_apa_matches_surname_and_year():
    sources = [
        _source(slug="a", title="A Great Paper", authors=["Jane Smith"], year=2024),
        _source(slug="b", title="Another Paper", authors=["John Doe"], year=2020),
    ]
    found = find_source_by_apa("Smith, J. (2024). A Great Paper.", sources)
    assert [s.slug for s in found] == ["a"]


def test_find_source_by_apa_returns_empty_when_nothing_matches():
    sources = [_source(slug="a", authors=["Jane Smith"], year=2024)]
    assert find_source_by_apa("Doe, J. (2020). Something Else.", sources) == []


def test_find_source_by_apa_returns_empty_when_unparseable():
    sources = [_source(slug="a", authors=["Jane Smith"], year=2024)]
    assert find_source_by_apa("not a citation at all", sources) == []


def test_find_source_by_apa_disambiguates_same_author_year_by_title_overlap():
    sources = [
        _source(slug="a", title="Attention Is All You Need", authors=["Jane Smith"], year=2024),
        _source(slug="b", title="A Completely Unrelated Subject", authors=["Jane Smith"], year=2024),
    ]
    found = find_source_by_apa("Smith, J. (2024). Attention mechanisms in transformers.", sources)
    assert found[0].slug == "a"


def test_find_source_by_apa_matches_nd_literally():
    sources = [
        _source(slug="a", authors=["Jane Smith"], year=None),
        _source(slug="b", authors=["Jane Smith"], year=2020),
    ]
    found = find_source_by_apa("Smith, J. (n.d.). Undated Work.", sources)
    assert [s.slug for s in found] == ["a"]
