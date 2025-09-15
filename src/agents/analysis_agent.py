"""
Analysis Agent - Analyzes and summarizes academic papers using LLM.
"""

import requests
import json
from typing import Dict, List, Any
import sys
from pathlib import Path

# Add utils to path for config
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config


class AnalysisAgent:
    """Analyze papers and generate summaries using Ollama."""
    
    def __init__(self):
        self.llm_config = config.get_llm_config()
        self.base_url = self.llm_config['base_url']
        self.model = self.llm_config['model']
    
    def analyze(self, papers: list) -> dict:
        """
        Analyze papers and generate summaries.
        
        Args:
            papers: List of paper metadata from SearchAgent
            
        Returns:
            Dict with summaries and metadata
        """
        summaries = []
        for paper in papers:
            summary = self._summarize_paper(paper)
            summaries.append(summary)
        
        return {
            'summaries': summaries,
            'author_count': len(set(
                author for paper in papers 
                for author in paper.get('authors', [])
            ))
        }
    
    def _summarize_paper(self, paper: dict) -> dict:
        """
        Summarize a single paper using Ollama.
        
        Args:
            paper: Paper metadata and content
            
        Returns:
            Summary with key findings, methodology, results
        """
        abstract = paper.get('abstract', 'No abstract available')
        title = paper.get('title', 'Unknown Title')
        
        # Try to get enhanced summary from Ollama
        enhanced_summary = self._get_ollama_summary(title, abstract)
        
        return {
            'title': title,
            'authors': paper.get('authors', []),
            'abstract': abstract,
            'summary': enhanced_summary or (abstract[:500] + '...' if len(abstract) > 500 else abstract),
            'key_findings': self._extract_key_findings(enhanced_summary or abstract),
            'methodology': self._extract_methodology(enhanced_summary or abstract),
            'connected_papers_url': f"https://www.connectedpapers.com/search?q={title.replace(' ', '%20')}"
        }
    
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