"""
Zotero Agent

This module provides the ZoteroAgent class that integrates Zotero libraries
with the Prisma literature review system. It handles searching, filtering,
and retrieving papers from Zotero collections for analysis.
"""

import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from pydantic import BaseModel, Field, field_validator

from ..utils.config import ZoteroConfig
from ..integrations.zotero import ZoteroClient, ZoteroAPIConfig, ZoteroClientError
from ..storage.models import ZoteroItem, ZoteroCollection, ZoteroItemType

logger = logging.getLogger(__name__)


class ZoteroSearchCriteria(BaseModel):
    """Search criteria for Zotero agent with validation"""
    query: Optional[str] = Field(None, description="Search query string")
    collections: Optional[List[str]] = Field(None, description="Collection keys to search")
    item_types: Optional[List[str]] = Field(None, description="Item types to include")
    tags: Optional[List[str]] = Field(None, description="Tags to filter by")
    date_range: Optional[Tuple[int, int]] = Field(None, description="Date range as (start_year, end_year)")
    limit: int = Field(100, ge=1, le=1000, description="Maximum number of results")
    
    @field_validator('item_types')
    @classmethod
    def validate_item_types(cls, v):
        if v is None:
            return v
        valid_types = [item_type.value for item_type in ZoteroItemType]
        for item_type in v:
            if item_type not in valid_types:
                raise ValueError(f'item_type "{item_type}" not in valid types: {valid_types}')
        return v
    
    @field_validator('date_range')
    @classmethod
    def validate_date_range(cls, v):
        if v is None:
            return v
        start_year, end_year = v
        if start_year > end_year:
            raise ValueError('start_year must be <= end_year')
        if start_year < 1000 or end_year > 3000:
            raise ValueError('Years must be between 1000 and 3000')
        return v


class ZoteroAgent:
    """
    Agent for interacting with Zotero libraries
    
    Provides high-level search and retrieval capabilities for integrating
    Zotero data with the Prisma literature review workflow.
    """
    
    def __init__(self, config: ZoteroConfig):
        """
        Initialize ZoteroAgent
        
        Args:
            config: ZoteroConfig with API credentials
        """
        self.config = config
        
        # Validate required fields
        if not config.api_key or not config.library_id:
            raise ValueError("ZoteroConfig must have api_key and library_id for API access")
        
        # Convert to API-specific config for the client
        api_config = ZoteroAPIConfig(
            api_key=config.api_key,
            library_id=config.library_id,
            library_type=config.library_type,
            api_version=3
        )
        self.client = ZoteroClient(api_config)
        self._collections_cache: Optional[List[ZoteroCollection]] = None
        
        logger.info(f"Initialized ZoteroAgent for {config.library_type} library {config.library_id}")
    
    def test_connection(self) -> bool:
        """Test Zotero connection"""
        return self.client.test_connection()
    
    def get_collections(self, refresh_cache: bool = False) -> List[ZoteroCollection]:
        """
        Get all collections in the library
        
        Args:
            refresh_cache: Whether to refresh the collections cache
            
        Returns:
            List of ZoteroCollection objects
        """
        if self._collections_cache is None or refresh_cache:
            try:
                collection_data = self.client.get_collections()
                self._collections_cache = [
                    ZoteroCollection.from_zotero_data(data) 
                    for data in collection_data
                ]
                logger.info(f"Loaded {len(self._collections_cache)} collections")
            except ZoteroClientError as e:
                logger.error(f"Failed to load collections: {e}")
                return []
        
        return self._collections_cache or []
    
    def find_collections_by_name(self, name_pattern: str) -> List[ZoteroCollection]:
        """
        Find collections matching a name pattern
        
        Args:
            name_pattern: Pattern to match (case-insensitive substring)
            
        Returns:
            List of matching collections
        """
        collections = self.get_collections()
        name_lower = name_pattern.lower()
        
        matching = [
            collection for collection in collections
            if name_lower in collection.name.lower()
        ]
        
        logger.info(f"Found {len(matching)} collections matching '{name_pattern}'")
        return matching
    
    def search_papers(self, criteria: ZoteroSearchCriteria) -> List[ZoteroItem]:
        """
        Search for papers based on criteria
        
        Args:
            criteria: ZoteroSearchCriteria object defining search parameters
            
        Returns:
            List of ZoteroItem objects matching criteria
        """
        papers = []
        
        try:
            # If specific collections are requested
            if criteria.collections:
                for collection_key in criteria.collections:
                    items = self.client.get_collection_items(collection_key, limit=criteria.limit)
                    papers.extend([ZoteroItem.from_zotero_data(item) for item in items])
            
            # If query search is requested
            elif criteria.query:
                items = self.client.search_items(criteria.query, limit=criteria.limit)
                papers.extend([ZoteroItem.from_zotero_data(item) for item in items])
            
            # Otherwise get all items
            else:
                items = self.client.get_items(limit=criteria.limit)
                papers.extend([ZoteroItem.from_zotero_data(item) for item in items])
            
            # Apply additional filters
            papers = self._apply_filters(papers, criteria)
            
            logger.info(f"Found {len(papers)} papers matching search criteria")
            return papers
            
        except ZoteroClientError as e:
            logger.error(f"Failed to search papers: {e}")
            return []
    
    def _apply_filters(self, papers: List[ZoteroItem], criteria: ZoteroSearchCriteria) -> List[ZoteroItem]:
        """Apply additional filtering to papers"""
        filtered = papers
        
        # Filter by item types
        if criteria.item_types:
            filtered = [p for p in filtered if p.item_type in criteria.item_types]
            logger.debug(f"After item type filter: {len(filtered)} papers")
        
        # Filter by tags
        if criteria.tags:
            tag_set = set(tag.lower() for tag in criteria.tags)
            filtered = [
                p for p in filtered
                if any(tag.tag.lower() in tag_set for tag in p.tags)
            ]
            logger.debug(f"After tag filter: {len(filtered)} papers")
        
        # Filter by date range
        if criteria.date_range:
            start_year, end_year = criteria.date_range
            filtered = [
                p for p in filtered
                if p.year and start_year <= p.year <= end_year
            ]
            logger.debug(f"After date filter: {len(filtered)} papers")
        
        return filtered
    
    def get_academic_papers(self, limit: int = 100) -> List[ZoteroItem]:
        """
        Get only academic papers (journal articles, conference papers, etc.)
        
        Args:
            limit: Maximum number of papers to retrieve
            
        Returns:
            List of academic papers
        """
        criteria = ZoteroSearchCriteria(
            item_types=[
                ZoteroItemType.JOURNAL_ARTICLE.value,
                ZoteroItemType.CONFERENCE_PAPER.value,
                ZoteroItemType.PREPRINT.value,
                ZoteroItemType.THESIS.value
            ],
            limit=limit
        )
        
        return self.search_papers(criteria)
    
    def get_papers_by_topic(self, topic: str, limit: int = 100) -> List[ZoteroItem]:
        """
        Search for papers related to a specific topic
        
        Args:
            topic: Research topic to search for
            limit: Maximum number of papers to retrieve
            
        Returns:
            List of papers related to the topic
        """
        criteria = ZoteroSearchCriteria(
            query=topic,
            limit=limit
        )
        
        # Also search in collections that might contain the topic
        relevant_collections = self.find_collections_by_name(topic)
        if relevant_collections:
            collection_keys = [c.key for c in relevant_collections[:3]]  # Limit to top 3
            criteria.collections = collection_keys
            logger.info(f"Including {len(collection_keys)} relevant collections")
        
        return self.search_papers(criteria)
    
    def get_recent_papers(self, years_back: int = 5, limit: int = 100) -> List[ZoteroItem]:
        """
        Get recent papers from the library
        
        Args:
            years_back: How many years back to search
            limit: Maximum number of papers to retrieve
            
        Returns:
            List of recent papers
        """
        from datetime import datetime
        current_year = datetime.now().year
        start_year = current_year - years_back
        
        criteria = ZoteroSearchCriteria(
            date_range=(start_year, current_year),
            limit=limit
        )
        
        return self.search_papers(criteria)
    
    def get_library_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the Zotero library
        
        Returns:
            Dictionary with library statistics and information
        """
        try:
            collections = self.get_collections()
            
            # Get a sample of items to analyze
            sample_items = self.client.get_items(limit=50)
            items = [ZoteroItem.from_zotero_data(item) for item in sample_items]
            
            # Analyze item types
            item_types = {}
            academic_papers = 0
            years = []
            
            for item in items:
                item_types[item.item_type] = item_types.get(item.item_type, 0) + 1
                if item.is_academic_paper:
                    academic_papers += 1
                if item.year:
                    years.append(item.year)
            
            year_range = (min(years), max(years)) if years else None
            
            summary = {
                "library_id": self.config.library_id,
                "library_type": self.config.library_type,
                "collections_count": len(collections),
                "sample_items_count": len(items),
                "academic_papers_in_sample": academic_papers,
                "item_types": item_types,
                "year_range": year_range,
                "collections": [
                    {
                        "key": c.key,
                        "name": c.name,
                        "parent": c.parent_collection
                    }
                    for c in collections
                ]
            }
            
            logger.info(f"Generated library summary: {summary['collections_count']} collections, "
                       f"{summary['sample_items_count']} items sampled")
            
            return summary
            
        except ZoteroClientError as e:
            logger.error(f"Failed to generate library summary: {e}")
            return {
                "error": str(e),
                "library_id": self.config.library_id,
                "library_type": self.config.library_type
            }
    
    def export_papers_metadata(self, papers: List[ZoteroItem]) -> List[Dict[str, Any]]:
        """
        Export papers metadata in a standardized format
        
        Args:
            papers: List of ZoteroItem objects
            
        Returns:
            List of dictionaries with standardized paper metadata
        """
        return [paper.to_dict() for paper in papers]