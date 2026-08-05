"""Unit tests for the allowlist HTML sanitizer applied to every
renderer.render() output (see prisma/services/html_sanitize.py)."""
from prisma.services.html_sanitize import sanitize_html


def test_strips_script_tags():
    out = sanitize_html("<p>hi</p><script>alert(1)</script>")
    assert "<script" not in out
    assert "alert(1)" not in out


def test_strips_event_handler_attributes():
    out = sanitize_html('<img src="x" onerror="alert(1)">')
    assert "onerror" not in out
    assert "alert(1)" not in out


def test_strips_javascript_href_but_keeps_link_text():
    out = sanitize_html('<a href="javascript:alert(1)">bad</a>')
    assert "javascript:" not in out
    assert "bad" in out


def test_preserves_fragment_wikilink_and_data_citekey():
    out = sanitize_html(
        '<a class="citation" href="#source:bar" data-citekey="bar">@bar</a>'
    )
    assert 'href="#source:bar"' in out
    assert 'data-citekey="bar"' in out
    assert 'class="citation"' in out


def test_preserves_transclusion_div_and_data_slug():
    out = sanitize_html('<div class="transclusion" data-slug="baz">stuff</div>')
    assert 'data-slug="baz"' in out
    assert "stuff" in out


def test_preserves_codehilite_syntax_highlight_spans():
    out = sanitize_html('<div class="codehilite"><span class="k">def</span></div>')
    assert 'class="k"' in out


def test_preserves_tables():
    out = sanitize_html("<table><tr><td>cell</td></tr></table>")
    assert "<table" in out
    assert "cell" in out


def test_allows_plain_http_links():
    out = sanitize_html('<a href="https://example.com">link</a>')
    assert 'href="https://example.com"' in out
