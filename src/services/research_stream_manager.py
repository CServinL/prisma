"""
Research Stream Manager

This service manages Research Streams - persistent research topics that use
Zotero Collections and smart tagging for organization and continuous monitoring.
"""

import logging
import json
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from pathlib import Path

from ..storage.models.research_stream_models import (
    ResearchStream, StreamStatus, RefreshFrequency, SmartTag, TagCategory,
    SearchCriteria, StreamUpdateResult, StreamSummary
)
from ..storage.models.zotero_models import ZoteroItem, ZoteroCollection, ZoteroSearchQuery, ZoteroSearchResult
from ..integrations.zotero.hybrid_client import ZoteroHybridClient
from ..utils.config import ConfigLoader

logger = logging.getLogger(__name__)


class ResearchStreamError(Exception):
    """Exception raised for research stream operations"""
    pass


class ResearchStreamManager:
    """
    Manager for Research Streams using Zotero Collections and smart tagging
    
    This service provides:
    - Create and manage research streams
    - Automatic paper discovery and organization
    - Smart tagging strategies
    - Continuous monitoring and updates
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the research stream manager"""
        self.config = ConfigLoader(config_path).load()
        self.zotero_client = ZoteroHybridClient(self.config)
        self.streams_file = Path(self.config.storage.base_path) / "research_streams.json"
        self._streams_cache: Dict[str, ResearchStream] = {}
        self._load_streams()
    
    def _load_streams(self):
        """Load research streams from storage"""
        try:
            if self.streams_file.exists():
                with open(self.streams_file, 'r', encoding='utf-8') as f:
                    streams_data = json.load(f)
                    
                for stream_id, stream_dict in streams_data.items():
                    try:
                        stream = ResearchStream.model_validate(stream_dict)
                        self._streams_cache[stream_id] = stream
                    except Exception as e:
                        logger.warning(f"Failed to load stream {stream_id}: {e}")
            
            logger.info(f"Loaded {len(self._streams_cache)} research streams")
            
        except Exception as e:
            logger.error(f"Error loading research streams: {e}")
            self._streams_cache = {}
    
    def _save_streams(self):
        """Save research streams to storage"""
        try:
            # Ensure directory exists
            self.streams_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert streams to dict format
            streams_data = {}
            for stream_id, stream in self._streams_cache.items():
                streams_data[stream_id] = stream.model_dump()
            
            # Save to file
            with open(self.streams_file, 'w', encoding='utf-8') as f:
                json.dump(streams_data, f, indent=2, default=str)
            
            logger.debug(f"Saved {len(self._streams_cache)} research streams")
            
        except Exception as e:
            logger.error(f"Error saving research streams: {e}")
            raise ResearchStreamError(f"Failed to save streams: {e}")
    
    def create_stream(
        self, 
        name: str, 
        search_query: str,
        description: Optional[str] = None,
        refresh_frequency: RefreshFrequency = RefreshFrequency.WEEKLY,
        parent_collection: Optional[str] = None
    ) -> ResearchStream:
        """
        Create a new research stream
        
        Args:
            name: Human-readable name for the stream
            search_query: Search query for finding papers
            description: Optional description
            refresh_frequency: How often to update
            parent_collection: Parent collection key (optional)
            
        Returns:
            Created ResearchStream
        """
        try:
            # Generate unique ID
            stream_id = self._generate_stream_id(name)
            
            # Create search criteria
            search_criteria = SearchCriteria(
                query=search_query,
                max_results=100
            )
            
            # Generate smart tags
            smart_tags = self._generate_smart_tags(stream_id, name)
            
            # Create the stream
            stream = ResearchStream(
                id=stream_id,
                name=name,
                description=description,
                collection_name=f"Prisma: {name}",
                parent_collection_key=parent_collection,
                search_criteria=search_criteria,
                smart_tags=smart_tags,
                refresh_frequency=refresh_frequency,
                status=StreamStatus.ACTIVE
            )
            
            # Create Zotero collection
            collection_data = stream.to_zotero_collection()
            created_collection = self.zotero_client.create_collection(collection_data)
            
            if created_collection:
                stream.collection_key = created_collection.key
                logger.info(f"Created Zotero collection: {created_collection.key}")
            else:
                logger.warning("Failed to create Zotero collection")
            
            # Store the stream
            self._streams_cache[stream_id] = stream
            self._save_streams()
            
            logger.info(f"Created research stream: {stream_id}")
            return stream
            
        except Exception as e:
            logger.error(f"Error creating research stream: {e}")
            raise ResearchStreamError(f"Failed to create stream: {e}")
    
    def update_stream(self, stream_id: str, force: bool = False) -> StreamUpdateResult:
        """
        Update a research stream by searching for new papers
        
        Args:
            stream_id: ID of the stream to update
            force: Force update even if not due
            
        Returns:
            StreamUpdateResult with update details
        """
        start_time = datetime.utcnow()
        
        try:
            # Get the stream
            stream = self.get_stream(stream_id)
            if not stream:
                raise ResearchStreamError(f"Stream not found: {stream_id}")
            
            # Check if update is due
            if not force and not stream.is_due_for_update():
                return StreamUpdateResult(
                    stream_id=stream_id,
                    success=False,
                    errors=["Update not due"]
                )
            
            # Search for new papers
            search_query = ZoteroSearchQuery(
                query=stream.search_criteria.query,
                tags=stream.search_criteria.tags,
                limit=stream.search_criteria.max_results
            )
            
            search_result = self.zotero_client.search_items(search_query)
            
            # Filter out existing papers
            existing_items = set()
            if stream.collection_key:
                collection_items = self.zotero_client.get_collection_items(stream.collection_key)
                existing_items = {item.key for item in collection_items}
            
            new_papers = [item for item in search_result.items if item.key not in existing_items]
            
            # Add new papers to collection with smart tags
            added_count = 0
            errors = []
            
            for paper in new_papers:
                try:
                    # Apply smart tags
                    enhanced_paper = self._apply_smart_tags(paper, stream)
                    
                    # Add to collection
                    if stream.collection_key:
                        success = self.zotero_client.add_item_to_collection(
                            enhanced_paper.key, 
                            stream.collection_key
                        )
                        if success:
                            added_count += 1
                        else:
                            errors.append(f"Failed to add paper {enhanced_paper.key} to collection")
                
                except Exception as e:
                    errors.append(f"Error processing paper {paper.key}: {e}")
            
            # Update stream metadata
            stream.last_updated = datetime.utcnow()
            stream.next_update = stream.calculate_next_update()
            stream.new_papers_last_update = added_count
            stream.total_papers += added_count
            
            # Save updated stream
            self._streams_cache[stream_id] = stream
            self._save_streams()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info(f"Updated stream {stream_id}: {added_count} new papers")
            
            return StreamUpdateResult(
                stream_id=stream_id,
                success=True,
                new_papers_found=added_count,
                errors=errors,
                duration_seconds=duration
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Error updating stream {stream_id}: {e}")
            
            return StreamUpdateResult(
                stream_id=stream_id,
                success=False,
                errors=[str(e)],
                duration_seconds=duration
            )
    
    def get_stream(self, stream_id: str) -> Optional[ResearchStream]:
        """Get a research stream by ID"""
        return self._streams_cache.get(stream_id)
    
    def list_streams(self, status: Optional[StreamStatus] = None) -> List[ResearchStream]:
        """List all research streams, optionally filtered by status"""
        streams = list(self._streams_cache.values())
        
        if status:
            streams = [s for s in streams if s.status == status]
        
        return sorted(streams, key=lambda s: s.created_at, reverse=True)
    
    def get_summary(self) -> StreamSummary:
        """Get summary statistics about research streams"""
        streams = list(self._streams_cache.values())
        active_streams = [s for s in streams if s.status == StreamStatus.ACTIVE]
        due_streams = [s for s in active_streams if s.is_due_for_update()]
        
        return StreamSummary(
            total_streams=len(streams),
            active_streams=len(active_streams),
            total_papers=sum(s.total_papers for s in streams),
            streams_due_update=len(due_streams),
            last_global_update=max((s.last_updated for s in streams if s.last_updated), default=None)
        )
    
    def _generate_stream_id(self, name: str) -> str:
        """Generate a unique stream ID from name"""
        import re
        
        # Clean the name
        clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower())
        clean_name = re.sub(r'\s+', '-', clean_name.strip())
        
        # Ensure uniqueness
        base_id = clean_name[:50]  # Limit length
        stream_id = base_id
        counter = 1
        
        while stream_id in self._streams_cache:
            stream_id = f"{base_id}-{counter}"
            counter += 1
        
        return stream_id
    
    def _generate_smart_tags(self, stream_id: str, name: str) -> List[SmartTag]:
        """Generate smart tags for a stream"""
        tags = [
            SmartTag(
                name=f"prisma-{stream_id}",
                category=TagCategory.PRISMA,
                auto_generated=True,
                description=f"Auto-generated tag for stream: {name}"
            ),
            SmartTag(
                name="prisma-auto",
                category=TagCategory.SOURCE,
                auto_generated=True,
                description="Added automatically by Prisma"
            ),
            SmartTag(
                name="status-new",
                category=TagCategory.STATUS,
                auto_generated=True,
                description="Newly added paper"
            )
        ]
        
        return tags
    
    def _apply_smart_tags(self, item: ZoteroItem, stream: ResearchStream) -> ZoteroItem:
        """Apply smart tags to a paper based on stream configuration"""
        # Get existing tags
        existing_tags = set(tag.name for tag in item.tags)
        
        # Add Prisma tags
        prisma_tags = stream.get_prisma_tags()
        
        # Add temporal tags
        current_year = datetime.now().year
        prisma_tags.append(f"year-{current_year}")
        
        # Add methodology tags based on title/abstract
        if item.title or item.abstract:
            text = f"{item.title or ''} {item.abstract or ''}".lower()
            
            if any(word in text for word in ['survey', 'review', 'overview']):
                prisma_tags.append("type-survey")
            elif any(word in text for word in ['empirical', 'experiment', 'evaluation']):
                prisma_tags.append("type-empirical")
            elif any(word in text for word in ['theoretical', 'theory', 'framework']):
                prisma_tags.append("type-theoretical")
        
        # Combine with existing tags
        all_tags = existing_tags.union(set(prisma_tags))
        
        # Update item tags
        from ..storage.models.zotero_models import ZoteroTag
        item.tags = [ZoteroTag(name=tag) for tag in sorted(all_tags)]
        
        return item