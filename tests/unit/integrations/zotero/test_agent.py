"""
Test Zotero Agent functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.zotero_agent import ZoteroAgent, ZoteroSearchCriteria
from src.integrations.zotero import ZoteroConfig, ZoteroClientError
from src.storage.models import ZoteroItem, ZoteroCollection, ZoteroCreator


class TestZoteroSearchCriteria:
    """Test ZoteroSearchCriteria data class"""
    
    def test_criteria_initialization(self):
        """Test basic criteria initialization"""
        criteria = ZoteroSearchCriteria(
            query="machine learning",
            collections=["COLL1", "COLL2"],
            limit=50
        )
        
        assert criteria.query == "machine learning"
        assert criteria.collections == ["COLL1", "COLL2"]
        assert criteria.limit == 50
        assert criteria.item_types is None
    
    def test_criteria_defaults(self):
        """Test default values"""
        criteria = ZoteroSearchCriteria()
        
        assert criteria.query is None
        assert criteria.collections is None
        assert criteria.item_types is None
        assert criteria.tags is None
        assert criteria.date_range is None
        assert criteria.limit == 100


class TestZoteroAgent:
    """Test ZoteroAgent with mocked client"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = ZoteroConfig(
            api_key="test_key",
            library_id="12345",
            library_type="user"
        )
        
        # Mock sample data
        self.mock_collection_data = [
            {
                "key": "COLL1", 
                "data": {"name": "AI Papers"},
                "version": 1
            },
            {
                "key": "COLL2", 
                "data": {"name": "Machine Learning"},
                "version": 2
            }
        ]
        
        self.mock_item_data = [
            {
                "key": "ITEM1",
                "version": 1,
                "data": {
                    "itemType": "journalArticle",
                    "title": "Neural Networks Study",
                    "creators": [
                        {"creatorType": "author", "firstName": "John", "lastName": "Doe"}
                    ],
                    "date": "2023",
                    "tags": [{"tag": "machine learning"}],
                    "collections": ["COLL1"]
                }
            },
            {
                "key": "ITEM2",
                "version": 2,
                "data": {
                    "itemType": "conferencePaper",
                    "title": "Deep Learning Applications",
                    "creators": [
                        {"creatorType": "author", "firstName": "Jane", "lastName": "Smith"}
                    ],
                    "date": "2022",
                    "tags": [{"tag": "deep learning"}],
                    "collections": ["COLL2"]
                }
            }
        ]
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_agent_initialization(self, mock_client_class):
        """Test agent initialization"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        
        assert agent.config == self.config
        assert agent.client == mock_client
        mock_client_class.assert_called_once_with(self.config)
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_test_connection(self, mock_client_class):
        """Test connection testing"""
        mock_client = Mock()
        mock_client.test_connection.return_value = True
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        result = agent.test_connection()
        
        assert result is True
        mock_client.test_connection.assert_called_once()
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_collections_success(self, mock_client_class):
        """Test successful collections retrieval"""
        mock_client = Mock()
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        collections = agent.get_collections()
        
        assert len(collections) == 2
        assert isinstance(collections[0], ZoteroCollection)
        assert collections[0].name == "AI Papers"
        assert collections[1].name == "Machine Learning"
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_collections_cached(self, mock_client_class):
        """Test collections caching"""
        mock_client = Mock()
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        
        # First call
        collections1 = agent.get_collections()
        # Second call should use cache
        collections2 = agent.get_collections()
        
        assert collections1 == collections2
        # Client should only be called once
        mock_client.get_collections.assert_called_once()
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_collections_refresh_cache(self, mock_client_class):
        """Test cache refresh"""
        mock_client = Mock()
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        
        # First call
        agent.get_collections()
        # Second call with refresh
        agent.get_collections(refresh_cache=True)
        
        # Client should be called twice
        assert mock_client.get_collections.call_count == 2
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_find_collections_by_name(self, mock_client_class):
        """Test finding collections by name pattern"""
        mock_client = Mock()
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        
        # Test case-insensitive search
        collections = agent.find_collections_by_name("machine")
        assert len(collections) == 1
        assert collections[0].name == "Machine Learning"
        
        # Test broader search
        collections = agent.find_collections_by_name("a")
        assert len(collections) == 2  # Both contain "a"
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_search_papers_by_query(self, mock_client_class):
        """Test searching papers by query"""
        mock_client = Mock()
        mock_client.search_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        criteria = ZoteroSearchCriteria(query="neural networks", limit=50)
        
        papers = agent.search_papers(criteria)
        
        assert len(papers) == 2
        assert isinstance(papers[0], ZoteroItem)
        assert papers[0].title == "Neural Networks Study"
        mock_client.search_items.assert_called_once_with("neural networks", limit=50)
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_search_papers_by_collections(self, mock_client_class):
        """Test searching papers by collections"""
        mock_client = Mock()
        mock_client.get_collection_items.return_value = [self.mock_item_data[0]]
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        criteria = ZoteroSearchCriteria(collections=["COLL1"], limit=25)
        
        papers = agent.search_papers(criteria)
        
        assert len(papers) == 1
        assert papers[0].title == "Neural Networks Study"
        mock_client.get_collection_items.assert_called_once_with("COLL1", limit=25)
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_search_papers_all_items(self, mock_client_class):
        """Test searching all papers"""
        mock_client = Mock()
        mock_client.get_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        criteria = ZoteroSearchCriteria(limit=100)
        
        papers = agent.search_papers(criteria)
        
        assert len(papers) == 2
        mock_client.get_items.assert_called_once_with(limit=100)
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_search_papers_with_filters(self, mock_client_class):
        """Test searching papers with additional filters"""
        mock_client = Mock()
        mock_client.get_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        criteria = ZoteroSearchCriteria(
            item_types=["journalArticle"],
            tags=["machine learning"],
            date_range=(2023, 2023),
            limit=100
        )
        
        papers = agent.search_papers(criteria)
        
        # Should filter to only journal articles from 2023 with machine learning tag
        assert len(papers) == 1
        assert papers[0].item_type == "journalArticle"
        assert papers[0].year == 2023
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_academic_papers(self, mock_client_class):
        """Test getting only academic papers"""
        mock_client = Mock()
        mock_client.get_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        papers = agent.get_academic_papers(limit=50)
        
        # Both test items are academic papers
        assert len(papers) == 2
        for paper in papers:
            assert paper.is_academic_paper is True
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_papers_by_topic(self, mock_client_class):
        """Test getting papers by topic"""
        mock_client = Mock()
        mock_client.search_items.return_value = self.mock_item_data
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client.get_collection_items.return_value = [self.mock_item_data[1]]  # Machine Learning collection items
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        papers = agent.get_papers_by_topic("machine learning", limit=30)
        
        # Should find Machine Learning collection and search it instead of doing query search
        assert len(papers) == 1
        # Collections search should be called instead of search_items because collection was found
        mock_client.get_collection_items.assert_called_once_with("COLL2", limit=30)
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_recent_papers(self, mock_client_class):
        """Test getting recent papers"""
        mock_client = Mock()
        mock_client.get_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        papers = agent.get_recent_papers(years_back=3, limit=40)
        
        # Both test papers are from 2022-2023, so should be included
        assert len(papers) == 2
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_library_summary(self, mock_client_class):
        """Test getting library summary"""
        mock_client = Mock()
        mock_client.get_collections.return_value = self.mock_collection_data
        mock_client.get_items.return_value = self.mock_item_data
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        summary = agent.get_library_summary()
        
        assert summary["library_id"] == "12345"
        assert summary["library_type"] == "user"
        assert summary["collections_count"] == 2
        assert summary["sample_items_count"] == 2
        assert summary["academic_papers_in_sample"] == 2
        assert "journalArticle" in summary["item_types"]
        assert "conferencePaper" in summary["item_types"]
        assert summary["year_range"] == (2022, 2023)
        assert len(summary["collections"]) == 2
    
    @patch('src.agents.zotero_agent.ZoteroClient')
    def test_get_library_summary_error(self, mock_client_class):
        """Test library summary with error"""
        mock_client = Mock()
        mock_client.get_collections.side_effect = ZoteroClientError("API error")
        mock_client.get_items.side_effect = ZoteroClientError("Items API error")  # This should trigger the error case
        mock_client_class.return_value = mock_client
        
        agent = ZoteroAgent(self.config)
        summary = agent.get_library_summary()
        
        # When both get_collections and get_items fail, the exception block should be hit
        assert "error" in summary
        assert summary["library_id"] == "12345"
    
    def test_export_papers_metadata(self):
        """Test exporting papers metadata"""
        # Create test items directly without mocking
        from src.storage.models import ZoteroCreator, ZoteroTag
        
        creators = [ZoteroCreator(creator_type="author", first_name="John", last_name="Doe")]
        tags = [ZoteroTag(tag="test")]
        
        papers = [
            ZoteroItem(
                key="TEST1",
                item_type="journalArticle",
                title="Test Paper",
                creators=creators,
                tags=tags,
                date="2023"
            )
        ]
        
        # Don't need to mock for this test
        config = ZoteroConfig(api_key="test", library_id="123")
        with patch('src.agents.zotero_agent.ZoteroClient'):
            agent = ZoteroAgent(config)
            metadata = agent.export_papers_metadata(papers)
        
        assert len(metadata) == 1
        assert metadata[0]["key"] == "TEST1"
        assert metadata[0]["title"] == "Test Paper"
        assert metadata[0]["authors"] == ["John Doe"]
        assert metadata[0]["year"] == 2023