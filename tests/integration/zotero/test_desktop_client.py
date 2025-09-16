"""
Test Suite for Zotero Desktop App Integration

This module tests the desktop app client functionality that maintains
100% compatibility with Zotero by using the official HTTP server.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import requests
from prisma.integrations.zotero.desktop_client import (
    ZoteroDesktopClient, 
    ZoteroDesktopConfig, 
    ZoteroDesktopError
)


class TestZoteroDesktopConfig:
    """Test configuration for desktop client"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = ZoteroDesktopConfig()
        
        assert config.server_url == "http://127.0.0.1:23119"
        assert config.timeout == 10.0
        assert config.check_running is True
        assert config.collection_key is None
    
    def test_custom_config(self):
        """Test custom configuration values"""
        config = ZoteroDesktopConfig(
            server_url="http://localhost:23119",
            timeout=30.0,
            check_running=False,
            collection_key="ABC123"
        )
        
        assert config.server_url == "http://localhost:23119"
        assert config.timeout == 30.0
        assert config.check_running is False
        assert config.collection_key == "ABC123"


class TestZoteroDesktopClient:
    """Test desktop app client functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = ZoteroDesktopConfig(check_running=False)
        
    @patch('requests.Session.get')
    def test_check_zotero_running_success(self, mock_get):
        """Test successful Zotero ping"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        client = ZoteroDesktopClient(self.config)
        assert client._check_zotero_running() is True
    
    @patch('requests.Session.get')
    def test_check_zotero_running_failure(self, mock_get):
        """Test failed Zotero ping"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        with pytest.raises(ZoteroDesktopError) as exc_info:
            ZoteroDesktopClient(ZoteroDesktopConfig(check_running=True))
        
        assert "Cannot connect to Zotero desktop app" in str(exc_info.value)
    
    @patch('requests.Session.get')
    def test_initialization_no_check(self, mock_get):
        """Test initialization without checking if running"""
        client = ZoteroDesktopClient(self.config)
        
        # Should not call ping during init
        mock_get.assert_not_called()
        assert client.config == self.config
    
    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_save_items_success(self, mock_get, mock_post):
        """Test successful item saving"""
        # Setup ping response
        mock_ping = Mock()
        mock_ping.status_code = 200
        mock_get.return_value = mock_ping
        
        # Setup save response  
        mock_save = Mock()
        mock_save.status_code = 200
        mock_post.return_value = mock_save
        
        client = ZoteroDesktopClient(self.config)
        
        items = [
            {
                "itemType": "journalArticle",
                "title": "Test Paper",
                "creators": [{"creatorType": "author", "firstName": "John", "lastName": "Doe"}],
                "DOI": "10.1000/test"
            }
        ]
        
        result = client.save_items(items)
        
        assert result is True
        mock_post.assert_called_once()
        
        # Check request data
        call_args = mock_post.call_args
        assert "/connector/saveItems" in call_args[0][0]
        
        request_data = call_args[1]['json']
        assert 'items' in request_data
        assert len(request_data['items']) == 1
        assert request_data['items'][0]['title'] == "Test Paper"
    
    def test_save_items_empty_list(self):
        """Test saving empty list of items"""
        client = ZoteroDesktopClient(self.config)
        
        result = client.save_items([])
        assert result is True  # Should succeed without doing anything
    
    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_save_items_with_collection(self, mock_get, mock_post):
        """Test saving items to specific collection"""
        # Setup responses
        mock_ping = Mock()
        mock_ping.status_code = 200
        mock_get.return_value = mock_ping
        
        mock_save = Mock()
        mock_save.status_code = 200
        mock_post.return_value = mock_save
        
        client = ZoteroDesktopClient(self.config)
        
        items = [{"itemType": "journalArticle", "title": "Test Paper"}]
        result = client.save_items(items, collection_key="ABC123")
        
        assert result is True
        
        # Check that collection was included in request
        call_args = mock_post.call_args
        request_data = call_args[1]['json']
        assert request_data['collection'] == "ABC123"
    
    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_save_items_server_error(self, mock_get, mock_post):
        """Test handling server error during save"""
        # Setup ping response
        mock_ping = Mock()
        mock_ping.status_code = 200
        mock_get.return_value = mock_ping
        
        # Setup error response
        mock_save = Mock()
        mock_save.status_code = 500
        mock_save.text = "Internal Server Error"
        mock_post.return_value = mock_save
        
        client = ZoteroDesktopClient(self.config)
        
        items = [{"itemType": "journalArticle", "title": "Test Paper"}]
        
        with pytest.raises(ZoteroDesktopError) as exc_info:
            client.save_items(items)
        
        assert "Failed to save items" in str(exc_info.value)
        assert "500" in str(exc_info.value)
    
    def test_format_item_for_zotero_simple(self):
        """Test item formatting for simple item"""
        client = ZoteroDesktopClient(self.config)
        
        item = {
            "title": "Test Paper",
            "creators": ["John Doe", "Jane Smith"],
            "DOI": "10.1000/test"
        }
        
        formatted = client._format_item_for_zotero(item)
        
        assert formatted is not None
        assert formatted["title"] == "Test Paper"
        assert formatted["DOI"] == "10.1000/test"
        assert formatted["itemType"] == "journalArticle"  # Default type
        
        # Check creators formatting
        assert len(formatted["creators"]) == 2
        assert formatted["creators"][0]["name"] == "John Doe"
        assert formatted["creators"][0]["creatorType"] == "author"
    
    def test_format_item_for_zotero_api_format(self):
        """Test item formatting for item already in API format"""
        client = ZoteroDesktopClient(self.config)
        
        item = {
            "data": {
                "itemType": "book",
                "title": "Test Book",
                "creators": [
                    {"creatorType": "author", "firstName": "John", "lastName": "Doe"}
                ]
            }
        }
        
        formatted = client._format_item_for_zotero(item)
        
        assert formatted is not None
        assert formatted["itemType"] == "book"
        assert formatted["title"] == "Test Book"
        assert len(formatted["creators"]) == 1
        assert formatted["creators"][0]["firstName"] == "John"
    
    def test_format_item_for_zotero_invalid(self):
        """Test item formatting for invalid item"""
        client = ZoteroDesktopClient(self.config)
        
        # Item that causes formatting error
        item = {"invalid": object()}  # Non-serializable object
        
        formatted = client._format_item_for_zotero(item)
        assert formatted is None
    
    @patch('requests.Session.get')
    def test_is_running_true(self, mock_get):
        """Test is_running when Zotero is running"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        client = ZoteroDesktopClient(self.config)
        assert client.is_running() is True
    
    @patch('requests.Session.get')
    def test_is_running_false(self, mock_get):
        """Test is_running when Zotero is not running"""
        mock_get.side_effect = requests.exceptions.ConnectionError()
        
        client = ZoteroDesktopClient(self.config)
        assert client.is_running() is False


class TestIntegrationScenarios:
    """Test realistic integration scenarios"""
    
    @patch('requests.Session')
    def test_typical_workflow(self, mock_session_class):
        """Test typical workflow of checking status and saving items"""
        # Setup mock session
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Setup ping response
        mock_ping = Mock()
        mock_ping.status_code = 200
        
        # Setup save response
        mock_save = Mock()
        mock_save.status_code = 200
        
        mock_session.get.return_value = mock_ping
        mock_session.post.return_value = mock_save
        
        # Initialize client
        config = ZoteroDesktopConfig(check_running=False)
        client = ZoteroDesktopClient(config)
        
        # Check if running
        assert client.is_running() is True
        
        # Save some items
        items = [
            {
                "itemType": "journalArticle",
                "title": "Paper from arXiv",
                "creators": [{"creatorType": "author", "firstName": "Alice", "lastName": "Research"}],
                "date": "2024",
                "DOI": "10.1000/arxiv.2024.001"
            },
            {
                "itemType": "journalArticle", 
                "title": "Paper from PubMed",
                "creators": [{"creatorType": "author", "firstName": "Bob", "lastName": "Medicine"}],
                "date": "2024",
                "DOI": "10.1000/pubmed.2024.002"
            }
        ]
        
        success = client.save_items(items, collection_key="research_collection")
        assert success is True
        
        # Verify the save call
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        
        # Check URL
        assert "/connector/saveItems" in call_args[0][0]
        
        # Check request data
        request_data = call_args[1]['json']
        assert len(request_data['items']) == 2
        assert request_data['collection'] == "research_collection"
        assert 'sessionID' in request_data
        assert request_data['uri'] == "https://prisma.ai/literature-review"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])