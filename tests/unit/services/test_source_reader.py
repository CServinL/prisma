"""Unit tests for prisma.services.source_reader — bounded, addressable
reads of one vault file's raw text (no Kùzu involvement)."""
import pytest

from prisma.services.source_reader import _EXCERPT_CHARS, _MAX_SCAN_CHARS, read_source
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


# ── literal ───────────────────────────────────────────────────────────────────

def test_literal_returns_matching_lines_with_context(vault):
    body = "\n".join(f"line {i}" for i in range(20)) + "\nTARGET here\n" + "\n".join(f"tail {i}" for i in range(5))
    _write(vault, "doc", body)
    resp = read_source(vault, "doc", mode="literal", query="TARGET")
    assert resp.match_count == 1
    assert "TARGET here" in resp.text
    assert "line 19" in resp.text  # 2 lines of leading context
    assert "tail 0" in resp.text   # 2 lines of trailing context


def test_literal_marks_the_hit_line_with_a_colon(vault):
    _write(vault, "doc", "alpha\nbeta needle gamma\ndelta")
    resp = read_source(vault, "doc", mode="literal", query="needle")
    # hit line uses "N:", context lines use "N-"
    assert "2:beta needle gamma" in resp.text
    assert "1-alpha" in resp.text


def test_literal_is_literal_not_regex(vault):
    # `\d+` must match as the literal four characters, not "one or more digits".
    _write(vault, "doc", r"contains \d+ literally" + "\nv1.0\nv2.3")
    resp = read_source(vault, "doc", mode="literal", query=r"\d+")
    assert resp.match_count == 1
    assert "contains \\d+ literally" in resp.text


def test_literal_handles_regex_special_characters_safely(vault):
    _write(vault, "doc", "a (b c\nunrelated")
    resp = read_source(vault, "doc", mode="literal", query="(b c")
    assert resp.match_count == 1


def test_literal_catastrophic_backtracking_pattern_is_inert(vault):
    # Would hang for a long time under real regex interpretation; must
    # resolve instantly and simply not match, since it's treated as a
    # literal string.
    _write(vault, "doc", "a" * 40 + "!")
    resp = read_source(vault, "doc", mode="literal", query="(a+)+$")
    assert resp.match_count == 0


def test_literal_no_query_returns_nothing(vault):
    _write(vault, "doc", "content")
    resp = read_source(vault, "doc", mode="literal")
    assert resp.text == "" and resp.match_count == 0


def test_literal_not_truncated_for_a_small_result(vault):
    _write(vault, "doc", "alpha\nneedle here\ndelta")
    resp = read_source(vault, "doc", mode="literal", query="needle")
    assert resp.truncated is False


def test_literal_caps_a_single_arbitrarily_long_line(vault):
    from prisma.services.source_reader import _LITERAL_MAX_LINE_CHARS
    _write(vault, "doc", "needle " + "x" * 10_000)
    resp = read_source(vault, "doc", mode="literal", query="needle")
    assert len(resp.text) <= _LITERAL_MAX_LINE_CHARS + 20  # + the "N:" prefix
    assert resp.truncated is True


def test_literal_marks_truncated_when_total_size_budget_is_exceeded(vault):
    from prisma.services.source_reader import _LITERAL_MAX_LINE_CHARS, _LITERAL_MAX_TOTAL_CHARS
    # Exactly 20 matches (at _LITERAL_MAX_MATCHES, not over it) so the
    # match-count cap alone wouldn't trigger truncated -- each match's line
    # is near the per-line cap, spaced far enough apart that context
    # windows don't overlap, so 20 blocks' combined size reliably exceeds
    # the total-size budget on its own.
    per_line = "needle " + "y" * _LITERAL_MAX_LINE_CHARS
    lines = [per_line if i % 5 == 0 else f"filler {i}" for i in range(100)]
    _write(vault, "doc", "\n".join(lines))
    resp = read_source(vault, "doc", mode="literal", query="needle")
    assert resp.match_count == 20
    assert resp.truncated is True
    assert len(resp.text) <= _LITERAL_MAX_TOTAL_CHARS + _LITERAL_MAX_LINE_CHARS  # one block's worth of slack before the size check breaks the loop


def test_literal_marks_truncated_when_more_matches_than_shown(vault):
    lines = [f"needle {i}" if i % 2 == 0 else f"filler {i}" for i in range(50)]
    _write(vault, "doc", "\n".join(lines))
    resp = read_source(vault, "doc", mode="literal", query="needle")
    assert resp.match_count == 25
    assert resp.truncated is True


# ── oversized input ───────────────────────────────────────────────────────────

def test_section_and_literal_bound_the_file_read_and_mark_truncated(vault):
    # A heading / match past _MAX_SCAN_CHARS is treated as absent rather
    # than pulling the whole (e.g. imported PDF) document into memory -- and
    # the response says so, so a miss isn't mistaken for exhaustive.
    body = "---\ntype: note\n---\n" + ("filler\n" * ((_MAX_SCAN_CHARS // 7) + 1000))
    body += "\n## Late Heading\nlate needle here\n"
    _write(vault, "big", body)

    section = read_source(vault, "big", mode="section", query="Late Heading")
    assert section.text == "" and section.truncated is True
    literal = read_source(vault, "big", mode="literal", query="late needle")
    assert literal.match_count == 0 and literal.truncated is True


def test_section_and_literal_not_truncated_for_a_small_file(vault):
    _write(vault, "small", "---\ntype: note\n---\n## H\nbody line\n")
    assert read_source(vault, "small", mode="section", query="H").truncated is False
    assert read_source(vault, "small", mode="literal", query="body").truncated is False


def test_unknown_mode_raises(vault):
    _write(vault, "doc", "content")
    with pytest.raises(ValueError, match="unknown read mode"):
        read_source(vault, "doc", mode="bogus")
