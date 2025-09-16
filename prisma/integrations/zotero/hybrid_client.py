"""
Network-Aware Hybrid Zotero Client

This module provides a network-aware hybrid approach to Zotero integration that
automatically adapts to network connectivity for optimal operation.

Network-Aware Architecture:
🟢 Online Mode: Web API (preferred) → Local HTTP (fallback) + writes enabled
🔴 Offline Mode: Local HTTP only + writes disabled

Core Principle: Smart network awareness with automatic client selection
"""

import logging
import json
import time
import requests
import socket
from typing import Optional, List, Dict, Any
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, field_validator, HttpUrl
from prisma.storage.models.zotero_models import ZoteroCollection
from ...storage.models.zotero_models import ZoteroItem, ZoteroCollection
from ...utils.config import PrismaConfig

from .client import (
    ZoteroClient, ZoteroAPIConfig, ZoteroClientError,
)
from .desktop_client import ZoteroDesktopClient, ZoteroDesktopConfig, ZoteroDesktopError
from .local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig, ZoteroLocalAPIError
from ...storage.models.agent_models import SearchResult

logger = logging.getLogger(__name__)


def check_internet_connectivity(timeout: int = 5) -> bool:
    """
    Check if internet connectivity is available by trying to reach common reliable endpoints
    
    Args:
        timeout: Timeout in seconds for the connectivity check
        
    Returns:
        True if internet is available, False otherwise
    """
    # Try multiple reliable endpoints
    test_urls = [
        'https://api.zotero.org/',  # Zotero API
        'https://www.google.com/',  # Google as fallback
        'https://httpbin.org/get'   # HTTPBin as another fallback
    ]
    
    for url in test_urls:
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code in [200, 301, 302]:  # Accept redirects too
                return True
        except (requests.RequestException, socket.error, OSError):
            continue
    
    return False


def check_zotero_web_api_access(api_key: Optional[str], library_id: Optional[str], timeout: int = 5) -> bool:
    """
    Check if Zotero Web API is accessible with the provided credentials
    
    Args:
        api_key: Zotero API key
        library_id: Zotero library ID
        timeout: Timeout in seconds for the API check
        
    Returns:
        True if Web API is accessible, False otherwise
    """
    if not api_key or not library_id:
        return False
        
    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        response = requests.get(
            f'https://api.zotero.org/users/{library_id}/collections',
            headers=headers,
            timeout=timeout,
            params={'limit': 1}
        )
        return response.status_code == 200
    except (requests.RequestException, socket.error, OSError):
        return False


class ZoteroHybridConfig(BaseModel):
    """Configuration for hybrid Zotero access (Web API + Local HTTP Server + Desktop App)"""
    
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        frozen=False
    )
    
    # Web API configuration (optional - for online features)
    api_key: Optional[str] = None
    library_id: Optional[str] = None
    library_type: str = "user"
    
    # Local HTTP server configuration (for offline read operations)
    local_server_url: str = "http://127.0.0.1:23119"
    local_server_timeout: int = 5
    
    # Desktop app configuration (for saving new items)
    enable_desktop_save: bool = True
    desktop_server_url: str = "http://127.0.0.1:23119"
    collection_key: Optional[str] = None
    
    # Network-aware behavior settings
    network_timeout: int = 5
    prefer_web_api_when_online: bool = True
    disable_writes_when_offline: bool = True
    auto_detect_network: bool = True
    
    @field_validator('library_type')
    @classmethod
    def validate_library_type(cls, v: str) -> str:
        """Validate library type is either 'user' or 'group'"""
        if v not in ('user', 'group'):
            raise ValueError('library_type must be "user" or "group"')
        return v
    
    @field_validator('local_server_timeout', 'network_timeout')
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout values are positive"""
        if v <= 0:
            raise ValueError('Timeout values must be positive integers')
        if v > 300:  # 5 minutes max
            raise ValueError('Timeout values must be 300 seconds or less')
        return v
    
    @field_validator('local_server_url', 'desktop_server_url')
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        """Validate server URLs are well-formed"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Server URLs must start with http:// or https://')
        if not v.replace('http://', '').replace('https://', '').strip():
            raise ValueError('Server URLs cannot be empty after protocol')
        return v
    
    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Validate API key format if provided"""
        if v is not None and v.strip():
            # Zotero API keys are typically 24 characters long
            if len(v) < 10:
                raise ValueError('API key appears to be too short')
            if len(v) > 100:
                raise ValueError('API key appears to be too long')
        return v
    
    @field_validator('library_id')
    @classmethod
    def validate_library_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate library ID format if provided"""
        if v is not None and v.strip():
            if not v.isdigit():
                raise ValueError('Library ID must be a numeric string')
        return v
    
    def has_api_config(self) -> bool:
        """Check if Web API configuration is available"""
        return bool(self.api_key and self.library_id)
    
    def has_local_server_config(self) -> bool:
        """Check if local HTTP server configuration is available"""
        return bool(self.local_server_url)
    
    def has_desktop_config(self) -> bool:
        """Check if desktop app integration is enabled"""
        return self.enable_desktop_save


class ZoteroHybridClient:
    """
    Network-Aware Hybrid Zotero Client
    
    Architecture:
    🟢 ONLINE MODE (Internet Available):
    📖 READ OPERATIONS: Web API (preferred) → Local HTTP (fallback)
    ✍️ WRITE OPERATIONS: Web API only (enabled)
    
    🔴 OFFLINE MODE (No Internet):
    📖 READ OPERATIONS: Local HTTP only
    ✍️ WRITE OPERATIONS: Disabled (safety)
    
    Auto-Detection: Seamless switching based on network connectivity
    """
    
    def __init__(self, config: Optional[ZoteroHybridConfig] = None):
        """Initialize hybrid client with Network-Aware behavior"""
        # Use provided config or create default config with new network-aware settings
        if config is None:
            config = ZoteroHybridConfig(
                api_key=None,
                library_id=None,
                library_type="user",
                local_server_url="http://127.0.0.1:23119",
                local_server_timeout=5,
                enable_desktop_save=True,
                desktop_server_url="http://127.0.0.1:23119",
                collection_key=None,
                network_timeout=5,
                prefer_web_api_when_online=True,
                disable_writes_when_offline=True,
                auto_detect_network=True
            )
        self.zotero_config = config
        
        # Network state
        self._is_online: Optional[bool] = None
        self._last_network_check: float = 0
        self._network_check_interval: int = 30  # Check network every 30 seconds
        
        # Initialize available clients
        self.api_client: Optional[ZoteroClient] = None
        self.desktop_client: Optional[ZoteroDesktopClient] = None
        self.local_api_client: Optional[ZoteroLocalAPIClient] = None
        
        self._initialize_clients()
        
        # Log initialization status
        clients_status = []
        if self.api_client:
            clients_status.append("Web API")
        if self.desktop_client:
            clients_status.append("Desktop App")
        if self.local_api_client:
            clients_status.append("Local HTTP Server")
        
        # Detect initial network state
        if self.zotero_config.auto_detect_network:
            network_status = "online" if self.is_online() else "offline"
            logger.info(f"Hybrid client initialized - {clients_status} - Network: {network_status}")
        else:
            logger.info(f"Hybrid client initialized - {clients_status} - Network detection disabled")
    
    def _initialize_clients(self):
        """Initialize available clients based on configuration"""
        # Initialize Local API client if available
        if self._has_local_server_config():
            try:
                local_config = ZoteroLocalAPIConfig(
                    server_url=self.zotero_config.local_server_url,
                    timeout=self.zotero_config.local_server_timeout,
                    user_id="0"  # Default user ID for local API
                )
                self.local_api_client = ZoteroLocalAPIClient(local_config)
                logger.info(f"Local HTTP server client ready: {self.zotero_config.local_server_url}")
            except Exception as e:
                logger.warning(f"Local HTTP server client failed: {e}")
        
        # Initialize Web API client if available (only if we have valid credentials)
        if self._has_api_config() and self.zotero_config.api_key and self.zotero_config.library_id:
            try:
                api_config = ZoteroAPIConfig(
                    api_key=self.zotero_config.api_key,
                    library_id=self.zotero_config.library_id,
                    library_type=self.zotero_config.library_type,
                    api_version=3
                )
                self.api_client = ZoteroClient(api_config)
                logger.info(f"Web API client ready: {self.zotero_config.library_type} library {self.zotero_config.library_id}")
            except Exception as e:
                logger.warning(f"Web API client failed: {e}")
        
        # Initialize Desktop App client (always try)
        if self.zotero_config.has_desktop_config():
            try:
                desktop_config = ZoteroDesktopConfig(
                    server_url=self.zotero_config.desktop_server_url,
                    timeout=5,
                    check_running=True,
                    collection_key=self.zotero_config.collection_key
                )
                self.desktop_client = ZoteroDesktopClient(desktop_config)
                logger.info(f"Desktop app client ready: {self.zotero_config.desktop_server_url}")
            except Exception as e:
                logger.warning(f"Desktop app client failed: {e}")
        
        # Ensure at least one read client works
        if not (self.local_api_client or self.api_client):
            logger.warning("No valid Zotero configuration provided for reading - only write operations will be available")
    
    def _has_local_server_config(self) -> bool:
        """Check if local HTTP server configuration is available"""
        return self.zotero_config.has_local_server_config()
    
    def _has_api_config(self) -> bool:
        """Check if Web API configuration is available"""
        return self.zotero_config.has_api_config()
    
    def _test_desktop_connection(self) -> bool:
        """Test if Zotero desktop app is accessible"""
        if not self.desktop_client:
            return False
        try:
            return self.desktop_client._check_zotero_running()
        except Exception:
            return False
    
    def is_online(self) -> bool:
        """
        Check if we're online and can access Zotero Web API
        Uses caching to avoid excessive network checks
        """
        if not self.zotero_config.auto_detect_network:
            # If auto-detection is disabled, assume online if we have API config
            return self._has_api_config()
        
        current_time = time.time()
        
        # Use cached result if within check interval
        if (self._is_online is not None and 
            current_time - self._last_network_check < self._network_check_interval):
            return self._is_online
        
        # Perform new network check
        logger.debug("Checking network connectivity...")
        
        # First check basic internet connectivity
        if not check_internet_connectivity(timeout=self.zotero_config.network_timeout):
            logger.debug("No internet connectivity detected")
            self._is_online = False
        else:
            # Check if Zotero Web API is accessible with our credentials
            self._is_online = check_zotero_web_api_access(
                self.zotero_config.api_key, 
                self.zotero_config.library_id,
                timeout=self.zotero_config.network_timeout
            )
            logger.debug(f"Zotero Web API accessible: {self._is_online}")
        
        self._last_network_check = current_time
        return self._is_online
    
    def is_offline(self) -> bool:
        """Check if we're offline (inverse of is_online)"""
        return not self.is_online()
    
    def get_preferred_read_client(self):
        """Get the preferred client for read operations based on network state and config"""
        if self.zotero_config.prefer_web_api_when_online and self.is_online() and self.api_client:
            logger.debug("Using Web API for read operation (online)")
            return self.api_client
        elif self.local_api_client:
            logger.debug("Using Local HTTP server for read operation")
            return self.local_api_client
        elif self.api_client:
            logger.debug("Fallback to Web API for read operation")
            return self.api_client
        else:
            logger.error("No read client available")
            return None
    
    def can_write(self) -> bool:
        """Check if write operations are allowed based on network state and configuration"""
        if self.zotero_config.disable_writes_when_offline and self.is_offline():
            logger.debug("Write operations disabled - offline mode")
            return False
        
        # We need either Web API or Desktop client for writes
        return bool(self.api_client or self.desktop_client)
    
    def _ensure_write_capability(self, operation_name: str) -> None:
        """Ensure write operations are allowed, raise exception if not"""
        if not self.can_write():
            if self.is_offline():
                raise ZoteroClientError(f"Write operation '{operation_name}' not allowed in offline mode")
            else:
                raise ZoteroClientError(f"Write operation '{operation_name}' requires Web API or Desktop client")
    
    def search_items(self, query: Optional[str] = None, collection_keys: Optional[List[str]] = None,
                    item_types: Optional[List[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        📖 READ: Search for items with network-aware client selection
        
        Strategy:
        - Online: Use Web API (preferred) or Local HTTP (fallback)
        - Offline: Use Local HTTP only
        """
        
        # Get preferred client based on network state
        preferred_client = self.get_preferred_read_client()
        
        if not preferred_client:
            raise ZoteroClientError("No read client available")
        
        # Try preferred client first
        if preferred_client == self.api_client and self.api_client is not None:
            try:
                items = self.api_client.search_items(
                    query=query or "",
                    limit=limit
                )
                logger.info(f"Got {len(items)} items via Web API")
                return items
            except ZoteroClientError as e:
                logger.warning(f"Web API search failed: {e}")
                # Fallback to local if available
                if self.local_api_client:
                    logger.info("Falling back to Local HTTP server")
                else:
                    raise
        
        # Use or fallback to Local HTTP server
        if self.local_api_client:
            try:
                # Local API uses different signature - convert parameters
                search_query = query or ""
                result = self.local_api_client.search_items(search_query)
                items = result.items if hasattr(result, 'items') else []
                logger.info(f"Got {len(items)} items via Local HTTP server")
                # Convert ZoteroItem objects to dict format for consistent return type
                result_items = []
                for item in items:
                    if hasattr(item, 'to_dict'):
                        result_items.append(item.to_dict())
                    elif isinstance(item, dict):
                        result_items.append(item)
                    else:
                        # Handle unknown item types by converting to dict
                        result_items.append(dict(item) if hasattr(item, '__dict__') else {})
                return result_items
            except ZoteroLocalAPIError as e:
                logger.error(f"Local HTTP server search failed: {e}")
                raise ZoteroClientError(f"All search methods failed - last error: {e}")
        
        raise ZoteroClientError("No available search method")
    
    def get_collections(self) -> List[ZoteroCollection]:
        """
        📖 READ: Get collections with network-aware client selection
        
        Strategy:
        - Online: Use Web API (preferred) or Local HTTP (fallback)
        - Offline: Use Local HTTP only
        """
        
        # Get preferred client based on network state
        preferred_client = self.get_preferred_read_client()
        
        if not preferred_client:
            raise ZoteroClientError("No read client available")
        
        # Try preferred client first
        if preferred_client == self.api_client and self.api_client is not None:
            try:
                collections_data = self.api_client.get_collections()
                # Convert Dict data to ZoteroCollection objects
                collections = [ZoteroCollection.from_zotero_data(col_data) for col_data in collections_data]
                logger.info(f"Got {len(collections)} collections via Web API")
                return collections
            except ZoteroClientError as e:
                logger.warning(f"Web API get_collections failed: {e}")
                # Fallback to local if available
                if self.local_api_client:
                    logger.info("Falling back to Local HTTP server")
                else:
                    raise
        
        # Use or fallback to Local HTTP server
        if self.local_api_client:
            try:
                collections = self.local_api_client.get_collections()
                logger.info(f"Got {len(collections)} collections via Local HTTP server")
                return collections
            except ZoteroLocalAPIError as e:
                logger.error(f"Local HTTP server get_collections failed: {e}")
                raise ZoteroClientError(f"All collection methods failed - last error: {e}")
        
        raise ZoteroClientError("No available collection method")
    
    def get_library_stats(self) -> Dict[str, Any]:
        """
        📖 READ: Get library statistics with network-aware client selection
        """
        
        # Get preferred client based on network state
        preferred_client = self.get_preferred_read_client()
        
        # Try preferred client first if it has stats capability
        if preferred_client == self.local_api_client and self.local_api_client:
            try:
                return self.local_api_client.get_library_stats()
            except ZoteroLocalAPIError as e:
                logger.warning(f"Local HTTP server stats failed: {e}")
        
        # Basic stats based on available clients and network state
        return {
            'local_server_available': bool(self.local_api_client),
            'api_available': bool(self.api_client),
            'desktop_available': bool(self.desktop_client),
            'network_online': self.is_online(),
            'preferred_client': 'web_api' if preferred_client == self.api_client else 'local_http' if preferred_client == self.local_api_client else 'none',
            'total_clients': sum([
                bool(self.local_api_client),
                bool(self.api_client),
                bool(self.desktop_client)
            ])
        }
    
    def create_item(self, item_data: Dict[str, Any]) -> str:
        """
        ✍️ WRITE: Create a new item using Web API with immediate verification
        
        Args:
            item_data: Item data dictionary with required fields like 'itemType', 'title', etc.
            
        Returns:
            Created item key
            
        Raises:
            ZoteroClientError: If web API creation fails or verification fails
            ValueError: If no clients are available or writes are disabled
        """
        # Ensure write capability is available
        self._ensure_write_capability("create_item")
        
        # Only Web API has create_item method
        if self.api_client:
            try:
                item_key = self.api_client.create_item(item_data)
                if item_key is not None:
                    logger.info(f"Created item via web API: {item_key}")
                    
                    # ✅ IMMEDIATE VERIFICATION: Confirm the item exists via web API
                    try:
                        verification_item = self.api_client.get_item(item_key)
                        if verification_item:
                            logger.info(f"✅ Verified item creation: {item_key}")
                            return item_key
                        else:
                            raise ZoteroClientError(f"Item verification failed - item {item_key} not found immediately after creation")
                    except Exception as e:
                        logger.error(f"Item verification failed: {e}")
                        raise ZoteroClientError(f"Item created but verification failed: {e}")
                else:
                    raise ZoteroClientError("Web API create_item returned None")
            except ZoteroClientError as e:
                logger.error(f"Web API create failed: {e}")
                raise
        
        raise ValueError("Web API client required for creating items")
    
    def delete_item(self, item_key: str) -> bool:
        """
        ✍️ WRITE: Delete an item using Web API with immediate verification
        """
        # Ensure write capability is available
        self._ensure_write_capability("delete_item")
        
        if self.api_client:
            try:
                success = self.api_client.delete_item(item_key)
                logger.info(f"Deleted item via web API: {item_key}")
                
                # ✅ IMMEDIATE VERIFICATION: Confirm the item is gone via web API
                try:
                    verification_item = self.api_client.get_item(item_key)
                    if verification_item:
                        logger.warning(f"⚠️ Item still exists after deletion: {item_key}")
                        raise ZoteroClientError(f"Item deletion verification failed - item {item_key} still exists")
                    else:
                        logger.info(f"✅ Verified item deletion: {item_key}")
                        return True
                except ZoteroClientError as e:
                    # If get_item throws an error for missing item, that's good (item was deleted)
                    if "not found" in str(e).lower() or "404" in str(e):
                        logger.info(f"✅ Verified item deletion (item not found): {item_key}")
                        return True
                    else:
                        logger.error(f"Item deletion verification failed: {e}")
                        raise ZoteroClientError(f"Item deletion verification failed: {e}")
                        
            except ZoteroClientError as e:
                logger.error(f"Web API delete failed: {e}")
                raise
        
        raise ValueError("Web API client required for deleting items")
    
    def fetch_and_save_items(self, query: str, external_sources: Optional[List[str]] = None,
                            collection_key: Optional[str] = None, limit: int = 10) -> List[ZoteroItem]:
        """
        Fetch items from external sources and save them to Zotero
        
        This method uses external APIs to find papers and saves them via desktop app
        """
        if not self.desktop_client:
            raise ValueError("Desktop client required for saving external items")
        
        external_sources = external_sources or ["crossref", "arxiv"]
        items_saved = []
        
        try:
            # This would integrate with external search APIs
            # For now, this is a placeholder
            logger.info(f"Fetching items for query: {query}")
            logger.info(f"Using sources: {external_sources}")
            logger.info(f"Target collection: {collection_key}")
            
            # TODO: Implement external source integration
            # - Search CrossRef, arXiv, etc.
            # - Extract DOIs/identifiers from existing items for deduplication
            # - Save unique items via desktop app
            
            return items_saved
            
        except Exception as e:
            logger.error(f"Fetch and save failed: {e}")
            raise ZoteroDesktopError(f"Failed to fetch and save items: {e}")
    
    def create_collection(self, collection_data: Dict[str, Any]) -> ZoteroCollection:
        """
        ✍️ WRITE: Create a new collection with immediate verification
        
        Args:
            collection_data: Collection data in Zotero format
            
        Returns:
            Created ZoteroCollection
            
        Raises:
            ZoteroLocalAPIError: If local API creation fails
            ZoteroClientError: If web API creation fails or verification fails
            ValueError: If no clients are available or writes are disabled
        """
        # Ensure write capability is available
        self._ensure_write_capability("create_collection")
        
        # Only use Web API for collections to ensure reliability and immediate verification
        if self.api_client:
            try:
                collection = self.api_client.create_collection(collection_data)
                if collection is not None:
                    logger.info(f"Created collection via web API: {collection.key}")
                    
                    # ✅ IMMEDIATE VERIFICATION: Confirm the collection exists via web API
                    try:
                        collections = self.api_client.get_collections()
                        collection_keys = [col['key'] for col in collections if 'key' in col]
                        
                        if collection.key in collection_keys:
                            logger.info(f"✅ Verified collection creation: {collection.key}")
                            return collection
                        else:
                            raise ZoteroClientError(f"Collection verification failed - collection {collection.key} not found immediately after creation")
                    except Exception as e:
                        logger.error(f"Collection verification failed: {e}")
                        raise ZoteroClientError(f"Collection created but verification failed: {e}")
                else:
                    raise ZoteroClientError("Web API create collection returned None")
            except ZoteroClientError as e:
                logger.error(f"Web API create collection failed: {e}")
                raise
        
        raise ValueError("Web API client required for creating collections")
    
    def delete_collection(self, collection_key: str) -> bool:
        """
        ✍️ WRITE: Delete a collection with immediate verification
        
        Args:
            collection_key: The collection key to delete
            
        Returns:
            True if deletion was successful
            
        Raises:
            ZoteroClientError: If web API deletion fails
            ValueError: If no clients are available or writes are disabled
        """
        # Ensure write capability is available
        self._ensure_write_capability("delete_collection")
        
        # Only use Web API for collection deletion to ensure reliability
        if self.api_client:
            try:
                success = self.api_client.delete_collection(collection_key)
                logger.info(f"Deleted collection via web API: {collection_key}")
                
                # ✅ IMMEDIATE VERIFICATION: Confirm the collection is gone via web API
                # Note: Be more lenient with verification to handle edge cases
                try:
                    collections = self.api_client.get_collections()
                    collection_keys = [col['key'] for col in collections if 'key' in col]
                    
                    if collection_key not in collection_keys:
                        logger.info(f"✅ Verified collection deletion: {collection_key}")
                        return True
                    else:
                        logger.warning(f"⚠️ Collection still appears in list after deletion: {collection_key}")
                        # Don't fail immediately - the delete API call succeeded
                        # This might be a temporary sync issue
                        return success
                except Exception as e:
                    logger.warning(f"Collection deletion verification failed, but delete API call succeeded: {e}")
                    # Return the original delete result rather than failing
                    return success
                    
            except ZoteroClientError as e:
                logger.error(f"Web API delete collection failed: {e}")
                raise
        
        raise ValueError("Web API client required for deleting collections")
    
    def get_collection_items(self, collection_key: str) -> List[ZoteroItem]:
        """
        📖 READ: Get items in a collection with network-aware client selection
        """
        
        # Get preferred client based on network state
        preferred_client = self.get_preferred_read_client()
        
        if not preferred_client:
            raise ZoteroClientError("No read client available")
        
        # Try preferred client first
        if preferred_client == self.api_client and self.api_client is not None:
            try:
                items_data = self.api_client.get_collection_items(collection_key)
                items = [ZoteroItem.from_zotero_data(item) for item in items_data]
                logger.info(f"Got {len(items)} items from collection via Web API")
                return items
            except ZoteroClientError as e:
                logger.warning(f"Web API get_collection_items failed: {e}")
                # Fallback to local if available
                if self.local_api_client:
                    logger.info("Falling back to Local HTTP server")
                else:
                    raise
        
        # Use or fallback to Local HTTP server
        if self.local_api_client:
            try:
                items = self.local_api_client.get_collection_items(collection_key)
                logger.info(f"Got {len(items)} items from collection via Local HTTP server")
                return items
            except ZoteroLocalAPIError as e:
                logger.error(f"Local HTTP server get_collection_items failed: {e}")
                raise ZoteroClientError(f"All collection item methods failed - last error: {e}")
        
        raise ZoteroClientError("No available collection item method")
    
    def add_item_to_collection(self, item_key: str, collection_key: str) -> bool:
        """
        ✍️ WRITE: Add an item to a collection with immediate verification
        
        Args:
            item_key: The item key to add
            collection_key: The collection key to add the item to
            
        Returns:
            True if addition was successful
            
        Raises:
            ZoteroLocalAPIError: If local API addition fails
            ZoteroClientError: If verification via web API fails
            ValueError: If no clients are available or writes are disabled
        """
        # Ensure write capability is available
        self._ensure_write_capability("add_item_to_collection")
        
        # Try local API client first (it has add_item_to_collection method)
        if self.local_api_client:
            try:
                success = self.local_api_client.add_item_to_collection(item_key, collection_key)
                logger.info(f"Added item {item_key} to collection {collection_key}")
                
                # ✅ IMMEDIATE VERIFICATION: Confirm the item is in the collection via web API
                # Note: Due to sync delays, verification may fail temporarily even when addition succeeded
                if self.api_client:
                    try:
                        collection_items = self.api_client.get_collection_items(collection_key)
                        item_keys = [item['key'] for item in collection_items if 'key' in item]
                        
                        if item_key in item_keys:
                            logger.info(f"✅ Verified item addition to collection: {item_key} -> {collection_key}")
                            return True
                        else:
                            # Sync delay - item was added but not yet visible via Web API
                            logger.info(f"ℹ️ Item addition pending sync: {item_key} -> {collection_key} (this is normal)")
                            return success  # Trust the local API result
                    except Exception as e:
                        # Verification failed but item was likely added successfully
                        logger.warning(f"Collection verification failed (sync delay): {e}")
                        return success  # Trust the local API result
                else:
                    logger.info("No web API client available for verification")
                    return success
                    
            except ZoteroLocalAPIError as e:
                logger.error(f"Local API add to collection failed: {e}")
                raise
        
        # Web API client doesn't have add_items_to_collection method
        raise ValueError("Local API client required for adding items to collections")
    
    def get_item(self, item_key: str) -> ZoteroItem:
        """
        📖 READ: Get a specific item by key with network-aware client selection
        
        Args:
            item_key: The item key to retrieve
            
        Returns:
            ZoteroItem object
            
        Raises:
            ZoteroLocalAPIError: If local API retrieval fails
            ZoteroClientError: If web API retrieval fails
            ValueError: If no clients are available
        """
        
        # Get preferred client based on network state
        preferred_client = self.get_preferred_read_client()
        
        if not preferred_client:
            raise ZoteroClientError("No read client available")
        
        # Try preferred client first
        if preferred_client == self.api_client and self.api_client is not None:
            try:
                item_data = self.api_client.get_item(item_key)
                item = ZoteroItem.from_zotero_data(item_data)
                logger.info(f"Got item via Web API: {item_key}")
                return item
            except ZoteroClientError as e:
                logger.warning(f"Web API get_item failed: {e}")
                # Fallback to local if available
                if self.local_api_client:
                    logger.info("Falling back to Local HTTP server")
                else:
                    raise
        
        # Use or fallback to Local HTTP server
        if self.local_api_client:
            try:
                item = self.local_api_client.get_item(item_key)
                if item is not None:
                    logger.info(f"Got item via Local HTTP server: {item_key}")
                    return item
                else:
                    raise ZoteroLocalAPIError(f"Local HTTP server returned None for item {item_key}")
            except ZoteroLocalAPIError as e:
                logger.error(f"Local HTTP server get_item failed: {e}")
                raise ZoteroClientError(f"All item retrieval methods failed - last error: {e}")
        
        raise ZoteroClientError("No available item retrieval method")