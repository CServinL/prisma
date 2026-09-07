"""Unit tests for prisma.services.source_reader — bounded, addressable
reads of one vault file's raw text (no Kùzu involvement)."""
import pytest

from prisma.services.source_reader import _EXCERPT_CHARS, read_source
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def _write(vault, slug, body):
    p = vault.root / "notes" / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary_returns_leading_excerpt(vault):
    _write(vault, "doc", "---\ntype: note\n---\n" + "A" * 5000)
    resp = read_source(vault, "doc")
    assert resp.mode == "summary"
    assert len(resp.text) == _EXCERPT_CHARS


def test_summary_is_default_mode(vault):
    _write(vault, "doc", "hello world")
    assert read_source(vault, "doc").mode == "summary"
    assert read_source(vault, "doc").text == "hello world"


def test_missing_slug_raises(vault):
    with pytest.raises(FileNotFoundError):
        read_source(vault, "nope")


# ── section ───────────────────────────────────────────────────────────────────

_SECTIONED = (
    "---\ntype: note\n---\n"
    "intro prose\n\n"
    "## Methods\nWe used a closed-form update.\n\n"
    "## Results\nAccuracy improved.\n"
)


def test_section_returns_matching_heading_body(vault):
    _write(vault, "doc", _SECTIONED)
    resp = read_source(vault, "doc", mode="section", query="results")
    assert "Accuracy improved." in resp.text
    assert "closed-form update" not in resp.text
    assert resp.available_sections == ["Methods", "Results"]


def test_section_case_insensitive_substring_match(vault):
    _write(vault, "doc", _SECTIONED)
    resp = read_source(vault, "doc", mode="section", query="METH")
    assert "closed-form update" in resp.text


def test_section_miss_returns_empty_text_with_heading_list(vault):
    _write(vault, "doc", _SECTIONED)
    resp = read_source(vault, "doc", mode="section", query="discussion")
    assert resp.text == ""
    assert resp.available_sections == ["Methods", "Results"]


def test_section_no_query_lists_headings_only(vault):
    _write(vault, "doc", _SECTIONED)
    resp = read_source(vault, "doc", mode="section")
    assert resp.text == ""
    assert resp.available_sections == ["Methods", "Results"]


# ── ripgrep ───────────────────────────────────────────────────────────────────

def test_ripgrep_returns_matching_lines_with_context(vault):
    body = "\n".join(f"line {i}" for i in range(20)) + "\nTARGET here\n" + "\n".join(f"tail {i}" for i in range(5))
    _write(vault, "doc", body)
    resp = read_source(vault, "doc", mode="ripgrep", query="TARGET")
    assert resp.match_count == 1
    assert "TARGET here" in resp.text
    assert "line 19" in resp.text  # 2 lines of leading context
    assert "tail 0" in resp.text   # 2 lines of trailing context


def test_ripgrep_marks_the_hit_line_with_a_colon(vault):
    _write(vault, "doc", "alpha\nbeta needle gamma\ndelta")
    resp = read_source(vault, "doc", mode="ripgrep", query="needle")
    # hit line uses "N:", context lines use "N-"
    assert "2:beta needle gamma" in resp.text
    assert "1-alpha" in resp.text


def test_ripgrep_is_literal_not_regex(vault):
    # Security fix (PR #104 review): regex interpretation was removed --
    # Python's stdlib `re` has no execution timeout, and `query` is
    # REST-caller-controlled, so a catastrophic-backtracking pattern could
    # hang a worker. `\d+` must be matched as the literal four characters,
    # not "one or more digits".
    _write(vault, "doc", r"contains \d+ literally" + "\nv1.0\nv2.3")
    resp = read_source(vault, "doc", mode="ripgrep", query=r"\d+")
    assert resp.match_count == 1
    assert "contains \\d+ literally" in resp.text


def test_ripgrep_handles_regex_special_characters_safely(vault):
    _write(vault, "doc", "a (b c\nunrelated")
    resp = read_source(vault, "doc", mode="ripgrep", query="(b c")
    assert resp.match_count == 1


def test_ripgrep_catastrophic_backtracking_pattern_is_inert(vault):
    # Would hang for a long time under real regex interpretation; must
    # resolve instantly and simply not match, since it's treated as a
    # literal string.
    _write(vault, "doc", "a" * 40 + "!")
    resp = read_source(vault, "doc", mode="ripgrep", query="(a+)+$")
    assert resp.match_count == 0


def test_ripgrep_no_query_returns_nothing(vault):
    _write(vault, "doc", "content")
    resp = read_source(vault, "doc", mode="ripgrep")
    assert resp.text == "" and resp.match_count == 0


# ── unknown mode ──────────────────────────────────────────────────────────────

def test_unknown_mode_raises(vault):
    _write(vault, "doc", "content")
    with pytest.raises(ValueError, match="unknown read mode"):
        read_source(vault, "doc", mode="bogus")
