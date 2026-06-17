"""
Test coordinator error handling scenarios.
"""

from unittest.mock import Mock, patch, mock_open
from .conftest import CoordinatorTestBase
from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import SearchResult, AnalysisResult
from prisma.storage.models.api_response_models import LLMRelevanceResult


class TestCoordinatorErrorHandling(CoordinatorTestBase):
    """Test PrismaCoordinator error handling."""
    
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

    def test_relevance_assessment_error_with_debug(self):
        """Test relevance assessment error handling with debug output."""
        coordinator = PrismaCoordinator(debug=True)
        
        with patch.object(coordinator.search_agent, 'search') as mock_search, \
             patch.object(coordinator.analysis_agent, 'assess_relevance') as mock_relevance, \
             patch.object(coordinator.analysis_agent, 'analyze') as mock_analyze, \
             patch.object(coordinator.report_agent, 'generate') as mock_report, \
             patch('prisma.coordinator.Path') as mock_path, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Setup mocks
            mock_search.return_value = SearchResult(
                papers=self.sample_papers[:1],  # Just one paper
                total_found=1,
                sources_searched=['test'],
                query='test query'
            )
            
            # Make relevance assessment fail for the paper
            mock_relevance.side_effect = Exception("LLM connection failed")
            
            mock_analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=0,
                total_papers=1,
                common_themes=[],
                avg_processing_time=1.0
            )
            
            mock_report_obj = Mock()
            mock_report_obj.content = "# Test Report"
            mock_report.return_value = mock_report_obj
            mock_path.return_value = "./test_output.md"
            
            config = {
                'topic': 'test',
                'sources': ['test'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should still succeed (papers kept when relevance assessment fails)
            self.assertTrue(result.success)
            self.assertEqual(result.papers_analyzed, 1)
            
            # Verify debug print for relevance assessment error
            self.assert_debug_message_printed(mock_print, 'Relevance assessment failed')
            self.assert_debug_message_printed(mock_print, 'keeping paper')

    def test_duplicate_checking_error_with_debug(self):
        """Test duplicate checking error handling with debug output in main workflow."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent 
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        
        with patch.object(coordinator.search_agent, 'search') as mock_search, \
             patch.object(coordinator.analysis_agent, 'assess_relevance') as mock_relevance, \
             patch.object(coordinator.analysis_agent, 'analyze') as mock_analyze, \
             patch.object(coordinator.report_agent, 'generate') as mock_report, \
             patch.object(coordinator, '_check_zotero_duplicate_simple') as mock_duplicate_check, \
             patch('prisma.coordinator.Path') as mock_path, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Setup mocks
            mock_search.return_value = SearchResult(
                papers=self.sample_papers[:1],  # Just one paper
                total_found=1,
                sources_searched=['test'],
                query='test query'
            )
            
            # Make relevance assessment pass
            mock_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant'
            )
            
            # Make duplicate check fail with exception
            mock_duplicate_check.side_effect = Exception("Duplicate check failed")
            
            mock_analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=0,
                total_papers=1,
                common_themes=[],
                avg_processing_time=1.0
            )
            
            mock_report_obj = Mock()
            mock_report_obj.content = "# Test Report"
            mock_report.return_value = mock_report_obj
            mock_path.return_value = "./test_output.md"
            
            config = {
                'topic': 'test',
                'sources': ['test'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should still succeed (treat all papers as new when duplicate checking fails)
            self.assertTrue(result.success)
            self.assertEqual(result.papers_analyzed, 1)
            
            # Should have warning about duplicate checking failure
            self.assertIn('Duplicate checking failed', str(result.warnings))
            
            # Verify debug print for duplicate checking error (lines 170-178)
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('Duplicate checking failed, treating all as new' in call for call in debug_calls))

    def test_duplicate_found_debug_output(self):
        """Test debug output when duplicates are found (lines 170-172)."""
        coordinator = PrismaCoordinator(debug=True)
        
        # Setup mock Zotero agent 
        mock_zotero_agent = Mock()
        coordinator.zotero_agent = mock_zotero_agent
        
        with patch.object(coordinator.search_agent, 'search') as mock_search, \
             patch.object(coordinator.analysis_agent, 'assess_relevance') as mock_relevance, \
             patch.object(coordinator.analysis_agent, 'analyze') as mock_analyze, \
             patch.object(coordinator.report_agent, 'generate') as mock_report, \
             patch.object(coordinator, '_check_zotero_duplicate_simple') as mock_duplicate_check, \
             patch('prisma.coordinator.Path') as mock_path, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('builtins.print') as mock_print:
            
            # Setup mocks
            mock_search.return_value = SearchResult(
                papers=self.sample_papers[:2],  # Two papers
                total_found=2,
                sources_searched=['test'],
                query='test query'
            )
            
            # Make relevance assessment pass for both papers
            mock_relevance.return_value = LLMRelevanceResult(
                is_relevant=True,
                relevance_level='HIGHLY_RELEVANT',
                confidence=0.95,
                semantic_score=0.9,
                reasoning='Highly relevant'
            )
            
            # Make first paper a duplicate, second paper new
            mock_duplicate_check.side_effect = [True, False]  # First is duplicate, second is new
            
            mock_analyze.return_value = AnalysisResult(
                summaries=[],
                author_count=0,
                total_papers=1,  # Only one new paper analyzed
                common_themes=[],
                avg_processing_time=1.0
            )
            
            mock_report_obj = Mock()
            mock_report_obj.content = "# Test Report"
            mock_report.return_value = mock_report_obj
            mock_path.return_value = "./test_output.md"
            
            config = {
                'topic': 'test',
                'sources': ['test'],
                'limit': 10,
                'output_file': './test_output.md'
            }
            
            result = coordinator.run_review(config)
            
            # Should succeed with one new paper analyzed
            self.assertTrue(result.success)
            self.assertEqual(result.papers_analyzed, 1)
            
            # Verify debug print for duplicate found (lines 170-172)
            debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
            self.assertTrue(any('📚 Duplicate found in Zotero' in call for call in debug_calls))