"""
External API Response Models

This module defines Pydantic models for standardizing external API responses
from services like OpenLibrary, Semantic Scholar, Google Books, etc.
These models ensure type safety and validation for external data sources.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class OpenLibraryAuthor(BaseModel):
    """OpenLibrary author response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    name: str = Field(..., description="Author name")
    key: Optional[str] = Field(None, description="OpenLibrary author key")


class OpenLibraryDocument(BaseModel):
    """OpenLibrary document response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., description="Book title")
    author_name: List[str] = Field(default_factory=list, description="List of author names")
    first_publish_year: Optional[int] = Field(None, description="First publication year")
    isbn: List[str] = Field(default_factory=list, description="ISBN numbers")
    key: str = Field(..., description="OpenLibrary key")
    publisher: List[str] = Field(default_factory=list, description="Publishers")
    language: List[str] = Field(default_factory=list, description="Languages")
    subject: List[str] = Field(default_factory=list, description="Subjects")
    edition_count: Optional[int] = Field(None, description="Number of editions")
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        """Clean and validate title"""
        return v.strip() if v else ""


class OpenLibraryResponse(BaseModel):
    """OpenLibrary search response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    start: int = Field(0, description="Start index")
    num_found: int = Field(0, description="Total number found")
    docs: List[OpenLibraryDocument] = Field(default_factory=list, description="Documents")


class SemanticScholarAuthor(BaseModel):
    """Semantic Scholar author model"""
    model_config = ConfigDict(populate_by_name=True)
    
    authorId: Optional[str] = Field(None, description="Author ID")
    name: str = Field(..., description="Author name")


class SemanticScholarPaper(BaseModel):
    """Semantic Scholar paper response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    paperId: str = Field(..., description="Paper ID")
    title: str = Field(..., description="Paper title")
    abstract: Optional[str] = Field(None, description="Paper abstract")
    authors: List[SemanticScholarAuthor] = Field(default_factory=list, description="Authors")
    year: Optional[int] = Field(None, description="Publication year")
    venue: Optional[str] = Field(None, description="Publication venue")
    url: Optional[str] = Field(None, description="Paper URL")
    citationCount: Optional[int] = Field(None, description="Citation count")
    influentialCitationCount: Optional[int] = Field(None, description="Influential citation count")
    isOpenAccess: Optional[bool] = Field(None, description="Open access status")
    openAccessPdf: Optional[Dict[str, str]] = Field(None, description="Open access PDF info")
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        """Clean and validate title"""
        return v.strip().replace('\n', ' ') if v else ""


class SemanticScholarResponse(BaseModel):
    """Semantic Scholar search response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    total: int = Field(0, description="Total results")
    offset: int = Field(0, description="Offset")
    next: Optional[int] = Field(None, description="Next page offset")
    data: List[SemanticScholarPaper] = Field(default_factory=list, description="Papers")


class GoogleBooksVolumeInfo(BaseModel):
    """Google Books volume info model"""
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., description="Book title")
    authors: List[str] = Field(default_factory=list, description="Authors")
    publisher: Optional[str] = Field(None, description="Publisher")
    publishedDate: Optional[str] = Field(None, description="Publication date")
    description: Optional[str] = Field(None, description="Description")
    industryIdentifiers: List[Dict[str, str]] = Field(default_factory=list, description="Identifiers (ISBN, etc.)")
    pageCount: Optional[int] = Field(None, description="Page count")
    categories: List[str] = Field(default_factory=list, description="Categories")
    language: Optional[str] = Field(None, description="Language")
    previewLink: Optional[str] = Field(None, description="Preview link")
    infoLink: Optional[str] = Field(None, description="Info link")


class GoogleBooksItem(BaseModel):
    """Google Books item model"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="Book ID")
    volumeInfo: GoogleBooksVolumeInfo = Field(..., description="Volume information")
    accessInfo: Optional[Dict[str, Any]] = Field(None, description="Access information")


class GoogleBooksResponse(BaseModel):
    """Google Books search response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    kind: str = Field("books#volumes", description="Response kind")
    totalItems: int = Field(0, description="Total items")
    items: List[GoogleBooksItem] = Field(default_factory=list, description="Book items")


class ArXivAuthor(BaseModel):
    """ArXiv author model"""
    model_config = ConfigDict(populate_by_name=True)
    
    name: str = Field(..., description="Author name")


class ArXivEntry(BaseModel):
    """ArXiv entry model"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="ArXiv ID")
    title: str = Field(..., description="Paper title")
    summary: str = Field(..., description="Abstract/summary")
    authors: List[ArXivAuthor] = Field(default_factory=list, description="Authors")
    published: str = Field(..., description="Publication date")
    updated: Optional[str] = Field(None, description="Update date")
    categories: List[str] = Field(default_factory=list, description="Categories")
    pdf_url: Optional[str] = Field(None, description="PDF URL")
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        """Clean and validate title"""
        return v.strip().replace('\n', ' ') if v else ""
    
    @field_validator('summary')
    @classmethod
    def validate_summary(cls, v):
        """Clean and validate summary"""
        return v.strip().replace('\n', ' ') if v else ""


class LLMRelevanceResult(BaseModel):
    """LLM relevance analysis result model"""
    model_config = ConfigDict(populate_by_name=True)
    
    is_relevant: bool = Field(..., description="Whether the content is relevant")
    relevance_level: str = Field("NOT_RELEVANT", description="Relevance level")
    semantic_score: float = Field(0.0, ge=0.0, le=1.0, description="Semantic relevance score")
    reasoning: str = Field("", description="Reasoning for the relevance decision")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in the assessment")
    
    @field_validator('relevance_level')
    @classmethod
    def validate_relevance_level(cls, v):
        """Validate relevance level"""
        valid_levels = ['NOT_RELEVANT', 'LOW_RELEVANCE', 'RELEVANT', 'HIGHLY_RELEVANT']
        if v not in valid_levels:
            raise ValueError(f'relevance_level must be one of {valid_levels}')
        return v


class OllamaGenerateResponse(BaseModel):
    """Ollama generate API response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    model: str = Field(..., description="Model name used")
    created_at: str = Field(..., description="Creation timestamp")
    response: str = Field(..., description="Generated response text")
    done: bool = Field(..., description="Whether generation is complete")
    context: Optional[List[int]] = Field(None, description="Context tokens")
    total_duration: Optional[int] = Field(None, description="Total duration in nanoseconds")
    load_duration: Optional[int] = Field(None, description="Load duration in nanoseconds")
    prompt_eval_count: Optional[int] = Field(None, description="Prompt evaluation token count")
    prompt_eval_duration: Optional[int] = Field(None, description="Prompt evaluation duration")
    eval_count: Optional[int] = Field(None, description="Evaluation token count")
    eval_duration: Optional[int] = Field(None, description="Evaluation duration")


class ZoteroItemCreationData(BaseModel):
    """Pydantic model for creating Zotero items"""
    model_config = ConfigDict(populate_by_name=True)
    
    itemType: str = Field(..., description="Zotero item type")
    title: str = Field(..., description="Item title")
    creators: List[Dict[str, str]] = Field(default_factory=list, description="Item creators")
    abstractNote: Optional[str] = Field(None, description="Abstract or note")
    url: Optional[str] = Field(None, description="URL")
    DOI: Optional[str] = Field(None, description="DOI")
    date: Optional[str] = Field(None, description="Publication date")
    publicationTitle: Optional[str] = Field(None, description="Publication title")
    volume: Optional[str] = Field(None, description="Volume")
    issue: Optional[str] = Field(None, description="Issue")
    pages: Optional[str] = Field(None, description="Pages")
    ISSN: Optional[str] = Field(None, description="ISSN")
    ISBN: Optional[str] = Field(None, description="ISBN")
    language: Optional[str] = Field(None, description="Language")
    tags: List[Dict[str, Any]] = Field(default_factory=list, description="Tags")
    collections: List[str] = Field(default_factory=list, description="Collection keys")
    
    @field_validator('itemType')
    @classmethod
    def validate_item_type(cls, v):
        """Validate Zotero item type"""
        valid_types = [
            'journalArticle', 'book', 'bookSection', 'conferencePaper',
            'thesis', 'report', 'webpage', 'preprint', 'manuscript',
            'presentation', 'other'
        ]
        if v not in valid_types:
            raise ValueError(f'itemType must be one of {valid_types}')
        return v
    
    @classmethod
    def from_paper_metadata(cls, paper, collection_key: Optional[str] = None) -> "ZoteroItemCreationData":
        """Create ZoteroItemCreationData from PaperMetadata"""
        creators = []
        if hasattr(paper, 'authors') and paper.authors:
            for author in paper.authors:
                if isinstance(author, str):
                    creators.append({
                        "creatorType": "author",
                        "name": author
                    })
                elif hasattr(author, 'name'):
                    creators.append({
                        "creatorType": "author", 
                        "name": author.name
                    })
        
        # Determine item type based on source
        item_type = "journalArticle"
        if hasattr(paper, 'source'):
            if paper.source == "arxiv":
                item_type = "preprint"
            elif paper.source in ["openlibrary", "googlebooks"]:
                item_type = "book"
        
        collections = [collection_key] if collection_key else []
        
        return cls(
            itemType=item_type,
            title=paper.title,
            creators=creators,
            abstractNote=getattr(paper, 'abstract', None),
            url=getattr(paper, 'url', None),
            DOI=getattr(paper, 'doi', None),
            date=getattr(paper, 'published_date', None),
            publicationTitle=getattr(paper, 'journal', None),
            volume=getattr(paper, 'volume', None),
            issue=getattr(paper, 'issue', None),
            pages=getattr(paper, 'pages', None),
            ISSN=None,
            ISBN=None,
            language=None,
            collections=collections
        )