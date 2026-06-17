"""
local-zotero set: skipped unless Zotero Desktop local API is reachable.
Run with: bash tests-sets/run-local-zotero.sh
"""

import pytest
import requests


def _zotero_reachable() -> bool:
    try:
        r = requests.get("http://localhost:23119/connector/ping", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def pytest_collection_modifyitems(items):
    if not _zotero_reachable():
        skip = pytest.mark.skip(reason="Zotero Desktop not reachable at localhost:23119")
        for item in items:
            item.add_marker(skip)
