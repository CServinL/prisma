"""
Unit tests for Analysis Agent.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
from datetime import datetime

# Add prisma to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from prisma.agents.analysis_agent import AnalysisAgent, _parse_confidence
from prisma.storage.models.agent_models import PaperMetadata, AnalysisResult, PaperSummary
from prisma.utils.config import LLMConfig


class TestAnalysisAgent(unittest.TestCase):
    """Test AnalysisAgent functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # AnalysisAgent() reads prisma.utils.config's module-level `config`
        # singleton and, since ChatLLM.from_llm_config() now resolves the
        # provider/base_url/api_key eagerly at construction time (not
        # per-call like the old hand-rolled transport), a real machine's
        # ~/.config/prisma/config.toml with e.g. provider=openrouter and an
        # unset api_key_env would make construction itself raise. Force a
        # known-good local config for the duration of construction instead
        # of mutating llm_config after the fact (too late now to matter).
        test_llm_config = LLMConfig(provider='ollama', model='qwen2.5:7b-32k', host='localhost:11434')
        with patch('prisma.agents.analysis_agent.config.get_llm_config', return_value=test_llm_config):
            self.analysis_agent = AnalysisAgent()
        self.sample_paper = PaperMetadata(
            title='Test Paper Title',
            authors=['Author One', 'Author Two'],
            abstract='This is a test abstract with some content about machine learning and neural networks.',
            source='test',
            url='https://example.com/paper',
            pdf_url=None,
            published_date=None,
            arxiv_id=None,
            doi=None,
            connected_papers_url=None,
            journal=None,
            volume=None,
            issue=None,
            pages=None
        )

    def test_initialization(self):
        """Test AnalysisAgent initializes correctly."""
        self.assertIsNotNone(self.analysis_agent.llm_config)
        self.assertIsNotNone(self.analysis_agent.model)
        self.assertIsNotNone(self.analysis_agent._chat_llm)

    # Every test below that reaches _call_llm mocks ChatLLM.complete directly
    # on the agent's own instance -- the agent routes every LLM call through
    # self._chat_llm (prisma.services.chat_llm.ChatLLM), so this is the one
    # seam that matters regardless of provider (ollama/llama_cpp/openrouter).
    def test_analyze_papers(self):
        """Test paper analysis functionality."""
        with patch.object(self.analysis_agent._chat_llm, 'complete', return_value='Summary of the paper.'):
            papers = [self.sample_paper]
            result = self.analysis_agent.analyze(papers)

        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(len(result.summaries), 1)
        self.assertEqual(result.author_count, 2)
        self.assertIsInstance(result.summaries[0], PaperSummary)

    def test_summarize_paper_structure(self):
        """Test paper summary structure."""
        with patch.object(self.analysis_agent._chat_llm, 'complete', return_value='Summary of the paper.'):
            summary = self.analysis_agent._summarize_paper(self.sample_paper)

        self.assertIsInstance(summary, PaperSummary)
        self.assertEqual(summary.title, self.sample_paper.title)
        self.assertEqual(summary.authors, self.sample_paper.authors)
        self.assertEqual(summary.abstract, self.sample_paper.abstract)
        self.assertIsInstance(summary.summary, str)
        self.assertIsInstance(summary.key_findings, list)
        self.assertIsInstance(summary.methodology, str)
        self.assertIsInstance(summary.connected_papers_url, str)

    def test_ollama_integration_success(self):
        """Test successful LLM integration."""
        with patch.object(
            self.analysis_agent._chat_llm, 'complete',
            return_value='This paper presents a novel approach to machine learning with significant improvements.',
        ):
            summary = self.analysis_agent._get_ollama_summary(
                self.sample_paper.title,
                self.sample_paper.abstract
            )

        self.assertIsNotNone(summary)
        self.assertIn('machine learning', summary)

    def test_ollama_integration_failure(self):
        """Test LLM integration failure handling."""
        with patch.object(self.analysis_agent._chat_llm, 'complete', side_effect=Exception("Connection failed")):
            summary = self.analysis_agent._get_ollama_summary(
                self.sample_paper.title,
                self.sample_paper.abstract
            )

        # Should handle failure gracefully and return empty string
        self.assertEqual(summary, "")

    def test_ollama_summary_returns_empty_when_no_answer(self):
        """ChatLLM.complete() returning None (lease denied or call failed)
        should be handled like any other LLM failure, not crash."""
        with patch.object(self.analysis_agent._chat_llm, 'complete', return_value=None) as mock_complete:
            summary = self.analysis_agent._get_ollama_summary(
                self.sample_paper.title,
                self.sample_paper.abstract
            )

        self.assertEqual(summary, "")
        self.assertTrue(mock_complete.called)

    def test_call_llm_passes_per_call_max_tokens_and_timeout(self):
        """Different operations tune max_tokens/timeout differently (e.g. a
        short yes/no prompt vs a full summary) -- confirm those per-call
        values actually reach ChatLLM.complete(), not just its config default."""
        with patch.object(self.analysis_agent._chat_llm, 'complete', return_value='ok') as mock_complete:
            self.analysis_agent._call_llm("prompt", temperature=0.2, max_tokens=42, timeout=7)

        mock_complete.assert_called_once()
        _, kwargs = mock_complete.call_args
        self.assertEqual(kwargs['temperature'], 0.2)
        self.assertEqual(kwargs['max_tokens'], 42)
        self.assertEqual(kwargs['timeout'], 7)

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


class TestParseConfidence(unittest.TestCase):
    def test_recognized_levels(self):
        self.assertEqual(_parse_confidence("HIGH"), 0.9)
        self.assertEqual(_parse_confidence("MEDIUM"), 0.6)
        self.assertEqual(_parse_confidence("LOW"), 0.3)

    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(_parse_confidence("  high  "), 0.9)

    def test_unrecognized_defaults_to_mid(self):
        self.assertEqual(_parse_confidence("banana"), 0.5)


if __name__ == '__main__':
    unittest.main()
