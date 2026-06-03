"""
local-zotero set: OUR local_api_client against a real running Zotero Desktop.
These are NOT unit tests — they verify our client code against the actual API.
Skipped automatically when Zotero Desktop is not running (see conftest.py).
"""

import os
import pytest
from prisma.integrations.zotero.local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig


@pytest.fixture(scope="module")
def local_client():
    cfg = ZoteroLocalAPIConfig(server_url="http://localhost:23119", user_id="0")
    return ZoteroLocalAPIClient(cfg)


def test_ping(local_client):
    assert local_client.ping() is True


def test_search_returns_list(local_client):
    result = local_client.search_items("")
    assert hasattr(result, "items")
    assert isinstance(result.items, list)


def test_get_collections_returns_list(local_client):
    collections = local_client.get_collections()
    assert isinstance(collections, list)
