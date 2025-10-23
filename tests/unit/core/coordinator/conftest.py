"""
Shared test fixtures and base class for coordinator tests.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open

# Add prisma to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from prisma.coordinator import PrismaCoordinator
from prisma.storage.models.agent_models import (
    PaperMetadata, SearchResult, AnalysisResult, PaperSummary, CoordinatorResult
)
from prisma.storage.models.api_response_models import LLMRelevanceResult


class CoordinatorTestBase(unittest.TestCase):
    """Base test class with shared fixtures for coordinator tests."""
    
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
    
    def assert_debug_message_printed(self, mock_print, message: str, msg: str | None = None):
        """
        Helper method to assert that a debug message was printed.
        
        Args:
            mock_print: The mocked print function
            message: The message string to look for in debug output
            msg: Optional custom failure message
        """
        debug_calls = [call.args[0] for call in mock_print.call_args_list if 'DEBUG' in str(call.args)]
        self.assertTrue(
            any(message in call for call in debug_calls),
            msg or f"Expected debug message containing '{message}' not found. Debug calls: {debug_calls}"
        )