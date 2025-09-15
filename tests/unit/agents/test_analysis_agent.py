"""
Unit tests for Analysis Agent.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

from agents.analysis_agent import AnalysisAgent


class TestAnalysisAgent(unittest.TestCase):
    """Test AnalysisAgent functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analysis_agent = AnalysisAgent()
        self.sample_paper = {
            'title': 'Test Paper Title',
            'authors': ['Author One', 'Author Two'],
            'abstract': 'This is a test abstract with some content about machine learning and neural networks.'
        }
    
    def test_initialization(self):
        """Test AnalysisAgent initializes correctly."""
        self.assertIsNotNone(self.analysis_agent.llm_config)
        self.assertIsNotNone(self.analysis_agent.base_url)
        self.assertIsNotNone(self.analysis_agent.model)
    
    def test_analyze_papers(self):
        """Test paper analysis functionality."""
        papers = [self.sample_paper]
        
        result = self.analysis_agent.analyze(papers)
        
        # Verify results structure
        self.assertIn('summaries', result)
        self.assertIn('author_count', result)
        self.assertEqual(len(result['summaries']), 1)
        self.assertEqual(result['author_count'], 2)
    
    def test_summarize_paper_structure(self):
        """Test paper summary structure."""
        summary = self.analysis_agent._summarize_paper(self.sample_paper)
        
        # Verify required fields
        required_fields = ['title', 'authors', 'abstract', 'summary', 'key_findings', 'methodology', 'connected_papers_url']
        for field in required_fields:
            self.assertIn(field, summary)
        
        # Verify data types
        self.assertIsInstance(summary['authors'], list)
        self.assertIsInstance(summary['key_findings'], list)
        self.assertIsInstance(summary['connected_papers_url'], str)
    
    @patch('agents.analysis_agent.requests.post')
    def test_ollama_integration_success(self, mock_post):
        """Test successful Ollama integration."""
        # Mock successful Ollama response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'response': 'This paper presents a novel approach to machine learning with significant improvements.'
        }
        mock_post.return_value = mock_response
        
        summary = self.analysis_agent._get_ollama_summary(
            self.sample_paper['title'],
            self.sample_paper['abstract']
        )
        
        self.assertIsNotNone(summary)
        self.assertIn('machine learning', summary)
    
    @patch('agents.analysis_agent.requests.post')
    def test_ollama_integration_failure(self, mock_post):
        """Test Ollama integration failure handling."""
        # Mock failed Ollama response
        mock_post.side_effect = Exception("Connection failed")
        
        summary = self.analysis_agent._get_ollama_summary(
            self.sample_paper['title'],
            self.sample_paper['abstract']
        )
        
        # Should handle failure gracefully
        self.assertIsNone(summary)
    
    def test_extract_key_findings(self):
        """Test key findings extraction."""
        text_with_findings = "The results show significant improvements. Key findings indicate better performance."
        text_without_findings = "This is a simple text without specific indicators."
        
        findings1 = self.analysis_agent._extract_key_findings(text_with_findings)
        findings2 = self.analysis_agent._extract_key_findings(text_without_findings)
        
        self.assertIsInstance(findings1, list)
        self.assertIsInstance(findings2, list)
        self.assertTrue(len(findings1) > 0)
        self.assertTrue(len(findings2) > 0)


if __name__ == '__main__':
    unittest.main()