"""
Unified Zotero Integration Package

This package provides a single, unified Zotero client wrapping the Zotero
Web API -- the only backend prisma talks to (confirmed 2026-07-27; the
former Hybrid/Local-API/Desktop-connector backends only ever read from
Zotero Desktop's local HTTP server on the same machine, a different
machine's concern than the server).

Usage:
    from prisma.integrations.zotero import ZoteroClient

    client = ZoteroClient.from_config(config)
    items = client.get_items()
    client.save_items(items, collection_key="research_stream_key")
"""

# Import the unified client - this is the ONLY client that should be used
from .unified_client import ZoteroClient

# Import core exception types that may be needed
try:
    from .client import ZoteroClientError
except ImportError:
    class ZoteroClientError(Exception):
        pass

# Export only the unified interface
__all__ = [
    "ZoteroClient",
    "ZoteroClientError",
]