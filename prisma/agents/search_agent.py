"""
Search Agent - Academic papers and books search with quality-based source management
"""

import requests
import xml.etree.ElementTree as ET
import json
import time
import logging
from typing import Dict, List, Any
from urllib.parse import quote, urljoin
from datetime import datetime

from ..storage.models.agent_models import SearchResult, PaperMetadata, BookMetadata
from ..storage.models.source_quality import (
    SourceQuality, get_source_quality, requires_llm_extraction,
    validate_academic_content, get_academic_confidence_score,
    AcademicValidationCriteria, SOURCE_REGISTRY
)

logger = logging.getLogger(__name__)


class SearchAgent:
    """Search for academic papers and books across multiple quality-rated sources."""
    
    def __init__(self):
        self.arxiv_base_url = "http://export.arxiv.org/api/query"
        self.openlibrary_base_url = "https://openlibrary.org"
        self.googlebooks_base_url = "https://www.googleapis.com/books/v1/volumes"
        self.academia_base_url = "https://www.academia.edu"
        self.semantic_scholar_base_url = "https://api.semanticscholar.org/graph/v1"
        
        # Initialize academic validation criteria
        self.validation_criteria = AcademicValidationCriteria()
        
        # Quality thresholds
        self.min_confidence_score = 0.3  # Minimum confidence for including results
        self.prefer_high_quality = True  # Prioritize 4-5 star sources
        
    def search(self, query: str, sources: List[str], limit: int = 10) -> SearchResult:
        """
        Search for papers and books across specified sources with quality prioritization.
        
        Args:
            query: Search query string
            sources: List of sources to search ('arxiv', 'semanticscholar', etc.)
            limit: Maximum number of items to return per source
            
        Returns:
            SearchResult with papers and books lists and metadata
        """
        # Sort sources by quality (highest first) if prefer_high_quality is enabled
        if self.prefer_high_quality:
            sources = sorted(sources, key=lambda s: get_source_quality(s).value, reverse=True)
            print(f"[INFO] Searching sources by quality: {sources}")
        
        all_papers = []
        all_books = []
        source_stats = {}
        
        for source in sources:
            source_quality = get_source_quality(source)
            print(f"[INFO] Searching {source} (Quality: {source_quality.value}⭐)")
            
            source_stats[source] = {
                'quality': source_quality.value,
                'papers_found': 0,
                'books_found': 0,
                'rejected': 0
            }
            
            papers_before = len(all_papers)
            books_before = len(all_books)
            
            if source.lower() == 'arxiv':
                papers = self._search_arxiv(query, limit)
                all_papers.extend(papers)
            elif source.lower() == 'openlibrary':
                books = self._search_openlibrary(query, limit)
                all_books.extend(books)
            elif source.lower() == 'googlebooks':
                books = self._search_googlebooks(query, limit)
                all_books.extend(books)
            elif source.lower() == 'academia':
                papers = self._search_academia(query, limit)
                all_papers.extend(papers)
            elif source.lower() == 'semanticscholar':
                papers = self._search_semantic_scholar(query, limit)
                all_papers.extend(papers)
            elif source.lower() == 'zotero':
                print(f"[INFO] Zotero local search - used for caching/deduplication")
                # Note: Zotero search handled separately in research streams
            else:
                print(f"[WARNING] Source '{source}' not yet implemented")
            
            # Update statistics
            source_stats[source]['papers_found'] = len(all_papers) - papers_before
            source_stats[source]['books_found'] = len(all_books) - books_before
        
        # Remove duplicates and limit results
        unique_papers = self._deduplicate_papers(all_papers)
        unique_books = self._deduplicate_books(all_books)
        limited_papers = unique_papers[:limit]
        limited_books = unique_books[:limit]
        
        # Print quality summary
        self._print_quality_summary(source_stats, len(limited_papers), len(limited_books))
        
        return SearchResult(
            papers=limited_papers,
            books=limited_books,
            total_found=len(unique_papers) + len(unique_books),
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
    
    def _parse_arxiv_entry(self, entry) -> PaperMetadata | None:
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
                connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(title)}",
                doi=None,
                journal=None,
                volume=None,
                issue=None,
                pages=None
            )
            
            # Validate academic quality
            is_valid, reasons = validate_academic_content(
                title=title,
                authors=authors,
                abstract=summary,
                venue="arXiv",  # arXiv is a recognized academic venue
                criteria=self.validation_criteria
            )
            
            if not is_valid:
                logger.debug(f"arXiv paper rejected: {'; '.join(reasons)}")
                return None
            
            # Calculate confidence score
            confidence = get_academic_confidence_score(
                title=title,
                authors=authors,
                abstract=summary,
                venue="arXiv",
                source_quality=SourceQuality.FIVE_STAR
            )
            
            if confidence < self.min_confidence_score:
                logger.debug(f"arXiv paper low confidence: {confidence:.2f}")
                return None
            
            logger.debug(f"arXiv paper accepted with confidence: {confidence:.2f}")
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
    
    def _deduplicate_books(self, books: List[BookMetadata]) -> List[BookMetadata]:
        """Remove duplicate books based on title and ISBN similarity."""
        if not books:
            return []
        
        unique_books = []
        seen_books = set()
        
        for book in books:
            # Create a unique key from title and ISBN (if available)
            title_key = book.title.lower().strip()
            isbn_key = book.isbn_13 or book.isbn_10 or ""
            book_key = f"{title_key}|{isbn_key}"
            
            if book_key not in seen_books:
                seen_books.add(book_key)
                unique_books.append(book)
        
        return unique_books
    
    def _search_openlibrary(self, query: str, limit: int) -> List[BookMetadata]:
        """Search Open Library API for books."""
        try:
            # Format query for Open Library search
            search_query = quote(query)
            
            # Build request URL - using the subjects endpoint for better results
            url = f"{self.openlibrary_base_url}/search.json?q={search_query}&limit={limit}"
            
            # Make request
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            books = []
            docs = data.get('docs', [])
            
            for doc in docs:
                book = self._parse_openlibrary_doc(doc)
                if book:
                    books.append(book)
            
            return books
            
        except Exception as e:
            print(f"[ERROR] Open Library search failed: {e}")
            return []
    
    def _parse_openlibrary_doc(self, doc: Dict) -> BookMetadata | None:
        """Parse a single Open Library document into book metadata."""
        try:
            # Extract basic fields
            title = doc.get('title', '').strip()
            if not title:
                return None
            
            # Extract authors
            authors = []
            author_names = doc.get('author_name', [])
            if isinstance(author_names, list):
                authors = [name.strip() for name in author_names if name.strip()]
            elif isinstance(author_names, str):
                authors = [author_names.strip()]
            
            # Extract description/summary
            description = ""
            if 'first_sentence' in doc and doc['first_sentence']:
                description = doc['first_sentence'][0] if isinstance(doc['first_sentence'], list) else str(doc['first_sentence'])
            
            # Extract ISBNs
            isbn_10 = None
            isbn_13 = None
            if 'isbn' in doc:
                isbns = doc['isbn'] if isinstance(doc['isbn'], list) else [doc['isbn']]
                for isbn in isbns:
                    isbn_clean = isbn.replace('-', '').replace(' ', '')
                    if len(isbn_clean) == 10:
                        isbn_10 = isbn_clean
                    elif len(isbn_clean) == 13:
                        isbn_13 = isbn_clean
            
            # Extract publication info
            publisher = doc.get('publisher', [])
            if isinstance(publisher, list) and publisher:
                publisher = publisher[0]
            elif not isinstance(publisher, str):
                publisher = None
            
            published_date = None
            if 'first_publish_year' in doc:
                published_date = str(doc['first_publish_year'])
            
            # Extract subjects and classification
            subjects = []
            if 'subject' in doc:
                subj_list = doc['subject'] if isinstance(doc['subject'], list) else [doc['subject']]
                subjects = [s.strip() for s in subj_list if s.strip()][:10]  # Limit to 10 subjects
            
            # Build Open Library URL
            key = doc.get('key', '')
            ol_url = f"https://openlibrary.org{key}" if key else f"https://openlibrary.org/search?q={quote(title)}"
            
            # Build book metadata using Pydantic model
            book = BookMetadata(
                title=title,
                authors=authors,
                description=description,
                source='openlibrary',
                url=ol_url,
                isbn_10=isbn_10,
                isbn_13=isbn_13,
                publisher=publisher,
                published_date=published_date,
                subjects=subjects,
                page_count=doc.get('number_of_pages_median'),
                language=doc.get('language', [None])[0] if doc.get('language') else None,
                oclc=None,
                lccn=None,
                edition=None,
                preview_url=None,
                cover_url=None
            )
            
            return book
            
        except Exception as e:
            print(f"[ERROR] Failed to parse Open Library entry: {e}")
            return None
    
    def _search_googlebooks(self, query: str, limit: int) -> List[BookMetadata]:
        """Search Google Books API for books."""
        try:
            # Format query for Google Books API
            search_query = quote(query)
            
            # Build request URL
            url = f"{self.googlebooks_base_url}?q={search_query}&maxResults={min(limit, 40)}"
            
            # Make request
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            books = []
            items = data.get('items', [])
            
            for item in items:
                book = self._parse_googlebooks_item(item)
                if book:
                    books.append(book)
            
            return books
            
        except Exception as e:
            print(f"[ERROR] Google Books search failed: {e}")
            return []
    
    def _parse_googlebooks_item(self, item: Dict) -> BookMetadata | None:
        """Parse a single Google Books item into book metadata."""
        try:
            volume_info = item.get('volumeInfo', {})
            
            # Extract basic fields
            title = volume_info.get('title', '').strip()
            if not title:
                return None
            
            # Extract authors
            authors = volume_info.get('authors', [])
            if not isinstance(authors, list):
                authors = []
            
            # Extract description
            description = volume_info.get('description', '')
            
            # Extract ISBNs
            isbn_10 = None
            isbn_13 = None
            industry_identifiers = volume_info.get('industryIdentifiers', [])
            for identifier in industry_identifiers:
                if identifier.get('type') == 'ISBN_10':
                    isbn_10 = identifier.get('identifier')
                elif identifier.get('type') == 'ISBN_13':
                    isbn_13 = identifier.get('identifier')
            
            # Extract publication info
            publisher = volume_info.get('publisher')
            published_date = volume_info.get('publishedDate')
            
            # Extract categories (subjects)
            categories = volume_info.get('categories', [])
            if not isinstance(categories, list):
                categories = []
            
            # Extract page count
            page_count = volume_info.get('pageCount')
            
            # Extract language
            language = volume_info.get('language')
            
            # Build Google Books URL
            google_url = volume_info.get('infoLink', f"https://books.google.com/books?q={quote(title)}")
            
            # Extract preview URL
            preview_url = volume_info.get('previewLink')
            
            # Extract cover URL
            cover_url = None
            image_links = volume_info.get('imageLinks', {})
            if image_links:
                cover_url = image_links.get('thumbnail') or image_links.get('smallThumbnail')
            
            # Build book metadata using Pydantic model
            book = BookMetadata(
                title=title,
                authors=authors,
                description=description,
                source='googlebooks',
                url=google_url,
                isbn_10=isbn_10,
                isbn_13=isbn_13,
                publisher=publisher,
                published_date=published_date,
                page_count=page_count,
                categories=categories,
                language=language,
                preview_url=preview_url,
                cover_url=cover_url,
                oclc=None,
                lccn=None,
                edition=None
            )
            
            return book
            
        except Exception as e:
            print(f"[ERROR] Failed to parse Google Books entry: {e}")
            return None
    
    def _search_academia(self, query: str, limit: int) -> List[PaperMetadata]:
        """Search Academia.edu for academic papers (web scraping approach)."""
        try:
            # Format query for Academia.edu search
            search_query = quote(query)
            
            # Build search URL
            url = f"{self.academia_base_url}/search?q={search_query}"
            
            # Headers to mimic a real browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # Make request with rate limiting
            time.sleep(1)  # Respectful rate limiting
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            papers = []
            
            # For now, return a simulated result to avoid complex HTML parsing
            # In a production implementation, you would parse the HTML response
            # This is a placeholder that demonstrates the structure
            
            # Note: Academia.edu search results would require HTML parsing with BeautifulSoup
            # which would need to be added as a dependency. For now, we'll return empty
            # but show the framework is in place.
            
            print(f"[INFO] Academia.edu search initiated for '{query}' - HTML parsing not implemented")
            return papers
            
        except Exception as e:
            print(f"[ERROR] Academia.edu search failed: {e}")
            return []
    
    def _parse_academia_paper(self, paper_element) -> PaperMetadata | None:
        """Parse Academia.edu paper element into paper metadata."""
        # This would be implemented with BeautifulSoup HTML parsing
        # Placeholder for the structure
        try:
            # Extract from HTML elements:
            # - Title from .work-title or similar
            # - Authors from .author-name or similar  
            # - Abstract from .abstract or similar
            # - URL from href attributes
            # - Publication info from metadata
            
            return None  # Placeholder
            
        except Exception as e:
            print(f"[ERROR] Failed to parse Academia.edu entry: {e}")
            return None

    def _search_semantic_scholar(self, query: str, limit: int) -> List[PaperMetadata]:
        """Search Semantic Scholar API for academic papers."""
        try:
            # Build request URL - using paper search endpoint
            url = f"{self.semantic_scholar_base_url}/paper/search"
            params = {
                'query': query,
                'limit': min(limit, 100),  # Max 100 per request
                'fields': 'paperId,title,abstract,authors,venue,year,doi,url'
            }
            
            # Make request with rate limiting
            time.sleep(0.1)  # Respectful rate limiting for API
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            papers = []
            paper_data = data.get('data', [])
            
            for paper_item in paper_data:
                paper = self._parse_semantic_scholar_paper(paper_item)
                if paper:
                    papers.append(paper)
            
            return papers
            
        except Exception as e:
            print(f"[ERROR] Semantic Scholar search failed: {e}")
            return []

    def _parse_semantic_scholar_paper(self, paper_data: Dict) -> PaperMetadata | None:
        """Parse a single Semantic Scholar paper into paper metadata."""
        try:
            # Extract basic fields
            title = paper_data.get('title', '').strip()
            if not title:
                return None
                
            abstract = paper_data.get('abstract', '') or ''
            
            # Extract authors
            authors = []
            author_list = paper_data.get('authors', [])
            for author in author_list:
                if isinstance(author, dict) and 'name' in author:
                    authors.append(author['name'])
                elif isinstance(author, str):
                    authors.append(author)
            
            # Extract publication info
            venue = paper_data.get('venue') or ''
            year = paper_data.get('year')
            doi = paper_data.get('doi')
            paper_id = paper_data.get('paperId', '')
            
            # Build URLs
            paper_url = paper_data.get('url') or f"https://www.semanticscholar.org/paper/{paper_id}"
            
            # Format publication date
            published_date = None
            if year:
                published_date = f"{year}-01-01"
            
            # Build paper metadata using Pydantic model
            paper = PaperMetadata(
                title=title,
                authors=authors,
                abstract=abstract,
                source='semanticscholar',
                url=paper_url,
                pdf_url=None,  # Semantic Scholar doesn't provide direct PDF URLs
                published_date=published_date,
                doi=doi,
                journal=venue,
                volume=None,
                issue=None,
                pages=None,
                arxiv_id=None,
                connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(title)}"
            )
            
            # Validate academic quality
            is_valid, reasons = validate_academic_content(
                title=title,
                authors=authors,
                abstract=abstract,
                venue=venue,
                criteria=self.validation_criteria
            )
            
            if not is_valid:
                logger.debug(f"Semantic Scholar paper rejected: {'; '.join(reasons)}")
                return None
            
            # Calculate confidence score
            confidence = get_academic_confidence_score(
                title=title,
                authors=authors,
                abstract=abstract,
                venue=venue,
                source_quality=SourceQuality.FIVE_STAR
            )
            
            if confidence < self.min_confidence_score:
                logger.debug(f"Semantic Scholar paper low confidence: {confidence:.2f}")
                return None
            
            logger.debug(f"Semantic Scholar paper accepted with confidence: {confidence:.2f}")
            return paper
            
        except Exception as e:
            logger.error(f"Failed to parse Semantic Scholar entry: {e}")
            return None

    def _print_quality_summary(self, source_stats: Dict, total_papers: int, total_books: int):
        """Print summary of search results by source quality"""
        print(f"\n📊 Search Quality Summary:")
        print(f"   Total Results: {total_papers} papers, {total_books} books")
        print(f"   Sources Used:")
        
        for source, stats in source_stats.items():
            if stats['papers_found'] + stats['books_found'] > 0:
                quality_stars = "⭐" * stats['quality']
                print(f"   • {source}: {quality_stars} - {stats['papers_found']}P + {stats['books_found']}B")
        print()