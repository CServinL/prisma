"""Unit tests for prisma.services.asset_rewrite — asset_prefix and rewrite_html.

Previously this rewriting logic lived inline in three FastAPI route
handlers (get_note's two .html branches, view_html) and could only be
exercised through a full HTTP request. Extracting it to pure functions
makes it directly testable, closing that coverage gap.
"""
from pathlib import Path

from prisma.services.asset_rewrite import asset_prefix, rewrite_html


class TestAssetPrefix:
    def test_nested_subdir(self):
        root = Path("/vault")
        file_path = root / "sources" / "paper.html"
        assert asset_prefix(root, file_path, "http://host:8765/") == "http://host:8765/vault/assets/sources/"

    def test_file_directly_in_root(self):
        root = Path("/vault")
        file_path = root / "paper.html"
        assert asset_prefix(root, file_path, "http://host:8765/") == "http://host:8765/vault/assets/"

    def test_file_not_under_root_falls_back_to_root_prefix(self):
        root = Path("/vault")
        file_path = Path("/elsewhere/paper.html")
        assert asset_prefix(root, file_path, "http://host:8765/") == "http://host:8765/vault/assets/"


class TestRewriteHtmlMarkdownMode:
    def test_rewrites_relative_asset_extension_src(self):
        html = '<img src="figure1.png">'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="markdown")
        assert out == '<img src="http://h/vault/assets/sub/figure1.png">'

    def test_leaves_non_asset_extension_src_untouched(self):
        html = '<img src="figure1.pdf">'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="markdown")
        assert out == html

    def test_leaves_absolute_and_data_urls_untouched(self):
        html = '<img src="https://example.com/a.png"><img src="data:image/png;base64,xx.png">'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="markdown")
        assert out == html

    def test_leaves_root_relative_untouched(self):
        html = '<img src="/already/absolute/path.png">'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="markdown")
        assert out == html


class TestRewriteHtmlFragmentMode:
    def test_rewrites_src_and_href_regardless_of_extension(self):
        html = '<img src="figure1.png"><a href="notes.html">link</a>'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="fragment")
        assert out == (
            '<img src="http://h/vault/assets/sub/figure1.png">'
            '<a href="http://h/vault/assets/sub/notes.html">link</a>'
        )

    def test_skips_mailto_and_tel(self):
        html = '<a href="mailto:a@b.com">mail</a><a href="tel:+123">call</a>'
        out = rewrite_html(html, "http://h/vault/assets/sub/", mode="fragment")
        assert out == html


class TestRewriteHtmlFullMode:
    def test_rewrites_standard_attributes(self):
        html = '<img src="a.png"><a href="b.html"><form action="c"><video poster="d.jpg"><object data="e.svg">'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert 'src="http://h/vault/assets/a.png"' in out
        assert 'href="http://h/vault/assets/b.html"' in out
        assert 'action="http://h/vault/assets/c"' in out
        assert 'poster="http://h/vault/assets/d.jpg"' in out
        assert 'data="http://h/vault/assets/e.svg"' in out

    def test_rewrites_srcset_each_entry_keeping_descriptors(self):
        html = '<img srcset="a.png 1x, sub/b.png 2x">'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert out == '<img srcset="http://h/vault/assets/a.png 1x, http://h/vault/assets/sub/b.png 2x">'

    def test_rewrites_css_url(self):
        html = '<style>.x { background: url(bg.png); }</style>'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert 'url(http://h/vault/assets/bg.png)' in out

    def test_rewrites_json_string_asset_paths(self):
        html = '<script>var x = {"icon": "icon.svg"};</script>'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert '"icon": "http://h/vault/assets/icon.svg"' in out

    def test_webkitgtk_xlink_href_data_fixup(self):
        html = '<image xlink:href="data:image/png;base64,xx"/>'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert out == '<image href="data:image/png;base64,xx"/>'

    def test_leaves_absolute_urls_untouched(self):
        html = '<a href="https://example.com/x"><img src="//cdn.example.com/y.png">'
        out = rewrite_html(html, "http://h/vault/assets/", mode="full")
        assert out == html
