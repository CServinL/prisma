"""
Storage models for Prisma
"""

from .zotero_models import (
    ZoteroItem, 
    ZoteroCollection, 
    ZoteroCreator, 
    ZoteroTag, 
    ZoteroLibrary, 
    ZoteroItemType
)

from .agent_models import (
    PaperMetadata,
    SearchResult,
    PaperSummary,
    AnalysisResult,
    ReportMetadata,
    LiteratureReviewReport,
    CoordinatorResult
)

from .api_response_models import (
    OpenLibraryDocument,
    OpenLibraryResponse,
    SemanticScholarPaper,
    SemanticScholarResponse,
    GoogleBooksItem,
    GoogleBooksResponse,
    ArXivEntry,
    LLMRelevanceResult,
    OllamaGenerateResponse,
    ZoteroItemCreationData
)

__all__ = [
    # Zotero models
    "ZoteroItem", 
    "ZoteroCollection", 
    "ZoteroCreator", 
    "ZoteroTag", 
    "ZoteroLibrary", 
    "ZoteroItemType",
    
    # Agent response models
    "PaperMetadata",
    "SearchResult",
    "PaperSummary", 
    "AnalysisResult",
    "ReportMetadata",
    "LiteratureReviewReport",
    "CoordinatorResult",
    
    # API response models
    "OpenLibraryDocument",
    "OpenLibraryResponse", 
    "SemanticScholarPaper",
    "SemanticScholarResponse",
    "GoogleBooksItem",
    "GoogleBooksResponse",
    "ArXivEntry",
    "LLMRelevanceResult",
    "OllamaGenerateResponse",
    "ZoteroItemCreationData"
]