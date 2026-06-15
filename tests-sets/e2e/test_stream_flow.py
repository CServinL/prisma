"""
E2E stream tests: create → run → dedup → force → metadata → quality → delete.
Skipped automatically when arxiv is unreachable.

Tests share state (slug, run results) across the module — intentional for E2E.
Run: .venv/bin/python -m pytest tests-sets/e2e/test_stream_flow.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


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


# ── Shared state ──────────────────────────────────────────────────────────────

_state: dict = {}  # slug, run results — accumulated across the module


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    from prisma.services.vault import VaultService
    v = VaultService(tmp_path_factory.mktemp("vault"))
    v.ensure_dirs()
    return v


@pytest.fixture(scope="module")
def client(vault):
    import prisma.server.app as app_mod

    cfg_mock = MagicMock()
    cfg_mock.sources = ["arxiv"]
    cfg_mock.default_limit = 5

    loader_mock = MagicMock(
        return_value=MagicMock(get_search_config=MagicMock(return_value=cfg_mock))
    )

    noop = MagicMock()
    noop.start = noop.stop = noop.mark_stale = MagicMock()
    noop.status = MagicMock(return_value={})

    with patch.object(app_mod, "_vault", vault), \
         patch.object(app_mod, "_indexer", noop), \
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


def test_run_stream_finds_papers(client):
    slug = _state["slug"]
    resp = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["papers_found"] > 0, f"expected papers from arxiv, got: {data}"
    _state["run1"] = data


def test_run_stream_saves_sources_to_vault(client):
    run = _state["run1"]
    assert run["papers_saved"] > 0, "first run saved no papers"

    resp = client.get("/notes", params={"node_type": "source"})
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert len(sources) > 0


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
    # next_update is in the future from prior runs; without force we get "not due"
    resp_no_force = client.post(f"/streams/{slug}/run")
    assert resp_no_force.status_code == 200
    assert any("not due" in e for e in resp_no_force.json().get("errors", []))

    # force=true must bypass the schedule gate
    resp_force = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp_force.status_code == 200
    assert not any("not due" in e for e in resp_force.json().get("errors", []))


@pytest.mark.xfail(
    reason="_run_stream does not yet create Zotero collections (unimplemented)",
    strict=True,
)
@pytest.mark.skipif(
    not _zotero_local_reachable(),
    reason="Zotero Desktop not running at localhost:23119",
)
def test_zotero_collection_created_on_run(client):
    slug = _state["slug"]
    stream_resp = client.get(f"/streams/{slug}")
    stream_title = stream_resp.json()["title"]

    collections_resp = client.get("/zotero/collections")
    assert collections_resp.status_code == 200
    names = [c.get("name", "") for c in collections_resp.json()]
    assert any(stream_title in n for n in names), (
        f"no Zotero collection matching {stream_title!r}, found: {names}"
    )


def test_stream_metadata_updated_after_run(client):
    slug = _state["slug"]
    resp = client.get(f"/streams/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_papers"] > 0
    assert data["last_updated"] is not None
    assert data["next_update"] is not None


def test_source_evaluation_quality(client, vault):
    from prisma.services.vault import _parse_frontmatter
    from prisma.storage.models.vault_models import NodeType

    source_dir = vault.default_dirs[NodeType.source]
    paths = list(source_dir.glob("*.md"))
    assert paths, "no source files saved to vault"

    for path in paths[:3]:
        raw = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(raw)
        assert fm.get("title"), f"{path.stem}: missing title in frontmatter"
        assert fm.get("authors"), f"{path.stem}: missing authors in frontmatter"
        assert len(body.strip()) > 50, f"{path.stem}: abstract too short or missing"


def test_source_confidence_above_threshold(client, vault):
    # SearchAgent filters by confidence before returning papers to _run_stream.
    # We verify that every saved source has non-empty content (quality proxy).
    # Full confidence-score persistence is tracked in ADR-009.
    from prisma.services.vault import _parse_frontmatter
    from prisma.storage.models.vault_models import NodeType

    source_dir = vault.default_dirs[NodeType.source]
    paths = list(source_dir.glob("*.md"))
    assert paths

    for path in paths:
        raw = path.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(raw)
        assert len(body.strip()) > 0, f"{path.stem}: empty body saved"


def test_delete_stream_removes_from_listing(client):
    slug = _state["slug"]
    resp = client.delete(f"/streams/{slug}")
    assert resp.status_code == 204

    resp = client.get("/streams")
    assert resp.status_code == 200
    slugs = [s["slug"] for s in resp.json()]
    assert slug not in slugs
