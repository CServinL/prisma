"""
Zotero API Client

This module provides a wrapper around the pyzotero library for accessing
Zotero Web API v3. It handles authentication, library access, and data
retrieval for integration with the Prisma literature review system.

Key Features:
- Library and group access via API keys
- Collections and items browsing
- Search and filtering capabilities  
- Rate limiting and error handling
- Data format standardization
"""

from typing import List, Dict, Any, Optional, Union
import logging
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

try:
    from pyzotero import zotero
except ImportError:
    zotero = None

# Import Pydantic models
from ...storage.models.zotero_models import ZoteroCollection, ZoteroItem, ZoteroAttachment

logger = logging.getLogger(__name__)


class ZoteroAPIConfig(BaseModel):
    """Configuration for Zotero API client with validation"""
    api_key: str = Field(..., description="Zotero API key")
    library_id: str = Field(..., description="Zotero library ID")
    library_type: str = Field("user", description="Library type: 'user' or 'group'")
    api_version: int = Field(3, description="Zotero API version")
    
    @field_validator('library_type')
    @classmethod
    def validate_library_type(cls, v):
        if v not in ('user', 'group'):
            raise ValueError('library_type must be "user" or "group"')
        return v
    
    @field_validator('api_version')
    @classmethod
    def validate_api_version(cls, v):
        if v != 3:
            raise ValueError('Only API version 3 is supported')
        return v


class ZoteroClientError(Exception):
    """Base exception for Zotero client errors"""
    pass


class ZoteroClient:
    """
    Zotero API client wrapper using pyzotero
    
    Provides high-level access to Zotero libraries, collections, and items
    with error handling and rate limiting.
    """
    
    def __init__(self, config: ZoteroAPIConfig):
        """
        Initialize Zotero client
        
        Args:
            config: ZoteroAPIConfig with API credentials and settings
            
        Raises:
            ZoteroClientError: If pyzotero is not installed or config is invalid
        """
        if zotero is None:
            raise ZoteroClientError(
                "pyzotero is required for Zotero integration. "
                "Install with: pip install pyzotero"
            )
            
        self.config = config
        self._client = None
        self._initialize_client()
        
    def _initialize_client(self):
        """Initialize the pyzotero client"""
        try:
            self._client = zotero.Zotero(
                library_id=self.config.library_id,
                library_type=self.config.library_type,
                api_key=self.config.api_key
            )
            logger.info(f"Initialized Zotero client for {self.config.library_type} library {self.config.library_id}")
        except Exception as e:
            raise ZoteroClientError(f"Failed to initialize Zotero client: {e}")
    
    def test_connection(self) -> bool:
        """
        Test the Zotero API connection
        
        Returns:
            bool: True if connection is successful
        """
        try:
            # Try to get library info
            info = self._client.key_info()
            logger.info(f"Zotero connection successful: {info}")
            return True
        except Exception as e:
            logger.error(f"Zotero connection failed: {e}")
            return False
    
    def get_collections(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve collections from the library
        
        Args:
            limit: Maximum number of collections to retrieve
            
        Returns:
            List of collection data dictionaries
        """
        try:
            collections = self._client.collections(limit=limit)
            logger.info(f"Retrieved {len(collections)} collections")
            return collections
        except Exception as e:
            logger.error(f"Failed to retrieve collections: {e}")
            raise ZoteroClientError(f"Failed to retrieve collections: {e}")
    
    def get_items(self, limit: int = 100, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve items from the library
        
        Args:
            limit: Maximum number of items to retrieve
            item_type: Filter by item type (e.g., "journalArticle", "book")
            
        Returns:
            List of item data dictionaries
        """
        try:
            params = {"limit": limit}
            if item_type:
                params["itemType"] = item_type
                
            items = self._client.items(**params)
            logger.info(f"Retrieved {len(items)} items")
            return items
        except Exception as e:
            logger.error(f"Failed to retrieve items: {e}")
            raise ZoteroClientError(f"Failed to retrieve items: {e}")
    
    def get_collection_items(self, collection_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve items from a specific collection
        
        Args:
            collection_key: Zotero collection key
            limit: Maximum number of items to retrieve
            
        Returns:
            List of item data dictionaries
        """
        try:
            items = self._client.collection_items(collection_key, limit=limit)
            logger.info(f"Retrieved {len(items)} items from collection {collection_key}")
            return items
        except Exception as e:
            logger.error(f"Failed to retrieve collection items: {e}")
            raise ZoteroClientError(f"Failed to retrieve collection items: {e}")
    
    def search_items(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search for items in the library
        
        Args:
            query: Search query string
            limit: Maximum number of items to retrieve
            
        Returns:
            List of matching item data dictionaries
        """
        try:
            items = self._client.items(q=query, limit=limit)
            logger.info(f"Found {len(items)} items matching '{query}'")
            return items
        except Exception as e:
            logger.error(f"Failed to search items: {e}")
            raise ZoteroClientError(f"Failed to search items: {e}")
    
    def get_item(self, item_key: str) -> Dict[str, Any]:
        """
        Retrieve a specific item by key
        
        Args:
            item_key: Zotero item key
            
        Returns:
            Item data dictionary
        """
        try:
            item = self._client.item(item_key)
            logger.info(f"Retrieved item {item_key}")
            return item
        except Exception as e:
            logger.error(f"Failed to retrieve item {item_key}: {e}")
            raise ZoteroClientError(f"Failed to retrieve item {item_key}: {e}")
    
    def get_tags(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve tags from the library
        
        Args:
            limit: Maximum number of tags to retrieve
            
        Returns:
            List of tag data dictionaries
        """
        try:
            tags = self._client.tags(limit=limit)
            logger.info(f"Retrieved {len(tags)} tags")
            return tags
        except Exception as e:
            logger.error(f"Failed to retrieve tags: {e}")
            raise ZoteroClientError(f"Failed to retrieve tags: {e}")
    
    def get_item_tags(self, item_key: str) -> List[Dict[str, Any]]:
        """
        Retrieve tags for a specific item
        
        Args:
            item_key: Zotero item key
            
        Returns:
            List of tag data dictionaries
        """
        try:
            tags = self._client.item_tags(item_key)
            logger.info(f"Retrieved {len(tags)} tags for item {item_key}")
            return tags
        except Exception as e:
            logger.error(f"Failed to retrieve item tags: {e}")
            raise ZoteroClientError(f"Failed to retrieve item tags: {e}")
    
    def create_collection(self, collection_data: Dict[str, Any]) -> Optional[ZoteroCollection]:
        """
        Create a new collection using pyzotero
        
        Args:
            collection_data: Collection data dictionary with 'name' and optional 'parentCollection'
            
        Returns:
            Created ZoteroCollection model or None if failed
        """
        try:
            if self._client is None:
                logger.error("Zotero client not initialized")
                return None
                
            # pyzotero expects a list of collection objects
            template = [collection_data]
            created = self._client.create_collections(template)
            
            # Check if creation was successful
            if created and 'successful' in created and created['successful']:
                # Get the first successful collection
                first_key = list(created['successful'].keys())[0]
                collection = created['successful'][first_key]
                
                collection_name = collection.get('data', {}).get('name', 'Unknown')
                collection_key = collection.get('key', 'Unknown')
                
                logger.info(f"Created collection: {collection_name} with key {collection_key}")
                
                # Return a proper Pydantic model
                return ZoteroCollection.from_zotero_data(collection)
            else:
                logger.error(f"Failed to create collection: {created}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            return None

    def delete_collection(self, collection_key: str) -> bool:
        """
        Delete a collection using pyzotero
        
        Args:
            collection_key: The key of the collection to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if self._client is None:
                logger.error("Zotero client not initialized")
                return False
                
            # Get the collection first to get its version (required for deletion)
            try:
                collection = self._client.collection(collection_key)
                if not collection:
                    logger.error(f"Collection {collection_key} not found")
                    return False
            except Exception as e:
                logger.error(f"Failed to fetch collection {collection_key} for deletion: {e}")
                return False
                
            # Delete using the collection key
            result = self._client.delete_collection(collection)
            logger.info(f"Successfully deleted collection: {collection_key}")
            return True
                
        except Exception as e:
            logger.error(f"Failed to delete collection {collection_key}: {e}")
            return False

    def create_item(self, item_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a new item in the Zotero library
        
        Args:
            item_data: Item data dictionary with required fields like 'itemType', 'title', etc.
            
        Returns:
            Created item key if successful, None if failed
        """
        try:
            if self._client is None:
                logger.error("Zotero client not initialized")
                return None
            
            # Validate required fields
            if 'itemType' not in item_data:
                logger.error("Item data must include 'itemType'")
                return None
            
            # Use pyzotero to create the item
            result = self._client.create_items([item_data])
            
            if result and isinstance(result, dict):
                # The create_items method returns a complex result dictionary
                # Check if there are successful items
                successful = result.get('successful', {})
                success = result.get('success', {})
                
                if successful and '0' in successful:
                    # Extract the key from the successful item
                    item_key = successful['0']['key']
                    logger.info(f"Successfully created item: {item_key}")
                    return item_key
                elif success and '0' in success:
                    # Alternative format - key is the value
                    item_key = success['0']
                    logger.info(f"Successfully created item: {item_key}")
                    return item_key
                else:
                    logger.error(f"No successful items in result: {result}")
                    return None
            else:
                logger.error(f"Failed to create item: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to create item: {e}")
            return None

    def delete_item(self, item_key: str) -> bool:
        """
        Delete an item from the Zotero library using web API
        
        Args:
            item_key: Zotero item key
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if self._client is None:
                logger.error("Zotero client not initialized")
                return False
            
            # Get the item to get its version for deletion
            item = self._client.item(item_key)
            if not item:
                logger.error(f"Item {item_key} not found")
                return False
            
            # Delete the item using pyzotero
            result = self._client.delete_item(item)
            
            if result:
                logger.info(f"Successfully deleted item {item_key}")
                return True
            else:
                logger.error(f"Failed to delete item {item_key}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete item {item_key}: {e}")
            return False