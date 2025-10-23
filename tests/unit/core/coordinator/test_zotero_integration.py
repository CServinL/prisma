"""
Test coordinator Zotero integration scenarios.
"""

from unittest.mock import Mock, patch, mock_open
from .conftest import CoordinatorTestBase
from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import AnalysisResult, PaperSummary, SearchResult
from prisma.storage.models.api_response_models import LLMRelevanceResult


class TestCoordinatorZoteroIntegration(CoordinatorTestBase):
    """Test PrismaCoordinator Zotero integration."""
    
    @patch('prisma.coordinator.ZoteroSearchCriteria')
    def test_check_zotero_duplicate_simple(self, mock_criteria):
        """Test _check_zotero_duplicate_simple method."""
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        self.coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.search_papers.return_value = []
        
        paper = self.sample_papers[0]
        result = self.coordinator._check_zotero_duplicate_simple(paper)
        
        self.assertFalse(result)  # No duplicates found
        mock_zotero_agent.search_papers.assert_called_once()
    
    def test_check_zotero_duplicate_simple_no_agent(self):
        """Test _check_zotero_duplicate_simple with no Zotero agent."""
        paper = self.sample_papers[0]
        result = self.coordinator._check_zotero_duplicate_simple(paper)
        
        self.assertFalse(result)  # Should return False when no agent
    
    @patch('prisma.coordinator.ZoteroSearchCriteria')
    def test_check_zotero_duplicate_simple_with_duplicate(self, mock_criteria):
        """Test _check_zotero_duplicate_simple when duplicate exists."""
        # Setup mock Zotero agent with duplicate result
        mock_zotero_agent = Mock()
        self.coordinator.zotero_agent = mock_zotero_agent
        
        # Mock duplicate item with same title
        duplicate_item = Mock()
        duplicate_item.title = self.sample_papers[0].title
        mock_zotero_agent.search_papers.return_value = [duplicate_item]
        
        # Mock the search criteria construction
        mock_criteria_instance = Mock()
        mock_criteria.return_value = mock_criteria_instance
        
        paper = self.sample_papers[0]
        result = self.coordinator._check_zotero_duplicate_simple(paper)
        
        self.assertTrue(result)  # Duplicate found
        mock_zotero_agent.search_papers.assert_called_once_with(mock_criteria_instance)
    
    def test_save_papers_to_zotero_no_agent(self):
        """Test _save_papers_to_zotero with no Zotero agent."""
        result = self.coordinator._save_papers_to_zotero(
            self.sample_papers, 
            self.sample_analysis_result, 
            'test topic'
        )
        
        self.assertEqual(result, 0)  # No papers saved when no agent
    
    def test_save_papers_to_zotero_error_handling(self):
        """Test _save_papers_to_zotero error scenarios directly."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent that will fail
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.client.save_items.side_effect = Exception("Zotero save failed")
        
        # Create test paper with high confidence score
        papers = []
        paper = Mock()
        paper.title = "Test Paper 1"
        paper.authors = ["Author 1"]
        paper.abstract = "Abstract 1"
        paper.url = "http://example.com/paper1"
        paper.doi = "10.1000/doi1"
        paper.source = "test"
        paper.confidence_score = 0.8  # Above threshold
        papers.append(paper)
        
        # Mock analysis results
        mock_analysis_results = Mock()
        mock_analysis_results.summaries = []
        
        with patch('builtins.print') as mock_print, \
             patch('prisma.coordinator.config') as mock_config:
            
            # Configure mock config
            mock_config.get.side_effect = lambda key, default=None: {
                'sources.zotero.min_confidence_for_save': 0.5,
                'sources.zotero.auto_save_collection': 'Test Collection'
            }.get(key, default)
            
            # Should return 0 when saving fails
            result = coordinator._save_papers_to_zotero(papers, mock_analysis_results, 'test topic')
            self.assertEqual(result, 0)
            
            # Verify debug print for error
            self.assert_debug_message_printed(mock_print, 'Failed to save items to Zotero')
    
    def test_save_papers_to_zotero_no_papers(self):
        """Test _save_papers_to_zotero with no papers."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        
        # Mock empty analysis results
        mock_analysis_results = Mock()
        mock_analysis_results.summaries = []
        
        result = coordinator._save_papers_to_zotero([], mock_analysis_results, 'test topic')
        
        # Should return 0 papers saved
        self.assertEqual(result, 0)
    
    def test_save_papers_to_zotero_no_zotero_agent(self):
        """Test _save_papers_to_zotero with no Zotero agent."""
        coordinator = PrismaCoordinator(debug=True)
        coordinator.zotero_agent = None
        
        # Mock analysis results
        mock_analysis_results = Mock()
        mock_analysis_results.summaries = []
        
        result = coordinator._save_papers_to_zotero(self.sample_papers, mock_analysis_results, 'test topic')
        
        # Should return 0 papers saved
        self.assertEqual(result, 0)
    
    def test_save_papers_to_zotero_comprehensive(self):
        """Test _save_papers_to_zotero method comprehensively."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.client = Mock()
        mock_zotero_agent.client.save_items.return_value = 1  # Return count of items saved
        
        # Test papers with different confidence scores
        papers = [
            self.sample_papers[0],  # Will be filtered out due to low confidence
            self.sample_papers[1]   # Will be saved due to high confidence
        ]
        
        # Mock analysis results with summaries
        analysis_results = AnalysisResult(
            summaries=[
                PaperSummary(
                    title='Deep Learning Applications',
                    authors=['Carol Brown'],
                    abstract='A comprehensive review.',
                    summary='Test summary for second paper',
                    key_findings=['Finding A'],
                    methodology='Review method',
                    url='https://example.com/paper2',
                    connected_papers_url='https://connectedpapers.com/2',
                    analysis_confidence=0.9,
                    processing_time=2.0
                )
            ],
            author_count=1,
            total_papers=1,
            common_themes=['deep learning'],
            avg_processing_time=2.0
        )
        
        # Create mock papers with confidence scores using Mock objects
        papers = []
        for i in range(2):
            paper = Mock()
            paper.title = f"Test Paper {i+1}"
            paper.authors = [f"Author {i+1}"]
            paper.abstract = f"Abstract {i+1}"
            paper.url = f"http://example.com/paper{i+1}"
            paper.doi = f"10.1000/doi{i+1}"
            paper.source = "test"
            # Set different confidence scores
            paper.confidence_score = 0.3 if i == 0 else 0.8  # First below threshold, second above
            papers.append(paper)
        
        with patch('builtins.print') as mock_print, \
             patch('prisma.coordinator.config') as mock_config:
            
            # Configure mock config
            mock_config.get.side_effect = lambda key, default=None: {
                'sources.zotero.min_confidence_for_save': 0.5,
                'sources.zotero.auto_save_collection': 'Test Collection'
            }.get(key, default)
            
            # Call the method
            result = coordinator._save_papers_to_zotero(papers, analysis_results, 'test topic')
            
            # Should save 1 paper (the one with high confidence)
            self.assertEqual(result, 1)
            
            # Verify save_items was called
            mock_zotero_agent.client.save_items.assert_called_once()
            
            # Verify the item structure
            call_args = mock_zotero_agent.client.save_items.call_args
            items = call_args.kwargs['items']  # keyword argument
            
            self.assertEqual(len(items), 1)
            item = items[0]
            # Should save the second paper (Test Paper 2 with 0.8 confidence, above 0.5 threshold)
            self.assertEqual(item['title'], 'Test Paper 2')
            self.assertEqual(item['itemType'], 'journalArticle')
            self.assertIn('Prisma-Discovery', [tag['tag'] for tag in item['tags']])
            self.assertIn('Confidence-0.80', [tag['tag'] for tag in item['tags']])
            self.assertIn('Source-test', [tag['tag'] for tag in item['tags']])
            self.assertIn('Topic-test topic', [tag['tag'] for tag in item['tags']])
            
            # Since we don't have matching summaries in our mock, check base abstract
            self.assertEqual(item['abstractNote'], 'Abstract 2')
    
    def test_save_papers_to_zotero_no_high_confidence_papers(self):
        """Test _save_papers_to_zotero with no papers meeting confidence threshold."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        
        papers = [self.sample_papers[0]]
        analysis_results = AnalysisResult(
            summaries=[],
            author_count=0,
            total_papers=0,
            common_themes=[],
            avg_processing_time=0.0
        )
        
        # Create mock papers with low confidence scores
        papers = []
        for i in range(2):
            paper = Mock()
            paper.title = f"Test Paper {i+1}"
            paper.authors = [f"Author {i+1}"]
            paper.abstract = f"Abstract {i+1}"
            paper.url = f"http://example.com/paper{i+1}"
            paper.doi = f"10.1000/doi{i+1}"
            paper.source = "test"
            paper.confidence_score = 0.3  # Below threshold
            papers.append(paper)
        
        with patch('builtins.print') as mock_print, \
             patch('prisma.coordinator.config') as mock_config:
            
            # Configure mock config
            mock_config.get.side_effect = lambda key, default=None: {
                'sources.zotero.min_confidence_for_save': 0.8
            }.get(key, default)
            
            # Call the method
            result = coordinator._save_papers_to_zotero(papers, analysis_results, 'test topic')
            
            # Should save 0 papers
            self.assertEqual(result, 0)
            
            # Verify debug message about no papers meeting threshold
            self.assert_debug_message_printed(mock_print, 'No papers meet minimum confidence threshold')