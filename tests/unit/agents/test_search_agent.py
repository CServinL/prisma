"""
Unit tests for Search Agent.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

from agents.search_agent import SearchAgent


class TestSearchAgent(unittest.TestCase):
    """Test SearchAgent functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.search_agent = SearchAgent()
    
    def test_initialization(self):
        """Test SearchAgent initializes correctly."""
        self.assertIsNotNone(self.search_agent.arxiv_base_url)
        self.assertEqual(self.search_agent.arxiv_base_url, "http://export.arxiv.org/api/query")
    
    @patch('agents.search_agent.requests.get')
    def test_search_success(self, mock_get):
        """Test successful search operation."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/test.123</id>
    <title>Test Paper Title</title>
    <summary>Test abstract content</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Test Author</name></author>
  </entry>
</feed>'''
        mock_get.return_value = mock_response
        
        # Test search
        result = self.search_agent.search(
            query="test query",
            sources=["arxiv"],
            limit=1
        )
        
        # Verify results
        self.assertIn('papers', result)
        self.assertIn('total_found', result)
        self.assertIn('sources_searched', result)
        self.assertIn('query', result)
        self.assertEqual(result['query'], "test query")
        self.assertEqual(result['sources_searched'], ["arxiv"])
    
    def test_search_unsupported_source(self):
        """Test search with unsupported source."""
        result = self.search_agent.search(
            query="test query",
            sources=["unsupported"],
            limit=10
        )
        
        # Should return empty results but not crash
        self.assertEqual(len(result['papers']), 0)
        self.assertEqual(result['sources_searched'], ["unsupported"])
    
    def test_deduplicate_papers(self):
        """Test paper deduplication functionality."""
        papers = [
            {'title': 'Paper A', 'id': '1'},
            {'title': 'Paper B', 'id': '2'},
            {'title': 'Paper A', 'id': '1'},  # Duplicate
        ]
        
        unique_papers = self.search_agent._deduplicate_papers(papers)
        
        # Should remove duplicate
        self.assertEqual(len(unique_papers), 2)
        titles = [p['title'] for p in unique_papers]
        self.assertIn('Paper A', titles)
        self.assertIn('Paper B', titles)


if __name__ == '__main__':
    unittest.main()