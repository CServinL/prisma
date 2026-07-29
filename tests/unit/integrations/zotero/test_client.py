"""Unit tests for the consolidated Zotero Web API client (client.py) --
the logic added/ported during the Stack A/Stack B consolidation (2026-07-28):
check_web_api_reachable, status(), find_by_identifier(), ensure_collection(),
get_pdf_bytes(), add_paper(), save_items(). pyzotero's Zotero() constructor
does no network I/O (verified: purely local credential storage), so these
tests build a real ZoteroClient and replace its underlying pyzotero object
(._client) with a MagicMock to control API responses without a real network.
"""
from unittest.mock import MagicMock, patch

import pytest

from prisma.integrations.zotero.client import (
    ZoteroAPIConfig,
    ZoteroClient,
    check_web_api_reachable,
)


def _client() -> ZoteroClient:
    c = ZoteroClient(ZoteroAPIConfig(api_key="key123", library_id="12345", library_type="user"))
    c._client = MagicMock()
    return c


# ── check_web_api_reachable ───────────────────────────────────────────────────

def test_check_web_api_reachable_false_when_no_credentials():
    assert check_web_api_reachable(None, "12345") is False
    assert check_web_api_reachable("key", None) is False


def test_check_web_api_reachable_true_on_200(monkeypatch):
    resp = MagicMock()
    resp.status = 200
    cm = MagicMock()
    cm.__enter__.return_value = resp
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: cm)
    assert check_web_api_reachable("key", "12345") is True


def test_check_web_api_reachable_false_on_exception(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("network down")
    monkeypatch.setattr("urllib.request.urlopen", _raise)
    assert check_web_api_reachable("key", "12345") is False


# ── status() ───────────────────────────────────────────────────────────────

def test_status_unconfigured():
    c = ZoteroClient(ZoteroAPIConfig(api_key="", library_id="", library_type="user"))
    body = c.status()
    assert body.model_dump() == {"mode": "web-api", "available": False, "reachable": False}


def test_status_configured_and_reachable(monkeypatch):
    c = _client()
    monkeypatch.setattr("prisma.integrations.zotero.client.check_web_api_reachable", lambda *a, **kw: True)
    body = c.status()
    assert body.model_dump() == {"mode": "web-api", "available": True, "reachable": True}


# ── find_by_identifier ────────────────────────────────────────────────────

def _zotero_item_raw(key, doi=None, title=None, collections=None):
    return {
        "key": key,
        "version": 1,
        "data": {
            "itemType": "journalArticle",
            "title": title,
            "DOI": doi,
            "collections": collections or [],
        },
    }


def test_find_by_identifier_matches_doi():
    c = _client()
    c._client.items.return_value = [_zotero_item_raw("K1", doi="10.1/xyz", title="A paper")]
    hit = c.find_by_identifier(doi="10.1/XYZ")
    assert hit is not None and hit.key == "K1"


def test_find_by_identifier_falls_back_to_title():
    c = _client()
    c._client.items.side_effect = [
        [],  # doi search
        [_zotero_item_raw("K2", doi=None, title="Exact Title")],  # title search
    ]
    hit = c.find_by_identifier(doi="10.1/nomatch", title="Exact Title")
    assert hit is not None and hit.key == "K2"


def test_find_by_identifier_no_match_returns_none():
    c = _client()
    c._client.items.return_value = []
    assert c.find_by_identifier(doi="none", title="none") is None


def test_find_by_identifier_respects_collection_scope():
    c = _client()
    c._client.items.return_value = [_zotero_item_raw("K3", doi="10.1/x", title="T", collections=["OTHER"])]
    assert c.find_by_identifier(doi="10.1/x", collection_key="TARGET") is None


# ── get_collection_items ───────────────────────────────────────────────────

def test_get_collection_items_without_query():
    c = _client()
    c._client.collection_items.return_value = [_zotero_item_raw("K1", title="A")]
    items = c.get_collection_items("COLL1")
    assert [i.key for i in items] == ["K1"]
    c._client.collection_items.assert_called_once_with("COLL1", limit=100)


def test_get_collection_items_passes_q_to_zotero_native_search():
    # Regression: previously the route filtered client-side on title
    # substring only -- this passes q straight through to Zotero's own
    # server-side search (matches title/creators/abstract/etc.), scoped to
    # the collection, in one call.
    c = _client()
    c._client.collection_items.return_value = [_zotero_item_raw("K2", title="Match")]
    items = c.get_collection_items("COLL1", query="neural networks")
    assert [i.key for i in items] == ["K2"]
    c._client.collection_items.assert_called_once_with("COLL1", limit=100, q="neural networks")


# ── ensure_collection ──────────────────────────────────────────────────────

def test_ensure_collection_returns_existing():
    c = _client()
    c._client.collections.return_value = [
        {"key": "C1", "version": 1, "data": {"name": "My Stream"}, "library": {}}
    ]
    result = c.ensure_collection("My Stream")
    assert result.key == "C1"
    c._client.create_collections.assert_not_called()


def test_ensure_collection_creates_when_missing():
    c = _client()
    c._client.collections.return_value = []
    c._client.create_collections.return_value = {
        "successful": {"0": {"key": "C2", "version": 1, "data": {"name": "New Stream"}}}
    }
    result = c.ensure_collection("New Stream")
    assert result.key == "C2"
    c._client.create_collections.assert_called_once()


# ── get_pdf_bytes ──────────────────────────────────────────────────────────

def test_get_pdf_bytes_finds_pdf_attachment():
    c = _client()
    c._client.children.return_value = [
        {"data": {"key": "ATT1", "contentType": "text/html"}},
        {"data": {"key": "ATT2", "contentType": "application/pdf"}},
    ]
    c._client.file.return_value = b"%PDF-1.4..."
    result = c.get_pdf_bytes("PARENT1")
    assert result == b"%PDF-1.4..."
    c._client.file.assert_called_once_with("ATT2")


def test_get_pdf_bytes_no_pdf_attachment_returns_none():
    c = _client()
    c._client.children.return_value = [{"data": {"key": "ATT1", "contentType": "text/html"}}]
    assert c.get_pdf_bytes("PARENT1") is None


def test_get_pdf_bytes_children_call_fails_returns_none():
    c = _client()
    c._client.children.side_effect = Exception("boom")
    assert c.get_pdf_bytes("PARENT1") is None


# ── add_paper ──────────────────────────────────────────────────────────────

class _FakePaper:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_add_paper_creates_item_and_returns_typed_result():
    c = _client()
    c._client.create_items.return_value = {
        "successful": {"0": _zotero_item_raw("NEWKEY", doi="10.1/new", title="New Paper")}
    }
    paper = _FakePaper(title="New Paper", authors=["Alice"], doi="10.1/new", abstract="abs", url="http://x")
    item = c.add_paper(paper, collection_key="COLL1")
    assert item.key == "NEWKEY"
    call_args = c._client.create_items.call_args[0][0]
    assert call_args[0]["title"] == "New Paper"
    assert call_args[0]["collections"] == ["COLL1"]


def test_add_paper_arxiv_id_sets_preprint_type():
    c = _client()
    c._client.create_items.return_value = {"successful": {"0": _zotero_item_raw("K", title="T")}}
    paper = _FakePaper(title="T", authors=[], arxiv_id="1234.5678")
    c.add_paper(paper)
    call_args = c._client.create_items.call_args[0][0]
    assert call_args[0]["itemType"] == "preprint"


def test_add_paper_raises_on_failure():
    c = _client()
    c._client.create_items.return_value = {"successful": {}}
    paper = _FakePaper(title="T", authors=[])
    with pytest.raises(Exception):
        c.add_paper(paper)


# ── save_items ─────────────────────────────────────────────────────────────

def test_save_items_creates_and_assigns_collection():
    c = _client()
    c._client.create_items.return_value = {"successful": {"0": {"key": "K1", "version": 1}}}
    c._client.item.return_value = {"data": {"collections": []}}
    keys = c.save_items([{"itemType": "journalArticle", "title": "T"}], collection_key="COLL1")
    assert keys == ["K1"]


def test_save_items_continues_after_one_failure():
    c = _client()
    c._client.create_items.side_effect = [
        {"successful": {}},  # first item fails
        {"successful": {"0": {"key": "K2", "version": 1}}},  # second succeeds
    ]
    keys = c.save_items([
        {"itemType": "journalArticle", "title": "Fails"},
        {"itemType": "journalArticle", "title": "Succeeds"},
    ])
    assert keys == ["K2"]
