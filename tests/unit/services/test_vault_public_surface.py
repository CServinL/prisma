"""Unit tests for VaultService's promoted public surface — iter_files,
find_file, node_type_from_frontmatter, unique_slug, find_stream_path,
create_source_from_citekey — previously reached externally (renderer.py,
app.py, chroma_service.py, knowledge_graph_service.py) only through their
underscore-prefixed private equivalents."""
import pytest

from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import NodeType


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


class TestIterFiles:
    def test_default_extension_is_md_only(self, vault):
        vault.create_note("Note A")
        (vault.root / "sources" / "companion.html").parent.mkdir(parents=True, exist_ok=True)
        (vault.root / "sources" / "companion.html").write_text("<html></html>")

        found = {p.suffix for p in vault.iter_files()}
        assert found == {".md"}

    def test_extensions_override_finds_only_matching_files(self, vault):
        vault.create_note("Note A")
        html_dir = vault.root / "sources"
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / "companion.html").write_text("<html></html>")

        found = list(vault.iter_files(extensions=(".html",)))
        assert len(found) == 1
        assert found[0].suffix == ".html"

    def test_multiple_extensions(self, vault):
        vault.create_note("Note A")
        html_dir = vault.root / "sources"
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / "companion.html").write_text("<html></html>")

        found = {p.suffix for p in vault.iter_files(extensions=(".md", ".html"))}
        assert found == {".md", ".html"}


class TestFindFile:
    def test_finds_md_file_by_slug(self, vault):
        note = vault.create_note("My Note")
        assert vault.find_file(note.slug) == vault._find_md(note.slug)

    def test_finds_html_file_by_slug(self, vault):
        html_dir = vault.root / "sources"
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / "paper.html").write_text("<html></html>")
        found = vault.find_file("paper")
        assert found is not None
        assert found.name == "paper.html"

    def test_returns_none_when_not_found(self, vault):
        assert vault.find_file("does-not-exist") is None

    def test_finds_md_file_by_serialized_dir_slug(self, vault):
        # "sources--paper" -- the same dir--name encoding move_node()
        # returns, and what the UI's "Copy slug" button now copies.
        sources_dir = vault.root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / "paper.md").write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
        found = vault.find_file("sources--paper")
        assert found is not None
        assert found == sources_dir / "paper.md"

    def test_bare_slug_still_resolves_when_a_dir_slug_also_exists(self, vault):
        # Existing bare-name [[wiki-links]] must keep resolving exactly as
        # before -- the dir--name decode is additive, not a replacement.
        sources_dir = vault.root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / "paper.md").write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
        assert vault.find_file("paper") == sources_dir / "paper.md"


class TestGetAnyResolvesCompoundSlugs:
    # Regression: find_file() had the dir--name decode, but get_any()
    # (the real GET /notes/{slug} path) discards find_file()'s resolved
    # path after sniffing node_type, and re-resolves via get_source()/
    # get_note() -> _find_md() directly -- which didn't have the decode
    # until it moved there. A find_file()-only test wouldn't have caught
    # this; get_any() is what the API route actually calls.

    def test_get_any_resolves_a_compound_slug_for_a_source(self, vault):
        sources_dir = vault.root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / "paper.md").write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
        node = vault.get_any("sources--paper")
        assert node.slug == "paper"

    def test_get_any_resolves_a_compound_slug_for_a_note(self, vault):
        notes_dir = vault.root / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "idea.md").write_text("---\ntype: note\n---\nBody.", encoding="utf-8")
        node = vault.get_any("notes--idea")
        assert node.slug == "idea"


class TestNodeTypeFromFrontmatter:
    def test_recognized_type(self, vault):
        assert vault.node_type_from_frontmatter({"type": "source"}) == NodeType.source

    def test_missing_type_defaults_to_note(self, vault):
        assert vault.node_type_from_frontmatter({}) == NodeType.note

    def test_unrecognized_type_falls_back_to_note(self, vault):
        assert vault.node_type_from_frontmatter({"type": "not-a-real-type"}) == NodeType.note


class TestUniqueSlug:
    def test_slugifies_title(self, vault):
        assert vault.unique_slug("Deep Learning") == "deep-learning"

    def test_disambiguates_on_collision(self, vault):
        vault.create_note("Deep Learning")
        assert vault.unique_slug("Deep Learning") == "deep-learning-1"

    def test_disambiguates_repeated_collisions(self, vault):
        vault.create_note("Foo")
        vault.create_note("Foo")
        assert vault.unique_slug("Foo") == "foo-2"


class TestFindStreamPath:
    def test_finds_existing_stream(self, vault):
        stream = vault.create_stream(title="My Stream", query="q")
        path = vault.find_stream_path(stream.slug)
        assert path is not None
        assert path.suffix == ".yaml"

    def test_returns_none_when_not_found(self, vault):
        assert vault.find_stream_path("does-not-exist") is None


class TestCreateSourceFromCitekey:
    def test_creates_source_with_full_metadata(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "paper body text",
            zotero_key="ABC123", authors=["Jane Smith"], tags=["ml"],
            year=2024, doi="10.1/xyz", url="https://example.com/paper",
        )
        assert source.citekey == "smith2024"
        assert source.title == "A Great Paper"
        assert source.body == "paper body text"
        assert source.zotero_key == "ABC123"
        assert source.authors == ["Jane Smith"]
        assert source.year == 2024
        assert source.doi == "10.1/xyz"
        # ADR-020: url was previously written to frontmatter but never read
        # back by get_source() -- silently dropped on every load. This
        # assertion is the regression test for that fix.
        assert source.url == "https://example.com/paper"

    def test_omits_optional_fields_when_not_given(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=[], tags=[],
        )
        assert source.year is None
        assert source.doi is None
        assert source.url is None
        assert source.journal is None
        assert source.item_type is None

    def test_creates_source_with_apa_bibliographic_fields(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=["Jane Smith"], tags=[],
            journal="Journal of Examples", volume="12", issue="3", pages="45-67",
            publisher="Example Press", item_type="journalArticle",
        )
        assert source.journal == "Journal of Examples"
        assert source.volume == "12"
        assert source.issue == "3"
        assert source.pages == "45-67"
        assert source.publisher == "Example Press"
        assert source.item_type == "journalArticle"

    def test_slug_disambiguated_on_citekey_collision(self, vault):
        vault.create_source_from_citekey(
            "smith2024", "First", "body1", zotero_key="A", authors=[], tags=[],
        )
        second = vault.create_source_from_citekey(
            "smith2024", "Second", "body2", zotero_key="B", authors=[], tags=[],
        )
        assert second.slug == "smith2024-1"


class TestUpdateSourceBibliographicFields:
    def test_merges_new_fields_leaving_existing_ones_untouched(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "the body text",
            zotero_key="ABC123", authors=["Jane Smith"], tags=["ml"], year=2024,
        )

        updated = vault.update_source_bibliographic_fields(
            source.slug, journal="Journal of Examples", volume="12", item_type="journalArticle",
        )

        assert updated.journal == "Journal of Examples"
        assert updated.volume == "12"
        assert updated.item_type == "journalArticle"
        # untouched
        assert updated.title == "A Great Paper"
        assert updated.authors == ["Jane Smith"]
        assert updated.year == 2024
        assert updated.body == "the body text"

    def test_does_not_blank_out_fields_when_called_with_none(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=[], tags=[], journal="Original Journal",
        )

        updated = vault.update_source_bibliographic_fields(source.slug, volume="5")

        assert updated.journal == "Original Journal"
        assert updated.volume == "5"

    def test_raises_file_not_found_for_missing_slug(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.update_source_bibliographic_fields("does-not-exist", journal="X")
