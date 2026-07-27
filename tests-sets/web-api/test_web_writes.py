"""
web-api set: the Zotero Web API client (client.py) against the real Zotero
Web API -- the only Zotero backend prisma talks to (confirmed 2026-07-27;
the local-API/hybrid/desktop-connector clients this used to test were
removed).
Skipped automatically when ZOTERO_API_KEY / ZOTERO_LIBRARY_ID are absent.
"""

import os
import pytest
from prisma.integrations.zotero.client import ZoteroClient, ZoteroAPIConfig


@pytest.fixture(scope="module")
def web_client():
    cfg = ZoteroAPIConfig(
        api_key=os.environ["ZOTERO_API_KEY"],
        library_id=os.environ["ZOTERO_LIBRARY_ID"],
        library_type="user",
    )
    return ZoteroClient(cfg)


def test_get_collections(web_client):
    cols = web_client.get_collections()
    assert isinstance(cols, list)


def test_search_items(web_client):
    items = web_client.search_items(query="machine learning", limit=5)
    assert isinstance(items, list)
