"""
Agents package for Prisma literature review system.

This package contains the 3 core agents:
- SearchAgent: Searches academic databases (PubMed, ArXiv)
- AnalysisAgent: Analyzes papers using Ollama LLM
- ReportAgent: Generates final literature review reports
"""

from .search_agent import SearchAgent
from .analysis_agent import AnalysisAgent
from .report_agent import ReportAgent

__all__ = ['SearchAgent', 'AnalysisAgent', 'ReportAgent']