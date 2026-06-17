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
             patch.object(ResearchStreamManager, '_try_create_zotero_client') as mock_create_client, \
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
    
    def test_try_create_zotero_client_success(self, mock_config):
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
    
    def test_try_create_zotero_client_failure(self, mock_config):
        """Test Zotero client creation failure degrades gracefully (returns None, no raise)."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch('prisma.integrations.zotero.ZoteroClient') as mock_zotero_client_class, \
             patch.object(ResearchStreamManager, '_load_streams'):

            mock_config_loader.return_value.config = mock_config
            mock_zotero_client_class.from_config.side_effect = Exception("Client creation failed")

            manager = ResearchStreamManager()
            assert manager.zotero_client is None

    def test_load_streams_success(self, mock_config, sample_stream_data):
        """Test successful loading of streams from file."""
        mock_file_content = json.dumps(sample_stream_data)
        
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_try_create_zotero_client'), \
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
             patch.object(ResearchStreamManager, '_try_create_zotero_client'), \
             patch('pathlib.Path.exists', return_value=False):
            
            mock_config_loader.return_value.config = mock_config
            
            manager = ResearchStreamManager()
            assert len(manager._streams_cache) == 0

    def test_load_streams_invalid_json(self, mock_config):
        """Test loading with invalid JSON file."""
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_try_create_zotero_client'), \
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


class TestUpdateStreamConnectivityOrder:
    """
    Connectivity check must fire BEFORE _ensure_stream_collection() so we never
    touch Zotero when offline and only then discover we can't search.
    """

    @pytest.fixture
    def manager_for_update(self, mock_config, mock_zotero_client):
        with patch('prisma.services.research_stream_manager.ConfigLoader') as mock_config_loader, \
             patch.object(ResearchStreamManager, '_try_create_zotero_client') as mock_create_client, \
             patch.object(ResearchStreamManager, '_load_streams'):
            mock_config_loader.return_value.config = mock_config
            mock_create_client.return_value = mock_zotero_client
            mgr = ResearchStreamManager()
        return mgr

    @pytest.fixture
    def mock_config(self):
        return {
            'sources': {
                'zotero': {
                    'enabled': True,
                    'library_type': 'user',
                    'library_id': '12345',
                    'api_key': 'test_key',
                }
            }
        }

    @pytest.fixture
    def mock_zotero_client(self):
        client = Mock()
        client.client_type = "test"
        client.client_info = "test client"
        client.create_collection.return_value = Mock(key="TEST123")
        return client

    def _active_stream(self, overdue=True):
        from datetime import timedelta
        next_upd = datetime.utcnow() - timedelta(hours=1) if overdue else datetime.utcnow() + timedelta(days=7)
        return ResearchStream(
            id="s1",
            name="S1",
            description="desc",
            collection_key="C1",
            collection_name="Prisma: S1",
            parent_collection_key=None,
            search_criteria=SearchCriteria(query="transformers", since_date=None),
            smart_tags=[],
            refresh_frequency=RefreshFrequency.WEEKLY,
            status=StreamStatus.ACTIVE,
            last_updated=datetime.utcnow() - timedelta(days=8),
            next_update=next_upd,
        )

    def test_offline_returns_failure_without_touching_collection(self, manager_for_update):
        mgr = manager_for_update
        stream = self._active_stream(overdue=True)
        mgr._streams_cache["s1"] = stream

        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn, \
             patch.object(mgr, '_ensure_stream_collection') as mock_ensure:
            mock_conn.is_online = False
            result = mgr.update_stream("s1")

        assert result.success is False
        assert any("offline" in e.lower() for e in result.errors)
        mock_ensure.assert_not_called()

    def test_online_proceeds_to_collection_check(self, manager_for_update):
        mgr = manager_for_update
        stream = self._active_stream(overdue=True)
        mgr._streams_cache["s1"] = stream

        mock_search_result = Mock()
        mock_search_result.papers = []

        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn, \
             patch.object(mgr, '_ensure_stream_collection', return_value="C1") as mock_ensure, \
             patch('prisma.agents.search_agent.SearchAgent') as mock_sa_cls, \
             patch.object(mgr, '_save_streams'):
            mock_conn.is_online = True
            mock_sa = Mock()
            mock_sa.search.return_value = mock_search_result
            mock_sa_cls.return_value = mock_sa
            mgr.zotero_client.search_items.return_value = []
            result = mgr.update_stream("s1")

        mock_ensure.assert_called_once_with(stream)

    def test_not_due_returns_early_without_connectivity_check(self, manager_for_update):
        mgr = manager_for_update
        stream = self._active_stream(overdue=False)
        mgr._streams_cache["s1"] = stream

        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn:
            mock_conn.is_online = False  # even offline, "not due" fires first
            result = mgr.update_stream("s1", force=False)

        assert result.success is False
        assert any("not due" in e.lower() for e in result.errors)

    def test_force_skips_due_check_but_still_checks_connectivity(self, manager_for_update):
        mgr = manager_for_update
        stream = self._active_stream(overdue=False)
        mgr._streams_cache["s1"] = stream

        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn, \
             patch.object(mgr, '_ensure_stream_collection'):
            mock_conn.is_online = False
            result = mgr.update_stream("s1", force=True)

        assert result.success is False
        assert any("offline" in e.lower() for e in result.errors)

    def test_unknown_stream_raises_error(self, manager_for_update):
        mgr = manager_for_update
        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn:
            mock_conn.is_online = True
            result = mgr.update_stream("does-not-exist")
        assert result.success is False

    def test_update_all_streams_online(self, manager_for_update):
        """update_stream called for each active overdue stream."""
        mgr = manager_for_update
        s1 = self._active_stream(overdue=True)
        s2 = self._active_stream(overdue=True)
        s2.id = "s2"
        mgr._streams_cache["s1"] = s1
        mgr._streams_cache["s2"] = s2

        mock_search_result = Mock()
        mock_search_result.papers = []

        with patch('prisma.services.research_stream_manager.connectivity') as mock_conn, \
             patch.object(mgr, '_ensure_stream_collection', return_value="C1"), \
             patch('prisma.agents.search_agent.SearchAgent') as mock_sa_cls, \
             patch.object(mgr, '_save_streams'):
            mock_conn.is_online = True
            mock_sa = Mock()
            mock_sa.search.return_value = mock_search_result
            mock_sa_cls.return_value = mock_sa
            mgr.zotero_client.search_items.return_value = []

            results = [mgr.update_stream(sid) for sid in ("s1", "s2")]

        assert all(r.success for r in results)