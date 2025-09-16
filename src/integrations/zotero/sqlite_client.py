"""
Zotero SQLite Database Client

This module provides direct access to Zotero's local SQLite database for offline
literature review operations. It implements the core functionality needed for
Day 2 MVP: "SQLite reading + search" for local library access.

Key Features:
- Direct SQLite database reading (offline operation)
- Fast full-text search across papers and metadata
- Collection-based filtering
- No API keys or internet connection required
- Optimized for large libraries with proper indexing

Database Schema Overview:
- items: Main items table with metadata
- itemData/itemDataValues: Field-value pairs for item properties
- creators: Authors, editors, translators, etc.
- collections: User-defined collections
- itemTypes: Document types (journal article, book, etc.)
"""

import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from contextlib import contextmanager

from pydantic import BaseModel, Field, field_validator
from ...storage.models.zotero_models import ZoteroItem, ZoteroCollection, ZoteroCreator, ZoteroTag

logger = logging.getLogger(__name__)


class ZoteroSQLiteConfig(BaseModel):
    """Configuration for Zotero SQLite client"""
    library_path: str = Field(..., description="Path to zotero.sqlite database file")
    cache_size: int = Field(10000, description="SQLite cache size for performance")
    timeout: float = Field(30.0, description="Database connection timeout in seconds")
    read_only: bool = Field(True, description="Open database in read-only mode for safety")
    
    @field_validator('library_path')
    @classmethod
    def validate_library_path(cls, v):
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Zotero database not found at: {v}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {v}")
        if not str(path).endswith('.sqlite'):
            raise ValueError(f"Expected .sqlite file, got: {v}")
        return str(path)


class ZoteroSQLiteError(Exception):
    """Base exception for Zotero SQLite client errors"""
    pass


class ZoteroSQLiteClient:
    """
    Direct SQLite client for Zotero database access
    
    Provides offline access to local Zotero libraries with fast search capabilities.
    Designed for MVP requirements: simple, fast, and reliable local library access.
    """
    
    def __init__(self, config: ZoteroSQLiteConfig):
        """
        Initialize Zotero SQLite client
        
        Args:
            config: ZoteroSQLiteConfig with database path and settings
        """
        self.config = config
        self._db_path = config.library_path
        self._field_cache = {}  # Cache for field name lookups
        self._type_cache = {}   # Cache for item type lookups
        
        # Test connection on initialization
        self._test_connection()
        logger.info(f"Initialized Zotero SQLite client: {self._db_path}")
    
    def _test_connection(self):
        """Test database connection and validate schema"""
        try:
            with self._get_connection() as conn:
                # Check if main tables exist
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name IN ('items', 'itemData', 'collections')
                """)
                tables = [row[0] for row in cursor.fetchall()]
                
                if len(tables) < 3:
                    raise ZoteroSQLiteError(
                        f"Invalid Zotero database: missing required tables. Found: {tables}"
                    )
                
                logger.info(f"Database connection successful. Tables found: {tables}")
                
        except sqlite3.Error as e:
            raise ZoteroSQLiteError(f"Failed to connect to database: {e}")
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper configuration"""
        conn = None
        try:
            # Configure connection for read-only access and performance
            uri = f"file:{self._db_path}?mode=ro" if self.config.read_only else self._db_path
            conn = sqlite3.connect(
                uri, 
                timeout=self.config.timeout,
                uri=True
            )
            
            # Optimize for read performance
            conn.execute(f"PRAGMA cache_size = {self.config.cache_size}")
            conn.execute("PRAGMA temp_store = memory")
            conn.execute("PRAGMA mmap_size = 268435456")  # 256MB memory mapping
            
            # Enable foreign key support
            conn.execute("PRAGMA foreign_keys = ON")
            
            yield conn
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise ZoteroSQLiteError(f"Database error: {e}")
        finally:
            if conn:
                conn.close()
    
    def _get_field_id(self, field_name: str) -> Optional[int]:
        """Get field ID for given field name with caching"""
        if field_name in self._field_cache:
            return self._field_cache[field_name]
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT fieldID FROM fields WHERE fieldName = ?", 
                (field_name,)
            )
            result = cursor.fetchone()
            
            field_id = result[0] if result else None
            self._field_cache[field_name] = field_id
            return field_id
    
    def _get_item_type_name(self, type_id: int) -> str:
        """Get item type name from type ID with caching"""
        if type_id in self._type_cache:
            return self._type_cache[type_id]
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT typeName FROM itemTypes WHERE itemTypeID = ?", 
                (type_id,)
            )
            result = cursor.fetchone()
            
            type_name = result[0] if result else "unknown"
            self._type_cache[type_id] = type_name
            return type_name
    
    def get_library_stats(self) -> Dict[str, Any]:
        """Get basic statistics about the Zotero library"""
        with self._get_connection() as conn:
            stats = {}
            
            # Total items
            cursor = conn.execute("SELECT COUNT(*) FROM items WHERE itemTypeID != 14")  # 14 = attachment
            stats['total_items'] = cursor.fetchone()[0]
            
            # Total collections
            cursor = conn.execute("SELECT COUNT(*) FROM collections")
            stats['total_collections'] = cursor.fetchone()[0]
            
            # Items by type
            cursor = conn.execute("""
                SELECT it.typeName, COUNT(*) as count
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE i.itemTypeID != 14
                GROUP BY it.typeName
                ORDER BY count DESC
            """)
            stats['items_by_type'] = dict(cursor.fetchall())
            
            logger.info(f"Library stats: {stats}")
            return stats
    
    def search_items(self, 
                    query: str = None,
                    collection_keys: List[str] = None,
                    item_types: List[str] = None,
                    limit: int = 100,
                    offset: int = 0) -> List[Dict[str, Any]]:
        """
        Search for items in the Zotero library
        
        Args:
            query: Text search query (searches title, abstract, creators)
            collection_keys: Filter by collection keys
            item_types: Filter by item types (e.g., 'journalArticle', 'book')
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            List of item dictionaries with basic metadata
        """
        with self._get_connection() as conn:
            # Build the search query
            where_conditions = ["i.itemTypeID != 14"]  # Exclude attachments
            params = []
            
            # Add text search
            if query:
                # Search in title and abstract
                title_field_id = self._get_field_id('title')
                abstract_field_id = self._get_field_id('abstractNote')
                
                search_conditions = []
                if title_field_id:
                    search_conditions.append(
                        f"(id.fieldID = {title_field_id} AND idv.value LIKE ?)"
                    )
                    params.append(f"%{query}%")
                
                if abstract_field_id:
                    search_conditions.append(
                        f"(id.fieldID = {abstract_field_id} AND idv.value LIKE ?)"
                    )
                    params.append(f"%{query}%")
                
                if search_conditions:
                    where_conditions.append(f"({' OR '.join(search_conditions)})")
            
            # Add collection filter
            if collection_keys:
                placeholders = ','.join('?' * len(collection_keys))
                where_conditions.append(f"""
                    i.itemID IN (
                        SELECT ci.itemID FROM collectionItems ci 
                        WHERE ci.collectionID IN (
                            SELECT collectionID FROM collections 
                            WHERE key IN ({placeholders})
                        )
                    )
                """)
                params.extend(collection_keys)
            
            # Add item type filter
            if item_types:
                placeholders = ','.join('?' * len(item_types))
                where_conditions.append(f"""
                    i.itemTypeID IN (
                        SELECT itemTypeID FROM itemTypes 
                        WHERE typeName IN ({placeholders})
                    )
                """)
                params.extend(item_types)
            
            # Build final query
            base_query = """
                SELECT DISTINCT i.itemID, i.key, i.itemTypeID, i.dateAdded, i.dateModified
                FROM items i
            """
            
            # Add joins if we're doing text search
            if query:
                base_query += """
                    LEFT JOIN itemData id ON i.itemID = id.itemID
                    LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
                """
            
            # Add WHERE clause
            where_clause = " AND ".join(where_conditions)
            query_sql = f"{base_query} WHERE {where_clause}"
            
            # Add ordering and limits
            query_sql += f" ORDER BY i.dateAdded DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            logger.debug(f"Executing search query: {query_sql}")
            logger.debug(f"Parameters: {params}")
            
            cursor = conn.execute(query_sql, params)
            results = []
            
            for row in cursor.fetchall():
                item_id, key, type_id, date_added, date_modified = row
                
                # Get basic item data
                item_data = {
                    'itemID': item_id,
                    'key': key,
                    'itemType': self._get_item_type_name(type_id),
                    'dateAdded': date_added,
                    'dateModified': date_modified
                }
                
                # Get field data
                field_cursor = conn.execute("""
                    SELECT f.fieldName, idv.value
                    FROM itemData id
                    JOIN fields f ON id.fieldID = f.fieldID
                    JOIN itemDataValues idv ON id.valueID = idv.valueID
                    WHERE id.itemID = ?
                """, (item_id,))
                
                for field_name, value in field_cursor.fetchall():
                    item_data[field_name] = value
                
                results.append(item_data)
            
            logger.info(f"Found {len(results)} items matching search criteria")
            return results
    
    def get_collections(self) -> List[Dict[str, Any]]:
        """Get all collections from the library"""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT collectionID, collectionName, key, parentCollectionID
                FROM collections
                ORDER BY collectionName
            """)
            
            collections = []
            for row in cursor.fetchall():
                coll_id, name, key, parent_id = row
                collections.append({
                    'collectionID': coll_id,
                    'name': name,
                    'key': key,
                    'parentCollectionID': parent_id
                })
            
            logger.info(f"Retrieved {len(collections)} collections")
            return collections
    
    def get_item_by_key(self, item_key: str) -> Optional[Dict[str, Any]]:
        """Get a specific item by its key"""
        items = self.search_items(limit=1)  # This will need to be modified
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT itemID, key, itemTypeID, dateAdded, dateModified
                FROM items
                WHERE key = ? AND itemTypeID != 14
            """, (item_key,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            item_id, key, type_id, date_added, date_modified = result
            
            # Get all field data for this item
            item_data = {
                'itemID': item_id,
                'key': key,
                'itemType': self._get_item_type_name(type_id),
                'dateAdded': date_added,
                'dateModified': date_modified
            }
            
            # Get field values
            field_cursor = conn.execute("""
                SELECT f.fieldName, idv.value
                FROM itemData id
                JOIN fields f ON id.fieldID = f.fieldID
                JOIN itemDataValues idv ON id.valueID = idv.valueID
                WHERE id.itemID = ?
            """, (item_id,))
            
            for field_name, value in field_cursor.fetchall():
                item_data[field_name] = value
            
            # Get creators
            creator_cursor = conn.execute("""
                SELECT ct.creatorType, c.firstName, c.lastName
                FROM itemCreators ic
                JOIN creators c ON ic.creatorID = c.creatorID
                JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
                WHERE ic.itemID = ?
                ORDER BY ic.orderIndex
            """, (item_id,))
            
            creators = []
            for creator_type, first_name, last_name in creator_cursor.fetchall():
                creators.append({
                    'creatorType': creator_type,
                    'firstName': first_name,
                    'lastName': last_name
                })
            
            if creators:
                item_data['creators'] = creators
            
            logger.debug(f"Retrieved item {item_key}: {item_data.get('title', 'No title')}")
            return item_data
    
    def get_collection_items(self, collection_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all items in a specific collection"""
        return self.search_items(collection_keys=[collection_key], limit=limit)
    
    def close(self):
        """Close any cached connections"""
        # Clear caches
        self._field_cache.clear()
        self._type_cache.clear()
        logger.info("Zotero SQLite client closed")