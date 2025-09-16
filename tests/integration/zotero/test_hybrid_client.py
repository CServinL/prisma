"""
Test Zotero Integration

Basic tests for the hybrid Zotero integration that uses both SQLite and Web API.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from prisma.integrations.zotero import ZoteroHybridClient, ZoteroHybridConfig


class TestZoteroHybridConfig:
    """Test the hybrid configuration"""
    
    def test_api_config_detection(self):
        """Test API configuration detection"""
        config = ZoteroHybridConfig(
            api_key="test_key",
            library_id="12345",
            library_type="user"
        )
        assert config.has_api_config() is True
        
        config_no_api = ZoteroHybridConfig()
        assert config_no_api.has_api_config() is False
    
    def test_sqlite_config_detection(self):
        """Test SQLite configuration detection"""
        # Test with non-existent path
        config = ZoteroHybridConfig(library_path="/nonexistent/path.sqlite")
        assert config.has_sqlite_config() is False
        
        # Test with existing path (would need actual file)
        # This would pass if the file exists
        # config_existing = ZoteroHybridConfig(library_path="existing_file.sqlite")
        # assert config_existing.has_sqlite_config() is True


class TestZoteroHybridClient:
    """Test the hybrid client functionality"""
    
    def test_initialization_no_config(self):
        """Test that initialization fails with no valid config"""
        config = ZoteroHybridConfig()
        
        with pytest.raises(ValueError, match="No valid Zotero configuration"):
            ZoteroHybridClient(config)
    
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteClient')
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteConfig')
    def test_sqlite_only_initialization(self, mock_sqlite_config, mock_sqlite_client):
        """Test initialization with SQLite only"""
        # Mock Path.exists to return True
        with patch.object(Path, 'exists', return_value=True):
            config = ZoteroHybridConfig(library_path="/test/zotero.sqlite")
            
            # Mock the SQLite client instance
            mock_client_instance = Mock()
            mock_sqlite_client.return_value = mock_client_instance
            
            client = ZoteroHybridClient(config)
            
            assert client.sqlite_client is not None
            assert client.api_client is None
            mock_sqlite_client.assert_called_once()
    
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroClient')
    def test_api_only_initialization(self, mock_api_client):
        """Test initialization with Web API only"""
        config = ZoteroHybridConfig(
            api_key="test_key",
            library_id="12345",
            library_type="user"
        )
        
        client = ZoteroHybridClient(config)
        
        assert client.sqlite_client is None
        assert client.api_client is not None
        mock_api_client.assert_called_once()
    
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroClient')
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteClient')  
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteConfig')
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroConfig')
    def test_hybrid_initialization(self, mock_zotero_config, mock_sqlite_config, mock_sqlite_client, mock_api_client):
        """Test initialization with both SQLite and API"""
        with patch.object(Path, 'exists', return_value=True):
            config = ZoteroHybridConfig(
                api_key="test_key",
                library_id="12345",
                library_type="user",
                library_path="/test/zotero.sqlite"
            )
            
            # Mock the client instances
            mock_sqlite_instance = Mock()
            mock_api_instance = Mock()
            mock_sqlite_client.return_value = mock_sqlite_instance
            mock_api_client.return_value = mock_api_instance
            
            client = ZoteroHybridClient(config)
            
            assert client.sqlite_client is not None
            assert client.api_client is not None
            mock_sqlite_client.assert_called_once()
            mock_api_client.assert_called_once()
    
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteClient')
    @patch('prisma.integrations.zotero.hybrid_client.ZoteroSQLiteConfig')
    def test_search_sqlite_preferred(self, mock_sqlite_config, mock_sqlite_client):
        """Test that SQLite is preferred for search when available"""
        with patch.object(Path, 'exists', return_value=True):
            config = ZoteroHybridConfig(
                library_path="/test/zotero.sqlite",
                prefer_sqlite=True
            )
            
            # Mock SQLite client to return results
            mock_sqlite_instance = Mock()
            mock_sqlite_instance.search_items.return_value = [
                {'title': 'Test Paper', 'key': 'ABC123'}
            ]
            mock_sqlite_client.return_value = mock_sqlite_instance
            
            client = ZoteroHybridClient(config)
            results = client.search_items(query="test")
            
            assert len(results) == 1
            assert results[0]['title'] == 'Test Paper'
            mock_sqlite_instance.search_items.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])