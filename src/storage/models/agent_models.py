"""
Agent Response Models

This module defines Pydantic models for standardizing agent responses
throughout the Prisma literature review pipeline. These models ensure
type safety, validation, and consistent data structures between agents.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class PaperMetadata(BaseModel):
    """Standardized paper metadata structure for search results"""
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., description="Paper title")
    authors: List[str] = Field(default_factory=list, description="List of author names")
    abstract: str = Field(..., description="Paper abstract or summary")
    source: str = Field(..., description="Source database (arxiv, pubmed, etc.)")
    url: str = Field(..., description="Primary URL to paper")
    pdf_url: Optional[str] = Field(None, description="Direct PDF download URL")
    published_date: Optional[str] = Field(None, description="Publication date (YYYY-MM-DD)")
    arxiv_id: Optional[str] = Field(None, description="ArXiv identifier")
    doi: Optional[str] = Field(None, description="Digital Object Identifier")
    connected_papers_url: Optional[str] = Field(None, description="Connected Papers URL for exploration")
    
    # Additional metadata
    journal: Optional[str] = Field(None, description="Journal or venue name")
    volume: Optional[str] = Field(None, description="Volume number")
    issue: Optional[str] = Field(None, description="Issue number")
    pages: Optional[str] = Field(None, description="Page range")
    
    @field_validator('authors')
    @classmethod
    def validate_authors(cls, v):
        """Ensure authors list contains only non-empty strings"""
        return [author.strip() for author in v if author and author.strip()]
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        """Clean and validate title"""
        return v.strip().replace('\n', ' ') if v else ""


class SearchResult(BaseModel):
    """Search agent response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    papers: List[PaperMetadata] = Field(default_factory=list, description="List of found papers")
    total_found: int = Field(..., ge=0, description="Total number of papers found")
    sources_searched: List[str] = Field(default_factory=list, description="Sources that were searched")
    query: str = Field(..., description="Original search query")
    timestamp: datetime = Field(default_factory=datetime.now, description="Search timestamp")
    
    @field_validator('total_found')
    @classmethod
    def validate_total(cls, v, info):
        """Ensure total_found is consistent with papers list"""
        return max(v, 0)  # Ensure non-negative


class PaperSummary(BaseModel):
    """Individual paper analysis summary"""
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., description="Paper title")
    authors: List[str] = Field(default_factory=list, description="Author names")
    abstract: str = Field(..., description="Original abstract")
    summary: str = Field(..., description="AI-generated summary")
    key_findings: List[str] = Field(default_factory=list, description="Key findings extracted")
    methodology: str = Field(default="", description="Research methodology description")
    
    # URLs and identifiers
    url: str = Field(..., description="Paper URL")
    connected_papers_url: Optional[str] = Field(None, description="Connected Papers URL")
    
    # Analysis metadata
    analysis_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Analysis confidence score")
    processing_time: Optional[float] = Field(None, ge=0.0, description="Processing time in seconds")
    
    @field_validator('key_findings')
    @classmethod
    def validate_findings(cls, v):
        """Ensure key findings are non-empty strings"""
        return [finding.strip() for finding in v if finding and finding.strip()]


class AnalysisResult(BaseModel):
    """Analysis agent response model"""
    model_config = ConfigDict(populate_by_name=True)
    
    summaries: List[PaperSummary] = Field(default_factory=list, description="Individual paper summaries")
    author_count: int = Field(..., ge=0, description="Total unique authors found")
    total_papers: int = Field(..., ge=0, description="Total papers analyzed")
    
    # Analysis statistics
    avg_processing_time: Optional[float] = Field(None, ge=0.0, description="Average processing time per paper")
    analysis_timestamp: datetime = Field(default_factory=datetime.now, description="Analysis completion time")
    
    # Research insights
    top_authors: List[str] = Field(default_factory=list, description="Most frequent authors")
    common_themes: List[str] = Field(default_factory=list, description="Common research themes")
    
    @field_validator('total_papers')
    @classmethod
    def validate_paper_count(cls, v, info):
        """Ensure total_papers matches summaries length"""
        if info.data and 'summaries' in info.data:
            return len(info.data['summaries'])
        return v


class ReportMetadata(BaseModel):
    """Report generation metadata"""
    model_config = ConfigDict(populate_by_name=True)
    
    generation_timestamp: datetime = Field(default_factory=datetime.now, description="Report generation time")
    prisma_version: str = Field(default="0.1.0-mvp", description="Prisma version used")
    
    # Search parameters
    search_query: str = Field(..., description="Original search query")
    sources_used: List[str] = Field(default_factory=list, description="Data sources used")
    papers_analyzed: int = Field(..., ge=0, description="Number of papers analyzed")
    
    # Processing statistics
    total_processing_time: Optional[float] = Field(None, ge=0.0, description="Total processing time")
    search_time: Optional[float] = Field(None, ge=0.0, description="Search phase time")
    analysis_time: Optional[float] = Field(None, ge=0.0, description="Analysis phase time")
    report_time: Optional[float] = Field(None, ge=0.0, description="Report generation time")


class LiteratureReviewReport(BaseModel):
    """Complete literature review report model"""
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., description="Report title")
    summary_count: int = Field(..., ge=0, description="Number of papers summarized")
    content: str = Field(..., description="Formatted report content (Markdown)")
    
    # Optional sections
    bibliography: Optional[List[str]] = Field(None, description="Bibliography entries")
    executive_summary: Optional[str] = Field(None, description="Executive summary")
    
    # Structured data
    metadata: ReportMetadata = Field(..., description="Report metadata")
    
    # Export capabilities
    export_formats: List[str] = Field(default=["markdown"], description="Available export formats")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "title": self.title,
            "summary_count": self.summary_count,
            "content": self.content,
            "bibliography": self.bibliography,
            "executive_summary": self.executive_summary,
            "metadata": self.metadata.model_dump(),
            "export_formats": self.export_formats
        }
    
    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        """Ensure content is not empty"""
        if not v or not v.strip():
            raise ValueError("Report content cannot be empty")
        return v.strip()


class CoordinatorResult(BaseModel):
    """Coordinator pipeline result model"""
    model_config = ConfigDict(populate_by_name=True)
    
    success: bool = Field(..., description="Whether the pipeline completed successfully")
    papers_analyzed: int = Field(..., ge=0, description="Number of papers analyzed")
    authors_found: int = Field(..., ge=0, description="Number of unique authors found")
    output_file: str = Field(..., description="Path to generated report file")
    
    # Processing metadata
    total_duration: Optional[float] = Field(None, ge=0.0, description="Total pipeline duration")
    pipeline_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional pipeline metadata")
    
    # Error handling
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings generated")
    
    @field_validator('output_file')
    @classmethod
    def validate_output_file(cls, v):
        """Ensure output file path is not empty"""
        if not v or not v.strip():
            raise ValueError("Output file path cannot be empty")
        return v.strip()


# Export all models
__all__ = [
    'PaperMetadata',
    'SearchResult', 
    'PaperSummary',
    'AnalysisResult',
    'ReportMetadata',
    'LiteratureReviewReport',
    'CoordinatorResult'
]