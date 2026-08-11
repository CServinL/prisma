"""Unit tests for the ADR-020 one-time source-metadata backfill."""
from unittest.mock import MagicMock

import pytest

from prisma.services.source_backfill import backfill_source_metadata
from prisma.services.vault import VaultService
from prisma.storage.models.zotero_models import ZoteroItem


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def _zotero_item(**overrides) -> ZoteroItem:
    defaults = dict(
        key="ZK1", title="A Great Paper", item_type="journalArticle", creators=[],
        publication_title="Journal of Examples", volume="12", issue="3", pages="45-67",
    )
    defaults.update(overrides)
    return ZoteroItem(**defaults)


def test_dry_run_reports_without_writing(vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ZK1", authors=["Jane Smith"], tags=[],
    )
    zotero = MagicMock()
    zotero.get_item.return_value = _zotero_item()

    results = backfill_source_metadata(vault, zotero, dry_run=True)

    assert len(results) == 1
    assert results[0].slug == source.slug
    assert results[0].updated is True
    reloaded = vault.get_source(source.slug)
    assert reloaded.journal is None  # nothing written


def test_apply_writes_the_fetched_fields(vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ZK1", authors=["Jane Smith"], tags=[],
    )
    zotero = MagicMock()
    zotero.get_item.return_value = _zotero_item()

    backfill_source_metadata(vault, zotero, dry_run=False)

    reloaded = vault.get_source(source.slug)
    assert reloaded.journal == "Journal of Examples"
    assert reloaded.volume == "12"
    assert reloaded.issue == "3"
    assert reloaded.pages == "45-67"
    assert reloaded.item_type == "journalArticle"


def test_skips_source_with_no_zotero_key(vault):
    vault.create_source_from_citekey(
        "manual2024", "Manually Added", "body", zotero_key="", authors=[], tags=[],
    )
    zotero = MagicMock()

    results = backfill_source_metadata(vault, zotero, dry_run=True)

    assert results[0].updated is False
    assert "no zotero_key" in results[0].error
    zotero.get_item.assert_not_called()


def test_skips_source_already_partially_backfilled(vault):
    vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ZK1", authors=[], tags=[],
        journal="Already Here",
    )
    zotero = MagicMock()

    results = backfill_source_metadata(vault, zotero, dry_run=True)

    assert results[0].updated is False
    assert results[0].error is None
    zotero.get_item.assert_not_called()


def test_reports_error_when_zotero_item_not_found(vault):
    vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ZK-GONE", authors=[], tags=[],
    )
    zotero = MagicMock()
    zotero.get_item.return_value = None

    results = backfill_source_metadata(vault, zotero, dry_run=True)

    assert results[0].updated is False
    assert "not found" in results[0].error


def test_backfills_multiple_sources_independently(vault):
    vault.create_source_from_citekey(
        "a2024", "Paper A", "body", zotero_key="ZKA", authors=[], tags=[],
    )
    vault.create_source_from_citekey(
        "b2024", "Paper B", "body", zotero_key="ZKB", authors=[], tags=[],
    )
    zotero = MagicMock()
    zotero.get_item.side_effect = lambda key: _zotero_item(key=key, title=f"Paper for {key}")

    results = backfill_source_metadata(vault, zotero, dry_run=False)

    assert {r.slug for r in results} == {"a2024", "b2024"}
    assert all(r.updated for r in results)
