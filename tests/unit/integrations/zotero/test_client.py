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
    ZoteroClientError,
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


def test_check_web_api_reachable_uses_users_endpoint_by_default(monkeypatch):
    captured = {}
    def _urlopen(req, timeout=None):
        captured["url"] = req.full_url
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(status=200)
        return cm
    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    check_web_api_reachable("key", "12345")
    assert "/users/12345/" in captured["url"]


def test_check_web_api_reachable_uses_groups_endpoint_for_group_libraries(monkeypatch):
    # Regression: group libraries were always probed against /users/, so
    # this reported "unreachable" regardless of real connectivity.
    captured = {}
    def _urlopen(req, timeout=None):
        captured["url"] = req.full_url
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(status=200)
        return cm
    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    check_web_api_reachable("key", "12345", library_type="group")
    assert "/groups/12345/" in captured["url"]


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


def test_status_passes_library_type_to_reachability_check(monkeypatch):
    c = ZoteroClient(ZoteroAPIConfig(api_key="key123", library_id="12345", library_type="group"))
    c._client = MagicMock()
    captured = {}
    def _fake_reachable(api_key, library_id, library_type="user"):
        captured["library_type"] = library_type
        return True
    monkeypatch.setattr("prisma.integrations.zotero.client.check_web_api_reachable", _fake_reachable)
    c.status()
    assert captured["library_type"] == "group"


# ── is_available() ─────────────────────────────────────────────────────────

def test_is_available_true_when_configured_does_not_hit_network(monkeypatch):
    # Regression: is_available() used to call test_connection() -> a live
    # key_info() network request. stream_runner.py calls this up to once
    # per paper found per run, so this must be a pure config check.
    c = _client()
    def _fail(*a, **kw):
        raise AssertionError("is_available() must not perform network I/O")
    monkeypatch.setattr(c, "test_connection", _fail)
    assert c.is_available() is True


def test_is_available_false_when_unconfigured():
    c = ZoteroClient(ZoteroAPIConfig(api_key="", library_id="", library_type="user"))
    assert c.is_available() is False


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


def test_find_by_identifier_uses_higher_search_limit_than_default():
    # Regression: search_items()'s 100-item default risked a false negative
    # for a common title/DOI whose exact match sat past page 1.
    c = _client()
    c._client.items.return_value = [_zotero_item_raw("K1", doi="10.1/xyz", title="A paper")]
    c.find_by_identifier(doi="10.1/xyz")
    _, kwargs = c._client.items.call_args
    assert kwargs["limit"] > 100


# ── get_collection_items ───────────────────────────────────────────────────

def test_get_collection_items_without_query():
    c = _client()
    c._client.everything.side_effect = lambda x: x
    c._client.collection_items.return_value = [_zotero_item_raw("K1", title="A")]
    items = c.get_collection_items("COLL1")
    assert [i.key for i in items] == ["K1"]
    c._client.collection_items.assert_called_once_with("COLL1")


def test_get_collection_items_passes_q_to_zotero_native_search():
    # Regression: previously the route filtered client-side on title
    # substring only -- this passes q straight through to Zotero's own
    # server-side search (matches title/creators/abstract/etc.), scoped to
    # the collection, in one call.
    c = _client()
    c._client.everything.side_effect = lambda x: x
    c._client.collection_items.return_value = [_zotero_item_raw("K2", title="Match")]
    items = c.get_collection_items("COLL1", query="neural networks")
    assert [i.key for i in items] == ["K2"]
    c._client.collection_items.assert_called_once_with("COLL1", q="neural networks")


def test_get_collection_items_paginates_past_first_page():
    # Regression: the old implementation was capped at limit=100, so
    # ensure_collection()/stream dedup could silently miss items past
    # page 1 for a large collection.
    c = _client()
    c._client.collection_items.return_value = "page1_query_result"
    c._client.everything.return_value = [
        _zotero_item_raw("K1", title="A"), _zotero_item_raw("K2", title="B"),
        _zotero_item_raw("K3", title="C"),
    ]
    items = c.get_collection_items("COLL1")
    assert [i.key for i in items] == ["K1", "K2", "K3"]
    c._client.everything.assert_called_once_with("page1_query_result")


# ── ensure_collection ──────────────────────────────────────────────────────

def test_ensure_collection_returns_existing():
    c = _client()
    c._client.everything.side_effect = lambda x: x
    c._client.collections.return_value = [
        {"key": "C1", "version": 1, "data": {"name": "My Stream"}, "library": {}}
    ]
    result = c.ensure_collection("My Stream")
    assert result.key == "C1"
    c._client.create_collections.assert_not_called()


def test_ensure_collection_creates_when_missing():
    c = _client()
    c._client.everything.side_effect = lambda x: x
    c._client.collections.return_value = []
    c._client.create_collections.return_value = {
        "successful": {"0": {"key": "C2", "version": 1, "data": {"name": "New Stream"}}}
    }
    result = c.ensure_collection("New Stream")
    assert result.key == "C2"
    c._client.create_collections.assert_called_once()


def test_ensure_collection_finds_existing_collection_past_first_page():
    # Regression: get_collections()'s 100-item cap meant a library with
    # >100 collections could get a duplicate created for an existing one
    # sitting past page 1.
    c = _client()
    c._client.collections.return_value = ["page1_query_result"]
    c._client.everything.return_value = [
        {"key": "C1", "version": 1, "data": {"name": "Old Stream"}, "library": {}},
        {"key": "C99", "version": 1, "data": {"name": "My Stream"}, "library": {}},
    ]
    result = c.ensure_collection("My Stream")
    assert result.key == "C99"
    c._client.create_collections.assert_not_called()


def test_ensure_collection_raises_when_creation_fails():
    # Regression: ensure_collection() used to return None on a failed
    # create_collection(), and callers (e.g. stream_runner.py) immediately
    # access .key with no None-check.
    c = _client()
    c._client.everything.side_effect = lambda x: x
    c._client.collections.return_value = []
    c._client.create_collections.return_value = {"successful": {}}
    with pytest.raises(ZoteroClientError):
        c.ensure_collection("Broken Stream")


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
