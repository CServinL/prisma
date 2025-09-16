"""
Source Quality Classification System

This module defines quality ratings for academic sources and validation criteria
for ensuring we only include legitimate academic content.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class SourceQuality(Enum):
    """Quality rating for academic sources (1-5 stars)"""
    FIVE_STAR = 5    # Premium APIs with curated academic content
    FOUR_STAR = 4    # Good APIs with structured data
    THREE_STAR = 3   # Basic APIs or reliable scraping targets
    TWO_STAR = 2     # HTML scraping with some structure
    ONE_STAR = 1     # Manual search forms, requires LLM extraction


class SourceMetadata(BaseModel):
    """Metadata about an academic source"""
    name: str = Field(..., description="Source name")
    quality: SourceQuality = Field(..., description="Quality rating")
    access_method: str = Field(..., description="Access method: api, rss, html_scraping, search_form")
    requires_llm: bool = Field(..., description="Whether LLM extraction is needed")
    rate_limits: Optional[str] = Field(None, description="Rate limit information")
    content_types: List[str] = Field(..., description="Content types: papers, books, theses, etc.")
    description: str = Field(..., description="Description of the source")
    strengths: List[str] = Field(..., description="Source strengths")
    limitations: List[str] = Field(..., description="Source limitations")


class AcademicValidationCriteria(BaseModel):
    """Criteria for validating academic content quality"""
    
    # Required fields
    require_authors: bool = True
    require_title: bool = True
    require_venue_or_publisher: bool = True
    
    # Minimum thresholds
    min_authors: int = 1
    min_title_length: int = 10
    min_abstract_length: int = 50
    
    # Content quality filters
    exclude_keywords: List[str] = [
        'blog post', 'social media', 'news article', 'advertisement',
        'spam', 'duplicate', 'test document', 'placeholder'
    ]
    
    # Academic indicators (bonus points)
    academic_venues: List[str] = [
        'journal', 'conference', 'symposium', 'workshop', 'proceedings',
        'review', 'transaction', 'letter', 'communication'
    ]
    
    # Publication requirements
    require_publication_date: bool = False
    min_publication_year: Optional[int] = 1990
    max_publication_year: Optional[int] = 2030


# Source Quality Database
SOURCE_REGISTRY: Dict[str, SourceMetadata] = {
    
    # ⭐⭐⭐⭐⭐ FIVE STAR SOURCES
    "semantic_scholar": SourceMetadata(
        name="Semantic Scholar",
        quality=SourceQuality.FIVE_STAR,
        access_method="api",
        requires_llm=False,
        rate_limits="1000 req/sec public, higher with API key",
        content_types=["papers", "citations", "authors"],
        description="AI-powered academic search with curated content and rich metadata",
        strengths=[
            "Excellent API with structured JSON responses",
            "Curated academic content with quality filtering",
            "Citation analysis and paper relationships",
            "Author disambiguation and profiles",
            "Abstracts and full metadata",
            "DOI and venue information"
        ],
        limitations=[
            "May not have all recent preprints",
            "Rate limits for heavy usage"
        ]
    ),
    
    "arxiv": SourceMetadata(
        name="arXiv",
        quality=SourceQuality.FIVE_STAR,
        access_method="api",
        requires_llm=False,
        rate_limits="Reasonable, no hard limits",
        content_types=["preprints", "papers"],
        description="High-quality preprint server with excellent API",
        strengths=[
            "Excellent XML API with full metadata",
            "High-quality academic preprints",
            "Direct PDF access",
            "Comprehensive subject classifications",
            "Author information and affiliations",
            "Real-time updates"
        ],
        limitations=[
            "Limited to STEM fields primarily",
            "Preprints may not be peer-reviewed"
        ]
    ),
    
    # ⭐⭐⭐⭐ FOUR STAR SOURCES
    "openlibrary": SourceMetadata(
        name="Open Library",
        quality=SourceQuality.FOUR_STAR,
        access_method="api",
        requires_llm=False,
        rate_limits="Reasonable API limits",
        content_types=["books", "academic_books"],
        description="Internet Archive's book database with good API",
        strengths=[
            "JSON API with structured data",
            "Millions of books including academic",
            "ISBN and publication metadata",
            "Subject classifications",
            "Free access to full texts"
        ],
        limitations=[
            "Mix of academic and non-academic content",
            "Variable metadata quality",
            "Some entries lack abstracts"
        ]
    ),
    
    "googlebooks": SourceMetadata(
        name="Google Books",
        quality=SourceQuality.FOUR_STAR,
        access_method="api",
        requires_llm=False,
        rate_limits="Daily quotas apply",
        content_types=["books", "academic_books"],
        description="Comprehensive book database with good API",
        strengths=[
            "JSON API with rich metadata",
            "Extensive book catalog",
            "Publisher information",
            "Preview links and covers",
            "Category classifications"
        ],
        limitations=[
            "Commercial focus, not purely academic",
            "API quotas and restrictions",
            "Limited full-text access"
        ]
    ),
    
    # ⭐⭐⭐ THREE STAR SOURCES
    "zotero": SourceMetadata(
        name="Zotero Local Database",
        quality=SourceQuality.THREE_STAR,
        access_method="api",
        requires_llm=False,
        rate_limits="No limits (local)",
        content_types=["papers", "books", "reports", "mixed"],
        description="User's personal research library with local API access",
        strengths=[
            "Local API with structured data",
            "User-curated content",
            "No rate limits",
            "Full metadata control",
            "Deduplication capabilities"
        ],
        limitations=[
            "Limited to user's existing collection",
            "Quality depends on user curation",
            "No new content discovery"
        ]
    ),
    
    # ⭐⭐ TWO STAR SOURCES  
    "academia_rss": SourceMetadata(
        name="Academia.edu RSS Feeds",
        quality=SourceQuality.TWO_STAR,
        access_method="rss",
        requires_llm=True,
        rate_limits="Respectful scraping needed",
        content_types=["papers", "theses", "presentations"],
        description="Individual researcher RSS feeds from Academia.edu",
        strengths=[
            "Real-time updates from researchers",
            "XML structure easier to parse",
            "Academic social network content"
        ],
        limitations=[
            "Requires knowing specific usernames",
            "Limited metadata in RSS",
            "Need LLM to extract details",
            "Individual feeds only"
        ]
    ),
    
    # ⭐ ONE STAR SOURCES
    "academia_search": SourceMetadata(
        name="Academia.edu Search",
        quality=SourceQuality.ONE_STAR,
        access_method="html_scraping",
        requires_llm=True,
        rate_limits="Very limited, anti-bot measures",
        content_types=["papers", "theses", "presentations"],
        description="Direct HTML scraping of Academia.edu search results",
        strengths=[
            "Large repository of academic content",
            "Theses and conference presentations",
            "International academic content"
        ],
        limitations=[
            "No API, only HTML scraping",
            "Anti-bot measures and CAPTCHAs",
            "Requires LLM for data extraction",
            "Rate limiting and blocking risks",
            "HTML structure changes frequently"
        ]
    ),
    
    "researchgate": SourceMetadata(
        name="ResearchGate",
        quality=SourceQuality.ONE_STAR,
        access_method="html_scraping",
        requires_llm=True,
        rate_limits="Aggressive anti-scraping",
        content_types=["papers", "preprints", "datasets"],
        description="Academic social network requiring HTML scraping",
        strengths=[
            "Large academic community",
            "Pre-publication papers",
            "Researcher networking data",
            "Research datasets"
        ],
        limitations=[
            "No public API",
            "Strong anti-scraping measures",
            "Requires authentication",
            "Legal and ToS concerns",
            "Complex HTML structure"
        ]
    )
}


def get_source_quality(source_name: str) -> SourceQuality:
    """Get quality rating for a source"""
    source_info = SOURCE_REGISTRY.get(source_name.lower())
    return source_info.quality if source_info else SourceQuality.ONE_STAR


def requires_llm_extraction(source_name: str) -> bool:
    """Check if source requires LLM for content extraction"""
    source_info = SOURCE_REGISTRY.get(source_name.lower())
    return source_info.requires_llm if source_info else True


def get_high_quality_sources() -> List[str]:
    """Get list of 4-5 star sources"""
    return [
        name for name, info in SOURCE_REGISTRY.items()
        if info.quality.value >= 4
    ]


def get_api_sources() -> List[str]:
    """Get list of sources with proper APIs"""
    return [
        name for name, info in SOURCE_REGISTRY.items()
        if info.access_method == "api"
    ]


def validate_academic_content(
    title: str,
    authors: List[str],
    abstract: str = "",
    venue: str = "",
    publisher: str = "",
    publication_year: Optional[int] = None,
    criteria: Optional[AcademicValidationCriteria] = None
) -> tuple[bool, List[str]]:
    """
    Validate if content meets academic standards
    
    Returns:
        (is_valid, reasons_for_rejection)
    """
    if criteria is None:
        criteria = AcademicValidationCriteria()
    
    reasons = []
    
    # Required field validation
    if criteria.require_title and (not title or len(title.strip()) < criteria.min_title_length):
        reasons.append(f"Title too short (min {criteria.min_title_length} chars)")
    
    if criteria.require_authors and (not authors or len(authors) < criteria.min_authors):
        reasons.append(f"Insufficient authors (min {criteria.min_authors})")
    
    if criteria.require_venue_or_publisher and not (venue or publisher):
        reasons.append("Missing venue/journal/publisher information")
    
    # Abstract validation
    if criteria.min_abstract_length > 0 and len(abstract.strip()) < criteria.min_abstract_length:
        reasons.append(f"Abstract too short (min {criteria.min_abstract_length} chars)")
    
    # Publication date validation
    if criteria.require_publication_date and not publication_year:
        reasons.append("Missing publication date")
    
    if publication_year:
        if criteria.min_publication_year and publication_year < criteria.min_publication_year:
            reasons.append(f"Publication year too old (min {criteria.min_publication_year})")
        if criteria.max_publication_year and publication_year > criteria.max_publication_year:
            reasons.append(f"Publication year too recent (max {criteria.max_publication_year})")
    
    # Content quality checks
    content_text = f"{title} {abstract} {venue} {publisher}".lower()
    
    for keyword in criteria.exclude_keywords:
        if keyword.lower() in content_text:
            reasons.append(f"Contains non-academic keyword: {keyword}")
    
    is_valid = len(reasons) == 0
    return is_valid, reasons


def get_academic_confidence_score(
    title: str,
    authors: List[str],
    abstract: str = "",
    venue: str = "",
    publisher: str = "",
    source_quality: SourceQuality = SourceQuality.THREE_STAR,
    criteria: Optional[AcademicValidationCriteria] = None
) -> float:
    """
    Calculate confidence score (0.0-1.0) for academic content
    
    Higher scores indicate more confidence that this is legitimate academic content
    """
    if criteria is None:
        criteria = AcademicValidationCriteria()
    
    score = 0.0
    max_score = 0.0
    
    # Source quality baseline (30% of score)
    score += source_quality.value * 0.06  # 0.06-0.30
    max_score += 0.30
    
    # Required fields (40% of score)
    if title and len(title.strip()) >= criteria.min_title_length:
        score += 0.15
    max_score += 0.15
    
    if authors and len(authors) >= criteria.min_authors:
        score += 0.15
    max_score += 0.15
    
    if venue or publisher:
        score += 0.10
    max_score += 0.10
    
    # Content indicators (30% of score)
    content_text = f"{venue} {publisher}".lower()
    academic_indicators = sum(1 for keyword in criteria.academic_venues if keyword in content_text)
    if academic_indicators > 0:
        score += min(0.20, academic_indicators * 0.05)
    max_score += 0.20
    
    if abstract and len(abstract.strip()) >= criteria.min_abstract_length:
        score += 0.10
    max_score += 0.10
    
    return score / max_score if max_score > 0 else 0.0