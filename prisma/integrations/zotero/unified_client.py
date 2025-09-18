#!/usr/bin/env python3
"""
Unified Zotero Client

This is the ONLY Zotero client that should be used throughout the application.
It encapsulates all the different implementation details (Hybrid, Local API, Web API)
and provides a single, clean interface for all Zotero operations.

Usage:
    from prisma.integrations.zotero import ZoteroClient
    
    client = ZoteroClient.from_config(config)
    items = client.get_items()
    client.save_items(items)
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from ...storage.models.zotero_models import ZoteroItem, ZoteroCollection, ZoteroTag
from ...utils.config import PrismaConfig

# Import the internal implementation clients (these should not be used directly)
from .hybrid_client import ZoteroHybridClient, ZoteroHybridConfig
from .local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig
from .client import ZoteroClient as ZoteroWebAPIClient

logger = logging.getLogger(__name__)


class ZoteroClient:
    """
    🎯 UNIFIED ZOTERO CLIENT
    
    This is the single entry point for all Zotero operations in Prisma.
    It automatically selects the best implementation client based on configuration
    and provides a consistent interface regardless of the underlying implementation.
    
    Features:
    - Automatic client selection (Hybrid > Local API > Web API)
    - Network-aware operation with automatic fallbacks
    - Unified save interface with collection assignment
    - Comprehensive error handling and logging
    - Integration-agnostic API
    """
    
    def __init__(self, config: PrismaConfig):
        """
        Initialize the unified Zotero client
        
        Args:
            config: Prisma configuration containing Zotero settings
        """
        self.config = config
        self._client = None
        self._client_type = None
        
        # Initialize the appropriate underlying client
        self._initialize_client()
    
    @classmethod
    def from_config(cls, config: PrismaConfig) -> 'ZoteroClient':
        """
        Create a ZoteroClient from Prisma configuration
        
        Args:
            config: Prisma configuration
            
        Returns:
            Configured ZoteroClient instance
        """
        return cls(config)
    
    @classmethod
    def from_config_file(cls, config_path: Path) -> 'ZoteroClient':
        """
        Create a ZoteroClient from configuration file
        
        Args:
            config_path: Path to Prisma configuration file
            
        Returns:
            Configured ZoteroClient instance
        """
        from ...utils.config import load_config
        config = load_config(config_path)
        return cls(config)
    
    def _initialize_client(self):
        """Initialize the appropriate underlying client based on configuration"""
        zotero_config = self.config.sources.zotero
        mode = getattr(zotero_config, 'mode', 'hybrid')
        
        logger.info(f"🔧 Initializing Zotero client in '{mode}' mode")
        
        try:
            if mode == 'hybrid':
                self._client = self._create_hybrid_client()
                self._client_type = 'hybrid'
                logger.info("✅ Using HybridClient (Local API + Web API with intelligent fallbacks)")
                
            elif mode == 'local_api':
                self._client = self._create_local_api_client()
                self._client_type = 'local_api'
                logger.info("✅ Using LocalAPIClient (Zotero 7 Local HTTP API)")
                
            elif mode == 'web_api':
                self._client = self._create_web_api_client()
                self._client_type = 'web_api'
                logger.info("✅ Using WebAPIClient (Zotero Web API)")
                
            else:
                # Default to hybrid for unknown modes
                logger.warning(f"⚠️ Unknown mode '{mode}', defaulting to hybrid")
                self._client = self._create_hybrid_client()
                self._client_type = 'hybrid'
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize Zotero client: {e}")
            raise ValueError(f"Failed to initialize Zotero client: {e}")
    
    def _create_hybrid_client(self) -> ZoteroHybridClient:
        """Create a hybrid client configuration"""
        zotero_config = self.config.sources.zotero
        
        hybrid_config = ZoteroHybridConfig(
            api_key=getattr(zotero_config, 'api_key', None),
            library_id=getattr(zotero_config, 'library_id', None),
            library_type=getattr(zotero_config, 'library_type', 'user'),
            local_server_url=getattr(zotero_config, 'server_url', 'http://127.0.0.1:23119'),
            local_server_timeout=5,
            enable_desktop_save=True,
            desktop_server_url=getattr(zotero_config, 'server_url', 'http://127.0.0.1:23119'),
            collection_key=None
        )
        return ZoteroHybridClient(hybrid_config)
    
    def _create_local_api_client(self) -> ZoteroLocalAPIClient:
        """Create a local API client configuration"""
        zotero_config = self.config.sources.zotero
        
        local_config = ZoteroLocalAPIConfig(
            server_url=getattr(zotero_config, 'server_url', 'http://127.0.0.1:23119'),
            timeout=5,
            user_id=0  # Default user ID for local API
        )
        return ZoteroLocalAPIClient(local_config)
    
    def _create_web_api_client(self) -> ZoteroWebAPIClient:
        """Create a web API client configuration"""
        from .client import ZoteroAPIConfig
        
        zotero_config = self.config.sources.zotero
        
        web_config = ZoteroAPIConfig(
            api_key=getattr(zotero_config, 'api_key', ''),
            library_id=getattr(zotero_config, 'library_id', ''),
            library_type=getattr(zotero_config, 'library_type', 'user')
        )
        return ZoteroWebAPIClient(web_config)
    
    # ==========================================
    # UNIFIED PUBLIC INTERFACE
    # ==========================================
    
    def get_items(self, limit: int = 100, item_type: Optional[str] = None) -> List[ZoteroItem]:
        """
        Get items from Zotero library
        
        Args:
            limit: Maximum number of items to retrieve
            item_type: Filter by item type (e.g., 'journalArticle')
            
        Returns:
            List of ZoteroItem objects
        """
        try:
            if hasattr(self._client, 'get_items'):
                items_data = self._client.get_items(limit=limit, item_type=item_type)
            else:
                raise AttributeError(f"Client {self._client_type} does not support get_items")
                
            # Convert to ZoteroItem objects if needed
            if items_data and isinstance(items_data[0], dict):
                return [ZoteroItem.from_zotero_data(item) for item in items_data]
            else:
                return items_data
                
        except Exception as e:
            # Log as debug instead of error since this is often just a capability check
            logger.debug(f"Failed to get items: {e}")
            raise
    
    def search_items(self, query: str, limit: int = 100) -> List[ZoteroItem]:
        """
        Search for items in Zotero library
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching ZoteroItem objects
        """
        try:
            if hasattr(self._client, 'search_items'):
                items_data = self._client.search_items(query, limit=limit)
            else:
                raise AttributeError(f"Client {self._client_type} does not support search_items")
                
            # Convert to ZoteroItem objects if needed
            if items_data and isinstance(items_data[0], dict):
                return [ZoteroItem.from_zotero_data(item) for item in items_data]
            else:
                return items_data
                
        except Exception as e:
            logger.error(f"❌ Failed to search items: {e}")
            raise
    
    def get_collections(self) -> List[ZoteroCollection]:
        """
        Get all collections from Zotero library
        
        Returns:
            List of ZoteroCollection objects
        """
        try:
            if hasattr(self._client, 'get_collections'):
                return self._client.get_collections()
            else:
                raise AttributeError(f"Client {self._client_type} does not support get_collections")
                
        except Exception as e:
            logger.error(f"❌ Failed to get collections: {e}")
            raise
    
    def get_collection_items(self, collection_key: str) -> List[ZoteroItem]:
        """
        Get all items from a specific collection
        
        Args:
            collection_key: Key of the collection to retrieve items from
            
        Returns:
            List of ZoteroItem objects in the collection
        """
        try:
            if hasattr(self._client, 'get_collection_items'):
                items_data = self._client.get_collection_items(collection_key)
                
                # Convert to ZoteroItem objects if needed
                if items_data and isinstance(items_data[0], dict):
                    return [ZoteroItem.from_zotero_data(item) for item in items_data]
                else:
                    return items_data
            else:
                raise AttributeError(f"Client {self._client_type} does not support get_collection_items")
                
        except Exception as e:
            logger.error(f"❌ Failed to get collection items: {e}")
            raise
    
    def create_collection(self, collection_data: Dict[str, Any]) -> ZoteroCollection:
        """
        Create a new collection
        
        Args:
            collection_data: Collection data dictionary
            
        Returns:
            Created ZoteroCollection object
        """
        try:
            if hasattr(self._client, 'create_collection'):
                return self._client.create_collection(collection_data)
            else:
                raise AttributeError(f"Client {self._client_type} does not support create_collection")
                
        except Exception as e:
            logger.error(f"❌ Failed to create collection: {e}")
            raise

    def delete_collection(self, collection_key: str) -> bool:
        """
        Delete a collection from Zotero library
        
        Args:
            collection_key: Key of the collection to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            if hasattr(self._client, 'delete_collection'):
                return self._client.delete_collection(collection_key)
            else:
                raise AttributeError(f"Client {self._client_type} does not support delete_collection")
                
        except Exception as e:
            logger.error(f"❌ Failed to delete collection {collection_key}: {e}")
            raise
    
    def save_items(self, items: List[Dict[str, Any]], 
                   collection_key: Optional[str] = None) -> List[str]:
        """
        🎯 UNIFIED SAVE INTERFACE
        
        This is the primary method for saving items to Zotero.
        It automatically handles:
        - Client selection and capabilities
        - Network detection and fallbacks
        - Collection assignment
        - Error handling and retries
        
        Args:
            items: List of item data dictionaries in Zotero format
            collection_key: Optional collection to add items to
            
        Returns:
            List of created item keys
        """
        try:
            # Use the unified save interface if available (preferred)
            if hasattr(self._client, 'save_items_to_zotero'):
                logger.info(f"💾 Saving {len(items)} items using unified interface")
                return self._client.save_items_to_zotero(
                    items=items,
                    collection_key=collection_key,
                    auto_assign_collection=bool(collection_key)
                )
            
            # Fallback to client-specific save methods
            elif hasattr(self._client, 'create_item'):
                logger.info(f"💾 Saving {len(items)} items using create_item method")
                created_keys = []
                for item_data in items:
                    item_key = self._client.create_item(item_data)
                    if item_key:
                        created_keys.append(item_key)
                        
                        # Add to collection if specified
                        if collection_key and hasattr(self._client, 'add_item_to_collection'):
                            try:
                                self._client.add_item_to_collection(item_key, collection_key)
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to add item to collection: {e}")
                
                return created_keys
            
            elif hasattr(self._client, 'save_items'):
                logger.info(f"💾 Saving {len(items)} items using save_items method")
                success = self._client.save_items(items)
                if success:
                    # Note: save_items doesn't return keys, so we return empty list
                    logger.warning("⚠️ save_items method doesn't return item keys")
                    return []
                else:
                    raise ValueError("save_items returned False")
            
            else:
                raise AttributeError(f"Client {self._client_type} does not support any save method")
                
        except Exception as e:
            logger.error(f"❌ Failed to save items: {e}")
            raise
    
    def delete_item(self, item_key: str) -> bool:
        """
        Delete an item from Zotero library
        
        Args:
            item_key: Key of the item to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            if hasattr(self._client, 'delete_item'):
                return self._client.delete_item(item_key)
            else:
                raise AttributeError(f"Client {self._client_type} does not support delete_item")
                
        except Exception as e:
            logger.error(f"❌ Failed to delete item {item_key}: {e}")
            raise
    
    def add_item_to_collection(self, item_key: str, collection_key: str) -> bool:
        """
        Add an item to a collection
        
        Args:
            item_key: Key of the item to add
            collection_key: Key of the collection
            
        Returns:
            True if addition was successful
        """
        try:
            if hasattr(self._client, 'add_item_to_collection'):
                return self._client.add_item_to_collection(item_key, collection_key)
            else:
                logger.warning(f"⚠️ Client {self._client_type} does not support add_item_to_collection")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to add item to collection: {e}")
            raise
    
    def get_library_stats(self) -> Dict[str, Any]:
        """
        Get library statistics
        
        Returns:
            Dictionary containing library statistics
        """
        try:
            if hasattr(self._client, 'get_library_stats'):
                return self._client.get_library_stats()
            else:
                # Fallback: calculate basic stats using supported methods
                collections = self.get_collections()
                
                return {
                    'total_items': 0,  # Can't get items count without get_items support
                    'total_collections': len(collections),
                    'client_type': self._client_type,
                    'api_available': True
                }
                
        except Exception as e:
            logger.error(f"❌ Failed to get library stats: {e}")
            return {
                'total_items': 0,
                'total_collections': 0,
                'client_type': self._client_type,
                'api_available': False,
                'error': str(e)
            }
    
    def is_available(self) -> bool:
        """
        Check if the Zotero client is available and functional
        
        Returns:
            True if client is available
        """
        try:
            if hasattr(self._client, 'is_available'):
                return self._client.is_available()
            else:
                # Fallback: try to get collections (supported by all clients)
                self.get_collections()
                return True
                
        except Exception:
            return False
    
    # ==========================================
    # CLIENT INFORMATION
    # ==========================================
    
    @property
    def client_type(self) -> str:
        """Get the type of underlying client being used"""
        return self._client_type
    
    @property
    def client_info(self) -> Dict[str, Any]:
        """Get information about the underlying client"""
        return {
            'type': self._client_type,
            'available': self.is_available(),
            'class': self._client.__class__.__name__ if self._client else None,
            'config_mode': getattr(self.config.sources.zotero, 'mode', 'unknown')
        }
    
    def __repr__(self) -> str:
        return f"ZoteroClient(type={self._client_type}, available={self.is_available()})"