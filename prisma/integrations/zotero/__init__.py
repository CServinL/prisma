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

from .client import ZoteroClient, ZoteroClientError

__all__ = [
    "ZoteroClient",
    "ZoteroClientError",
]