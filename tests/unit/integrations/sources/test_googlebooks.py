from unittest.mock import MagicMock, patch

from prisma.integrations.sources.googlebooks import GoogleBooksSource

_RESPONSE = {
    "items": [
        {
            "id": "abc123XYZ",
            "volumeInfo": {
                "title": "Deep Learning",
                "authors": ["Ian Goodfellow"],
                "description": "A textbook.",
                "industryIdentifiers": [
                    {"type": "ISBN_10", "identifier": "0262035618"},
                    {"type": "ISBN_13", "identifier": "9780262035613"},
                ],
                "publisher": "MIT Press",
                "publishedDate": "2016",
                "categories": ["Computers"],
                "pageCount": 800,
                "language": "en",
                "infoLink": "https://books.google.com/books?id=x",
                "imageLinks": {"thumbnail": "https://books.google.com/thumb.jpg"},
            }
        }
    ]
}


@patch("prisma.integrations.sources.googlebooks.requests.get")
def test_search_parses_items(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: _RESPONSE)
    source = GoogleBooksSource()

    result = source.search("deep learning", limit=1)

    assert len(result.books) == 1
    book = result.books[0]
    assert book.isbn_13 == "9780262035613"
    assert book.cover_url == "https://books.google.com/thumb.jpg"


@patch("prisma.integrations.sources.googlebooks.requests.get")
def test_api_key_added_to_params(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"items": []})
    source = GoogleBooksSource(api_key="secret")

    source.search("query", limit=1)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["key"] == "secret"


def test_daily_cap_exhausted_skips_request():
    source = GoogleBooksSource(daily_cap=1)
    source._limiter.acquire = MagicMock(side_effect=[True, False])

    with patch("prisma.integrations.sources.googlebooks.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"items": []})
        source.search("q1", limit=1)
        result = source.search("q2", limit=1)

    assert result.books == []
    assert mock_get.call_count == 1
