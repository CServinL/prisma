"""Unit tests for services/renderer.py's markdown -> HTML pipeline --
wikilink/citation/transclusion resolution, and (2026-08-04) that its output
is routed through html_sanitize.sanitize_html before ever reaching a
caller's {@html}."""
import pytest

from prisma.services.renderer import render
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_render_basic_markdown_to_html(vault):
    html, broken_links, broken_citations = render("# Title\n\nSome **bold** text.", vault)
    assert "<h1" in html
    assert "<strong>bold</strong>" in html
    assert broken_links == []
    assert broken_citations == []


def test_render_tables_and_fenced_code(vault):
    html, _, _ = render("| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\n```", vault)
    assert "<table>" in html
    assert "<code" in html


def test_render_resolves_existing_wikilink(vault):
    vault.create_note(title="Other Note", body="content")
    html, broken_links, _ = render("See [[other-note]] for details.", vault)
    assert 'class="wikilink"' in html
    assert 'href="#note:other-note"' in html
    assert broken_links == []


def test_render_reports_broken_wikilink(vault):
    html, broken_links, _ = render("See [[does-not-exist]] for details.", vault)
    assert broken_links == ["does-not-exist"]
    assert "broken-wikilink" in html


def test_render_resolves_a_vault_uri_wikilink(vault):
    # ADR-021's copy/paste interchange form -- what "Copy slug" now
    # produces -- must itself work as a pasted-back [[wiki-link]].
    sources_dir = vault.root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "paper.md").write_text("---\ntype: source\n---\nBody.", encoding="utf-8")
    html, broken_links, _ = render("See [[vault:/sources/paper]] for details.", vault)
    assert broken_links == []
    assert 'href="#note:sources--paper"' in html
    # The visible label keeps the vault: form the author actually typed.
    assert ">vault:/sources/paper<" in html


def test_render_strips_a_script_tag_embedded_in_note_body(vault):
    # Python-Markdown passes raw inline HTML through untouched by design --
    # this is exactly what html_sanitize.sanitize_html exists to catch
    # before the result ever reaches {@html} in the UI.
    html, _, _ = render("Some text.\n\n<script>alert(1)</script>\n\nMore text.", vault)
    assert "<script" not in html
    assert "alert(1)" not in html


def test_render_strips_event_handler_attribute_embedded_in_note_body(vault):
    html, _, _ = render('<img src="x" onerror="alert(1)">', vault)
    assert "onerror" not in html
