"""
Zotero integration module
"""

from .client import ZoteroClient, ZoteroConfig, ZoteroClientError

__all__ = ["ZoteroClient", "ZoteroConfig", "ZoteroClientError"]