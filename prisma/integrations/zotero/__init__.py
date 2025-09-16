"""
Zotero Integration Package

This package provides comprehensive Zotero integration with multiple approaches:
- Web API client for online access
- Local HTTP server for offline read operations  
- Desktop app client for saving items (100% compatible)
- Hybrid client that intelligently combines all approaches
- Local API client for enhanced Zotero 7 integration

Key Features:
- Read existing library data (Web API/Local HTTP server)
- Save new items via desktop app (maintains compatibility)
- Intelligent fallback strategies
- Full compatibility with Zotero sync and data integrity
"""

# Import core clients
try:
    from .client import ZoteroClient, ZoteroAPIConfig, ZoteroClientError
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
    from .hybrid_client import ZoteroHybridClient, ZoteroHybridConfig
except ImportError:
    pass

__all__ = [
    # Web API Client
    "ZoteroClient",
    "ZoteroAPIConfig", 
    "ZoteroClientError",
    
    # Desktop App Client
    "ZoteroDesktopClient",
    "ZoteroDesktopConfig", 
    "ZoteroDesktopError",
    
    # Local API Client
    "ZoteroLocalAPIClient",
    "ZoteroLocalAPIConfig",
    "ZoteroLocalAPIError",
    
    # Hybrid Client (Recommended)
    "ZoteroHybridClient",
    "ZoteroHybridConfig",
]