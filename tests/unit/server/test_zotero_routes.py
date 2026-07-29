"""Unit tests for the two API routes added when the CLI was minimized
(2026-07-27): GET /zotero/stats and POST /zotero/sync-pending replace the
old `prisma zotero stats` and `prisma sync` CLI commands.
"""

from fastapi.testclient import TestClient

from prisma.server.app import app
from prisma.storage.models.zotero_models import ZoteroItem, ZoteroCreator

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


def test_sync_pending_online_flushes_queue(monkeypatch):
    class _NonEmptyQueue:
        def __init__(self, *a, **kw):
            self.pending_count = 2

    class _FakeManager:
        def __init__(self, *a, **kw):
            pass

        def sync_pending(self):
            return (2, 0)

    monkeypatch.setattr("prisma.storage.pending_queue.PendingWriteQueue", _NonEmptyQueue)
    monkeypatch.setattr("prisma.server.app.connectivity.is_online", True)
    monkeypatch.setattr(
        "prisma.services.research_stream_manager.ResearchStreamManager", _FakeManager
    )

    r = client.post("/zotero/sync-pending")
    assert r.status_code == 200
    assert r.json() == {"synced": 2, "failed": 0, "pending_before": 2}
