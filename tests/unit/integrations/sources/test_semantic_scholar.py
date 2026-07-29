from unittest.mock import MagicMock, patch

from prisma.integrations.sources.semantic_scholar import SemanticScholarSource

_RESPONSE = {
    "data": [
        {
            "paperId": "abc123",
            "title": "A Sufficiently Long Test Paper Title About Deep Learning",
            "abstract": "This is a long enough abstract to pass the minimum length validation criteria used elsewhere in the pipeline.",
            "authors": [{"name": "Jane Doe"}],
            "venue": "NeurIPS",
            "year": 2024,
            "doi": "10.1234/abc",
            "url": "https://www.semanticscholar.org/paper/abc123",
        }
    ]
}


@patch("prisma.integrations.sources.semantic_scholar.requests.get")
def test_search_parses_papers(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: _RESPONSE)
    source = SemanticScholarSource()

    result = source.search("deep learning", limit=1)

    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.doi == "10.1234/abc"
    assert paper.journal == "NeurIPS"
    assert paper.source == "semanticscholar"


@patch("prisma.integrations.sources.semantic_scholar.requests.get")
def test_api_key_sets_header(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": []})
    source = SemanticScholarSource(api_key="secret-key")

    source.search("query", limit=1)

    _, kwargs = mock_get.call_args
    assert kwargs["headers"] == {"x-api-key": "secret-key"}


@patch("prisma.integrations.sources.semantic_scholar.requests.get")
def test_no_key_sends_no_auth_header(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": []})
    source = SemanticScholarSource()

    source.search("query", limit=1)

    _, kwargs = mock_get.call_args
    assert kwargs["headers"] == {}
