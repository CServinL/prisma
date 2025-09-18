"""
Test coordinator main workflow scenarios.
"""

from unittest.mock import Mock, patch, mock_open
from .conftest import CoordinatorTestBase
from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import SearchResult
from prisma.storage.models.api_response_models import LLMRelevanceResult


class TestCoordinatorWorkflow(CoordinatorTestBase):
    """Test PrismaCoordinator main workflow."""
    
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
                'output_file': './failed_output.md'
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
        mock_path.return_value = "./test_output.md"
        
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