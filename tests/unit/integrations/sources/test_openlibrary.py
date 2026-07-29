from unittest.mock import MagicMock, patch

from prisma.integrations.sources.openlibrary import OpenLibrarySource

_RESPONSE = {
    "start": 0,
    "num_found": 1,
    "docs": [
        {
            "title": "Deep Learning",
            "author_name": ["Ian Goodfellow"],
            "first_publish_year": 2016,
            "isbn": ["0262035618", "9780262035613"],
            "key": "/works/OL123W",
            "publisher": ["MIT Press"],
            "language": ["eng"],
            "subject": ["Machine learning", "Neural networks"],
        }
    ],
}


@patch("prisma.integrations.sources.openlibrary.requests.get")
def test_search_parses_docs(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: _RESPONSE)
    source = OpenLibrarySource()

    result = source.search("deep learning", limit=1)

    assert len(result.books) == 1
    book = result.books[0]
    assert book.title == "Deep Learning"
    assert book.isbn_10 == "0262035618"
    assert book.isbn_13 == "9780262035613"
    # Regression test: doc is a Pydantic model, not a dict -- a prior bug
    # called doc.get('language', ...) here, which raised AttributeError on
    # every single document and silently returned zero books in
    # production. This must read the real field, not raise.
    assert book.language == "eng"


@patch("prisma.integrations.sources.openlibrary.requests.get")
def test_sends_identifying_user_agent(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"start": 0, "num_found": 0, "docs": []})
    source = OpenLibrarySource()

    source.search("query", limit=1)

    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]


@patch("prisma.integrations.sources.openlibrary.requests.get")
def test_doc_with_no_language_returns_none(mock_get):
    docs = dict(_RESPONSE)
    docs["docs"] = [{**_RESPONSE["docs"][0], "language": []}]
    mock_get.return_value = MagicMock(status_code=200, json=lambda: docs)
    source = OpenLibrarySource()

    result = source.search("deep learning", limit=1)

    assert result.books[0].language is None
