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
    "CoordinatorResult"
]