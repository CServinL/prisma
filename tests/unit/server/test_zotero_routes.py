"""Unit tests for the two API routes added when the CLI was minimized
(2026-07-27): GET /zotero/stats and POST /zotero/sync-pending replace the
old `prisma zotero stats` and `prisma sync` CLI commands.

The tests below this point (isolated router section) instead build
zotero_routes.py's router in isolation (bare FastAPI app + a tmp_path
VaultService), same approach as test_notes_routes.py/test_streams_routes.py
-- appropriate here since zotero_import writes real files, and this
module-level `client` fixture talks to the full app.py singleton's real
(potentially non-tmp) _vault.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.app import app
from prisma.server.zotero_routes import build_zotero_router
from prisma.services.vault import VaultService
from prisma.storage.models.zotero_models import ZoteroCreator, ZoteroItem, ZoteroTag

client = TestClient(app, client=("127.0.0.1", 12345))


def _item(item_type="journalArticle", doi="10.1/x", abstract="abs", authors=("A",)):
    creators = [ZoteroCreator(creator_type="author", name=a) for a in authors]
    return ZoteroItem(
        key="K1", title="T", item_type=item_type, creators=creators, date="2024",
        abstract_note=abstract, doi=doi, url=None, publication_title=None, tags=[], collections=[],
    )


def test_zotero_stats_empty_library(monkeypatch):
    from prisma.server import app as app_module
    monkeypatch.setattr(app_module._zotero, "get_all_items", lambda **kw: [])

    r = client.get("/zotero/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_items"] == 0
    assert body["quality_score"] == 100.0


def test_zotero_stats_counts_and_quality(monkeypatch):
    from prisma.server import app as app_module
    items = [
        _item(),
        _item(doi=None),
        _item(abstract=None, authors=()),
    ]
    monkeypatch.setattr(app_module._zotero, "get_all_items", lambda **kw: items)

    r = client.get("/zotero/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_items"] == 3
    assert body["item_type_counts"] == {"journalArticle": 3}
    assert body["items_without_doi"] == 1
    assert body["items_without_abstract"] == 1
    assert body["items_without_authors"] == 1
    assert 0 < body["quality_score"] < 100


def test_sync_pending_no_actions_queued(monkeypatch):
    class _EmptyQueue:
        def __init__(self, *a, **kw):
            self.pending_count = 0

    monkeypatch.setattr("prisma.storage.pending_queue.PendingWriteQueue", _EmptyQueue)

    r = client.post("/zotero/sync-pending")
    assert r.status_code == 200
    assert r.json() == {"synced": 0, "failed": 0, "pending_before": 0}


def test_sync_pending_offline_returns_503(monkeypatch):
    class _NonEmptyQueue:
        def __init__(self, *a, **kw):
            self.pending_count = 3

    monkeypatch.setattr("prisma.storage.pending_queue.PendingWriteQueue", _NonEmptyQueue)
    monkeypatch.setattr("prisma.server.app.connectivity.is_online", False)

    r = client.post("/zotero/sync-pending")
    assert r.status_code == 503


def test_zotero_items_passes_query_through_when_scoped_to_collection(monkeypatch):
    # Regression: /zotero/items used to narrow by a client-side title-only
    # substring when both collection and q were given; it must now pass q
    # straight through to get_collection_items so Zotero's own richer
    # search (title/creators/abstract/etc.) applies, scoped to the collection.
    from prisma.server import app as app_mod
    from unittest.mock import MagicMock

    mock_zotero = MagicMock()
    mock_zotero.get_collection_items.return_value = [_item()]
    monkeypatch.setattr(app_mod, "_zotero", mock_zotero)

    r = client.get("/zotero/items", params={"collection": "COLL1", "q": "neural networks"})
    assert r.status_code == 200
    mock_zotero.get_collection_items.assert_called_once_with("COLL1", query="neural networks")


def test_zotero_items_response_includes_authors_and_year(monkeypatch):
    # Regression: response_model=list[ZoteroItem] serialized via FastAPI's
    # default alias-based dump, which emits Zotero's raw field names
    # (itemType, abstractNote, ...) and silently drops `authors`/`year`
    # since those are computed @property accessors, not declared Pydantic
    # fields -- the UI's item list reads exactly these two fields.
    from prisma.server import app as app_mod

    mock_zotero = MagicMock()
    mock_zotero.get_all_items.return_value = [_item(authors=("Ada Lovelace",))]
    monkeypatch.setattr(app_mod, "_zotero", mock_zotero)

    r = client.get("/zotero/items")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["authors"] == ["Ada Lovelace"]
    assert body[0]["year"] == 2024
    assert body[0]["title"] == "T"
    assert body[0]["key"] == "K1"


def test_sync_pending_online_flushes_queue(monkeypatch):
    class _NonEmptyQueue:
        def __init__(self, *a, **kw):
            self.pending_count = 2

        def flush(self, zotero_client):
            return (2, 0)

    monkeypatch.setattr("prisma.storage.pending_queue.PendingWriteQueue", _NonEmptyQueue)
    monkeypatch.setattr("prisma.server.app.connectivity.is_online", True)

    r = client.post("/zotero/sync-pending")
    assert r.status_code == 200
    assert r.json() == {"synced": 2, "failed": 0, "pending_before": 2}


# ── Isolated router tests (build_zotero_router directly) ─────────────────────
# /zotero/status, /zotero/collections, and /zotero/import/{key} had zero test
# coverage anywhere before this router extraction -- import in particular has
# real branching logic (existing-import dedup, PDF-vs-abstract-fallback body,
# citekey creation) worth covering now that it's isolable from the full app.

@pytest.fixture
def vault(tmp_path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


@pytest.fixture
def zotero() -> MagicMock:
    return MagicMock()


@pytest.fixture
def indexer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def isolated_client(vault, zotero, indexer) -> TestClient:
    isolated_app = FastAPI()
    isolated_app.include_router(build_zotero_router(
        get_vault=lambda: vault,
        get_zotero=lambda: zotero,
        get_indexer=lambda: indexer,
    ))
    return TestClient(isolated_app)


def _zotero_item(**overrides) -> ZoteroItem:
    defaults = dict(
        key="K1", title="A Great Paper", item_type="journalArticle",
        creators=[ZoteroCreator(creator_type="author", name="Jane Smith")],
        date="2024", abstract_note="an abstract", doi="10.1/xyz",
        url="https://example.com/paper", publication_title="Journal of Things",
        tags=[ZoteroTag(tag="ml")], collections=[],
    )
    defaults.update(overrides)
    return ZoteroItem(**defaults)


def test_zotero_status(isolated_client, zotero):
    from prisma.integrations.zotero.client import ZoteroStatus
    zotero.status.return_value = ZoteroStatus(mode="web_api", available=True, reachable=True)
    r = isolated_client.get("/zotero/status")
    assert r.status_code == 200
    assert r.json() == {"mode": "web_api", "available": True, "reachable": True}


def test_zotero_collections_success(isolated_client, zotero):
    from prisma.storage.models.zotero_models import ZoteroCollection
    zotero.get_collections.return_value = [ZoteroCollection(key="C1", name="My Collection")]
    r = isolated_client.get("/zotero/collections")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "My Collection"


def test_zotero_collections_failure_returns_503(isolated_client, zotero):
    zotero.get_collections.side_effect = RuntimeError("network down")
    r = isolated_client.get("/zotero/collections")
    assert r.status_code == 503


def test_zotero_import_404_when_item_not_found(isolated_client, zotero):
    zotero.get_item.return_value = None
    r = isolated_client.post("/zotero/import/DOES-NOT-EXIST")
    assert r.status_code == 404


def test_zotero_import_returns_existing_source_if_already_imported(isolated_client, vault, zotero):
    # Already in the vault (zotero_key frontmatter match) -- must not
    # re-create, just render and return the existing source.
    existing = vault.create_source_from_citekey(
        "smith2024", "Already Here", "body text",
        zotero_key="K1", authors=["Jane Smith"], tags=[],
    )
    zotero.get_item.return_value = _zotero_item(key="K1")

    r = isolated_client.post("/zotero/import/K1")
    assert r.status_code == 201
    assert r.json()["slug"] == existing.slug
    zotero.get_pdf_bytes.assert_not_called()


def test_zotero_import_creates_source_from_abstract_when_no_pdf(isolated_client, vault, zotero, indexer):
    zotero.get_item.return_value = _zotero_item(key="K2")
    zotero.get_pdf_bytes.return_value = None

    r = isolated_client.post("/zotero/import/K2")
    assert r.status_code == 201
    data = r.json()
    assert data["slug"] == "smith2024"  # make_citekey: first author's last name + year
    assert "an abstract" in data["html"]
    indexer.mark_stale.assert_called_once()

    source = vault.get_source(data["slug"])
    assert source.zotero_key == "K2"
    assert source.doi == "10.1/xyz"
    # ADR-020: these were fetched from ZoteroItem but discarded before --
    # only ever used to build unstructured body prose, never persisted as
    # structured fields.
    assert source.journal == "Journal of Things"
    assert source.item_type == "journalArticle"
    assert source.url == "https://example.com/paper"
