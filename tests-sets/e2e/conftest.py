"""
e2e set: skipped unless internet + Ollama + Zotero creds are all present.
These test complete flows, not individual units. Real APIs expected.
Run with: bash tests-sets/run-e2e.sh
"""

import os
import pytest
import requests


def _all_deps_present() -> bool:
    if not (os.getenv("ZOTERO_API_KEY") and os.getenv("ZOTERO_LIBRARY_ID")):
        return False
    try:
        requests.get("http://localhost:11434/api/tags", timeout=3)
    except Exception:
        return False
    return True


def pytest_collection_modifyitems(items):
    if not _all_deps_present():
        skip = pytest.mark.skip(
            reason="e2e requires internet + Ollama + ZOTERO_API_KEY/ZOTERO_LIBRARY_ID"
        )
        for item in items:
            # stream flow tests manage their own skip logic (internet-only gate)
            if "test_stream_flow" not in item.nodeid:
                item.add_marker(skip)
