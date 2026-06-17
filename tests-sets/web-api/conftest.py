"""
web-api set: skipped unless ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are set.
Secrets never committed — pass via environment variables.
Run with: bash tests-sets/run-web-api.sh
"""

import os
import tempfile
import pytest
import yaml


def _creds_present() -> bool:
    return bool(os.getenv("ZOTERO_API_KEY") and os.getenv("ZOTERO_LIBRARY_ID"))


def pytest_collection_modifyitems(items):
    if not _creds_present():
        skip = pytest.mark.skip(
            reason="ZOTERO_API_KEY and ZOTERO_LIBRARY_ID env vars required"
        )
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def web_api_config_file(tmp_path_factory):
    """Write a temp config built from env vars — secrets never touch disk as literals."""
    data = {
        "sources": {
            "zotero": {
                "enabled": True,
                "mode": "hybrid",
                "local_api_url": "http://localhost:23119",
                "api_key": os.environ.get("ZOTERO_API_KEY", ""),
                "library_id": os.environ.get("ZOTERO_LIBRARY_ID", ""),
                "library_type": "user",
            }
        },
        "llm": {"provider": "ollama", "model": "llama3.1:8b", "host": "localhost:11434"},
        "search": {"default_limit": 10, "sources": ["arxiv"]},
        "output": {"directory": "./outputs", "format": "markdown"},
    }
    cfg = tmp_path_factory.mktemp("web_api") / "config.yaml"
    cfg.write_text(yaml.dump(data))
    return str(cfg)
