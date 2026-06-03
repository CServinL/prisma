"""
web-api set: OUR ZoteroHybridClient write path against the real Zotero Web API.
Skipped automatically when ZOTERO_API_KEY / ZOTERO_LIBRARY_ID are absent.
"""

import os
import pytest
from prisma.integrations.zotero.hybrid_client import ZoteroHybridClient, ZoteroHybridConfig


@pytest.fixture(scope="module")
def hybrid_client():
    cfg = ZoteroHybridConfig(
        api_key=os.environ["ZOTERO_API_KEY"],
        library_id=os.environ["ZOTERO_LIBRARY_ID"],
        library_type="user",
        local_api_url="http://localhost:23119",
    )
    return ZoteroHybridClient(cfg)


def test_get_collections(hybrid_client):
    cols = hybrid_client.get_collections()
    assert isinstance(cols, list)


def test_search_items(hybrid_client):
    items = hybrid_client.search_items(query="machine learning", limit=5)
    assert isinstance(items, list)
