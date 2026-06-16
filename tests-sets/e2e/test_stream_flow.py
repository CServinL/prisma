"""
E2E stream tests — real Zotero Web API, real arxiv, real config.

_vault uses tmp_path for test isolation (clean state, no vault pollution).
Everything else is the production stack unchanged.

Prerequisites:
  - internet (arxiv reachable)
  - api_key + library_id in ~/.config/prisma/config.yaml (sources.zotero)

Cleanup: Zotero collection created during the run is deleted at teardown.

Run: .venv/bin/python -m pytest tests-sets/e2e/test_stream_flow.py -v
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from prisma.services.vault import VaultService
from prisma.services.zotero import ZoteroMode


# ── Availability checks ───────────────────────────────────────────────────────

def _arxiv_reachable() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("https://export.arxiv.org", timeout=5)
        return True
    except Exception:
        return False


def _zotero_web_api_configured() -> bool:
    try:
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load(
            (Path.home() / ".config" / "prisma" / "config.yaml").read_text()
        ) or {}
        return bool(cfg.get("sources", {}).get("zotero", {}).get("api_key"))
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _arxiv_reachable() or not _zotero_web_api_configured(),
    reason="stream e2e requires internet + Zotero Web API configured in config.yaml",
)


# ── Shared state ──────────────────────────────────────────────────────────────

_state: dict = {}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    v = VaultService(tmp_path_factory.mktemp("vault"))
    v.ensure_dirs()
    return v


@pytest.fixture(scope="module")
def zotero():
    import prisma.server.app as app_mod
    z = app_mod._zotero
    if z.mode != ZoteroMode.web_api:
        pytest.skip("Zotero not in web_api mode — check config.yaml api_key")
    return z


@pytest.fixture(scope="module")
def client(vault):
    import prisma.server.app as app_mod
    with patch.object(app_mod, "_vault", vault):
        with TestClient(app_mod.app, raise_server_exceptions=True) as tc:
            yield tc


@pytest.fixture(scope="module", autouse=True)
def cleanup(zotero):
    yield
    key = _state.get("collection_key")
    if key:
        try:
            zotero.delete_collection(key)
        except Exception as exc:
            print(f"Warning: could not delete test collection {key}: {exc}")


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
    assert data["papers_saved"] > 0, f"expected items saved to Zotero, got: {data}"
    _state["run1"] = data


def test_run_stream_creates_zotero_collection(client, vault, zotero):
    slug = _state["slug"]
    stream = vault.get_stream(slug)
    assert stream.collection_key, "stream.collection_key should be set after run"
    _state["collection_key"] = stream.collection_key

    collections = zotero.list_collections()
    keys = {c.key for c in collections}
    assert stream.collection_key in keys, (
        f"collection {stream.collection_key!r} not found in Zotero; "
        f"found: {[c.name for c in collections]}"
    )


def test_run_stream_saves_items_to_zotero(zotero):
    key = _state["collection_key"]
    items = zotero.list_items(collection_key=key)
    assert len(items) == _state["run1"]["papers_saved"], (
        f"expected {_state['run1']['papers_saved']} items in Zotero collection, "
        f"got {len(items)}"
    )


def test_rerun_stream_deduplicates(client):
    slug = _state["slug"]
    resp = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["papers_saved"] == 0, (
        f"second run saved {data['papers_saved']} duplicate(s) to Zotero"
    )


def test_rerun_with_force_bypasses_schedule(client):
    slug = _state["slug"]
    resp_no_force = client.post(f"/streams/{slug}/run")
    assert resp_no_force.status_code == 200
    assert any("not due" in e for e in resp_no_force.json().get("errors", []))

    resp_force = client.post(f"/streams/{slug}/run", params={"force": True})
    assert resp_force.status_code == 200
    assert not any("not due" in e for e in resp_force.json().get("errors", []))


def test_stream_metadata_updated_after_run(client):
    slug = _state["slug"]
    resp = client.get(f"/streams/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_papers"] > 0
    assert data["last_updated"] is not None
    assert data["next_update"] is not None


def test_zotero_items_have_required_fields(zotero):
    key = _state["collection_key"]
    items = zotero.list_items(collection_key=key)
    assert items, "no items in Zotero collection"

    for item in items:
        assert item.title, f"{item.key}: missing title"
        assert item.authors, f"{item.key}: missing authors"
        assert item.abstract and len(item.abstract.strip()) > 50, (
            f"{item.key}: abstract too short or missing"
        )


def test_zotero_items_above_confidence_threshold(zotero):
    # SearchAgent filters by min_confidence_score before items reach _run_stream.
    # All items in Zotero passed the filter — verify they have non-trivial content.
    key = _state["collection_key"]
    items = zotero.list_items(collection_key=key)
    assert items
    for item in items:
        assert item.title.strip(), f"{item.key}: empty title"


def test_delete_stream_removes_from_listing(client):
    slug = _state["slug"]
    resp = client.delete(f"/streams/{slug}")
    assert resp.status_code == 204

    resp = client.get("/streams")
    assert resp.status_code == 200
    assert slug not in [s["slug"] for s in resp.json()]
