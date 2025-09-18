"""
Unit tests for PrismaCoordinator - Main orchestration logic.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
import tempfile
import os

# Add prisma to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import (
    PaperMetadata, SearchResult, AnalysisResult, PaperSummary, CoordinatorResult
)
from prisma.storage.models.api_response_models import LLMRelevanceResult


class TestPrismaCoordinator(unittest.TestCase):
    """Test PrismaCoordinator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.coordinator = PrismaCoordinator(debug=False)
        
        # Sample paper metadata for testing
        self.sample_papers = [
            PaperMetadata(
                title='Neural Networks for Classification',
                authors=['Alice Smith', 'Bob Jones'],
                abstract='This paper presents a novel approach to neural network classification.',
                source='arxiv',
                url='https://example.com/paper1',
                pdf_url='https://example.com/paper1.pdf',
                arxiv_id='2301.00001',
                doi='10.1000/test.1',
                connected_papers_url='https://connectedpapers.com/1',
                journal='Neural Computing',
                volume='15',
                issue='3',
                pages='1-12',
                published_date='2023-01-01'
            ),
            PaperMetadata(
                title='Deep Learning Applications',
                authors=['Carol Brown'],
                abstract='A comprehensive review of deep learning applications in various domains.',
                source='semanticscholar',
                url='https://example.com/paper2',
                pdf_url='https://example.com/paper2.pdf',
                arxiv_id='2302.00001',
                doi='10.1000/test.2',
                connected_papers_url='https://connectedpapers.com/2',
                journal='AI Review',
                volume='20',
                issue='1',
                pages='45-67',
                published_date='2023-02-01'
            ),
            PaperMetadata(
                title='Machine Learning Fundamentals',
                authors=['David Wilson'],
                abstract='Introduction to machine learning concepts and algorithms.',
                source='arxiv',
                url='https://example.com/paper3',
                pdf_url='https://example.com/paper3.pdf',
                arxiv_id='2303.00001',
                doi='10.1000/test.3',
                connected_papers_url='https://connectedpapers.com/3',
                journal='ML Journal',
                volume='10',
                issue='2',
                pages='123-145',
                published_date='2023-03-01'
            )
        ]
        
        # Sample search result
        self.sample_search_result = SearchResult(
            papers=self.sample_papers,
            total_found=3,
            sources_searched=['arxiv', 'semanticscholar'],
            query='neural networks'
        )
        
        # Sample analysis result
        self.sample_analysis_result = AnalysisResult(
            summaries=[
                PaperSummary(
                    title=paper.title,
                    authors=paper.authors,
                    abstract=paper.abstract,
                    summary='Test summary',
                    key_findings=['Finding 1', 'Finding 2'],
                    methodology='Test methodology',
                    url=paper.url,
                    connected_papers_url=paper.connected_papers_url,
                    analysis_confidence=0.9,
                    processing_time=0.5
                ) for paper in self.sample_papers
            ],
            author_count=4,
            total_papers=3,
            avg_processing_time=0.5,
            top_authors=['Alice Smith', 'Bob Jones', 'Carol Brown', 'David Wilson'],
            common_themes=['neural networks', 'deep learning']
        )
    
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
    
    def test_run_review_no_papers_found(self):
        """Test run_review when no papers are found."""
        # Mock search agent to return empty results
        with patch.object(self.coordinator.search_agent, 'search') as mock_search, \
             patch('prisma.coordinator.Path') as mock_path:
            
            empty_result = SearchResult(
                papers=[],
                total_found=0,
                sources_searched=['arxiv'],
                query='nonexistent topic'
            )
            mock_search.return_value = empty_result
            
            # Mock Path to return a valid fallback output file
            mock_output_path = Mock()
            mock_path.return_value = mock_output_path
            mock_output_path.exists.return_value = False
            mock_output_path.__str__ = Mock(return_value='./failed_output.md')
            
            config = {
                'topic': 'nonexistent topic',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': './failed_output.md'  # Provide output_file path
            }
            
            result = self.coordinator.run_review(config)
            
            self.assertFalse(result.success)
            self.assertEqual(result.papers_analyzed, 0)
            self.assertEqual(result.authors_found, 0)
            self.assertIn("No papers found", result.errors[0])
    
    @patch('prisma.coordinator.Path')
    def test_run_review_successful_workflow(self, mock_path):
        """Test successful run_review workflow."""
        # Mock file operations - return string instead of Mock
        mock_path.return_value = "./test_output.md"  # Return string directly
        
        # Mock all the agents
        with patch.object(self.coordinator.search_agent, 'search') as mock_search, \
             patch.object(self.coordinator.analysis_agent, 'assess_relevance') as mock_relevance, \
             patch.object(self.coordinator.analysis_agent, 'analyze') as mock_analyze, \
             patch.object(self.coordinator.report_agent, 'generate') as mock_report, \
             patch('builtins.open', mock_open()) as mock_file:
            
            # Setup mocks
            mock_search.return_value = self.sample_search_result
            mock_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                semantic_score=0.9,
                reasoning='Test reasoning',
                confidence=0.8
            )
            mock_analyze.return_value = self.sample_analysis_result
            
            # Mock report as object with content attribute
            mock_report_obj = Mock()
            mock_report_obj.content = "# Test Report\nContent here"
            mock_report.return_value = mock_report_obj
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv', 'semanticscholar'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = self.coordinator.run_review(config)
            
            # Verify successful execution
            self.assertTrue(result.success)
            self.assertEqual(result.papers_analyzed, 3)  # All papers relevant
            self.assertEqual(result.authors_found, 4)
            self.assertIsNotNone(result.output_file)
            if result.total_duration is not None:
                self.assertGreater(result.total_duration, 0)
            
            # Verify method calls
            mock_search.assert_called_once_with(
                query='neural networks',
                sources=['arxiv', 'semanticscholar'],
                limit=10
            )
            self.assertEqual(mock_relevance.call_count, 3)  # One per paper
            mock_analyze.assert_called_once()
            mock_report.assert_called_once()
    
    def test_run_review_with_irrelevant_papers(self):
        """Test run_review workflow with all irrelevant papers."""
        with patch.object(self.coordinator.search_agent, 'search') as mock_search, \
             patch.object(self.coordinator.analysis_agent, 'assess_relevance') as mock_relevance:
            
            mock_search.return_value = self.sample_search_result
            
            # Mock relevance assessment - all papers irrelevant
            relevance_results = [
                LLMRelevanceResult(
                    is_relevant=False,
                    relevance_level='NOT_RELEVANT',
                    semantic_score=0.2,
                    reasoning='Not relevant',
                    confidence=0.8
                ),
                LLMRelevanceResult(
                    is_relevant=False,
                    relevance_level='NOT_RELEVANT',
                    semantic_score=0.2,
                    reasoning='Not relevant',
                    confidence=0.9
                ),
                LLMRelevanceResult(
                    is_relevant=False,
                    relevance_level='NOT_RELEVANT',
                    semantic_score=0.1,
                    reasoning='Not relevant',
                    confidence=0.8
                )
            ]
            mock_relevance.side_effect = relevance_results
            
            config = {
                'topic': 'specific neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = self.coordinator.run_review(config)
            
            # Should fail because no relevant papers after filtering
            self.assertFalse(result.success)
            self.assertIn("No relevant papers found", result.errors[0])
            
            # Verify pipeline metadata exists and contains expected fields
            if result.pipeline_metadata is not None:
                self.assertIn('papers_found', result.pipeline_metadata)
                self.assertIn('papers_discarded', result.pipeline_metadata)
                self.assertEqual(result.pipeline_metadata['papers_found'], 3)
                self.assertEqual(result.pipeline_metadata['papers_discarded'], 3)
    
    def test_run_review_with_relevance_assessment_error(self):
        """Test run_review when relevance assessment fails."""
        with patch.object(self.coordinator.search_agent, 'search') as mock_search, \
             patch.object(self.coordinator.analysis_agent, 'assess_relevance') as mock_relevance, \
             patch.object(self.coordinator.analysis_agent, 'analyze') as mock_analyze, \
             patch.object(self.coordinator.report_agent, 'generate') as mock_report, \
             patch('prisma.coordinator.Path') as mock_path, \
             patch('builtins.open', mock_open()) as mock_file:
            
            # Setup mocks
            mock_search.return_value = self.sample_search_result
            mock_relevance.side_effect = Exception("LLM connection failed")
            mock_analyze.return_value = self.sample_analysis_result
            
            # Mock report as object with content attribute
            mock_report_obj = Mock()
            mock_report_obj.content = "# Test Report"
            mock_report.return_value = mock_report_obj
            
            # Mock Path
            mock_path.return_value = "./test_output.md"
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = self.coordinator.run_review(config)
            
            # Should still succeed - papers kept when relevance assessment fails
            self.assertTrue(result.success)
            self.assertEqual(result.papers_analyzed, 3)  # All papers kept as fallback
    
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
    
    def test_debug_output(self):
        """Test that debug output is produced when debug=True."""
        coordinator = PrismaCoordinator(debug=True)
        
        with patch('builtins.print') as mock_print:
            # Mock search agent to return empty results for quick test
            with patch.object(coordinator.search_agent, 'search') as mock_search:
                empty_result = SearchResult(
                    papers=[],
                    total_found=0,
                    sources_searched=['arxiv'],
                    query='test topic'
                )
                mock_search.return_value = empty_result
                
                config = {
                    'topic': 'test topic',
                    'sources': ['arxiv'],
                    'limit': 10,
                    'output_file': './test_output.md'
                }
                
                coordinator.run_review(config)
                
                # Verify debug output was produced
                debug_calls = [call for call in mock_print.call_args_list 
                              if '[DEBUG]' in str(call)]
                self.assertGreater(len(debug_calls), 0)
    
    def test_run_review_with_debug_output_comprehensive(self):
        """Test debug output coverage throughout the workflow."""
        # Create coordinator with debug enabled
        coordinator = PrismaCoordinator(debug=True)
        
        # Mock all agents
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch.object(coordinator, 'analysis_agent') as mock_analysis, \
             patch.object(coordinator, 'report_agent') as mock_report, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Mock search results
            mock_search.search.return_value = SearchResult(
                papers=self.sample_papers[:1],  # One paper
                total_found=1,
                sources_searched=['arxiv'],
                query='neural networks'
            )
            
            # Mock relevance assessment
            mock_analysis.assess_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant to neural networks'
            )
            
            # Mock analysis results
            mock_analysis.analyze.return_value = AnalysisResult(
                summaries=[
                    PaperSummary(
                        title='Neural Networks for Classification',
                        authors=['Alice Smith'],
                        abstract='This paper presents a novel approach to neural network classification.',
                        summary='Test summary',
                        key_findings=['Finding 1'],
                        methodology='Test method',
                        url='https://example.com/paper1',
                        connected_papers_url='https://connectedpapers.com/1',
                        analysis_confidence=0.9,
                        processing_time=1.5
                    )
                ],
                author_count=1,
                total_papers=1,
                common_themes=['neural networks'],
                avg_processing_time=1.5
            )
            
            # Mock report generation
            mock_report.generate.return_value = Mock(content='Test report')
            
            # Run the review
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Verify debug prints were called for different stages
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            
            # Check for key debug messages that should appear
            self.assertTrue(any('Searching for papers on:' in call for call in debug_calls))
            self.assertTrue(any('Found' in call and 'papers' in call for call in debug_calls))
            self.assertTrue(any('Assessing document relevance' in call for call in debug_calls))
            self.assertTrue(any('Relevant (HIGHLY_RELEVANT)' in call for call in debug_calls))
            self.assertTrue(any('Checking for duplicates' in call for call in debug_calls))
            self.assertTrue(any('Analyzing' in call and 'papers' in call for call in debug_calls))
            self.assertTrue(any('Generating report' in call for call in debug_calls))
    
    def test_run_review_with_filtered_papers_debug(self):
        """Test debug output when papers are filtered out."""
        coordinator = PrismaCoordinator(debug=True)
        
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch.object(coordinator, 'analysis_agent') as mock_analysis, \
             patch('builtins.print') as mock_print:
            
            # Mock search results
            mock_search.search.return_value = SearchResult(
                papers=self.sample_papers[:1],
                total_found=1,
                sources_searched=['arxiv'],
                query='neural networks'
            )
            
            # Mock relevance assessment - paper not relevant
            mock_analysis.assess_relevance.return_value = LLMRelevanceResult(
                is_relevant=False,
                relevance_level='NOT_RELEVANT',
                confidence=0.3,
                semantic_score=0.2,
                reasoning='Not relevant'
            )
            
            # Run the review (will fail due to no relevant papers)
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should fail due to no relevant papers
            self.assertFalse(result.success)
            
            # Verify debug prints include filtered papers
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            
            # Check for filtered paper debug message
            self.assertTrue(any('Filtered (NOT_RELEVANT)' in call for call in debug_calls))
    
    def test_run_review_main_exception_handling(self):
        """Test main exception handler in run_review method."""
        coordinator = PrismaCoordinator(debug=True)
        
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch('builtins.print') as mock_print, \
             patch('traceback.print_exc') as mock_traceback:
            
            # Make search_agent raise an exception
            mock_search.search.side_effect = Exception("Search failed")
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should return failure result
            self.assertFalse(result.success)
            self.assertEqual(result.papers_analyzed, 0)
            self.assertEqual(result.authors_found, 0)
            self.assertIn('Search failed', result.errors)
            self.assertEqual(result.output_file, 'test_output.md')
            
            # Verify traceback was printed in debug mode
            mock_traceback.assert_called_once()
    
    def test_save_papers_to_zotero_error_handling(self):
        """Test _save_papers_to_zotero error scenarios."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent that will fail
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.client.save_items.side_effect = Exception("Zotero save failed")
        
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch.object(coordinator, 'analysis_agent') as mock_analysis, \
             patch.object(coordinator, 'report_agent') as mock_report, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Mock search results
            mock_search.search.return_value = SearchResult(
                papers=self.sample_papers[:1],
                total_found=1,
                sources_searched=['arxiv'],
                query='neural networks'
            )
            
            # Mock relevance assessment
            mock_analysis.assess_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant'
            )
            
            # Mock analysis results
            mock_analysis.analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=1,
                total_papers=0,
                common_themes=[],
                avg_processing_time=1.0
            )
            
            # Mock report generation
            mock_report.generate.return_value = Mock(content='Test report')
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should still succeed but with warnings
            self.assertTrue(result.success)
            self.assertIn('Failed to save papers to Zotero', result.warnings)
            
            # Verify debug print for Zotero save error
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('Zotero save error' in call for call in debug_calls))
    
    def test_check_zotero_duplicate_search_error(self):
        """Test _check_zotero_duplicate_simple error scenarios."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent that will fail on search
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.search_papers.side_effect = Exception("Search failed")
        
        with patch('builtins.print') as mock_print:
            paper = self.sample_papers[0]
            result = coordinator._check_zotero_duplicate_simple(paper)
            
            # Should return False when search fails
            self.assertFalse(result)
            
            # Verify debug print for error
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('Error checking duplicate' in call for call in debug_calls))
    
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
    
    def test_run_review_no_zotero_agent_debug(self):
        """Test debug output when no Zotero agent available."""
        coordinator = PrismaCoordinator(debug=True)
        coordinator.zotero_agent = None
        
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch.object(coordinator, 'analysis_agent') as mock_analysis, \
             patch.object(coordinator, 'report_agent') as mock_report, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Mock search results
            mock_search.search.return_value = SearchResult(
                papers=self.sample_papers[:1],
                total_found=1,
                sources_searched=['arxiv'],
                query='neural networks'
            )
            
            # Mock relevance assessment
            mock_analysis.assess_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant'
            )
            
            # Mock analysis results
            mock_analysis.analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=1,
                total_papers=1,
                common_themes=[],
                avg_processing_time=1.0
            )
            
            # Mock report generation
            mock_report.generate.return_value = Mock(content='Test report')
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should succeed
            self.assertTrue(result.success)
            
            # Verify debug print for no Zotero agent
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('Zotero agent not available' in call for call in debug_calls))
    
    def test_run_review_duplicate_check_debug(self):
        """Test debug output for duplicate checking."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.search_papers.return_value = []  # No duplicates
        
        with patch.object(coordinator, 'search_agent') as mock_search, \
             patch.object(coordinator, 'analysis_agent') as mock_analysis, \
             patch.object(coordinator, 'report_agent') as mock_report, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Mock search results
            mock_search.search.return_value = SearchResult(
                papers=self.sample_papers[:1],
                total_found=1,
                sources_searched=['arxiv'],
                query='neural networks'
            )
            
            # Mock relevance assessment
            mock_analysis.assess_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant'
            )
            
            # Mock analysis results
            mock_analysis.analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=1,
                total_papers=1,
                common_themes=[],
                avg_processing_time=1.0
            )
            
            # Mock report generation
            mock_report.generate.return_value = Mock(content='Test report')
            
            config = {
                'topic': 'neural networks',
                'sources': ['arxiv'],
                'limit': 10,
                'output_file': 'test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should succeed
            self.assertTrue(result.success)
            
            # Verify debug prints for duplicate checking
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('Duplicate check complete' in call for call in debug_calls))
    
    def test_save_papers_to_zotero_comprehensive(self):
        """Test _save_papers_to_zotero method comprehensively."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        mock_zotero_agent.client = Mock()
        mock_zotero_agent.client.save_items.return_value = ['item1', 'item2']
        
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
        
        with patch('builtins.print') as mock_print, \
             patch('prisma.coordinator.config') as mock_config, \
             patch('builtins.getattr') as mock_getattr:
            
            # Configure mock config
            mock_config.get.side_effect = lambda key, default=None: {
                'sources.zotero.min_confidence_for_save': 0.5,
                'sources.zotero.auto_save_collection': 'Test Collection'
            }.get(key, default)
            
            # Mock getattr to return different confidence scores
            def getattr_side_effect(obj, attr, default=None):
                if attr == 'confidence_score':
                    if obj == papers[0]:
                        return 0.3  # Below threshold
                    elif obj == papers[1]:
                        return 0.8  # Above threshold
                elif attr in ['venue', 'year']:
                    return ''  # Empty string for optional fields
                return default
            
            mock_getattr.side_effect = getattr_side_effect
            
            # Call the method
            result = coordinator._save_papers_to_zotero(papers, analysis_results, 'test topic')
            
            # Should save 1 paper (the one with high confidence)
            self.assertEqual(result, 1)
            
            # Verify save_items was called
            mock_zotero_agent.client.save_items.assert_called_once()
            
            # Verify the item structure
            call_args = mock_zotero_agent.client.save_items.call_args
            items = call_args[1]['items']  # keyword argument
            
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item['title'], 'Deep Learning Applications')
            self.assertEqual(item['itemType'], 'journalArticle')
            self.assertIn('Prisma-Discovery', [tag['tag'] for tag in item['tags']])
            self.assertIn('Confidence-0.80', [tag['tag'] for tag in item['tags']])
            self.assertIn('Source-semantic_scholar', [tag['tag'] for tag in item['tags']])
            self.assertIn('Topic-test topic', [tag['tag'] for tag in item['tags']])
            
            # Verify summary was added to abstract
            self.assertIn('[Prisma Summary]', item['abstractNote'])
            self.assertIn('Test summary for second paper', item['abstractNote'])
    
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
        
        with patch('builtins.print') as mock_print, \
             patch('prisma.coordinator.config') as mock_config, \
             patch('builtins.getattr') as mock_getattr:
            
            # Configure mock config
            mock_config.get.side_effect = lambda key, default=None: {
                'sources.zotero.min_confidence_for_save': 0.8
            }.get(key, default)
            
            # Mock getattr to return low confidence
            mock_getattr.return_value = 0.3  # Below threshold
            
            # Call the method
            result = coordinator._save_papers_to_zotero(papers, analysis_results, 'test topic')
            
            # Should save 0 papers
            self.assertEqual(result, 0)
            
            # Verify debug message about no papers meeting threshold
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('No papers meet minimum confidence threshold' in call for call in debug_calls))


if __name__ == '__main__':
    unittest.main()