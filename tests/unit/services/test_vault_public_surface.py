"""Unit tests for VaultService's promoted public surface — iter_files,
find_file, node_type_from_frontmatter, unique_slug, find_stream_path,
create_source_from_citekey — previously reached externally (renderer.py,
app.py, chroma_service.py, knowledge_graph_service.py) only through their
underscore-prefixed private equivalents."""
from pathlib import Path

import pytest

from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import NodeType, SourceKind, SourceOrigin


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

    def test_slug_for_relpath_round_trips_through_find_file_for_a_nested_path(self, vault):
        # slug_for_relpath() is the encode counterpart of the dir--name decode
        # in _resolve_compound_slug()/_find_md(); the two must stay inverses,
        # including for a path more than one directory deep.
        nested_dir = vault.root / "sources" / "archive"
        nested_dir.mkdir(parents=True, exist_ok=True)
        md = nested_dir / "paper.md"
        md.write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
        rel = md.relative_to(vault.root)

        slug = vault.slug_for_relpath(rel)

        assert slug == "sources--archive--paper"
        assert vault.find_file(slug) == md
        assert vault._resolve_compound_slug(slug, ".md") == md

    def test_slug_for_relpath_round_trips_for_a_dotted_filename(self, vault):
        # `paper.v1.md` encodes to `sources--paper.v1`; the decode must not
        # rewrite the trailing `.v1` as a suffix and collapse the file to
        # `sources/paper.md`.
        sources_dir = vault.root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        md = sources_dir / "paper.v1.md"
        md.write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
        rel = md.relative_to(vault.root)

        slug = vault.slug_for_relpath(rel)

        assert slug == "sources--paper.v1"
        assert vault.find_file(slug) == md
        assert vault._resolve_compound_slug(slug, ".md") == md

    def test_compound_slug_cannot_escape_vault_root_via_dotdot(self, vault, tmp_path):
        # vault.root is tmp_path/"vault"; "..--secret" decodes via
        # .replace("--", "/") to "../secret", landing exactly at
        # tmp_path/"secret.md" -- one level above vault.root, where this
        # test actually plants the file.
        outside = tmp_path / "secret.md"
        outside.write_text("---\ntype: note\n---\nleaked", encoding="utf-8")
        assert vault.find_file("..--secret") is None

    def test_compound_slug_of_bare_separator_does_not_raise(self, vault):
        assert vault.find_file("--") is None

    def test_compound_slug_resolving_to_a_directory_is_not_returned_as_a_file(self, vault):
        # A directory literally named "notes.md" -- exists() is True for it,
        # so read_source() would open() a directory and 500. is_file() must
        # reject it, degrading to the intended 404.
        (vault.root / "wiki" / "page.md").mkdir(parents=True, exist_ok=True)
        assert vault._resolve_compound_slug("wiki--page", ".md") is None
        assert vault.find_file("wiki--page") is None

    def test_compound_slug_cannot_escape_vault_root_via_leading_separator(self, vault):
        # "--etc--passwd" decodes to "/etc/passwd" -- Path's own / operator
        # discards the left operand entirely when the right side is
        # absolute, so self.root / "/etc/passwd" would otherwise silently
        # become Path("/etc/passwd") rather than staying inside the vault.
        assert vault.find_file("--etc--passwd") is None

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


class TestFrontmatterForRelpath:
    def test_reads_year_from_a_nested_relative_path(self, vault):
        (vault.root / "sources").mkdir(parents=True, exist_ok=True)
        (vault.root / "sources" / "paper.md").write_text(
            "---\ntype: source\nyear: 2018\n---\nBody.", encoding="utf-8")
        assert vault.frontmatter_for_relpath("sources/paper.md")["year"] == 2018

    def test_missing_file_is_empty(self, vault):
        assert vault.frontmatter_for_relpath("sources/nope.md") == {}

    def test_cannot_escape_the_vault_root(self, vault, tmp_path):
        (tmp_path / "outside.md").write_text("---\nyear: 1999\n---\nx", encoding="utf-8")
        assert vault.frontmatter_for_relpath("../outside.md") == {}


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

    def test_year_zero_is_not_silently_dropped_at_creation(self, vault):
        # Same falsy-zero bug class fixed on the update side
        # (test_year_zero_is_not_silently_dropped below) -- must agree, or
        # POST /notes/sources and PATCH /{slug}/source disagree on whether
        # year=0 sticks for the identical field.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[], year=0,
        )
        assert source.year == 0

    def test_slug_disambiguated_on_citekey_collision(self, vault):
        vault.create_source_from_citekey(
            "smith2024", "First", "body1", zotero_key="A", authors=[], tags=[],
        )
        second = vault.create_source_from_citekey(
            "smith2024", "Second", "body2", zotero_key="B", authors=[], tags=[],
        )
        assert second.slug == "smith2024-1"

    def test_origin_defaults_to_zotero_when_zotero_key_given(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        assert source.origin == SourceOrigin.zotero

    def test_creates_upload_source_with_no_zotero_key(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key=None, origin=SourceOrigin.upload, authors=[], tags=[],
        )
        assert source.zotero_key is None
        assert source.origin == SourceOrigin.upload
        # Not just None after parsing -- the key must be absent from the
        # raw frontmatter entirely, not written as `zotero_key: null`.
        raw = source.path.read_text(encoding="utf-8")
        assert "zotero_key" not in raw

    def test_source_kind_round_trips(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=[], tags=[], source_kind=SourceKind.web,
        )
        assert vault.get_source(source.slug).source_kind == SourceKind.web

    def test_source_kind_defaults_to_paper_when_absent_from_frontmatter(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        # Not written to frontmatter at all for the default -- only a
        # non-default source_kind gets persisted (see create_source_from_
        # citekey). Confirms get_source() still falls back correctly.
        raw = source.path.read_text(encoding="utf-8")
        assert "source_kind" not in raw
        assert vault.get_source(source.slug).source_kind == SourceKind.paper

    def test_unrecognized_origin_falls_back_instead_of_raising(self, vault):
        # Same defensive-fallback contract as VaultService.node_type_from_
        # frontmatter() (an unrecognized `type:` value degrades to `note`
        # rather than crashing the read) -- origin/source_kind must do the
        # same for a hand-edited or forward-incompatible frontmatter value,
        # or GET /notes/{slug} 500s for that one node instead of degrading.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        raw = source.path.read_text(encoding="utf-8")
        source.path.write_text(raw.replace("origin: zotero", "origin: some-future-value"), encoding="utf-8")
        assert vault.get_source(source.slug).origin == SourceOrigin.zotero

    def test_unrecognized_source_kind_falls_back_instead_of_raising(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=[], tags=[], source_kind=SourceKind.web,
        )
        raw = source.path.read_text(encoding="utf-8")
        source.path.write_text(raw.replace("source_kind: web", "source_kind: some-future-value"), encoding="utf-8")
        assert vault.get_source(source.slug).source_kind == SourceKind.paper


class TestCitekeyExists:
    def test_true_for_an_existing_citekey(self, vault):
        vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        assert vault.citekey_exists("smith2024") is True

    def test_false_for_an_unused_citekey(self, vault):
        assert vault.citekey_exists("nobody2099") is False

    def test_finds_citekey_even_with_a_large_body(self, vault):
        # citekey_exists() reads only each file's head (_CITEKEY_SCAN_READ_
        # BYTES), not the whole file -- it runs inside create_source_from_
        # citekey_if_free()'s lock, so a full-body read per file would
        # serialize every manual create behind a scan whose cost scales
        # with total vault content, not just file count. This confirms the
        # bound doesn't break detection: frontmatter is always at the start
        # of the file, so a body far larger than the bound (e.g. a full
        # PDF-extracted paper) doesn't hide the citekey.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "x" * 50_000, zotero_key="ABC123", authors=[], tags=[],
        )
        assert vault.citekey_exists("smith2024") is True

    def test_finds_citekey_even_with_a_huge_frontmatter_block(self, vault):
        # Regression: the bound used to be _FRONTMATTER_READ_BYTES (8192),
        # copied from frontmatter_for_relpath()'s best-effort use case where
        # silently degrading on overflow is fine. Here it isn't -- a long
        # author list can push the frontmatter block itself (not just the
        # body) past that, truncating mid-YAML so _parse_frontmatter can't
        # find the closing '---' and returns {}, silently reporting an
        # in-use citekey as free and letting a real collision through
        # despite create_source_from_citekey_if_free()'s lock.
        huge_authors = [f"Author Number {i}" for i in range(500)]
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=huge_authors, tags=[],
        )
        raw = source.path.read_text(encoding="utf-8")
        frontmatter_end = raw.index("\n---", 3) + 4
        assert frontmatter_end > 8192  # confirms this actually exercises the old, too-small bound
        assert vault.citekey_exists("smith2024") is True


class TestCreateSourceFromCitekeyIfFree:
    def test_raises_on_collision(self, vault):
        vault.create_source_from_citekey_if_free(
            "smith2024", "First", "body1", zotero_key="A", authors=[], tags=[],
        )
        with pytest.raises(ValueError):
            vault.create_source_from_citekey_if_free(
                "smith2024", "Second", "body2", zotero_key="B", authors=[], tags=[],
            )

    def test_concurrent_creates_with_the_same_citekey_lock_out_one_of_them(self, vault, monkeypatch):
        # A purely sequential duplicate-citekey test (test_raises_on_collision
        # above) passes identically whether or not _source_write_lock exists
        # at all -- it never has two requests in flight together, so it can't
        # prove the TOCTOU race is actually closed. This widens the window
        # between the check and the write (real file I/O in both already
        # releases the GIL, so genuine OS-thread interleaving is possible
        # even without this, just not reliably reproducible on demand) and
        # asserts exactly one of two truly concurrent callers wins.
        import threading
        import time

        real_citekey_exists = VaultService.citekey_exists

        def slow_citekey_exists(self, citekey):
            result = real_citekey_exists(self, citekey)
            time.sleep(0.05)
            return result

        monkeypatch.setattr(VaultService, "citekey_exists", slow_citekey_exists)

        results: list[str] = []

        def worker():
            try:
                vault.create_source_from_citekey_if_free(
                    "smith2024", "A Great Paper", "body", zotero_key="X", authors=[], tags=[],
                )
                results.append("created")
            except ValueError:
                results.append("rejected")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["created", "rejected"]


class TestAttachSourceCompanion:
    def test_attaches_svg_without_touching_body(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "original body", zotero_key="ABC123", authors=[], tags=[],
        )
        updated = vault.attach_source_companion(source.slug, "figure.svg", b"<svg></svg>")
        assert updated.original_ext == ".svg"
        assert updated.body == "original body"

    def test_attaches_html_and_reaches_ensure_md_format(self, vault):
        # Real docu_craft HTML->MD conversion, same non-committal assertion
        # style as test_notes_routes.py's test_generate_md_format_creates_
        # companion -- whether the body actually gets populated depends on
        # docu_craft's own conversion succeeding for this snippet, not this
        # method's concern to assert on. What matters: the companion file
        # exists, original_ext updates, and the call doesn't raise.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "", zotero_key="ABC123", authors=[], tags=[],
        )
        updated = vault.attach_source_companion(source.slug, "paper.html", b"<html><body>hi</body></html>")
        assert updated.original_ext == ".html"

    def test_rejects_unsupported_extension(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        with pytest.raises(ValueError):
            vault.attach_source_companion(source.slug, "archive.zip", b"data")

    def test_replacing_extension_removes_stale_companion(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "figure.svg", b"<svg></svg>")
        vault.attach_source_companion(source.slug, "figure.jpg", b"\xff\xd8\xff")
        updated = vault.get_source(source.slug)
        assert updated.original_ext == ".jpg"
        assert vault.find_companion(source.slug).suffix == ".jpg"

    def test_raises_file_not_found_for_missing_slug(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.attach_source_companion("does-not-exist", "figure.svg", b"<svg></svg>")

    def test_replacing_extension_preserves_old_companion_if_write_fails(self, vault, monkeypatch):
        # Regression: the old companion was unlinked BEFORE the new bytes
        # were written -- a write failure between the two (disk full,
        # permission error, killed mid-write) left the Source with no
        # companion at all instead of the original, untouched one.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "figure.svg", b"<svg></svg>")
        old_companion = vault.find_companion(source.slug)
        assert old_companion.suffix == ".svg"

        def boom(self, data):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_bytes", boom)
        with pytest.raises(OSError):
            vault.attach_source_companion(source.slug, "figure.jpg", b"\xff\xd8\xff")
        assert old_companion.exists(), "old companion must survive a failed replacement write"

    def test_same_extension_reupload_preserves_old_companion_if_write_fails(self, vault, monkeypatch):
        # Regression: the cross-extension fix above only reordered unlink
        # vs. write -- it did nothing for the (more common) same-extension
        # case, e.g. re-uploading a corrected paper.pdf over an existing
        # paper.pdf. There, companion_path IS the existing file, so writing
        # straight to it truncates it immediately; a failure mid-write left
        # the original destroyed (empty/corrupt), not "untouched" as the
        # adjacent comment claimed.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "paper.pdf", b"original pdf bytes v1")
        companion = vault.find_companion(source.slug)
        assert companion.suffix == ".pdf"

        # A bare raise-only stub wouldn't reproduce the real bug: real
        # write_bytes() opens the target in "wb" (truncating immediately)
        # before the write can fail, so the fake must truncate too, or this
        # test would pass even against the unfixed code.
        original_write_bytes = Path.write_bytes

        def boom(self, data):
            original_write_bytes(self, b"")
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_bytes", boom)
        with pytest.raises(OSError):
            vault.attach_source_companion(source.slug, "paper.pdf", b"corrected pdf bytes v2")
        assert companion.read_bytes() == b"original pdf bytes v1", (
            "a failed re-upload must not destroy the existing companion"
        )

    def test_first_attach_does_not_clobber_a_hand_typed_body(self, vault, monkeypatch):
        # Regression: force=True was passed unconditionally, even on a
        # FIRST attachment (existing is None) -- overwriting the exact
        # kind of genuinely hand-typed body (a manually created Source's
        # own prose, or one synthesized at Zotero-import time from the
        # abstract when no PDF was available) that ensure_md_format()'s
        # empty-body-only gate exists to protect everywhere else it's used.
        monkeypatch.setattr("prisma.services.vault.pdf_bytes_to_md", lambda data: "extracted text")
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "hand-typed body, no companion yet",
            zotero_key="ABC123", authors=[], tags=[],
        )
        updated = vault.attach_source_companion(source.slug, "paper.pdf", b"pdf bytes")
        assert updated.body == "hand-typed body, no companion yet"

    def test_first_pdf_attach_after_a_non_extraction_companion_does_not_clobber(self, vault, monkeypatch):
        # Regression: is_replace was set whenever ANY prior companion
        # existed, not only when the prior one was itself extraction-
        # relevant (.pdf/.html/.htm) -- a .jpg cover attached first never
        # ran extraction, so the following .pdf attach is still a FIRST
        # real extraction, not a refresh; treating it as a "replace" forced
        # through the empty-body-only gate and clobbered the hand-typed body.
        monkeypatch.setattr("prisma.services.vault.pdf_bytes_to_md", lambda data: "extracted text")
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "My own hand-typed summary.",
            zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "cover.jpg", b"\xff\xd8\xff")
        updated = vault.attach_source_companion(source.slug, "paper.pdf", b"pdf bytes")
        assert updated.body == "My own hand-typed summary."

    def test_replacing_a_pdf_companion_reextracts_the_body(self, vault, monkeypatch):
        # Regression: attach_source_companion() originally called
        # ensure_md_format() without force=True, which only fills an EMPTY
        # body -- so re-uploading a corrected PDF after the first extraction
        # already populated the body silently kept serving the stale first
        # extraction forever. docu_craft's real pdf/html conversion isn't
        # installed in this dev venv (confirmed: both raise ModuleNotFound
        # for fitz/beautifulsoup4 and degrade to "", which would mask this
        # entirely), so pdf_bytes_to_md is monkeypatched here to control its
        # return value directly and actually exercise the force-vs-not gate.
        calls = iter(["first extracted text", "second extracted text"])
        monkeypatch.setattr("prisma.services.vault.pdf_bytes_to_md", lambda data: next(calls))
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "paper.pdf", b"pdf bytes v1")
        assert vault.get_source(source.slug).body == "first extracted text"
        vault.attach_source_companion(source.slug, "paper.pdf", b"pdf bytes v2")
        assert vault.get_source(source.slug).body == "second extracted text"

    def test_reuploading_identical_bytes_does_not_reextract(self, vault, monkeypatch):
        calls = []
        monkeypatch.setattr("prisma.services.vault.pdf_bytes_to_md", lambda data: calls.append(data) or "extracted once")
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "paper.pdf", b"identical bytes")
        assert len(calls) == 1
        vault.attach_source_companion(source.slug, "paper.pdf", b"identical bytes")
        assert len(calls) == 1  # not called a second time -- byte-identical re-upload is a no-op

    def test_differently_sized_reupload_skips_reading_the_old_companion(self, vault, monkeypatch):
        # A differently-sized upload can never be byte-identical -- checking
        # size first avoids reading the whole old companion into memory just
        # to prove two objects of different length aren't equal, doubling
        # peak memory on every meaningfully-changed large-file re-upload.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "", zotero_key="ABC123", authors=[], tags=[],
        )
        vault.attach_source_companion(source.slug, "figure.jpg", b"\xff\xd8\xff old")

        def boom(self):
            raise AssertionError("must not read the old companion when sizes differ")

        monkeypatch.setattr(Path, "read_bytes", boom)
        vault.attach_source_companion(source.slug, "figure.jpg", b"\xff\xd8\xff a much longer new image")


class TestEnsureMdFormatCleansUpOnFailure:
    def test_temp_file_is_removed_when_docu_craft_render_raises(self, vault, monkeypatch, tmp_path):
        # Regression: NamedTemporaryFile(delete=False) creates the temp
        # file before _dc_render() runs; the old code only unlinked it on
        # the success path, so a render failure leaked it. Made worse by
        # attach_source_companion()'s force=True: a user retrying a
        # failing companion upload now leaked one temp file per retry, not
        # just once.
        import tempfile as tempfile_module

        created: list[Path] = []
        real_ntf = tempfile_module.NamedTemporaryFile

        def recording_ntf(*args, **kwargs):
            tf = real_ntf(*args, **kwargs)
            created.append(Path(tf.name))
            return tf

        monkeypatch.setattr(tempfile_module, "NamedTemporaryFile", recording_ntf)
        monkeypatch.setattr("docu_craft.render", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

        companion = vault.default_dirs[NodeType.source] / "paper.html"
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_text("<html><body>hi</body></html>", encoding="utf-8")

        result = vault.ensure_md_format(companion)

        assert result is False
        assert len(created) == 1
        assert not created[0].exists()


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

    def test_merges_title_authors_year_doi_tags(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "Original Title", "body",
            zotero_key="ABC123", authors=["Jane Smith"], tags=["ml"],
            year=2020, journal="Original Journal",
        )

        updated = vault.update_source_bibliographic_fields(
            source.slug, title="New Title", authors=["Jane Smith", "Bob Jones"],
            year=2024, doi="10.1/new", tags=["ml", "nlp"],
        )

        assert updated.title == "New Title"
        assert updated.authors == ["Jane Smith", "Bob Jones"]
        assert updated.year == 2024
        assert updated.doi == "10.1/new"
        assert updated.tags == ["ml", "nlp"]
        # journal was set at creation and not passed to this update call --
        # must stay untouched, same merge-only-given-fields guarantee the
        # original 7-field version already had.
        assert updated.journal == "Original Journal"

    def test_source_kind_is_editable_after_creation(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        assert source.source_kind == SourceKind.paper
        updated = vault.update_source_bibliographic_fields(source.slug, source_kind=SourceKind.web)
        assert updated.source_kind == SourceKind.web

    def test_explicit_empty_string_clears_doi(self, vault):
        # doi uses `is not None` too (it's in the same new-field group as
        # authors/tags/title/year) -- an explicit "" must actually clear it,
        # matching the UI's edit-metadata dialog, which relies on this to
        # let a user blank out a wrong DOI (see +page.svelte's
        # submitSourceForm() comment on why doi isn't converted to null on
        # blank the way url/journal/etc. are).
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[], doi="10.1/wrong",
        )
        updated = vault.update_source_bibliographic_fields(source.slug, doi="")
        assert updated.doi == ""

    def test_citekey_is_not_an_accepted_parameter(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[],
        )
        with pytest.raises(TypeError):
            vault.update_source_bibliographic_fields(source.slug, citekey="hijacked2024")

    def test_explicit_empty_authors_and_tags_actually_clear_them(self, vault):
        # authors/tags use `is not None`, not the original 7 fields' truthy
        # check -- an explicit [] from the edit route means "clear it," a
        # real edit action, not "field wasn't given."
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=["Jane Smith"], tags=["ml"],
        )
        updated = vault.update_source_bibliographic_fields(source.slug, authors=[], tags=[])
        assert updated.authors == []
        assert updated.tags == []

    def test_omitting_authors_leaves_it_untouched(self, vault):
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body",
            zotero_key="ABC123", authors=["Jane Smith"], tags=[],
        )
        updated = vault.update_source_bibliographic_fields(source.slug, doi="10.1/x")
        assert updated.authors == ["Jane Smith"]

    def test_year_zero_is_not_silently_dropped(self, vault):
        # year uses `is not None` too, unlike the original 7 fields' `if
        # value:` -- a falsy-but-meaningful value must actually take effect,
        # not silently no-op.
        source = vault.create_source_from_citekey(
            "smith2024", "A Great Paper", "body", zotero_key="ABC123", authors=[], tags=[], year=2020,
        )
        updated = vault.update_source_bibliographic_fields(source.slug, year=0)
        assert updated.year == 0


class TestMoveNodeRejectsPathTraversal:
    # Regression: move_node()'s own ad hoc guard only rejected ".." components
    # via `".." in Path(dest_dir).parts`, never `Path(dest_dir).is_absolute()`.
    # `self.root / "/etc/cron.d"` discards the left operand entirely (Python's
    # PurePath truediv semantics for an absolute right operand), so an
    # absolute dest_dir sailed straight through to `dest.mkdir(...)` and
    # `path.rename(new_path)`, physically moving the file outside the vault.
    def test_absolute_dest_dir_is_rejected(self, vault, tmp_path):
        note = vault.create_note("Note A")
        outside = tmp_path / "outside"

        with pytest.raises(ValueError):
            vault.move_node(note.slug, dest_dir=str(outside))

        assert not outside.exists()
        assert vault.find_file(note.slug) is not None

    def test_dotdot_dest_dir_is_still_rejected(self, vault):
        note = vault.create_note("Note A")

        with pytest.raises(ValueError):
            vault.move_node(note.slug, dest_dir="../../escaped")

    def test_relative_dest_dir_still_moves_the_file(self, vault):
        note = vault.create_note("Note A")

        new_slug, old_rel, new_rel = vault.move_node(note.slug, dest_dir="sources")

        assert (vault.root / new_rel).exists()
        assert new_rel.startswith("sources/")


class TestCreateDirRejectsPathTraversal:
    def test_absolute_path_is_rejected(self, vault, tmp_path):
        outside = tmp_path / "outside"

        with pytest.raises(ValueError):
            vault.create_dir(str(outside))

        assert not outside.exists()

    def test_dotdot_path_is_still_rejected(self, vault):
        with pytest.raises(ValueError):
            vault.create_dir("../../escaped")

    def test_relative_path_still_creates_the_dir(self, vault):
        vault.create_dir("notes/subdir")

        assert (vault.root / "notes" / "subdir").is_dir()
