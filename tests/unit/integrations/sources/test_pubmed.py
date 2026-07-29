from unittest.mock import MagicMock, patch

from prisma.integrations.sources.pubmed import PubMedSource, _normalize_pubdate

_ESEARCH_RESPONSE = {"esearchresult": {"idlist": ["111"]}}
_ESUMMARY_RESPONSE = {
    "result": {
        "uids": ["111"],
        "111": {
            "uid": "111",
            "title": "A Sufficiently Long Test Paper Title About Genomics",
            "authors": [{"name": "Jane Doe"}],
            "fulljournalname": "Journal of Testing",
            "source": "J Test",
            "pubdate": "2026 Jul 15",
            "volume": "5",
            "issue": "2",
            "pages": "10-20",
            "articleids": [{"idtype": "doi", "value": "10.1234/test"}],
        },
    }
}
_EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID>
<Article><Abstract><AbstractText>This is a long enough abstract to pass validation elsewhere in the pipeline for real.</AbstractText></Abstract></Article>
</MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def _mock_response(json_data=None, content=None):
    m = MagicMock(status_code=200)
    if json_data is not None:
        m.json = lambda: json_data
    if content is not None:
        m.content = content
    return m


@patch("prisma.integrations.sources.pubmed.requests.get")
def test_search_makes_three_calls_and_parses(mock_get):
    mock_get.side_effect = [
        _mock_response(json_data=_ESEARCH_RESPONSE),
        _mock_response(json_data=_ESUMMARY_RESPONSE),
        _mock_response(content=_EFETCH_XML),
    ]
    source = PubMedSource()

    result = source.search("genomics", limit=3)

    assert mock_get.call_count == 3
    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.doi == "10.1234/test"
    assert paper.journal == "Journal of Testing"
    assert paper.published_date == "2026-07-15"
    assert "long enough abstract" in paper.abstract


@patch("prisma.integrations.sources.pubmed.requests.get")
def test_empty_esearch_short_circuits(mock_get):
    mock_get.return_value = _mock_response(json_data={"esearchresult": {"idlist": []}})
    source = PubMedSource()

    result = source.search("nothing matches this", limit=3)

    assert result.papers == []
    assert mock_get.call_count == 1  # esummary/efetch never called


@patch("prisma.integrations.sources.pubmed.requests.get")
def test_api_key_added_to_every_call(mock_get):
    mock_get.side_effect = [
        _mock_response(json_data=_ESEARCH_RESPONSE),
        _mock_response(json_data=_ESUMMARY_RESPONSE),
        _mock_response(content=_EFETCH_XML),
    ]
    source = PubMedSource(api_key="secret")

    source.search("genomics", limit=3)

    for call in mock_get.call_args_list:
        assert call.kwargs["params"]["api_key"] == "secret"


def test_normalize_pubdate_variants():
    assert _normalize_pubdate("2026") == "2026"
    assert _normalize_pubdate("2026 Jul") == "2026-07"
    assert _normalize_pubdate("2026 Jul 15") == "2026-07-15"
    assert _normalize_pubdate("") is None
    assert _normalize_pubdate("2026 Unknown 15") == "2026"
