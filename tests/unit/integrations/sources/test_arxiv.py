from unittest.mock import MagicMock, patch

from prisma.integrations.sources.arxiv import ArxivSource

_ATOM_FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/test.123</id>
    <title>A Sufficiently Long Test Paper Title About Machine Learning</title>
    <summary>This is a long enough abstract to pass the minimum length validation criteria used elsewhere in the pipeline for academic content.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Test Author</name></author>
  </entry>
</feed>'''


@patch("prisma.integrations.sources.arxiv.requests.get")
def test_search_parses_entries(mock_get):
    mock_response = MagicMock(status_code=200, content=_ATOM_FEED)
    mock_get.return_value = mock_response

    source = ArxivSource()
    result = source.search("machine learning", limit=1)

    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.arxiv_id == "test.123"
    assert paper.source == "arxiv"
    assert paper.journal == "arXiv"  # so centralized validation sees a venue
    assert result.books == []


@patch("prisma.integrations.sources.arxiv.requests.get")
def test_search_returns_empty_on_http_error(mock_get):
    mock_get.side_effect = Exception("network down")
    source = ArxivSource()
    result = source.search("test", limit=1)
    assert result.papers == []
    assert result.books == []


@patch("prisma.integrations.sources.arxiv.requests.get")
def test_rate_limiter_denial_skips_the_call(mock_get):
    source = ArxivSource()
    source._limiter.acquire = MagicMock(return_value=False)
    result = source.search("test", limit=1)
    assert result.papers == []
    mock_get.assert_not_called()
