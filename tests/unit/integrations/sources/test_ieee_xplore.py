from unittest.mock import MagicMock, patch

from prisma.integrations.sources.ieee_xplore import IEEEXploreSource, _to_paper_metadata
from prisma.storage.models.api_response_models import IEEEXploreArticle

_FAKE_ARTICLE = {
    "title": "A Sufficiently Long Test Paper Title About Robotics",
    "authors": {"authors": [{"full_name": "Jane Doe"}, {"full_name": "John Smith"}]},
    "abstract": "A long enough abstract to pass validation elsewhere in the pipeline for real.",
    "doi": "10.1109/TEST.2026.1234567",
    "publication_title": "IEEE Transactions on Testing",
    "publication_year": 2026,
    "volume": "5",
    "issue": "2",
    "start_page": "10",
    "end_page": "20",
    "article_number": 9999999,
    "pdf_url": None,
}


def test_no_api_key_skips_entirely_without_network():
    source = IEEEXploreSource()  # no key
    with patch("prisma.integrations.sources.ieee_xplore.requests.get") as mock_get:
        result = source.search("robotics", limit=3)
    assert result.papers == []
    mock_get.assert_not_called()


def test_no_api_key_fails_probe():
    source = IEEEXploreSource()
    assert source.probe() is False


@patch("prisma.integrations.sources.ieee_xplore.requests.get")
def test_search_with_key_parses_articles(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"articles": [_FAKE_ARTICLE]})
    source = IEEEXploreSource(api_key="secret")

    result = source.search("robotics", limit=3)

    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.authors == ["Jane Doe", "John Smith"]
    assert paper.pages == "10-20"
    assert paper.url == "https://ieeexplore.ieee.org/document/9999999"

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["apikey"] == "secret"


def test_parse_article_flat_authors_list():
    article = IEEEXploreArticle.model_validate(dict(_FAKE_ARTICLE, authors=["Solo Author"]))
    paper = _to_paper_metadata(article)
    assert paper.authors == ["Solo Author"]


def test_parse_article_missing_title_returns_none():
    article = IEEEXploreArticle.model_validate({"title": ""})
    assert _to_paper_metadata(article) is None


def test_parse_article_no_url_returns_none():
    raw = dict(_FAKE_ARTICLE)
    raw.pop("article_number")
    raw["html_url"] = None
    article = IEEEXploreArticle.model_validate(raw)
    assert _to_paper_metadata(article) is None
