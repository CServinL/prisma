"""
Test coordinator debug output scenarios.
"""

from unittest.mock import Mock, patch, mock_open
from .conftest import CoordinatorTestBase
from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import SearchResult, AnalysisResult, PaperSummary
from prisma.storage.models.api_response_models import LLMRelevanceResult


class TestCoordinatorDebugOutput(CoordinatorTestBase):
    """Test PrismaCoordinator debug output."""
    
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