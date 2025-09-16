"""
Zotero Desktop App Integration Client

This module integrates with Zotero's desktop application HTTP server to save
items directly to the user's Zotero library. This approach maintains 100%
compatibility with Zotero and preserves data integrity.

Key Features:
- Uses Zotero's built-in HTTP server (localhost:23119)
- Saves items through official Zotero connector API
- Maintains sync integrity with Zotero servers
- No database corruption risk
- Future-proof integration
"""

import logging
import json
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ZoteroDesktopConfig(BaseModel):
    """Configuration for Zotero desktop app integration"""
    server_url: str = Field("http://127.0.0.1:23119", description="Zotero HTTP server URL")
    timeout: float = Field(10.0, description="Request timeout in seconds")
    check_running: bool = Field(True, description="Check if Zotero is running before operations")
    collection_key: Optional[str] = Field(None, description="Default collection to save items to")


class ZoteroDesktopError(Exception):
    """Exception raised for Zotero desktop integration errors"""
    pass


class ZoteroDesktopClient:
    """
    Client for integrating with Zotero desktop app via HTTP server
    
    This client mimics the behavior of Zotero browser connectors to save
    items directly to the user's Zotero library through the official API.
    """
    
    def __init__(self, config: ZoteroDesktopConfig):
        """Initialize desktop client"""
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.timeout
        
        if config.check_running:
            self._check_zotero_running()
    
    def _check_zotero_running(self) -> bool:
        """Check if Zotero desktop app is running and accessible"""
        try:
            response = self.session.get(f"{self.config.server_url}/connector/ping")
            if response.status_code == 200:
                logger.info("Zotero desktop app is running and accessible")
                return True
            else:
                raise ZoteroDesktopError(f"Zotero ping failed with status {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise ZoteroDesktopError(
                f"Cannot connect to Zotero desktop app at {self.config.server_url}. "
                f"Please ensure Zotero is running. Error: {e}"
            )
    
    def save_items(self, items: List[Dict[str, Any]], collection_key: Optional[str] = None) -> bool:
        """
        Save items to Zotero library using the connector API
        
        Args:
            items: List of item dictionaries in Zotero format
            collection_key: Optional collection to save items to
            
        Returns:
            bool: True if successful
            
        Raises:
            ZoteroDesktopError: If save operation fails
        """
        if not items:
            logger.warning("No items to save")
            return True
        
        # Use provided collection or default
        target_collection = collection_key or self.config.collection_key
        
        try:
            # Format items for Zotero connector API
            formatted_items = []
            for item in items:
                formatted_item = self._format_item_for_zotero(item)
                if formatted_item:
                    formatted_items.append(formatted_item)
            
            if not formatted_items:
                logger.warning("No valid items to save after formatting")
                return False
            
            # Prepare request data
            request_data = {
                "items": formatted_items,
                "uri": "https://prisma.ai/literature-review",  # Source identifier
                "sessionID": f"prisma-{int(time.time())}"
            }
            
            # Add collection if specified
            if target_collection:
                request_data["collection"] = target_collection
            
            # Send to Zotero
            response = self.session.post(
                f"{self.config.server_url}/connector/saveItems",
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "X-Zotero-Connector-API-Version": "3"
                }
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully saved {len(formatted_items)} items to Zotero")
                return True
            else:
                raise ZoteroDesktopError(
                    f"Failed to save items. Status: {response.status_code}, "
                    f"Response: {response.text}"
                )
                
        except requests.exceptions.RequestException as e:
            raise ZoteroDesktopError(f"Network error while saving items: {e}")
        except Exception as e:
            raise ZoteroDesktopError(f"Unexpected error while saving items: {e}")
    
    def _format_item_for_zotero(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert item to Zotero connector format
        
        This method transforms items from various sources (Web API, external APIs)
        into the format expected by Zotero's connector API.
        """
        try:
            # Handle different input formats
            if "data" in item:
                # Already in Zotero API format
                zotero_item = item["data"].copy()
            else:
                # Convert from simplified format
                zotero_item = item.copy()
            
            # Check for non-serializable objects
            import json
            try:
                json.dumps(zotero_item)
            except (TypeError, ValueError):
                logger.warning(f"Item contains non-serializable objects: {list(zotero_item.keys())}")
                return None
            
            # Ensure required fields
            if "itemType" not in zotero_item:
                zotero_item["itemType"] = "journalArticle"  # Default type
            
            # Ensure creators are in correct format
            if "creators" in zotero_item:
                formatted_creators = []
                for creator in zotero_item["creators"]:
                    if isinstance(creator, str):
                        # Convert string to creator object
                        formatted_creators.append({
                            "creatorType": "author",
                            "name": creator
                        })
                    else:
                        formatted_creators.append(creator)
                zotero_item["creators"] = formatted_creators
            
            # Add metadata
            zotero_item["accessDate"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Clean up None values
            cleaned_item = {k: v for k, v in zotero_item.items() if v is not None}
            
            return cleaned_item
            
        except Exception as e:
            logger.error(f"Error formatting item: {e}")
            return None
    
    def create_collection(self, name: str, parent_key: Optional[str] = None) -> Optional[str]:
        """
        Create a new collection in Zotero
        
        Note: This requires direct API access since the connector doesn't support
        collection creation. This method would need Web API credentials.
        """
        logger.warning("Collection creation via desktop client not yet implemented")
        return None
    
    def get_collections(self) -> List[Dict[str, Any]]:
        """
        Get available collections
        
        Note: The connector HTTP server doesn't provide read access.
        Use the SQLite client or Web API for reading collections.
        """
        logger.warning("Reading collections via desktop client not supported")
        return []
    
    def is_running(self) -> bool:
        """Check if Zotero desktop app is running"""
        try:
            self._check_zotero_running()
            return True
        except ZoteroDesktopError:
            return False


# Example usage
def example_save_to_zotero():
    """Example of saving items to Zotero desktop app"""
    
    # Configure desktop client
    config = ZoteroDesktopConfig(
        check_running=True,
        collection_key=None  # Save to root library
    )
    
    try:
        client = ZoteroDesktopClient(config)
        
        # Example items from Web API or external sources
        items = [
            {
                "itemType": "journalArticle",
                "title": "Example Paper Found via Prisma",
                "creators": [
                    {"creatorType": "author", "firstName": "John", "lastName": "Doe"}
                ],
                "date": "2024",
                "DOI": "10.1000/example",
                "abstractNote": "This paper was discovered by Prisma and saved to Zotero.",
                "url": "https://example.com/paper"
            }
        ]
        
        # Save to Zotero
        success = client.save_items(items)
        if success:
            print("✅ Items saved to Zotero successfully!")
        
    except ZoteroDesktopError as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure Zotero desktop app is running")


if __name__ == "__main__":
    example_save_to_zotero()