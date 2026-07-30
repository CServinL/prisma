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

    def test_omits_optional_fields_when_not_given(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=[], tags=[],
        )
        assert source.year is None
        assert source.doi is None

    def test_slug_disambiguated_on_citekey_collision(self, vault):
        vault.create_source_from_citekey(
            "smith2024", "First", "body1", zotero_key="A", authors=[], tags=[],
        )
        second = vault.create_source_from_citekey(
            "smith2024", "Second", "body2", zotero_key="B", authors=[], tags=[],
        )
        assert second.slug == "smith2024-1"
