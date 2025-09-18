"""
Analysis Agent - Analyzes and summarizes academic papers using LLM.
"""

import requests
import json
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime
import time

from ..utils.config import config
from ..storage.models.agent_models import PaperMetadata, PaperSummary, AnalysisResult, ReportMetadata, LiteratureReviewReport
from ..storage.models.api_response_models import OllamaGenerateResponse, LLMRelevanceResult


class AnalysisAgent:
    """Analyze papers and generate summaries using Ollama."""
    
    def __init__(self):
        self.llm_config = config.get_llm_config()
        self.base_url = self.llm_config.base_url
        self.model = self.llm_config.model
    
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
                # Use Pydantic model for response validation
                ollama_response = OllamaGenerateResponse.model_validate(response.json())
                return ollama_response.response.strip()
            else:
                print(f"[WARNING] Ollama request failed: {response.status_code}")
                return ""
                
        except Exception as e:
            print(f"[WARNING] Ollama analysis failed: {e}")
            return ""
    
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
    
    def assess_relevance(self, paper_title: str, paper_abstract: str, topic: str) -> LLMRelevanceResult:
        """
        Assess if a paper is relevant to a topic using semantic understanding via LLM.
        
        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper
            topic: Research topic to assess relevance against
            
        Returns:
            Dict with relevance assessment results
        """
        try:
            prompt = f"""Analyze whether this research paper is semantically relevant to the research topic.

Research Topic: {topic}

Paper Title: {paper_title}

Paper Abstract: {paper_abstract}

Please evaluate:
1. Does this paper contribute knowledge to the research topic?
2. Are the methods, findings, or applications related to the topic?
3. Would this paper be valuable for someone researching this topic?

Consider semantic relationships, not just keyword matches. For example, a paper about "neural networks for image recognition" would be relevant to "computer vision" even without exact word matches.

Respond with:
RELEVANCE: [HIGHLY_RELEVANT/RELEVANT/SOMEWHAT_RELEVANT/NOT_RELEVANT]
CONFIDENCE: [HIGH/MEDIUM/LOW]
REASONING: [2-3 sentences explaining the semantic connection or lack thereof]"""

            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,  # Some creativity for nuanced evaluation
                        "num_predict": 250
                    }
                },
                timeout=45
            )
            
            if response.status_code == 200:
                result = response.json().get('response', '').strip()
                return self._parse_semantic_relevance(result)
            else:
                print(f"[WARNING] Semantic relevance assessment failed: {response.status_code}")
                return LLMRelevanceResult(
                    is_relevant=False,
                    relevance_level="UNKNOWN",
                    confidence=0.0,
                    reasoning=f"LLM request failed with status {response.status_code}",
                    semantic_score=0.0
                )
                
        except Exception as e:
            print(f"[WARNING] Semantic relevance assessment failed: {e}")
            return LLMRelevanceResult(
                is_relevant=False,
                relevance_level="UNKNOWN", 
                confidence=0.0,
                reasoning=f"Assessment failed due to error: {e}",
                semantic_score=0.0
            )
    
    def _parse_semantic_relevance(self, response: str) -> LLMRelevanceResult:
        """Parse LLM response for semantic relevance assessment."""
        try:
            lines = response.split('\n')
            relevance_level = "NOT_RELEVANT"
            confidence = "LOW"
            reasoning = "Unable to parse reasoning"
            
            for line in lines:
                if line.startswith("RELEVANCE:"):
                    relevance_level = line.split(":", 1)[1].strip()
                elif line.startswith("CONFIDENCE:"):
                    confidence = line.split(":", 1)[1].strip()
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
            
            # Convert to boolean and numeric score
            is_relevant = relevance_level in ["HIGHLY_RELEVANT", "RELEVANT", "SOMEWHAT_RELEVANT"]
            
            # Semantic score based on relevance level
            score_map = {
                "HIGHLY_RELEVANT": 0.9,
                "RELEVANT": 0.7,
                "SOMEWHAT_RELEVANT": 0.5,
                "NOT_RELEVANT": 0.1
            }
            semantic_score = score_map.get(relevance_level, 0.0)
            
            # Convert confidence to float
            confidence_value = 0.5  # Default
            if confidence.upper() in ["LOW", "MEDIUM", "HIGH"]:
                confidence_map = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.9}
                confidence_value = confidence_map[confidence.upper()]
            
            return LLMRelevanceResult(
                is_relevant=is_relevant,
                relevance_level=relevance_level,
                confidence=confidence_value,
                reasoning=reasoning,
                semantic_score=semantic_score
            )
            
        except Exception as e:
            return LLMRelevanceResult(
                is_relevant=False,
                relevance_level="NOT_RELEVANT",
                confidence=0.3, 
                reasoning=f"Failed to parse LLM response: {e}",
                semantic_score=0.0
            )
    
    def _simple_relevance_check(self, title: str, abstract: str, topic: str) -> Dict[str, Any]:
        """This method is deprecated - semantic evaluation should be used instead."""
        return {
            "is_relevant": False,
            "relevance_level": "NOT_RELEVANT",
            "confidence": "LOW",
            "reasoning": "Fallback method - semantic evaluation unavailable",
            "semantic_score": 0.0
        }
    
    def _fetch_full_text(self, paper: dict) -> str:
        """Fetch full text of paper if available."""
        # TODO: Implement paper fetching from various sources
        return ""