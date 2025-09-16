"""
Zotero Integration Package

This package provides comprehensive Zotero integration with multiple approaches:
- Web API client for online access
- SQLite client for offline/fast local access  
- Desktop app client for saving items (100% compatible)
- Hybrid client that intelligently combines all approaches
- Local API client for enhanced Zotero 7 integration

Key Features:
- Read existing library data (SQLite/Web API/Local API)
- Save new items via desktop app (maintains compatibility)
- Intelligent fallback strategies
- Full compatibility with Zotero sync and data integrity
"""

# Import core clients
try:
    from .client import ZoteroClient, ZoteroConfig, ZoteroClientError
except ImportError:
    pass

try:
    from .desktop_client import ZoteroDesktopClient, ZoteroDesktopConfig, ZoteroDesktopError
except ImportError:
    pass

try:
    from .local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig, ZoteroLocalAPIError
except ImportError:
    pass

# Import other clients that may have import issues when running standalone
try:
    from .sqlite_client import ZoteroSQLiteClient, ZoteroSQLiteConfig, ZoteroSQLiteError
except ImportError:
    pass

try:
    from .hybrid_client import ZoteroHybridClient, ZoteroHybridConfig
except ImportError:
    pass

__all__ = [
    # Web API Client
    "ZoteroClient",
    "ZoteroConfig", 
    "ZoteroClientError",
    
    # SQLite Client
    "ZoteroSQLiteClient",
    "ZoteroSQLiteConfig",
    "ZoteroSQLiteError",
    
    # Desktop App Client
    "ZoteroDesktopClient",
    "ZoteroDesktopConfig", 
    "ZoteroDesktopError",
    
    # Hybrid Client (Recommended)
    "ZoteroHybridClient",
    "ZoteroHybridConfig",
]