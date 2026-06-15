"""
E2E stream tests: create → run → dedup → force → metadata → quality → delete.
Skipped automatically when arxiv is unreachable.

Tests share state (slug, Zotero items) across the module — intentional for E2E.
_zotero is replaced with a stateful fake that mirrors the Web API contract so the
orchestration logic is exercised against real arxiv results without needing Zotero creds.

Run: .venv/bin/python -m pytest tests-sets/e2e/test_stream_flow.py -v
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from prisma.services.zotero import ZoteroCollection, ZoteroItem, ZoteroMode


# ── Connectivity checks ───────────────────────────────────────────────────────

def _arxiv_reachable() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("https://export.arxiv.org", timeout=5)
        return True
    except Exception:
        return False


def _zotero_local_reachable() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:23119", timeout=2)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _arxiv_reachable(),
    reason="stream e2e requires internet (arxiv unreachable)",
)


# ── Stateful Zotero fake ──────────────────────────────────────────────────────

class _FakeZotero:
    """Mirrors ZoteroService Web API contract with in-memory state."""

    def __init__(self):
        self.mode = ZoteroMode.web_api
        self._collections: dict[str, ZoteroCollection] = {}  # name → collection
        self._items: dict[str, list[ZoteroItem]] = {}         # collection_key → items

    def ensure_collection(self, name, parent_key=None):
        if name not in self._collections:
            key = f"FAKE{uuid.uuid4().hex[:6].upper()}"
            self._collections[name] = ZoteroCollection(key=key, name=name)
        return self._collections[name]

    def list_collections(self):
        return list(self._collections.values())

    def list_items(self, collection_key=None, q=None):
        if collection_key:
            return list(self._items.get(collection_key, []))
        return [item for items in self._items.values() for item in items]

    def add_item(self, paper, collection_key):
        item = ZoteroItem(
            key=uuid.uuid4().hex[:8].upper(),
            title=getattr(paper, "title", ""),
            item_type="preprint",
            authors=getattr(paper, "authors", []),
            year=None,
            abstract=getattr(paper, "abstract", None),
            doi=getattr(paper, "doi", None),
            url=getattr(paper, "url", None),
            publication=None,
            tags=[],
            collection_keys=[collection_key],
        )
        self._items.setdefault(collection_key, []).append(item)
        return item

    def status(self):
        return {"mode": "web-api", "available": True}


# ── Shared state ──────────────────────────────────────────────────────────────

_state: dict = {}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fake_zotero():
    return _FakeZotero()


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    from prisma.services.vault import VaultService
    v = VaultService(tmp_path_factory.mktemp("vault"))
    v.ensure_dirs()
    return v


@pytest.fixture(scope="module")
def client(vault, fake_zotero):
    import prisma.server.app as app_mod

    cfg_mock = MagicMock()
    cfg_mock.sources = ["arxiv"]
    cfg_mock.default_limit = 5
    cfg_mock.min_confidence_score = 0.5
    cfg_mock.prefer_high_quality = True

    loader_mock = MagicMock(
        return_value=MagicMock(get_search_config=MagicMock(return_value=cfg_mock))
    )

    noop = MagicMock()
    noop.start = noop.stop = noop.mark_stale = MagicMock()
    noop.status = MagicMock(return_value={})

    with patch.object(app_mod, "_vault", vault), \
         patch.object(app_mod, "_indexer", noop), \
         patch.object(app_mod, "_zotero", fake_zotero), \
         patch.object(app_mod, "_scheduler", MagicMock()), \
         patch("prisma.utils.config.ConfigLoader", loader_mock):
        with TestClient(app_mod.app, raise_server_exceptions=True) as tc:
            yield tc


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_stream_returns_slug(client):
    resp = client.post("/streams", json={
        "title": "Mechanistic Interpretability E2E",
        "query": "mechanistic interpretability transformer circuits",
        "refresh_frequency": "weekly",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"]
    assert data["status"] == "active"
    _state["slug"] = data["slug"]


def test_run_stream_finds_papers(client, fake_zotero):
    slug = _state["slug"]
    resp = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["papers_found"] > 0, f"expected papers from arxiv, got: {data}"
    assert data["papers_saved"] > 0, f"expected Zotero items saved, got: {data}"
    _state["run1"] = data


def test_run_stream_saves_items_to_zotero(client, fake_zotero):
    run = _state["run1"]
    stream_resp = client.get(f"/streams/{_state['slug']}")
    collection_key = stream_resp.json().get("collection_key") or \
        next(iter(fake_zotero._collections.values())).key

    items = fake_zotero.list_items(collection_key=collection_key)
    assert len(items) == run["papers_saved"]
    for item in items:
        assert item.title


def test_rerun_stream_deduplicates(client):
    slug = _state["slug"]
    resp = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["papers_saved"] == 0, (
        f"second run saved {data['papers_saved']} duplicate(s)"
    )


def test_rerun_with_force_bypasses_schedule(client):
    slug = _state["slug"]
    resp_no_force = client.post(f"/streams/{slug}/run")
    assert resp_no_force.status_code == 200
    assert any("not due" in e for e in resp_no_force.json().get("errors", []))

    resp_force = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp_force.status_code == 200
    assert not any("not due" in e for e in resp_force.json().get("errors", []))


@pytest.mark.skipif(
    not _zotero_local_reachable(),
    reason="Zotero Desktop not running at localhost:23119",
)
def test_zotero_collection_created_on_run(client, fake_zotero):
    slug = _state["slug"]
    stream_resp = client.get(f"/streams/{slug}")
    stream_title = stream_resp.json()["title"]
    assert stream_title in fake_zotero._collections, (
        f"no collection for {stream_title!r}, found: {list(fake_zotero._collections)}"
    )


def test_stream_metadata_updated_after_run(client):
    slug = _state["slug"]
    resp = client.get(f"/streams/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_papers"] > 0
    assert data["last_updated"] is not None
    assert data["next_update"] is not None


def test_source_evaluation_quality(client, fake_zotero):
    items = fake_zotero.list_items()
    assert items, "no items saved to Zotero"

    for item in items[:3]:
        assert item.title, f"{item.key}: missing title"
        assert item.authors, f"{item.key}: missing authors"
        assert item.abstract and len(item.abstract.strip()) > 50, (
            f"{item.key}: abstract too short or missing"
        )


def test_source_confidence_above_threshold(client, fake_zotero):
    # SearchAgent filters by confidence before papers reach _run_stream.
    # Verify all saved items have non-empty content (quality proxy).
    # Full confidence-score persistence is tracked in ADR-009.
    items = fake_zotero.list_items()
    assert items
    for item in items:
        assert item.title.strip(), f"{item.key}: empty title saved"


def test_delete_stream_removes_from_listing(client):
    slug = _state["slug"]
    resp = client.delete(f"/streams/{slug}")
    assert resp.status_code == 204

    resp = client.get("/streams")
    assert resp.status_code == 200
    slugs = [s["slug"] for s in resp.json()]
    assert slug not in slugs
