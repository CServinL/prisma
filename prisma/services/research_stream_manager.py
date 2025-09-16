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
        self.config = ConfigLoader().config
        self.zotero_client = self._create_zotero_client()
        self.streams_file = Path("./data") / "research_streams.json"
        self._streams_cache: Dict[str, ResearchStream] = {}
        self._load_streams()
    
    def _create_zotero_client(self):
        """Create appropriate Zotero client based on configuration mode"""
        zotero_mode = getattr(self.config.sources.zotero, 'mode', 'hybrid')
        
        if zotero_mode == 'local_api':
            from ..integrations.zotero.local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig
            server_url = getattr(self.config.sources.zotero, 'server_url', 'http://127.0.0.1:23119')
            local_config = ZoteroLocalAPIConfig(
                server_url=server_url,
                timeout=30.0,
                user_id="0"
            )
            return ZoteroLocalAPIClient(local_config)
        else:
            # Default to hybrid client for other modes
            from ..integrations.zotero.hybrid_client import ZoteroHybridClient, ZoteroHybridConfig
            
            # Convert PrismaConfig to ZoteroHybridConfig
            zotero_config = ZoteroHybridConfig(
                api_key=getattr(self.config.sources.zotero, 'api_key', None),
                library_id=getattr(self.config.sources.zotero, 'library_id', None),
                library_type=getattr(self.config.sources.zotero, 'library_type', 'user'),
                local_server_url=getattr(self.config.sources.zotero, 'server_url', 'http://127.0.0.1:23119'),
                local_server_timeout=5,
                enable_desktop_save=True,
                desktop_server_url=getattr(self.config.sources.zotero, 'server_url', 'http://127.0.0.1:23119'),
                collection_key=None,
                prefer_local_server=True,
                fallback_to_api=True
            )
            return ZoteroHybridClient(zotero_config)
    
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
            
            # Create Zotero collection (if supported by client)
            collection_data = stream.to_zotero_collection()
            created_collection = self.zotero_client.create_collection(collection_data)
            
            if created_collection:
                stream.collection_key = created_collection.key
                logger.info(f"Created Zotero collection: {created_collection.key}")
            else:
                logger.warning(f"Failed to create Zotero collection '{stream.collection_name}' - local API may not support collection creation")
                logger.info("Items will be saved to library without collection organization")
            
            # Store the stream
            self._streams_cache[stream_id] = stream
            self._save_streams()
            
            logger.info(f"Created research stream: {stream_id}")
            return stream
            
        except Exception as e:
            logger.error(f"Error creating research stream: {e}")
            raise ResearchStreamError(f"Failed to create stream: {e}")
    
    def _ensure_stream_collection(self, stream: ResearchStream) -> Optional[str]:
        """
        Ensure the stream's collection exists in Zotero, creating it if necessary.
        Returns the collection key if successful, None otherwise.
        """
        try:
            if stream.collection_key:
                # Collection key exists, verify it's still valid
                try:
                    collections = self.zotero_client.get_collections()
                    for collection in collections:
                        if hasattr(collection, 'key') and collection.key == stream.collection_key:
                            logger.info(f"Stream collection exists: {stream.collection_key}")
                            return stream.collection_key
                    
                    # Collection key is invalid, reset it
                    logger.warning(f"Collection key {stream.collection_key} no longer exists, will recreate")
                    stream.collection_key = None
                except Exception as e:
                    logger.warning(f"Failed to verify collection: {e}")
                    stream.collection_key = None
            
            # No collection key or invalid key - find existing or create new
            if stream.collection_name:
                # Try to find existing collection by name
                try:
                    collections = self.zotero_client.get_collections()
                    for collection in collections:
                        if hasattr(collection, 'name') and collection.name == stream.collection_name:
                            logger.info(f"Found existing collection: {collection.name} -> {collection.key}")
                            stream.collection_key = collection.key
                            return collection.key
                except Exception as e:
                    logger.warning(f"Failed to search for existing collection: {e}")
                
                # Collection doesn't exist, create it
                try:
                    collection_data = {
                        "name": stream.collection_name,
                        "parentCollection": stream.parent_collection_key or False
                    }
                    created_collection = self.zotero_client.create_collection(collection_data)
                    
                    if created_collection and hasattr(created_collection, 'key'):
                        stream.collection_key = created_collection.key
                        logger.info(f"Created new collection: {stream.collection_name} -> {created_collection.key}")
                        
                        # Save updated stream immediately
                        self._streams_cache[stream.id] = stream
                        self._save_streams()
                        
                        return created_collection.key
                    else:
                        logger.error(f"Failed to create collection {stream.collection_name}")
                        return None
                        
                except Exception as e:
                    logger.error(f"Error creating collection: {e}")
                    return None
            
            return None
            
        except Exception as e:
            logger.error(f"Error ensuring stream collection: {e}")
            return None
    
    def update_stream(self, stream_id: str, force: bool = False, refresh_cache: bool = False) -> StreamUpdateResult:
        """
        Update a research stream by searching for new papers
        
        Args:
            stream_id: ID of the stream to update
            force: Force update even if not due
            refresh_cache: If True, refresh cached metadata for existing items instead of using cache
            
        Returns:
            StreamUpdateResult with update details
        """
        start_time = datetime.utcnow()
        
        try:
            # Get the stream
            stream = self.get_stream(stream_id)
            if not stream:
                raise ResearchStreamError(f"Stream not found: {stream_id}")
            
            # Ensure the stream's collection exists in Zotero
            collection_key = self._ensure_stream_collection(stream)
            if collection_key:
                logger.info(f"Using collection: {stream.collection_name} -> {collection_key}")
            else:
                logger.warning(f"No collection available for stream {stream_id}")
            
            # Check if update is due
            if not force and not stream.is_due_for_update():
                return StreamUpdateResult(
                    stream_id=stream_id,
                    success=False,
                    errors=["Update not due"]
                )
            
            # Import SearchAgent for internet searches
            from ..agents.search_agent import SearchAgent
            search_agent = SearchAgent()
            
            # Define search sources (prioritizing academic sources)
            search_sources = ['arxiv', 'semanticscholar']  # High-quality academic sources
            
            # Search internet sources for new papers
            search_query_str = stream.search_criteria.query
            logger.info(f"Searching internet sources for: {search_query_str}")
            
            # Use SearchAgent to find papers from internet sources
            search_result = search_agent.search(
                query=search_query_str,
                sources=search_sources,
                limit=stream.search_criteria.max_results
            )
            
            errors = []  # Initialize errors list
            
            # Get all found papers from internet search
            internet_papers = search_result.papers
            logger.info(f"Found {len(internet_papers)} papers from internet sources")
            
            # Handle cache refresh vs normal operation
            updated_count = 0
            if refresh_cache:
                logger.info("REFRESH CACHE MODE: Processing internet sources fully, updating existing items")
                # In refresh mode, we want to update metadata for existing papers
                existing_items = {}
                updated_items = []
                if stream.collection_key:
                    collection_items = self.zotero_client.get_collection_items(stream.collection_key)
                    existing_items = {item.key: item for item in collection_items}
                
                # Process all papers fully and update existing ones with better info
                new_papers = []
                for paper in internet_papers:
                    # Check if paper exists locally (by DOI, title similarity, etc.)
                    existing_key = self._find_existing_paper_key(paper, existing_items)
                    
                    if existing_key:
                        try:
                            # Update existing paper with fresh metadata
                            logger.info(f"Updating cached metadata for paper: {paper.title[:50]}...")
                            # Here we would update the local item with fresh data
                            updated_items.append(existing_key)
                            updated_count += 1
                        except Exception as e:
                            errors.append(f"Error updating cached paper: {e}")
                    else:
                        # This is a new paper not in our local collection
                        new_papers.append(paper)
                
                logger.info(f"Cache refresh mode: Updated {len(updated_items)} existing items, found {len(new_papers)} new papers")
            else:
                logger.info("DEFAULT CACHE MODE: Light processing, using cached details when available")
                # Normal mode: light processing of internet sources, get details from local cache
                
                # ALWAYS check the entire library for duplicates, not just the collection
                logger.info("Checking entire library for existing papers to avoid duplicates...")
                all_library_items = self.zotero_client.search_items("")
                library_items = {}
                if hasattr(all_library_items, 'items'):
                    library_items = {item.key: item for item in all_library_items.items}
                elif isinstance(all_library_items, list):
                    library_items = {getattr(item, 'key', str(i)): item for i, item in enumerate(all_library_items)}
                
                # Also get collection items to know which existing items are already in the collection
                collection_items = {}
                if stream.collection_key:
                    try:
                        collection_item_list = self.zotero_client.get_collection_items(stream.collection_key)
                        collection_items = {item.key: item for item in collection_item_list}
                        logger.info(f"Collection {stream.collection_key} currently has {len(collection_items)} items")
                    except Exception as e:
                        logger.warning(f"Could not get collection items: {e}")
                
                new_papers = []
                existing_papers_to_add = []  # Papers that exist but may not be in collection
                
                for paper in internet_papers:
                    # Check if we have this paper in the entire library (by DOI or title)
                    existing_key = self._find_existing_paper_key(paper, library_items)
                    
                    if not existing_key:
                        # This is a new paper not in our library - add to processing list
                        new_papers.append(paper)
                    else:
                        logger.info(f"Paper already exists in library: {paper.title[:50]}...")
                        
                        # If we have a collection and this existing item is not in it, add it to our list
                        if stream.collection_key and existing_key not in collection_items:
                            # This existing paper is not in our stream collection yet
                            existing_papers_to_add.append(existing_key)
                            logger.info(f"Will add existing paper to collection: {paper.title[:50]}...")
                        elif stream.collection_key and existing_key in collection_items:
                            logger.info(f"Paper already in collection, skipping: {paper.title[:50]}...")
                
                # Add existing papers to the stream collection if needed
                if stream.collection_key and existing_papers_to_add:
                    logger.info(f"Adding {len(existing_papers_to_add)} existing papers to collection {stream.collection_key}")
                    for item_key in existing_papers_to_add:
                        try:
                            success = self.zotero_client.add_item_to_collection(item_key, stream.collection_key)
                            if success:
                                logger.info(f"Added existing item {item_key} to collection")
                            else:
                                logger.warning(f"Failed to add existing item {item_key} to collection")
                        except Exception as e:
                            logger.error(f"Error adding existing item {item_key} to collection: {e}")
                            errors.append(f"Error adding existing item to collection: {e}")
            
            # Save new papers to Zotero and add to collection
            added_count = 0
            
            for paper in new_papers:
                try:
                    # Convert PaperMetadata to Zotero item and save it
                    logger.info(f"Saving new paper to Zotero: {paper.title[:50]}...")
                    
                    # Create Zotero item data from PaperMetadata
                    zotero_item_data = {
                        "itemType": "journalArticle",
                        "title": paper.title,
                        "abstractNote": getattr(paper, 'abstract', '') or '',
                        "DOI": getattr(paper, 'doi', '') or '',
                        "url": getattr(paper, 'url', '') or '',
                        "date": getattr(paper, 'publication_date', '') or '',
                        "publicationTitle": getattr(paper, 'journal', '') or '',
                        "creators": []
                    }
                    
                    # Add authors if available
                    if hasattr(paper, 'authors') and paper.authors:
                        for author in paper.authors:
                            if isinstance(author, str):
                                # Simple string author
                                zotero_item_data["creators"].append({
                                    "creatorType": "author",
                                    "name": author
                                })
                            elif hasattr(author, 'name'):
                                # Author object with name
                                zotero_item_data["creators"].append({
                                    "creatorType": "author", 
                                    "name": author.name
                                })
                    
                    # Save to Zotero using appropriate method based on client type
                    if hasattr(self.zotero_client, 'create_item'):
                        # HybridClient method - returns item key
                        try:
                            item_key = self.zotero_client.create_item(zotero_item_data)
                            if item_key:
                                added_count += 1
                                logger.info(f"Successfully saved paper to Zotero: {paper.title[:50]}...")
                                
                                # Add to collection if specified
                                if stream.collection_key:
                                    try:
                                        self.zotero_client.add_item_to_collection(item_key, stream.collection_key)
                                        logger.info(f"Added item to collection: {stream.collection_key}")
                                    except Exception as e:
                                        logger.warning(f"Failed to add item to collection: {e}")
                            else:
                                errors.append(f"Failed to save paper to Zotero: {paper.title[:50]}...")
                        except Exception as e:
                            errors.append(f"Error saving paper via create_item: {e}")
                            logger.error(f"Error saving paper via create_item: {e}")
                            
                    elif hasattr(self.zotero_client, 'save_items'):
                        # LocalAPIClient method - fallback
                        try:
                            save_success = self.zotero_client.save_items([zotero_item_data])
                            if save_success:
                                added_count += 1
                                logger.info(f"Successfully saved paper to Zotero: {paper.title[:50]}...")
                            else:
                                errors.append(f"Failed to save paper to Zotero: {paper.title[:50]}...")
                        except Exception as e:
                            errors.append(f"Error saving paper via save_items: {e}")
                            logger.error(f"Error saving paper via save_items: {e}")
                            
                    else:
                        error_msg = f"Zotero client does not support item creation. Current client: {type(self.zotero_client).__name__}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                
                except Exception as e:
                    paper_title = getattr(paper, 'title', 'unknown')[:50]
                    errors.append(f"Error processing paper {paper_title}: {e}")
                    logger.error(f"Error processing paper {paper_title}: {e}")
            
            # Update stream metadata
            stream.last_updated = datetime.utcnow()
            stream.next_update = stream.calculate_next_update()
            stream.new_papers_last_update = added_count
            stream.total_papers += added_count
            
            # Save updated stream
            self._streams_cache[stream_id] = stream
            self._save_streams()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            if refresh_cache:
                logger.info(f"Updated stream {stream_id}: {added_count} new papers, {updated_count} items refreshed")
            else:
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
    
    def _find_existing_paper_key(self, paper, existing_items: Dict) -> Optional[str]:
        """
        Find if a paper from internet search already exists in local Zotero collection.
        
        Args:
            paper: PaperMetadata from internet search
            existing_items: Dict of {key: ZoteroItem} from local collection
            
        Returns:
            Key of existing item if found, None otherwise
        """
        # Match by DOI first (most reliable)
        if hasattr(paper, 'doi') and paper.doi:
            paper_doi = paper.doi.lower().strip()
            for key, item in existing_items.items():
                # Handle both attribute access and dict access
                item_doi = None
                if hasattr(item, 'doi') and item.doi:
                    item_doi = item.doi.lower().strip()
                elif isinstance(item, dict) and item.get('DOI'):
                    item_doi = item.get('DOI', '').lower().strip()
                elif hasattr(item, 'raw_data') and item.raw_data.get('data', {}).get('DOI'):
                    item_doi = item.raw_data['data']['DOI'].lower().strip()
                
                if item_doi and item_doi == paper_doi:
                    logger.info(f"Found existing paper by DOI match: {paper.title[:50]}...")
                    return key
        
        # Match by title similarity (enhanced implementation)
        if hasattr(paper, 'title') and paper.title:
            paper_title = self._normalize_title(paper.title)
            for key, item in existing_items.items():
                # Handle both attribute access and dict access
                item_title = None
                if hasattr(item, 'title') and item.title:
                    item_title = self._normalize_title(item.title)
                elif isinstance(item, dict) and item.get('title'):
                    item_title = self._normalize_title(item.get('title', ''))
                elif hasattr(item, 'raw_data') and item.raw_data.get('data', {}).get('title'):
                    item_title = self._normalize_title(item.raw_data['data']['title'])
                
                if item_title and item_title == paper_title:
                    logger.info(f"Found existing paper by title match: {paper.title[:50]}...")
                    return key
        
        return None
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison by removing punctuation and extra whitespace"""
        import re
        # Convert to lowercase, remove punctuation, normalize whitespace
        normalized = re.sub(r'[^\w\s]', '', title.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
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