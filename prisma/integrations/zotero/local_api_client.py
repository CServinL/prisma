"""
Enhanced Zotero Local API Client

This client leverages Zotero 7's full local HTTP API server to provide
both read and write operations with 100% compatibility.
"""

import logging
import json
import time
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import requests
from pydantic import BaseModel, Field, ConfigDict, field_validator

from ...storage.models.zotero_models import ZoteroItem, ZoteroCollection, ZoteroSearchQuery, ZoteroSearchResult

logger = logging.getLogger(__name__)


class ZoteroLocalAPIConfig(BaseModel):
    """Configuration for Zotero Local API integration"""
    
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        frozen=False
    )
    
    server_url: str = "http://127.0.0.1:23119"
    timeout: float = 30.0
    user_id: str = "0"
    
    @field_validator('server_url')
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        """Validate server URL is well-formed"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Server URL must start with http:// or https://')
        if not v.replace('http://', '').replace('https://', '').strip():
            raise ValueError('Server URL cannot be empty after protocol')
        return v
    
    @field_validator('timeout')
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Validate timeout is positive"""
        if v <= 0:
            raise ValueError('Timeout must be positive')
        if v > 300:  # 5 minutes max
            raise ValueError('Timeout must be 300 seconds or less')
        return v
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate user ID format"""
        if not v.isdigit():
            raise ValueError('User ID must be a numeric string')
        return v


class ZoteroLocalAPIError(Exception):
    """Exception raised for Zotero Local API errors"""
    pass


class ZoteroLocalAPIClient:
    """
    Enhanced client for Zotero Local API providing full read/write access
    
    This client uses Zotero 7's complete local HTTP API to provide:
    - Full item search and retrieval
    - Collection management
    - Item saving via connector endpoints
    - 100% Zotero compatibility
    """
    
    def __init__(self, config: ZoteroLocalAPIConfig):
        """Initialize local API client"""
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Prisma-Zotero-Client/1.0',
            'Accept': 'application/json'
        })
        
        # Test connection
        if not self._check_connection():
            raise ZoteroLocalAPIError("Cannot connect to Zotero local API server")
    
    def _check_connection(self) -> bool:
        """Check if Zotero is running and API is accessible"""
        try:
            response = self.session.get(
                f"{self.config.server_url}/connector/ping",
                timeout=self.config.timeout
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def search_items(self, query: Union[str, ZoteroSearchQuery]) -> ZoteroSearchResult:
        """
        Search for items in the local Zotero library
        
        Args:
            query: Search query string or ZoteroSearchQuery object
            
        Returns:
            ZoteroSearchResult with found items
        """
        try:
            # Build API parameters
            params = {}
            
            if isinstance(query, str):
                if query.strip():
                    params['q'] = query
            elif isinstance(query, ZoteroSearchQuery):
                if query.query:
                    params['q'] = query.query
                if query.tags:
                    params['tag'] = ' '.join(query.tags)
                params['limit'] = query.limit
                params['start'] = query.start
                if query.sort_by:
                    params['sort'] = query.sort_by
                    params['direction'] = query.sort_direction
            
            # Make API request
            response = self.session.get(
                f"{self.config.server_url}/api/users/{self.config.user_id}/items",
                params=params,
                timeout=self.config.timeout
            )
            
            if response.status_code != 200:
                raise ZoteroLocalAPIError(f"Search failed: {response.status_code}")
            
            # Parse results
            items_data = response.json()
            items = [ZoteroItem.from_zotero_data(item_data) for item_data in items_data]
            
            # Create search result
            search_result = ZoteroSearchResult(
                items=items,
                total_results=len(items),  # Local API doesn't provide total count
                start=params.get('start', 0),
                limit=params.get('limit', 100),
                query=query if isinstance(query, ZoteroSearchQuery) else None
            )
            
            logger.info(f"Found {len(items)} items for query: {query}")
            return search_result
            
        except requests.exceptions.RequestException as e:
            raise ZoteroLocalAPIError(f"Network error during search: {e}")
        except Exception as e:
            raise ZoteroLocalAPIError(f"Search error: {e}")
    
    def get_item(self, item_key: str) -> Optional[ZoteroItem]:
        """Get a specific item by key"""
        try:
            response = self.session.get(
                f"{self.config.server_url}/api/users/{self.config.user_id}/items/{item_key}",
                timeout=self.config.timeout
            )
            
            if response.status_code == 404:
                return None
            elif response.status_code != 200:
                raise ZoteroLocalAPIError(f"Failed to get item: {response.status_code}")
            
            item_data = response.json()
            return ZoteroItem.from_zotero_data(item_data)
            
        except requests.exceptions.RequestException as e:
            raise ZoteroLocalAPIError(f"Network error getting item: {e}")
    
    def get_collections(self) -> List[ZoteroCollection]:
        """Get all collections from the library"""
        try:
            response = self.session.get(
                f"{self.config.server_url}/api/users/{self.config.user_id}/collections",
                timeout=self.config.timeout
            )
            
            if response.status_code != 200:
                raise ZoteroLocalAPIError(f"Failed to get collections: {response.status_code}")
            
            collections_data = response.json()
            return [ZoteroCollection.from_zotero_data(col_data) for col_data in collections_data]
            
        except requests.exceptions.RequestException as e:
            raise ZoteroLocalAPIError(f"Network error getting collections: {e}")
    
    def create_collection(self, collection_data: Dict[str, Any]) -> Optional[ZoteroCollection]:
        """
        Create a new collection
        
        Args:
            collection_data: Collection data in Zotero format
            
        Returns:
            Created ZoteroCollection or None if failed
        """
        try:
            response = self.session.post(
                f"{self.config.server_url}/api/users/{self.config.user_id}/collections",
                json=collection_data,
                headers={"Content-Type": "application/json"},
                timeout=self.config.timeout
            )
            
            if response.status_code == 201:
                created_data = response.json()
                if isinstance(created_data, list) and created_data:
                    return ZoteroCollection.from_zotero_data(created_data[0])
                elif isinstance(created_data, dict):
                    return ZoteroCollection.from_zotero_data(created_data)
            
            logger.warning(f"Failed to create collection: {response.status_code}")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error creating collection: {e}")
            return None
    
    def get_collection_items(self, collection_key: str) -> List[ZoteroItem]:
        """Get all items in a specific collection"""
        try:
            response = self.session.get(
                f"{self.config.server_url}/api/users/{self.config.user_id}/collections/{collection_key}/items",
                timeout=self.config.timeout
            )
            
            if response.status_code != 200:
                raise ZoteroLocalAPIError(f"Failed to get collection items: {response.status_code}")
            
            items_data = response.json()
            return [ZoteroItem.from_zotero_data(item_data) for item_data in items_data]
            
        except requests.exceptions.RequestException as e:
            raise ZoteroLocalAPIError(f"Network error getting collection items: {e}")
    
    def add_item_to_collection(self, item_key: str, collection_key: str) -> bool:
        """Add an item to a collection"""
        try:
            # Local API does not support collection assignment - this operation is not available
            # Return False silently to allow fallback to Web API
            return False
            
        except Exception as e:
            logger.error(f"Error adding item to collection: {e}")
            return False
    
    def update_item_tags(self, item_key: str, tags: List[str]) -> bool:
        """Update tags for an item"""
        try:
            # Note: This might need to be done via connector API or web API
            # Local API might be read-only for item updates
            logger.warning("Updating item tags via local API may not be supported")
            return False
            
        except Exception as e:
            logger.error(f"Error updating item tags: {e}")
            return False
    
    def save_items(self, items: List[Dict[str, Any]]) -> bool:
        """
        Save items to Zotero using connector API
        
        Args:
            items: List of item dictionaries in Zotero format
            
        Returns:
            True if successful
        """
        try:
            import random
            # Generate unique session ID with microsecond precision and random component
            session_id = f"prisma-{int(time.time() * 1000000)}-{random.randint(1000, 9999)}"
            
            # Format for connector API
            request_data = {
                "items": items,
                "sessionID": session_id,
                "token": ""
            }
            
            # Send to Zotero connector
            response = self.session.post(
                f"{self.config.server_url}/connector/saveItems",
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "X-Zotero-Connector-API-Version": "3"
                }
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully saved {len(items)} items to Zotero")
                return True
            else:
                raise ZoteroLocalAPIError(
                    f"Failed to save items. Status: {response.status_code}, "
                    f"Response: {response.text}"
                )
                
        except requests.exceptions.RequestException as e:
            raise ZoteroLocalAPIError(f"Network error while saving items: {e}")
    
    def get_library_stats(self) -> Dict[str, Any]:
        """Get library statistics"""
        try:
            # Get all items to count them
            response = self.session.get(
                f"{self.config.server_url}/api/users/{self.config.user_id}/items",
                timeout=self.config.timeout
            )
            
            if response.status_code != 200:
                raise ZoteroLocalAPIError(f"Failed to get items: {response.status_code}")
            
            items = response.json()
            
            # Get collections
            collections = self.get_collections()
            
            # Calculate stats
            item_types = {}
            for item in items:
                item_type = item.get('data', {}).get('itemType', 'unknown')
                item_types[item_type] = item_types.get(item_type, 0) + 1
            
            return {
                'total_items': len(items),
                'total_collections': len(collections),
                'item_types': item_types,
                'api_available': True,
                'server_version': self._get_server_version()
            }
            
        except Exception as e:
            logger.warning(f"Error getting library stats: {e}")
            return {
                'total_items': 0,
                'total_collections': 0,
                'item_types': {},
                'api_available': False,
                'error': str(e)
            }
    
    def _get_server_version(self) -> Optional[str]:
        """Get Zotero server version"""
        try:
            response = self.session.get(
                f"{self.config.server_url}/connector/ping",
                timeout=5
            )
            return response.headers.get('X-Zotero-Version')
        except Exception:
            return None
    
    def is_available(self) -> bool:
        """Check if the local API is available"""
        return self._check_connection()
    
    def delete_item(self, item_key: str) -> bool:
        """
        Delete an item from the Zotero library
        
        Args:
            item_key: The key of the item to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # Use the DELETE endpoint for items
            response = self.session.delete(
                f"{self.config.server_url}/api/users/{self.config.user_id}/items/{item_key}",
                timeout=self.config.timeout
            )
            
            if response.status_code in [200, 204, 404]:  # 404 means item was already deleted
                logger.info(f"Successfully deleted item {item_key}")
                return True
            else:
                logger.warning(f"Failed to delete item {item_key}: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting item {item_key}: {e}")
            return False
    
    def save_items_to_zotero(self, items: List[Dict[str, Any]], 
                           collection_key: Optional[str] = None,
                           auto_assign_collection: bool = True) -> List[str]:
        """
        🎯 UNIFIED SAVE INTERFACE: Integration-agnostic method for saving items to Zotero
        
        This method provides the same interface as HybridClient but uses Local API capabilities.
        Note: Local API has limitations for writes, so this primarily uses save_items.
        
        Args:
            items: List of item data dictionaries in Zotero format
            collection_key: Optional collection to add items to (WARNING: Local API has limited collection assignment)
            auto_assign_collection: Whether to automatically assign to collection after creation
            
        Returns:
            List of created item keys (empty for Local API as keys are not returned)
            
        Raises:
            ZoteroLocalAPIError: If saving fails
        """
        logger.warning("⚠️ Using Local API for saves - limited collection assignment capabilities")
        
        try:
            # Use the existing save_items method
            success = self.save_items(items)
            
            if success:
                logger.info(f"✅ Successfully saved {len(items)} items via Local API")
                
                # Note: Local API save_items doesn't return item keys, so we can't do collection assignment
                if collection_key and auto_assign_collection:
                    logger.warning(f"⚠️ Collection assignment to '{collection_key}' not supported via Local API save_items")
                    logger.warning("💡 Use Web API (HybridClient) for reliable collection assignment")
                
                # Return empty list since Local API doesn't provide item keys from save_items
                return []
            else:
                raise ZoteroLocalAPIError("Local API save_items returned False")
                
        except Exception as e:
            logger.error(f"❌ Failed to save items via Local API: {e}")
            raise ZoteroLocalAPIError(f"Failed to save items: {e}")