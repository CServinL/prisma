"""Unit tests for chat_render.py -- footnote markers surviving as real,
clickable-hook elements through the markdown->HTML->sanitize pipeline."""
import pytest

from prisma.services.chat_render import render_chat_message
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_footnote_marker_becomes_a_span_with_data_index(vault):
    html = render_chat_message("Attention uses self-attention.[^1]", vault)
    assert '<span class="footnote-marker" data-footnote-index="1">1</span>' in html


def test_multiple_footnote_markers_each_get_their_own_index(vault):
    html = render_chat_message("First claim.[^1] Second claim.[^2]", vault)
    assert 'data-footnote-index="1"' in html
    assert 'data-footnote-index="2"' in html


def test_content_with_no_footnote_markers_renders_unchanged(vault):
    html = render_chat_message("Just a plain reply, no citations.", vault)
    assert "footnote-marker" not in html
    assert "Just a plain reply" in html


def test_renders_tables_and_code_blocks_in_chat_replies(vault):
    html = render_chat_message("| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\n```", vault)
    assert "<table>" in html
    assert "<code" in html


def test_strips_a_script_tag_the_model_echoed_from_tool_results(vault):
    html = render_chat_message("Some reply.\n\n<script>alert(1)</script>", vault)
    assert "<script" not in html
    assert "alert(1)" not in html
