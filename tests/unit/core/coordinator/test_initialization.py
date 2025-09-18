"""
Test coordinator initialization scenarios.
"""

from unittest.mock import Mock, patch
from .conftest import CoordinatorTestBase
from prisma.coordinator import PrismaCoordinator


class TestCoordinatorInitialization(CoordinatorTestBase):
    """Test PrismaCoordinator initialization."""
    
    def test_initialization_without_zotero(self):
        """Test coordinator initialization without Zotero."""
        coordinator = PrismaCoordinator(debug=True)
        
        self.assertIsNotNone(coordinator.search_agent)
        self.assertIsNotNone(coordinator.analysis_agent)
        self.assertIsNotNone(coordinator.report_agent)
        self.assertIsNone(coordinator.zotero_agent)
        self.assertTrue(coordinator.debug)
    
    @patch('prisma.coordinator.config')
    def test_initialization_with_zotero_enabled(self, mock_config):
        """Test coordinator initialization with Zotero enabled."""
        # Mock config to enable Zotero
        mock_config.get.side_effect = lambda key, default=None: {
            'sources.zotero.enabled': True,
            'sources.zotero.auto_save_papers': True,
            'sources.zotero': {
                'api_key': 'test_key',
                'library_id': '12345',
                'library_type': 'user'
            }
        }.get(key, default)
        
        with patch('prisma.coordinator.ZoteroAgent') as mock_zotero_agent:
            mock_zotero_agent.return_value = Mock()
            coordinator = PrismaCoordinator(debug=True)
            
            self.assertIsNotNone(coordinator.zotero_agent)
            mock_zotero_agent.assert_called_once()
    
    @patch('prisma.coordinator.config')
    def test_initialization_with_zotero_error(self, mock_config):
        """Test coordinator initialization with Zotero configuration error."""
        # Mock config to enable Zotero
        mock_config.get.side_effect = lambda key, default=None: {
            'sources.zotero.enabled': True,
            'sources.zotero.auto_save_papers': True,
            'sources.zotero': {}
        }.get(key, default)
        
        with patch('prisma.coordinator.ZoteroAgent') as mock_zotero_agent:
            mock_zotero_agent.side_effect = Exception("Invalid configuration")
            coordinator = PrismaCoordinator(debug=True)
            
            # Should handle the error gracefully
            self.assertIsNone(coordinator.zotero_agent)
    
    def test_get_status(self):
        """Test get_status method."""
        status = self.coordinator.get_status()
        
        self.assertIn('version', status)
        self.assertIn('status', status)
        self.assertIn('agents', status)
        self.assertEqual(status['status'], 'ready')
        self.assertIn('search', status['agents'])
        self.assertIn('analysis', status['agents'])
        self.assertIn('report', status['agents'])