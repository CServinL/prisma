"""
Hybrid Zotero Configuration and Client

This module provides a hybrid approach to Zotero integration that can use both
SQLite (for fast local access) and Web API (for fresh data) intelligently.

Features:
- SQLite-first search for maximum speed and offline capability
- Web API fallback for fresh data when SQLite is unavailable
- Automatic caching of Web API results to local cache database
- Write-through cache pattern for optimal performance
"""

import logging
import sqlite3
import json
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
from contextlib import contextmanager

from pydantic import BaseModel, Field, ConfigDict
from ...storage.models.zotero_models import ZoteroItem, ZoteroCollection
from ...utils.config import PrismaConfig

from . import (
    ZoteroClient, ZoteroConfig, ZoteroClientError,
    ZoteroSQLiteClient, ZoteroSQLiteConfig, ZoteroSQLiteError
)
from .desktop_client import ZoteroDesktopClient, ZoteroDesktopConfig, ZoteroDesktopError
from ...storage.models.agent_models import SearchResult

logger = logging.getLogger(__name__)


class ZoteroHybridConfig(BaseModel):
    """Configuration for hybrid Zotero access (SQLite + Web API + Desktop App)"""
    # Web API configuration (optional - for online features)
    api_key: Optional[str] = Field(None, description="Zotero API key")
    library_id: Optional[str] = Field(None, description="Zotero library ID")
    library_type: str = Field("user", description="Library type: 'user' or 'group'")
    
    # SQLite configuration (preferred for local access)
    library_path: Optional[str] = Field(None, description="Path to zotero.sqlite database file")
    
    # Desktop app configuration (for saving new items)
    enable_desktop_save: bool = Field(True, description="Enable saving items via Zotero desktop app")
    desktop_server_url: str = Field("http://127.0.0.1:23119", description="Zotero HTTP server URL")
    collection_key: Optional[str] = Field(None, description="Default collection to save items to")
    
    # Cache configuration (deprecated - use desktop app instead)
    cache_path: Optional[str] = Field(None, description="Path to cache database (auto-generated if None)")
    cache_ttl_hours: int = Field(24, description="Cache time-to-live in hours")
    enable_caching: bool = Field(False, description="Enable caching of Web API results (use desktop app instead)")
    
    # Hybrid behavior settings
    prefer_sqlite: bool = Field(True, description="Prefer SQLite over Web API when both available")
    fallback_to_api: bool = Field(True, description="Fallback to Web API if SQLite fails")
    cache_size: int = Field(10000, description="SQLite cache size for performance")
    
    def has_api_config(self) -> bool:
        """Check if Web API configuration is available"""
        return bool(self.api_key and self.library_id)
    
    def has_sqlite_config(self) -> bool:
        """Check if SQLite configuration is available"""
        return bool(self.library_path and Path(self.library_path).exists())
    
    def has_desktop_config(self) -> bool:
        """Check if desktop app integration is enabled"""
        return self.enable_desktop_save
    
    def get_cache_path(self) -> str:
        """Get cache database path (auto-generate if not specified)"""
        if self.cache_path:
            return self.cache_path
        
        # Auto-generate cache path next to main library
        if self.library_path:
            library_dir = Path(self.library_path).parent
            return str(library_dir / "prisma_cache.sqlite")
        
        # Fallback to current directory
        return "./prisma_zotero_cache.sqlite"


class ZoteroHybridClient:
    """
    Hybrid client that intelligently uses SQLite, Web API, and Desktop App
    
    Strategy:
    - SQLite first (fast, offline) for reading existing data
    - Web API fallback for fresh data when SQLite unavailable
    - Desktop App for saving new items (maintains 100% Zotero compatibility)
    """
    
    def __init__(self, config):
        """Initialize hybrid client with SQLite, Web API, and Desktop App"""
        # Handle both ZoteroHybridConfig and PrismaConfig
        if hasattr(config, 'sources') and hasattr(config.sources, 'zotero'):
            # PrismaConfig structure
            self.zotero_config = config.sources.zotero
        elif hasattr(config, 'zotero'):
            # Legacy config structure
            self.zotero_config = config.zotero
        else:
            # Direct ZoteroConfig
            self.zotero_config = config
            
        self.sqlite_client: Optional[ZoteroSQLiteClient] = None
        self.api_client: Optional[ZoteroClient] = None
        self.desktop_client: Optional[ZoteroDesktopClient] = None
        
        self._initialize_clients()
        
        clients_status = {
            "SQLite": bool(self.sqlite_client),
            "API": bool(self.api_client), 
            "Desktop": bool(self.desktop_client)
        }
        logger.info(f"Hybrid client initialized - {clients_status}")
    
    def _initialize_clients(self):
        """Initialize available clients based on configuration"""
        # Initialize SQLite client if available
        if self._has_sqlite_config():
            try:
                sqlite_config = ZoteroSQLiteConfig(
                    library_path=self.zotero_config.library_path,
                    cache_size=getattr(self.zotero_config, 'cache_size', 10000)
                )
                self.sqlite_client = ZoteroSQLiteClient(sqlite_config)
                logger.info(f"SQLite client ready: {self.zotero_config.library_path}")
            except Exception as e:
                logger.warning(f"SQLite client failed: {e}")
        
        # Initialize Web API client if available
        if self._has_api_config():
            try:
                api_config = ZoteroConfig(
                    api_key=self.zotero_config.api_key,
                    library_id=self.zotero_config.library_id,
                    library_type=self.zotero_config.library_type
                )
                self.api_client = ZoteroClient(api_config)
                logger.info(f"Web API client ready: {self.zotero_config.library_type} library {self.zotero_config.library_id}")
            except Exception as e:
                logger.warning(f"Web API client failed: {e}")
        
        # Initialize Desktop App client (always try)
        try:
            desktop_config = ZoteroDesktopConfig()
            self.desktop_client = ZoteroDesktopClient(desktop_config)
            logger.info("Desktop client ready")
        except Exception as e:
            logger.warning(f"Desktop client failed: {e}")
        
        # Ensure at least one read client works
        if not (self.sqlite_client or self.api_client):
            raise ValueError("No valid Zotero configuration provided for reading")
    
    def _has_sqlite_config(self) -> bool:
        """Check if SQLite configuration is available"""
        return (hasattr(self.zotero_config, 'library_path') and 
                self.zotero_config.library_path and 
                Path(self.zotero_config.library_path).exists())
    
    def _has_api_config(self) -> bool:
        """Check if Web API configuration is available"""
        return (hasattr(self.zotero_config, 'api_key') and 
                self.zotero_config.api_key and
                hasattr(self.zotero_config, 'library_id') and 
                self.zotero_config.library_id)
    
    def _test_desktop_connection(self) -> bool:
        """Test if Zotero desktop app is accessible"""
        if not self.desktop_client:
            return False
        try:
            return self.desktop_client._check_zotero_running()
        except Exception:
            return False
    
    def search_items(self, query: str = None, collection_keys: List[str] = None, 
                    item_types: List[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search items using hybrid approach
        
        Returns:
            List of item dictionaries with consistent format
        """
        # Try SQLite first if preferred
        prefer_sqlite = getattr(self.zotero_config, 'prefer_sqlite', True)
        fallback_to_api = getattr(self.zotero_config, 'fallback_to_api', True)
        if self.sqlite_client and prefer_sqlite:
            try:
                items = self.sqlite_client.search_items(
                    query=query,
                    collection_keys=collection_keys,
                    item_types=item_types,
                    limit=limit
                )
                if items:
                    logger.info(f"Found {len(items)} items via SQLite")
                    return items
            except ZoteroSQLiteError as e:
                logger.warning(f"SQLite search failed: {e}")
                if not fallback_to_api:
                    return []
        
        # Fallback to Web API
        if self.api_client:
            try:
                if query:
                    items = self.api_client.search_items(query, limit=limit)
                else:
                    items = self.api_client.get_items(limit=limit)
                
                logger.info(f"Found {len(items)} items via Web API")
                return items
            except ZoteroClientError as e:
                logger.error(f"Web API search failed: {e}")
        
        return []
    
    def get_collections(self) -> List[Dict[str, Any]]:
        """Get collections using hybrid approach"""
        # Try SQLite first if preferred
        prefer_sqlite = getattr(self.zotero_config, 'prefer_sqlite', True)
        fallback_to_api = getattr(self.zotero_config, 'fallback_to_api', True)
        if self.sqlite_client and prefer_sqlite:
            try:
                collections = self.sqlite_client.get_collections()
                logger.info(f"Got {len(collections)} collections via SQLite")
                return collections
            except ZoteroSQLiteError as e:
                logger.warning(f"SQLite collections failed: {e}")
                if not fallback_to_api:
                    return []
        
        # Fallback to Web API
        if self.api_client:
            try:
                collections = self.api_client.get_collections()
                # Convert to consistent format
                normalized = []
                for coll in collections:
                    normalized.append({
                        'key': coll.get('key', ''),
                        'name': coll.get('data', {}).get('name', ''),
                        'parentCollectionID': coll.get('data', {}).get('parentCollection'),
                    })
                logger.info(f"Got {len(normalized)} collections via Web API")
                return normalized
            except ZoteroClientError as e:
                logger.error(f"Web API collections failed: {e}")
        
        return []
    
    def get_library_stats(self) -> Dict[str, Any]:
        """Get library statistics (SQLite only feature)"""
        if self.sqlite_client:
            try:
                return self.sqlite_client.get_library_stats()
            except ZoteroSQLiteError as e:
                logger.warning(f"SQLite stats failed: {e}")
        
        return {
            'note': 'Statistics available via SQLite client only',
            'api_available': bool(self.api_client),
            'sqlite_available': bool(self.sqlite_client),
            'desktop_available': bool(self.desktop_client)
        }
    
    def save_items_to_zotero(self, items: List[Dict[str, Any]], 
                            collection_key: Optional[str] = None) -> bool:
        """
        Save new items to Zotero using the desktop app (100% compatible)
        
        This method saves items through Zotero's HTTP server, exactly like
        the browser connectors do. This maintains perfect compatibility.
        
        Args:
            items: List of item dictionaries to save
            collection_key: Optional collection to save items to
            
        Returns:
            bool: True if successful
            
        Raises:
            ZoteroDesktopError: If Zotero desktop app is not running or save fails
        """
        if not items:
            logger.warning("No items to save")
            return True
        
        if not self.desktop_client:
            raise ZoteroDesktopError(
                "Desktop app integration not configured. "
                "Set enable_desktop_save=True in config."
            )
        
        try:
            # Check if Zotero is running
            if not self.desktop_client.is_running():
                raise ZoteroDesktopError(
                    "Zotero desktop app is not running. Please start Zotero and try again."
                )
            
            # Save items via desktop app
            success = self.desktop_client.save_items(items, collection_key)
            
            if success:
                logger.info(f"✅ Successfully saved {len(items)} items to Zotero")
                
                # Optional: After saving, items will be available in SQLite on next search
                # This creates a natural write-through cache effect
                
            return success
            
        except ZoteroDesktopError:
            raise  # Re-raise desktop-specific errors
        except Exception as e:
            raise ZoteroDesktopError(f"Unexpected error saving to Zotero: {e}")
    
    def fetch_and_save_items(self, query: str, external_sources: List[str] = None,
                           save_to_collection: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch items from external sources and save them to Zotero
        
        This is the main workflow method that:
        1. Searches external APIs (arXiv, PubMed, etc.)
        2. Finds items not already in local library
        3. Saves new items to Zotero via desktop app
        4. Returns summary of results
        
        Args:
            query: Search query
            external_sources: List of external APIs to search
            save_to_collection: Collection to save new items to
            
        Returns:
            Dict with search results and save status
        """
        results = {
            "query": query,
            "existing_items": 0,
            "new_items_found": 0,
            "items_saved": 0,
            "errors": []
        }
        
        try:
            # First, search existing library
            existing_items = self.search_items(query, limit=1000)
            results["existing_items"] = len(existing_items)
            
            # Extract DOIs/identifiers from existing items for deduplication
            existing_dois = set()
            existing_titles = set()
            for item in existing_items:
                if "DOI" in item:
                    existing_dois.add(item["DOI"].lower())
                if "title" in item:
                    existing_titles.add(item["title"].lower().strip())
            
            # TODO: Search external sources would be implemented here
            # For now, this is a placeholder for the external search integration
            # that will be implemented in Day 3 (Multi-Source Search)
            
            logger.info(
                f"Search completed - Found {results['existing_items']} existing items. "
                f"External source integration pending (Day 3)."
            )
            
            return results
            
        except Exception as e:
            error_msg = f"Error in fetch and save workflow: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
            return results
    
    def create_collection(self, collection_data: Dict[str, Any]) -> Optional[ZoteroCollection]:
        """
        Create a new collection using the best available method
        
        Args:
            collection_data: Collection data in Zotero format
            
        Returns:
            Created ZoteroCollection or None if failed
        """
        # Try local API first (Zotero 7)
        if hasattr(self, 'local_client') and self.local_client:
            try:
                collection = self.local_client.create_collection(collection_data)
                if collection:
                    logger.info(f"Created collection via local API: {collection.name}")
                    return collection
            except Exception as e:
                logger.warning(f"Local API collection creation failed: {e}")
        
        # Try web API as fallback
        if self.api_client:
            try:
                # Convert to web API format
                api_data = [collection_data]  # Web API expects array
                response = self.api_client.create_collections(api_data)
                
                if response and len(response) > 0:
                    collection_dict = response[0]
                    collection = ZoteroCollection.from_zotero_data(collection_dict)
                    logger.info(f"Created collection via web API: {collection.name}")
                    return collection
                    
            except Exception as e:
                logger.warning(f"Web API collection creation failed: {e}")
        
        logger.error("Failed to create collection - no working methods available")
        return None
    
    def get_collection_items(self, collection_key: str) -> List[ZoteroItem]:
        """Get all items in a specific collection"""
        # Try local API first
        if hasattr(self, 'local_client') and self.local_client:
            try:
                items = self.local_client.get_collection_items(collection_key)
                logger.info(f"Got {len(items)} items from collection via local API")
                return items
            except Exception as e:
                logger.warning(f"Local API collection items failed: {e}")
        
        # Try SQLite as fallback
        if self.sqlite_client:
            try:
                # SQLite client might not have this method yet
                if hasattr(self.sqlite_client, 'get_collection_items'):
                    items = self.sqlite_client.get_collection_items(collection_key)
                    logger.info(f"Got {len(items)} items from collection via SQLite")
                    return items
            except Exception as e:
                logger.warning(f"SQLite collection items failed: {e}")
        
        # Try web API as last resort
        if self.api_client:
            try:
                items_data = self.api_client.collection_items(collection_key)
                items = [ZoteroItem.from_zotero_data(item) for item in items_data]
                logger.info(f"Got {len(items)} items from collection via web API")
                return items
            except Exception as e:
                logger.warning(f"Web API collection items failed: {e}")
        
        logger.error(f"Failed to get collection items for {collection_key}")
        return []
    
    def add_item_to_collection(self, item_key: str, collection_key: str) -> bool:
        """Add an item to a collection"""
        # This typically requires web API
        if self.api_client:
            try:
                success = self.api_client.add_items_to_collection(collection_key, [item_key])
                if success:
                    logger.info(f"Added item {item_key} to collection {collection_key}")
                    return True
            except Exception as e:
                logger.warning(f"Web API add to collection failed: {e}")
        
        # Desktop client might support this via connector
        if self.desktop_client:
            try:
                # This would need to be implemented in desktop client
                logger.warning("Desktop client collection membership not yet implemented")
            except Exception as e:
                logger.warning(f"Desktop collection membership failed: {e}")
        
        return False
    
    def update_item_tags(self, item_key: str, tags: List[str]) -> bool:
        """Update tags for an item"""
        # This typically requires web API
        if self.api_client:
            try:
                # Get current item
                item_data = self.api_client.item(item_key)
                
                # Update tags
                item_data['data']['tags'] = [{"tag": tag} for tag in tags]
                
                # Save back
                success = self.api_client.update_item(item_key, item_data)
                if success:
                    logger.info(f"Updated tags for item {item_key}")
                    return True
            except Exception as e:
                logger.warning(f"Web API tag update failed: {e}")
        
        return False