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


def test_create_note_response_echoes_tags(client):
    r = client.post("/notes", json={"title": "My Note", "tags": ["ml"]})
    assert r.json()["tags"] == ["ml"]


def test_create_note_rejects_whitespace_only_title(client):
    r = client.post("/notes", json={"title": "   "})
    assert r.status_code == 422


def test_create_note_drops_blank_tag_entries(client):
    r = client.post("/notes", json={"title": "My Note", "tags": ["real", "   "]})
    assert r.status_code == 201
    assert r.json()["tags"] == ["real"]


def test_create_note_rejects_an_absurdly_long_tag(client):
    r = client.post("/notes", json={"title": "My Note", "tags": ["a" * 5000]})
    assert r.status_code == 422


def test_create_note_rejects_too_many_tags(client):
    r = client.post("/notes", json={"title": "My Note", "tags": [f"tag{i}" for i in range(500)]})
    assert r.status_code == 422


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


def test_save_note_response_echoes_tags(client, vault):
    vault.create_note("My Note", "body", tags=["ml"])
    r = client.put("/notes/my-note", json={"body": "updated body"})
    assert r.json()["tags"] == ["ml"]


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


def test_set_note_type_not_shadowed_by_a_node_literally_named_sources(client, vault):
    # A node whose slug is literally "sources" must not collide with the
    # source-edit route's own path segment.
    vault.create_note("Sources", "body")
    r = client.patch("/notes/sources/type", json={"node_type": "source"})
    assert r.status_code == 200
    assert r.json()["node_type"] == "source"


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


# ── GET /notes/{slug}/read (READ_SOURCE's REST surface) ──────────────────────

_SECTIONED_DOC = (
    "---\ntype: note\ntitle: Doc\n---\n"
    "intro line\n\n"
    "## Methods\nA closed-form update.\n\n"
    "## Results\nAccuracy improved by 4 points.\n"
)


def test_read_summary_mode_default(client, vault):
    vault.create_note("Doc", body="The transformer uses self-attention.")
    r = client.get("/notes/doc/read")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "summary"
    assert "self-attention" in body["text"]


def test_read_section_mode(client, vault):
    (vault.default_dirs[NodeType.note] / "doc.md").write_text(_SECTIONED_DOC, encoding="utf-8")
    r = client.get("/notes/doc/read", params={"mode": "section", "query": "results"})
    assert r.status_code == 200
    body = r.json()
    assert "Accuracy improved" in body["text"]
    assert body["available_sections"] == ["Methods", "Results"]


def test_read_literal_mode(client, vault):
    (vault.default_dirs[NodeType.note] / "doc.md").write_text(_SECTIONED_DOC, encoding="utf-8")
    r = client.get("/notes/doc/read", params={"mode": "literal", "query": "closed-form"})
    assert r.status_code == 200
    body = r.json()
    assert body["match_count"] == 1
    assert "closed-form update" in body["text"]


def test_read_rejects_unknown_mode(client, vault):
    vault.create_note("Doc", body="text")
    assert client.get("/notes/doc/read", params={"mode": "bogus"}).status_code == 422


def test_read_missing_slug_is_404(client):
    assert client.get("/notes/nope/read").status_code == 404


def test_read_rejects_path_traversal_slug(client, vault, tmp_path):
    # This module's vault fixture uses vault.root == tmp_path directly (see
    # the `vault` fixture above), so a single-hop "..--secret" decodes to
    # tmp_path.parent/"secret.md" -- one level above vault.root, where this
    # test actually plants the file.
    outside = tmp_path.parent / "secret.md"
    outside.write_text("---\ntype: note\n---\nleaked", encoding="utf-8")
    r = client.get("/notes/..--secret/read")
    assert r.status_code == 404
    assert "leaked" not in r.text


def test_create_source_with_auto_citekey(client, recorder):
    r = client.post("/notes/sources", json={
        "title": "A Great Paper", "authors": ["Jane Smith"], "year": 2024,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["citekey"] == "smith2024"
    assert data["authors"] == ["Jane Smith"]
    assert data["year"] == 2024
    assert recorder.mark_stale_calls == 1
    assert recorder.broadcasts[0][0]["action"] == "create"


def test_create_source_auto_citekey_does_not_drop_year_zero(client):
    r = client.post("/notes/sources", json={"title": "A Great Paper", "authors": ["Jane Smith"], "year": 0})
    assert r.status_code == 201
    assert r.json()["citekey"] == "smith0"


def test_create_source_with_explicit_citekey(client):
    r = client.post("/notes/sources", json={"title": "A Great Paper", "citekey": "custom2024"})
    assert r.status_code == 201
    assert r.json()["citekey"] == "custom2024"


def test_create_source_rejects_duplicate_citekey(client):
    client.post("/notes/sources", json={"title": "First", "citekey": "dup2024"})
    r = client.post("/notes/sources", json={"title": "Second", "citekey": "dup2024"})
    assert r.status_code == 409


def test_get_note_echoes_tags_for_prefilling_the_edit_dialog(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=["ml", "nlp"],
    )
    r = client.get(f"/notes/{source.slug}")
    assert r.json()["tags"] == ["ml", "nlp"]


def test_edit_source_updates_tags_and_source_kind(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=["ml"],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"tags": ["ml", "nlp"], "source_kind": "web"})
    assert r.status_code == 200
    data = r.json()
    assert data["tags"] == ["ml", "nlp"]
    assert data["source_kind"] == "web"


def test_edit_source_response_echoes_the_request_slug_not_the_bare_stem(client, vault):
    # A moved source's bare stem can collide with an unrelated file
    # elsewhere -- the response must echo the slug this route actually
    # resolved, not source.slug's bare file stem.
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    new_slug, _, _ = vault.move_node(source.slug, dest_dir="notes")
    assert new_slug != "smith2024"  # confirms this really is a compound slug

    colliding_dir = vault.default_dirs[NodeType.source]
    colliding_dir.mkdir(parents=True, exist_ok=True)
    (colliding_dir / "smith2024.md").write_text(
        "---\ntype: source\ntitle: Unrelated\ncitekey: unrelated2099\n---\nUnrelated body.",
        encoding="utf-8",
    )

    r = client.patch(f"/notes/{new_slug}/source", json={"journal": "New Journal"})
    assert r.status_code == 200
    assert r.json()["slug"] == new_slug


def test_create_source_no_metadata_still_works(client):
    # Metadata-only Source, no companion at all -- e.g. a physical book.
    r = client.post("/notes/sources", json={"title": "A Physical Book"})
    assert r.status_code == 201
    assert r.json()["original_ext"] is None


def test_create_source_does_not_pay_for_a_full_vault_citekey_scan(client, vault, monkeypatch):
    # A create/edit/companion-upload response must not trigger a
    # full-vault citekey-index rebuild to populate a value no caller uses.
    calls = []
    monkeypatch.setattr(
        "prisma.services.renderer._build_citekey_index",
        lambda v: calls.append(1) or {},
    )
    r = client.post("/notes/sources", json={"title": "X"})
    assert r.status_code == 201
    assert r.json()["html"] == ""
    assert calls == []


def test_create_source_rejects_whitespace_only_title(client):
    r = client.post("/notes/sources", json={"title": "   "})
    assert r.status_code == 422


def test_edit_source_rejects_whitespace_only_title(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"title": "   "})
    assert r.status_code == 422


def test_create_source_rejects_when_no_citekey_can_be_generated(client):
    # make_citekey() legitimately returns "" for an author name with no
    # ASCII letters (e.g. non-Latin script) and no year/usable title word --
    # letting an empty citekey through would silently store citekey: "" and
    # 409 every subsequent unrelated source with the same fate, instead of
    # surfacing that this one genuinely needs an explicit citekey.
    r = client.post("/notes/sources", json={"title": "!!!", "authors": ["田中太郎"]})
    assert r.status_code == 400


def test_create_source_rejects_whitespace_only_explicit_citekey(client):
    r = client.post("/notes/sources", json={"title": "X", "citekey": "   "})
    assert r.status_code == 400
    # A caller who supplied a (blank) citekey must not be told to retype
    # title/authors instead.
    assert "provide one explicitly" not in r.json()["detail"]


def test_create_source_rejects_an_absurdly_long_explicit_citekey(client):
    r = client.post("/notes/sources", json={"title": "X", "citekey": "a" * 5000})
    assert r.status_code == 422


def test_create_source_rejects_an_absurdly_long_auto_generated_citekey(client):
    # An auto-generated citekey (derived from the first author's last
    # name) must be bounded too, not just an explicit one.
    r = client.post("/notes/sources", json={"title": "X", "authors": ["a" * 5000]})
    assert r.status_code == 422


def test_create_source_rejects_an_absurdly_long_bibliographic_field(client):
    r = client.post("/notes/sources", json={"title": "X", "journal": "a" * 5000})
    assert r.status_code == 422


def test_edit_source_rejects_an_absurdly_long_bibliographic_field(client):
    r = client.post("/notes/sources", json={"title": "X"})
    slug = r.json()["slug"]
    r = client.patch(f"/notes/{slug}/source", json={"doi": "a" * 5000})
    assert r.status_code == 422


def test_create_source_rejects_too_many_authors(client):
    r = client.post("/notes/sources", json={"title": "X", "authors": ["Smith"] + [f"Coauthor{i}" for i in range(500)]})
    assert r.status_code == 422


def test_create_source_drops_blank_author_and_tag_entries(client):
    # A whitespace-only entry must be dropped, not rejected -- one bad
    # entry among otherwise-good ones shouldn't fail the whole request.
    r = client.post("/notes/sources", json={"title": "X", "authors": ["  ", "Jane Smith"], "tags": ["ml", "   "]})
    assert r.status_code == 201
    data = r.json()
    assert data["authors"] == ["Jane Smith"]
    assert data["tags"] == ["ml"]


def test_edit_source_drops_blank_author_and_tag_entries(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"authors": ["Jane Smith", "  "], "tags": ["   ", "nlp"]})
    assert r.status_code == 200
    data = r.json()
    assert data["authors"] == ["Jane Smith"]
    assert data["tags"] == ["nlp"]


def test_create_source_drops_blanks_before_enforcing_the_author_count_cap(client):
    # Blanks must be dropped before the count cap is enforced -- 201 raw
    # entries, only 190 real, must pass since 190 is under the cap.
    authors = ["Smith"] + [f"Coauthor{i}" for i in range(189)] + ["   "] * 11
    assert len(authors) == 201
    r = client.post("/notes/sources", json={"title": "X", "authors": authors})
    assert r.status_code == 201
    assert len(r.json()["authors"]) == 190


def test_create_source_rejects_an_absurdly_long_title(client):
    r = client.post("/notes/sources", json={"title": "a" * 5000})
    assert r.status_code == 422


def test_create_source_accepts_a_long_but_not_absurd_title(client):
    # A title under max_length=512 but over ext4's 255-byte-per-component
    # filename limit must still succeed -- _slugify() truncates it.
    r = client.post("/notes/sources", json={"title": "a" * 400})
    assert r.status_code == 201


def test_create_note_accepts_a_long_but_not_absurd_title(client):
    r = client.post("/notes", json={"title": "a" * 400})
    assert r.status_code == 201


def test_two_long_titles_sharing_a_slugified_prefix_dont_collide(client):
    # Two titles sharing the same 200-char truncated prefix must still
    # get distinct slugs.
    long_prefix = "a" * 250
    r1 = client.post("/notes", json={"title": long_prefix + "-ending-one"})
    r2 = client.post("/notes", json={"title": long_prefix + "-ending-two"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["slug"] != r2.json()["slug"]


def test_create_source_rejects_negative_year(client):
    r = client.post("/notes/sources", json={"title": "X", "year": -100})
    assert r.status_code == 422


def test_create_source_rejects_boolean_year(client):
    # `year: true` coerces to 1 under Pydantic's lax mode, satisfying
    # ge=0 -- must be rejected on type, not just range.
    r = client.post("/notes/sources", json={"title": "X", "year": True})
    assert r.status_code == 422


def test_edit_source_rejects_negative_year(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"year": -100})
    assert r.status_code == 422


def test_edit_source_rejects_boolean_year(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"year": True})
    assert r.status_code == 422


def test_create_source_rejects_an_absurdly_large_year(client):
    r = client.post("/notes/sources", json={"title": "X", "year": 10**2000})
    assert r.status_code == 422


def test_edit_source_rejects_an_absurdly_large_year(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"year": 10**2000})
    assert r.status_code == 422


def test_edit_source_returns_404_not_500_on_concurrent_delete(client, vault, monkeypatch):
    # A delete landing between the isinstance check and the write must
    # surface as 404, not an unhandled 500.
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    real_get_any = VaultService.get_any

    def get_any_then_delete(self, slug):
        node = real_get_any(self, slug)
        self._find_md(slug).unlink()
        return node

    monkeypatch.setattr(VaultService, "get_any", get_any_then_delete)
    r = client.patch(f"/notes/{source.slug}/source", json={"doi": "10.1/x"})
    assert r.status_code == 404


def test_upload_companion_returns_404_not_500_on_concurrent_delete(client, vault, monkeypatch):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    real_get_any = VaultService.get_any

    def get_any_then_delete(self, slug):
        node = real_get_any(self, slug)
        self._find_md(slug).unlink()
        return node

    monkeypatch.setattr(VaultService, "get_any", get_any_then_delete)
    r = client.post(f"/notes/{source.slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 404


def test_edit_source_returns_400_when_type_changes_out_from_under_it(client, vault, monkeypatch):
    # A concurrent type change landing between the isinstance check and
    # the locked write must reject the edit, not let it write Source-only
    # fields into what is now a Note.
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    real_get_any = VaultService.get_any

    def get_any_then_convert(self, slug):
        node = real_get_any(self, slug)
        self.set_node_type(slug, NodeType.note)
        return node

    monkeypatch.setattr(VaultService, "get_any", get_any_then_convert)
    r = client.patch(f"/notes/{source.slug}/source", json={"doi": "10.1/x"})
    assert r.status_code == 400


def test_upload_companion_returns_400_when_type_changes_out_from_under_it(client, vault, monkeypatch):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    real_get_any = VaultService.get_any

    def get_any_then_convert(self, slug):
        node = real_get_any(self, slug)
        self.set_node_type(slug, NodeType.note)
        return node

    monkeypatch.setattr(VaultService, "get_any", get_any_then_convert)
    r = client.post(f"/notes/{source.slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 400


def test_edit_source_merges_only_given_fields(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body",
        zotero_key="ABC", authors=["Jane Smith"], tags=[], journal="Original Journal",
    )
    r = client.patch(f"/notes/{source.slug}/source", json={"doi": "10.1/new"})
    assert r.status_code == 200
    data = r.json()
    assert data["doi"] == "10.1/new"
    assert data["journal"] == "Original Journal"


def test_edit_source_not_found(client):
    r = client.patch("/notes/does-not-exist/source", json={"doi": "10.1/x"})
    assert r.status_code == 404


def test_edit_source_rejects_non_source_slug(client, vault):
    note = vault.create_note("My Note", "body")
    r = client.patch(f"/notes/{note.slug}/source", json={"doi": "10.1/x"})
    assert r.status_code == 400


def test_upload_companion_rejects_bad_extension(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.post(f"/notes/{source.slug}/companion",
                     files={"file": ("archive.zip", b"data", "application/zip")})
    assert r.status_code == 400


def test_upload_companion_rejects_an_oversized_file(client, vault, monkeypatch):
    # Confirms the route surfaces read_upload_bounded()'s 413 correctly --
    # the cap itself is covered directly in test_upload_utils.py.
    from fastapi import HTTPException

    def fake_read_upload_bounded(file, max_bytes=None):
        raise HTTPException(status_code=413, detail="file too large")

    monkeypatch.setattr("prisma.server.notes_routes.read_upload_bounded", fake_read_upload_bounded)
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.post(f"/notes/{source.slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 413


def test_upload_companion_attaches_svg(client, vault):
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    r = client.post(f"/notes/{source.slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 200
    assert r.json()["original_ext"] == ".svg"


def test_upload_companion_response_echoes_the_request_slug_not_the_bare_stem(client, vault):
    # Same regression as edit_source's version above, for the companion
    # upload route.
    source = vault.create_source_from_citekey(
        "smith2024", "A Great Paper", "body", zotero_key="ABC", authors=[], tags=[],
    )
    new_slug, _, _ = vault.move_node(source.slug, dest_dir="notes")

    r = client.post(f"/notes/{new_slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 200
    assert r.json()["slug"] == new_slug


def test_upload_companion_not_found(client):
    r = client.post("/notes/does-not-exist/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 404


def test_upload_companion_rejects_non_source_slug(client, vault):
    note = vault.create_note("My Note", "body")
    r = client.post(f"/notes/{note.slug}/companion",
                     files={"file": ("figure.svg", b"<svg></svg>", "image/svg+xml")})
    assert r.status_code == 400
