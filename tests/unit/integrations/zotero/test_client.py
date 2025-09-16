"""
Test Zotero client func        config = ZoteroAPIConfig(
            api_key="test_key",
            library_id="12345"
        )ality with mocking
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from prisma.integrations.zotero import ZoteroClient, ZoteroAPIConfig, ZoteroClientError


class TestZoteroConfig:
    """Test ZoteroAPIConfig data class"""
    
    def test_config_initialization(self):
        """Test basic config initialization"""
        config = ZoteroAPIConfig(
            api_key="test_key_123",
            library_id="12345",
            library_type="user",
            api_version=3
        )
        
        assert config.api_key == "test_key_123"
        assert config.library_id == "12345"
        assert config.library_type == "user"
        assert config.api_version == 3
    
    def test_config_defaults(self):
        """Test default values"""
        config = ZoteroAPIConfig(
            api_key="test_key",
            library_id="123",
            library_type="user",
            api_version=3
        )
        
        assert config.library_type == "user"
        assert config.api_version == 3


class TestZoteroClient:
    """Test ZoteroClient with mocked pyzotero"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = ZoteroAPIConfig(
            api_key="test_key_123",
            library_id="12345",
            library_type="user",
            api_version=3
        )
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_client_initialization_success(self, mock_zotero):
        """Test successful client initialization"""
        mock_zotero_instance = Mock()
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        
        assert client.config == self.config
        mock_zotero.Zotero.assert_called_once_with(
            library_id="12345",
            library_type="user",
            api_key="test_key_123"
        )
    
    @patch('prisma.integrations.zotero.client.zotero', None)
    def test_client_initialization_no_pyzotero(self):
        """Test initialization fails when pyzotero not installed"""
        with pytest.raises(ZoteroClientError, match="pyzotero is required"):
            ZoteroClient(self.config)
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_client_initialization_failure(self, mock_zotero):
        """Test initialization fails with invalid config"""
        mock_zotero.Zotero.side_effect = Exception("Invalid API key")
        
        with pytest.raises(ZoteroClientError, match="Failed to initialize"):
            ZoteroClient(self.config)
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_test_connection_success(self, mock_zotero):
        """Test successful connection test"""
        mock_zotero_instance = Mock()
        mock_zotero_instance.key_info.return_value = {"userID": 12345}
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        result = client.test_connection()
        
        assert result is True
        mock_zotero_instance.key_info.assert_called_once()
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_test_connection_failure(self, mock_zotero):
        """Test connection test failure"""
        mock_zotero_instance = Mock()
        mock_zotero_instance.key_info.side_effect = Exception("Connection failed")
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        result = client.test_connection()
        
        assert result is False
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_collections_success(self, mock_zotero):
        """Test successful collections retrieval"""
        mock_collections = [
            {"key": "ABC123", "data": {"name": "Collection 1"}},
            {"key": "DEF456", "data": {"name": "Collection 2"}}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.collections.return_value = mock_collections
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        collections = client.get_collections(limit=50)
        
        assert len(collections) == 2
        assert collections[0]["key"] == "ABC123"
        mock_zotero_instance.collections.assert_called_once_with(limit=50)
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_collections_failure(self, mock_zotero):
        """Test collections retrieval failure"""
        mock_zotero_instance = Mock()
        mock_zotero_instance.collections.side_effect = Exception("API error")
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        
        with pytest.raises(ZoteroClientError, match="Failed to retrieve collections"):
            client.get_collections()
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_items_success(self, mock_zotero):
        """Test successful items retrieval"""
        mock_items = [
            {"key": "ITEM1", "data": {"title": "Paper 1", "itemType": "journalArticle"}},
            {"key": "ITEM2", "data": {"title": "Paper 2", "itemType": "conferencePaper"}}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.items.return_value = mock_items
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        items = client.get_items(limit=25, item_type="journalArticle")
        
        assert len(items) == 2
        assert items[0]["key"] == "ITEM1"
        mock_zotero_instance.items.assert_called_once_with(
            limit=25, 
            itemType="journalArticle"
        )
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_search_items_success(self, mock_zotero):
        """Test successful item search"""
        mock_items = [
            {"key": "SEARCH1", "data": {"title": "Neural Networks"}}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.items.return_value = mock_items
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        items = client.search_items("neural networks", limit=10)
        
        assert len(items) == 1
        assert items[0]["key"] == "SEARCH1"
        mock_zotero_instance.items.assert_called_once_with(
            q="neural networks",
            limit=10
        )
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_collection_items_success(self, mock_zotero):
        """Test successful collection items retrieval"""
        mock_items = [
            {"key": "COLL_ITEM1", "data": {"title": "Collection Paper 1"}}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.collection_items.return_value = mock_items
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        items = client.get_collection_items("COLLECTION123", limit=20)
        
        assert len(items) == 1
        assert items[0]["key"] == "COLL_ITEM1"
        mock_zotero_instance.collection_items.assert_called_once_with(
            "COLLECTION123",
            limit=20
        )
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_item_success(self, mock_zotero):
        """Test successful single item retrieval"""
        mock_item = {
            "key": "SINGLE_ITEM", 
            "data": {"title": "Single Paper"}
        }
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.item.return_value = mock_item
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        item = client.get_item("SINGLE_ITEM")
        
        assert item["key"] == "SINGLE_ITEM"
        mock_zotero_instance.item.assert_called_once_with("SINGLE_ITEM")
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_tags_success(self, mock_zotero):
        """Test successful tags retrieval"""
        mock_tags = [
            {"tag": "machine learning"},
            {"tag": "neural networks"}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.tags.return_value = mock_tags
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        tags = client.get_tags(limit=100)
        
        assert len(tags) == 2
        assert tags[0]["tag"] == "machine learning"
        mock_zotero_instance.tags.assert_called_once_with(limit=100)
    
    @patch('prisma.integrations.zotero.client.zotero')
    def test_get_item_tags_success(self, mock_zotero):
        """Test successful item tags retrieval"""
        mock_tags = [
            {"tag": "ai"},
            {"tag": "deep learning"}
        ]
        
        mock_zotero_instance = Mock()
        mock_zotero_instance.item_tags.return_value = mock_tags
        mock_zotero.Zotero.return_value = mock_zotero_instance
        
        client = ZoteroClient(self.config)
        tags = client.get_item_tags("ITEM_KEY")
        
        assert len(tags) == 2
        assert tags[0]["tag"] == "ai"
        mock_zotero_instance.item_tags.assert_called_once_with("ITEM_KEY")