"""Unit tests for RichContent -- standalone, no prisma-domain models."""
from prisma.schema_gov import ContentFormat, RichContent


def test_defaults_to_markdown_format():
    c = RichContent(value="**bold**")
    assert c.format == ContentFormat.markdown
    assert c.rendered_html is None


def test_accepts_all_declared_formats():
    for fmt in ContentFormat:
        c = RichContent(format=fmt, value="x")
        assert c.format == fmt


def test_round_trips_through_model_dump_and_validate():
    c = RichContent(format=ContentFormat.html, value="<p>hi</p>", rendered_html="<p>hi</p>")
    restored = RichContent.model_validate(c.model_dump())
    assert restored == c
