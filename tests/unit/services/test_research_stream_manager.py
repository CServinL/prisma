"""
Unit tests for ResearchStreamManager service.
"""

import json
import pytest
from unittest.mock import Mock, patch, mock_open, MagicMock
from pathlib import Path
from datetime import datetime, timedelta

from prisma.services.research_stream_manager import ResearchStreamManager, ResearchStreamError
from prisma.storage.models.research_stream_models import (
    ResearchStream, StreamStatus, RefreshFrequency, SmartTag, TagCategory,
    SearchCriteria, StreamUpdateResult, StreamSummary
)
from prisma.storage.models.agent_models import SearchResult, PaperMetadata
from prisma.storage.models.zotero_models import ZoteroItem, ZoteroCollection


class TestResearchStreamManager:
    """Test ResearchStreamManager core functionality."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock configuration."""
        return {
            'sources': {
                'zotero': {
                    'enabled': True,
                    'library_type': 'user',
                    'library_id': '12345',
                    'api_key': 'test_key'
                }
            }
        }
    
    @pytest.fixture
    def mock_zotero_client(self):
        """Mock Zotero client."""
        client = Mock()
        client.client_type = "test"
        client.client_info = "test client"
        client.create_collection.return_value = Mock(key="TEST123")
        return client
        
    @pytest.fixture
    def sample_stream_data(self):
        """Sample research stream data."""
        return {
            "test-stream": {
                "id": "test-stream",
                "name": "Test Stream",
                "description": "Test description",
                "collection_key": "TEST123",
                "collection_name": "Prisma: Test Stream",
                "parent_collection_key": None,
                "search_criteria": {
                    "query": "test query",
                    "tags": [],
                    "exclude_tags": [],
                    "item_types": [],
                    "since_date": None,
                    "max_results": 100
                },
                "smart_tags": [],
                "status": "active",
                "refresh_frequency": "weekly",
                "last_updated": "2025-09-01T00:00:00",
                "next_update": "2025-09-08T00:00:00",
                "total_papers": 0,
                "new_papers_last_update": 0,
                "created_at": "2025-09-01T00:00:00",
                "created_by": "test"
            }
        }
    
    @pytest.fixture
    def manager(self, mock_config, mock_zotero_client):
        """Create a ResearchStreamManager instance for testing."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_create_zotero_client') as mock_create_client, \
             patch.object(ResearchStreamManager, '_load_streams') as mock_load:
            
            mock_config_loader.return_value.config = mock_config
            mock_create_client.return_value = mock_zotero_client
            mock_load.return_value = None
            
            manager = ResearchStreamManager()
            return manager

    def test_initialization(self, manager, mock_zotero_client):
        """Test ResearchStreamManager initialization."""
        assert manager.zotero_client == mock_zotero_client
        assert manager.streams_file == Path("./data") / "research_streams.json"
        assert isinstance(manager._streams_cache, dict)
    
    def test_create_zotero_client_success(self, mock_config):
        """Test successful Zotero client creation."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch('prisma.integrations.zotero.ZoteroClient') as mock_zotero_client_class, \
             patch.object(ResearchStreamManager, '_load_streams'):
            
            mock_config_loader.return_value.config = mock_config
            mock_client = Mock()
            mock_client.client_type = "test"
            mock_client.client_info = "test client"
            mock_zotero_client_class.from_config.return_value = mock_client
            
            manager = ResearchStreamManager()
            assert manager.zotero_client == mock_client
    
    def test_create_zotero_client_failure(self, mock_config):
        """Test Zotero client creation failure."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch('prisma.integrations.zotero.ZoteroClient') as mock_zotero_client_class, \
             patch.object(ResearchStreamManager, '_load_streams'):
            
            mock_config_loader.return_value.config = mock_config
            mock_zotero_client_class.from_config.side_effect = Exception("Client creation failed")
            
            with pytest.raises(ValueError, match="Failed to initialize Zotero client"):
                ResearchStreamManager()

    def test_load_streams_success(self, mock_config, sample_stream_data):
        """Test successful loading of streams from file."""
        mock_file_content = json.dumps(sample_stream_data)
        
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_create_zotero_client'), \
             patch('builtins.open', mock_open(read_data=mock_file_content)), \
             patch('pathlib.Path.exists', return_value=True):
            
            mock_config_loader.return_value.config = mock_config
            
            manager = ResearchStreamManager()
            
            assert len(manager._streams_cache) == 1
            assert "test-stream" in manager._streams_cache
            assert manager._streams_cache["test-stream"].name == "Test Stream"

    def test_load_streams_file_not_exists(self, mock_config):
        """Test loading when streams file doesn't exist."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_create_zotero_client'), \
             patch('pathlib.Path.exists', return_value=False):
            
            mock_config_loader.return_value.config = mock_config
            
            manager = ResearchStreamManager()
            assert len(manager._streams_cache) == 0

    def test_load_streams_invalid_json(self, mock_config):
        """Test loading with invalid JSON file."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_create_zotero_client'), \
             patch('builtins.open', mock_open(read_data="invalid json")), \
             patch('pathlib.Path.exists', return_value=True):
            
            mock_config_loader.return_value.config = mock_config
            
            manager = ResearchStreamManager()
            assert len(manager._streams_cache) == 0

    def test_save_streams_success(self, manager):
        """Test successful saving of streams to file."""
        # Add a test stream to cache
        test_stream = ResearchStream(
            id="test-stream",
            name="Test Stream",
            description="Test description",
            collection_key="TEST123",
            collection_name="Prisma: Test Stream",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        manager._streams_cache["test-stream"] = test_stream
        
        with patch('builtins.open', mock_open()) as mock_file, \
             patch('pathlib.Path.mkdir') as mock_mkdir, \
             patch('json.dump') as mock_json_dump:
            
            manager._save_streams()
            
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_file.assert_called_once()
            mock_json_dump.assert_called_once()

    def test_save_streams_failure(self, manager):
        """Test save streams failure handling."""
        with patch('builtins.open', side_effect=IOError("Write failed")):
            with pytest.raises(ResearchStreamError, match="Failed to save streams"):
                manager._save_streams()

    def test_create_stream_success(self, manager):
        """Test successful stream creation."""
        with patch.object(manager, '_save_streams') as mock_save:
            stream = manager.create_stream(
                name="AI Research",
                search_query="artificial intelligence",
                description="AI research stream"
            )
            
            assert stream.name == "AI Research"
            assert stream.search_criteria.query == "artificial intelligence"
            assert stream.description == "AI research stream"
            assert stream.status == StreamStatus.ACTIVE
            assert stream.refresh_frequency == RefreshFrequency.WEEKLY
            assert len(stream.smart_tags) > 0  # Should have auto-generated tags
            
            # Verify it was saved
            mock_save.assert_called_once()
            
            # Verify it's in cache
            assert stream.id in manager._streams_cache

    def test_create_stream_zotero_collection_creation(self, manager):
        """Test stream creation with Zotero collection."""
        mock_collection = Mock()
        mock_collection.key = "NEW_COLLECTION_KEY"
        manager.zotero_client.create_collection.return_value = mock_collection
        
        with patch.object(manager, '_save_streams'):
            stream = manager.create_stream(
                name="Test Stream",
                search_query="test query"
            )
            
            assert stream.collection_key == "NEW_COLLECTION_KEY"
            manager.zotero_client.create_collection.assert_called_once()

    def test_create_stream_collection_creation_failure(self, manager):
        """Test stream creation when Zotero collection creation fails."""
        manager.zotero_client.create_collection.return_value = None
        
        with patch.object(manager, '_save_streams'):
            stream = manager.create_stream(
                name="Test Stream",
                search_query="test query"
            )
            
            assert stream.collection_key is None

    def test_create_stream_failure(self, manager):
        """Test stream creation failure."""
        with patch.object(manager, '_save_streams', side_effect=Exception("Save failed")):
            with pytest.raises(ResearchStreamError, match="Failed to create stream"):
                manager.create_stream("Test", "query")

    def test_get_stream_exists(self, manager):
        """Test getting an existing stream."""
        test_stream = ResearchStream(
            id="test-stream",
            name="Test Stream",
            description="Test description",
            collection_key="TEST123",
            collection_name="Test Collection",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        manager._streams_cache["test-stream"] = test_stream
        
        result = manager.get_stream("test-stream")
        assert result == test_stream

    def test_get_stream_not_exists(self, manager):
        """Test getting a non-existent stream."""
        result = manager.get_stream("non-existent")
        assert result is None

    def test_list_streams_all(self, manager):
        """Test listing all streams."""
        stream1 = ResearchStream(
            id="stream1",
            name="Stream 1",
            description="Stream 1 description",
            collection_key="KEY1",
            collection_name="Collection 1",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test1", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        stream2 = ResearchStream(
            id="stream2",
            name="Stream 2",
            description="Stream 2 description",
            collection_key="KEY2",
            collection_name="Collection 2",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test2", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.PAUSED,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        
        manager._streams_cache["stream1"] = stream1
        manager._streams_cache["stream2"] = stream2
        
        result = manager.list_streams()
        assert len(result) == 2
        assert stream1 in result
        assert stream2 in result

    def test_list_streams_filtered_by_status(self, manager):
        """Test listing streams filtered by status."""
        stream1 = ResearchStream(
            id="stream1",
            name="Stream 1",
            description="Stream 1 description",
            collection_key="KEY1",
            collection_name="Collection 1",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test1", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        stream2 = ResearchStream(
            id="stream2",
            name="Stream 2", 
            description="Stream 2 description",
            collection_key="KEY2",
            collection_name="Collection 2",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test2", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.PAUSED,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        
        manager._streams_cache["stream1"] = stream1
        manager._streams_cache["stream2"] = stream2
        
        result = manager.list_streams(status=StreamStatus.ACTIVE)
        assert len(result) == 1
        assert stream1 in result
        assert stream2 not in result

    def test_get_summary(self, manager):
        """Test getting stream summary."""
        # Create test streams with different statuses
        active_stream = ResearchStream(
            id="active",
            name="Active Stream",
            description="Active stream description",
            collection_key="KEY_ACTIVE",
            collection_name="Active Collection",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            total_papers=10,
            last_updated=datetime.now(),
            next_update=datetime.now() - timedelta(hours=1)  # Due for update
        )
        
        paused_stream = ResearchStream(
            id="paused",
            name="Paused Stream",
            description="Paused stream description",
            collection_key="KEY_PAUSED",
            collection_name="Paused Collection",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.PAUSED,
            total_papers=5,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        
        manager._streams_cache["active"] = active_stream
        manager._streams_cache["paused"] = paused_stream
        
        summary = manager.get_summary()
        
        assert summary.total_streams == 2
        assert summary.active_streams == 1
        assert summary.total_papers == 15
        assert summary.streams_due_update == 1
        assert summary.last_global_update is not None

    def test_generate_stream_id_simple(self, manager):
        """Test stream ID generation from name."""
        stream_id = manager._generate_stream_id("AI Research")
        assert stream_id == "ai-research"

    def test_generate_stream_id_with_special_chars(self, manager):
        """Test stream ID generation with special characters."""
        stream_id = manager._generate_stream_id("AI & ML Research (2024)!")
        assert stream_id == "ai-ml-research-2024"

    def test_generate_stream_id_uniqueness(self, manager):
        """Test stream ID uniqueness when collision occurs."""
        # Add existing stream
        existing_stream = ResearchStream(
            id="ai-research",
            name="Existing",
            description="Existing stream",
            collection_key="KEY_EXISTING",
            collection_name="Existing",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="test", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.now(),
            next_update=datetime.now() + timedelta(days=7)
        )
        manager._streams_cache["ai-research"] = existing_stream
        
        # Generate new ID - should get unique suffix
        stream_id = manager._generate_stream_id("AI Research")
        assert stream_id == "ai-research-1"

    def test_generate_smart_tags(self, manager):
        """Test smart tag generation."""
        tags = manager._generate_smart_tags("test-stream", "Test Stream")
        
        assert len(tags) == 3
        
        # Check tag names
        tag_names = [tag.name for tag in tags]
        assert "prisma-test-stream" in tag_names
        assert "prisma-auto" in tag_names
        assert "status-new" in tag_names
        
        # Check tag categories
        tag_categories = [tag.category for tag in tags]
        assert TagCategory.PRISMA in tag_categories
        assert TagCategory.SOURCE in tag_categories
        assert TagCategory.STATUS in tag_categories
        
        # Check auto_generated flag
        assert all(tag.auto_generated for tag in tags)