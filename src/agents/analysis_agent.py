"""
Analysis Agent - Analyzes and summarizes academic papers using LLM.
"""

import requests
import json
from typing import Dict, List, Any
import sys
from pathlib import Path
from datetime import datetime
import time

# Add utils to path for config
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config
from storage.models.agent_models import AnalysisResult, PaperSummary, PaperMetadata


class AnalysisAgent:
    """Analyze papers and generate summaries using Ollama."""
    
    def __init__(self):
        self.llm_config = config.get_llm_config()
        self.base_url = self.llm_config['base_url']
        self.model = self.llm_config['model']
    
    def analyze(self, papers: List[PaperMetadata]) -> AnalysisResult:
        """
        Analyze papers and generate summaries.
        
        Args:
            papers: List of paper metadata from SearchAgent
            
        Returns:
            AnalysisResult with summaries and metadata
        """
        summaries = []
        processing_times = []
        
        for paper in papers:
            start_time = time.time()
            summary = self._summarize_paper(paper)
            processing_time = time.time() - start_time
            
            processing_times.append(processing_time)
            summaries.append(summary)
        
        # Extract unique authors
        all_authors = []
        for paper in papers:
            all_authors.extend(paper.authors)
        unique_authors = list(set(all_authors))
        
        # Calculate average processing time
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        # Generate top authors (most frequent)
        author_counts = {}
        for author in all_authors:
            author_counts[author] = author_counts.get(author, 0) + 1
        top_authors = sorted(author_counts.keys(), key=lambda x: author_counts[x], reverse=True)[:10]
        
        return AnalysisResult(
            summaries=summaries,
            author_count=len(unique_authors),
            total_papers=len(papers),
            avg_processing_time=avg_processing_time,
            analysis_timestamp=datetime.now(),
            top_authors=top_authors,
            common_themes=[]  # TODO: Implement theme extraction
        )
    
    def _summarize_paper(self, paper: PaperMetadata) -> PaperSummary:
        """
        Summarize a single paper using Ollama.
        
        Args:
            paper: Paper metadata from SearchAgent
            
        Returns:
            PaperSummary with key findings, methodology, results
        """
        start_time = time.time()
        
        # Try to get enhanced summary from Ollama
        enhanced_summary = self._get_ollama_summary(paper.title, paper.abstract)
        
        # Extract key findings and methodology
        summary_text = enhanced_summary or paper.abstract
        key_findings = self._extract_key_findings(summary_text)
        methodology = self._extract_methodology(summary_text)
        
        processing_time = time.time() - start_time
        
        return PaperSummary(
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            summary=enhanced_summary or (paper.abstract[:500] + '...' if len(paper.abstract) > 500 else paper.abstract),
            key_findings=key_findings,
            methodology=methodology,
            url=paper.url,
            connected_papers_url=paper.connected_papers_url or f"https://www.connectedpapers.com/search?q={paper.title.replace(' ', '%20')}",
            analysis_confidence=0.8 if enhanced_summary else 0.5,
            processing_time=processing_time
        )
    
    def _get_ollama_summary(self, title: str, abstract: str) -> str:
        """Get enhanced summary from Ollama LLM."""
        try:
            prompt = f"""Analyze this research paper and provide a concise summary in 2-3 sentences:

Title: {title}

Abstract: {abstract}

Provide a clear, academic summary focusing on the main contribution and significance."""

            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 200
                    }
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
            else:
                print(f"[WARNING] Ollama request failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"[WARNING] Ollama analysis failed: {e}")
            return None
    
    def _extract_key_findings(self, text: str) -> List[str]:
        """Extract key findings from summary text."""
        # Simple extraction for MVP - could be enhanced with NLP
        if "findings" in text.lower() or "results" in text.lower():
            return [text.split('.')[0] + '.']
        return ['Key findings extracted from analysis']
    
    def _extract_methodology(self, text: str) -> str:
        """Extract methodology information from summary text."""
        # Simple extraction for MVP - could be enhanced with NLP
        if "method" in text.lower() or "approach" in text.lower():
            return "Methodology identified in analysis"
        return "Methodology analysis from abstract"
    
    def _fetch_full_text(self, paper: dict) -> str:
        """Fetch full text of paper if available."""
        # TODO: Implement paper fetching from various sources
        pass