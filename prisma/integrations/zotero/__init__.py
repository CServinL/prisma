"""
Unified Zotero Integration Package

This package provides a single, unified Zotero client that encapsulates all 
implementation details and provides a clean, consistent interface.

Key Features:
- Single ZoteroClient that handles all Zotero operations
- Automatic client selection based on configuration
- Network-aware operation with intelligent fallbacks
- Unified save interface with collection assignment
- Integration-agnostic API

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

try:
    from .local_api_client import ZoteroLocalAPIError
except ImportError:
    class ZoteroLocalAPIError(Exception):
        pass

try:
    from .desktop_client import ZoteroDesktopError
except ImportError:
    class ZoteroDesktopError(Exception):
        pass

# Export only the unified interface
__all__ = [
    "ZoteroClient",
    "ZoteroClientError",
    "ZoteroLocalAPIError", 
    "ZoteroDesktopError",
]