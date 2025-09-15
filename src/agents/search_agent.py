"""
Search Agent - Fast MVP implementation with arXiv API
"""

import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Any
from urllib.parse import quote
from datetime import datetime

from storage.models.agent_models import SearchResult, PaperMetadata


class SearchAgent:
    """Search for academic papers - MVP with arXiv only."""
    
    def __init__(self):
        self.arxiv_base_url = "http://export.arxiv.org/api/query"
        
    def search(self, query: str, sources: List[str], limit: int = 10) -> SearchResult:
        """
        Search for papers across specified sources.
        
        Args:
            query: Search query string
            sources: List of sources to search (currently only 'arxiv')
            limit: Maximum number of papers to return
            
        Returns:
            SearchResult with papers list and metadata
        """
        all_papers = []
        
        for source in sources:
            if source.lower() == 'arxiv':
                papers = self._search_arxiv(query, limit)
                all_papers.extend(papers)
            else:
                print(f"[WARNING] Source '{source}' not yet implemented")
        
        # Remove duplicates and limit results
        unique_papers = self._deduplicate_papers(all_papers)
        limited_papers = unique_papers[:limit]
        
        return SearchResult(
            papers=limited_papers,
            total_found=len(unique_papers),
            sources_searched=sources,
            query=query,
            timestamp=datetime.now()
        )
    
    def _search_arxiv(self, query: str, limit: int) -> List[PaperMetadata]:
        """Search arXiv API for papers."""
        try:
            # Format query for arXiv API
            search_query = f"all:{quote(query)}"
            
            # Build request URL
            url = f"{self.arxiv_base_url}?search_query={search_query}&start=0&max_results={limit}"
            
            # Make request
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse XML response
            root = ET.fromstring(response.content)
            
            papers = []
            entries = root.findall('{http://www.w3.org/2005/Atom}entry')
            
            for entry in entries:
                paper = self._parse_arxiv_entry(entry)
                if paper:
                    papers.append(paper)
            
            return papers
            
        except Exception as e:
            print(f"[ERROR] ArXiv search failed: {e}")
            return []
    
    def _parse_arxiv_entry(self, entry) -> PaperMetadata:
        """Parse a single arXiv entry into paper metadata."""
        try:
            # Namespaces
            atom_ns = '{http://www.w3.org/2005/Atom}'
            arxiv_ns = '{http://arxiv.org/schemas/atom}'
            
            # Extract basic fields
            title = entry.find(f'{atom_ns}title').text.strip().replace('\n', ' ')
            summary = entry.find(f'{atom_ns}summary').text.strip().replace('\n', ' ')
            
            # Get arXiv ID from the ID field
            arxiv_id = entry.find(f'{atom_ns}id').text.split('/')[-1]
            
            # Extract authors
            authors = []
            for author in entry.findall(f'{atom_ns}author'):
                name = author.find(f'{atom_ns}name').text
                authors.append(name)
            
            # Extract publication date
            published = entry.find(f'{atom_ns}published').text[:10]  # YYYY-MM-DD
            
            # Build paper metadata using Pydantic model
            paper = PaperMetadata(
                title=title,
                authors=authors,
                abstract=summary,
                source='arxiv',
                arxiv_id=arxiv_id,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                published_date=published,
                connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(title)}"
            )
            
            return paper
            
        except Exception as e:
            print(f"[ERROR] Failed to parse arXiv entry: {e}")
            return None
    
    def _deduplicate_papers(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """Remove duplicate papers based on title similarity."""
        if not papers:
            return []
        
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title_key = paper.title.lower().strip()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_papers.append(paper)
        
        return unique_papers