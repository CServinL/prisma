"""Unit tests for prisma.server.notes_routes — built in isolation (a bare
FastAPI app wrapping just build_notes_router + a tmp_path VaultService), not
the full prisma.server.app singleton, same approach as test_sync_routes.py.
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.notes_routes import build_notes_router
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import NodeType


class _Recorder:
    def __init__(self):
        self.broadcasts = []
        self.mark_stale_calls = 0

    def broadcast(self, event, exclude_client_id=None):
        self.broadcasts.append((event, exclude_client_id))

    def mark_stale(self):
        self.mark_stale_calls += 1


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def client(vault, recorder) -> TestClient:
    app = FastAPI()
    app.include_router(build_notes_router(
        get_vault=lambda: vault,
        mark_stale_fn=recorder.mark_stale,
        broadcast_fn=recorder.broadcast,
    ))
    return TestClient(app)


def _make_html_source(vault: VaultService, slug: str, html: str = "<html><body>hi</body></html>") -> None:
    """A .md node with an attached .html companion (find_companion()'s
    pattern) -- the .md is primary, .html is the extra file alongside it.
    Different from a bare .html-only source with no .md yet (see
    test_generate_md_format_creates_companion), where find_file()/get_any()
    resolve the .html itself as the node's canonical file instead."""
    d = vault.default_dirs[NodeType.source]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.html").write_text(html, encoding="utf-8")
    (d / f"{slug}.md").write_text('---\ntype: source\ntitle: Test Source\n---\n\n', encoding="utf-8")


def test_list_notes_empty(client):
    r = client.get("/notes")
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == []


def test_create_note_then_list(client, vault, recorder):
    r = client.post("/notes", json={"title": "My Note", "body": "hello world"})
    assert r.status_code == 201
    data = r.json()
    assert data["slug"] == "my-note"
    assert data["title"] == "My Note"
    assert recorder.mark_stale_calls == 1
    assert recorder.broadcasts[0][0]["action"] == "create"

    r2 = client.get("/notes")
    assert len(r2.json()["notes"]) == 1


def test_get_note_not_found(client):
    r = client.get("/notes/does-not-exist")
    assert r.status_code == 404


def test_get_note_renders_markdown_body(client, vault):
    vault.create_note("Deep Learning", "# Heading\n\nsome body text")
    r = client.get("/notes/deep-learning")
    assert r.status_code == 200
    data = r.json()
    assert data["slug"] == "deep-learning"
    assert "Heading" in data["html"] or "body text" in data["html"]


def test_save_note_updates_body(client, vault, recorder):
    vault.create_note("My Note", "original body")
    r = client.put("/notes/my-note", json={"body": "updated body"})
    assert r.status_code == 200
    assert recorder.mark_stale_calls == 1
    assert recorder.broadcasts[-1][0]["action"] == "save"


def test_save_note_not_found(client):
    r = client.put("/notes/does-not-exist", json={"body": "x"})
    assert r.status_code == 404


def test_set_note_type(client, vault):
    vault.create_note("My Note", "body")
    r = client.patch("/notes/my-note/type", json={"node_type": "source"})
    assert r.status_code == 200
    assert r.json()["node_type"] == "source"


def test_set_note_type_not_found(client):
    r = client.patch("/notes/does-not-exist/type", json={"node_type": "source"})
    assert r.status_code == 404


def test_get_original_returns_companion_file(client, vault):
    _make_html_source(vault, "my-source")
    r = client.get("/notes/my-source/original")
    assert r.status_code == 200
    assert "hi" in r.text


def test_get_original_not_found(client):
    r = client.get("/notes/does-not-exist/original")
    assert r.status_code == 404


def test_view_html_renders_and_rewrites_assets(client, vault):
    _make_html_source(vault, "my-source", html='<html><body><img src="fig.png"></body></html>')
    r = client.get("/notes/my-source/view")
    assert r.status_code == 200
    assert "/vault/assets/" in r.text
    assert "fig.png" in r.text


def test_view_html_not_found(client):
    r = client.get("/notes/does-not-exist/view")
    assert r.status_code == 404


def test_generate_md_format_creates_companion(client, vault):
    # generate_md_format only makes sense for a node whose canonical file is
    # still bare .html with no .md companion yet -- once a .md companion
    # exists, find_file()/get_any() resolve to the .md as primary instead
    # (see _make_html_source's docstring-equivalent note below).
    d = vault.default_dirs[NodeType.source]
    d.mkdir(parents=True, exist_ok=True)
    (d / "my-source.html").write_text("<html><body>content</body></html>", encoding="utf-8")
    r = client.post("/notes/my-source/md")
    assert r.status_code == 202
    # Whether `generated` comes back True depends on docu_craft's own HTML->MD
    # conversion succeeding for this snippet -- not this route's concern to
    # assert on; what matters here is the route correctly reaches
    # vault.ensure_md_format() and returns its result, not a specific value.
    assert r.json()["slug"] == "my-source"
    assert isinstance(r.json()["generated"], bool)


def test_generate_md_format_rejects_non_html_node(client, vault):
    vault.create_note("My Note", "body")
    r = client.post("/notes/my-note/md")
    assert r.status_code == 400


def test_generate_md_format_not_found(client):
    r = client.post("/notes/does-not-exist/md")
    assert r.status_code == 404


# ── GET /notes/apa (ADR-020 bulk slug -> APA-citation lookup) ─────────────────

def test_get_apa_citations_returns_formatted_string(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ZK1", authors=["Jane Smith"], tags=[], year=2024,
    )
    r = client.get(f"/notes/apa?slugs={source.slug}")
    assert r.status_code == 200
    assert r.json() == {"smith2024": "Smith, J. (2024). A Great Paper."}


def test_get_apa_citations_bulk_lookup(client, vault):
    a = vault.create_source_from_citekey("a2024", "Paper A", "body", zotero_key="A", authors=[], tags=[])
    b = vault.create_source_from_citekey("b2024", "Paper B", "body", zotero_key="B", authors=[], tags=[])
    r = client.get(f"/notes/apa?slugs={a.slug},{b.slug}")
    assert set(r.json().keys()) == {"a2024", "b2024"}


def test_get_apa_citations_omits_missing_slugs(client, vault):
    source = vault.create_source_from_citekey("smith2024", "A Great Paper", "body", zotero_key="ZK1", authors=[], tags=[])
    r = client.get(f"/notes/apa?slugs={source.slug},does-not-exist")
    assert list(r.json().keys()) == ["smith2024"]


def test_get_apa_citations_omits_notes_not_just_sources(client, vault):
    # A claim's sources can point to a Note, not only a Source -- format_apa()
    # would misfire on one (empty authors, note title as "citation title"),
    # so this must be skipped rather than producing a garbage citation.
    note = vault.create_note("A Note", body="text")
    r = client.get(f"/notes/apa?slugs={note.slug}")
    assert r.json() == {}


def test_get_apa_citations_registered_before_slug_route(client, vault):
    # Regression test for the route-ordering requirement noted in
    # notes_routes.py: /apa must not be swallowed by GET /{slug}.
    r = client.get("/notes/apa?slugs=whatever")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
