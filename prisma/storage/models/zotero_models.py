"""
Data models for Zotero integration using Pydantic

This module defines Pydantic models for representing Zotero items,
collections, and related metadata in a consistent format for use throughout
the Prisma literature review system.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum
import re

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ZoteroItemType(str, Enum):
    """Supported Zotero item types"""
    JOURNAL_ARTICLE = "journalArticle"
    BOOK = "book"
    BOOK_SECTION = "bookSection"
    CONFERENCE_PAPER = "conferencePaper"
    THESIS = "thesis"
    REPORT = "report"
    WEBPAGE = "webpage"
    PREPRINT = "preprint"
    MANUSCRIPT = "manuscript"
    PRESENTATION = "presentation"
    OTHER = "other"


class ZoteroCreator(BaseModel):
    """Represents a creator (author, editor, etc.) in Zotero"""
    model_config = ConfigDict(populate_by_name=True)
    
    creator_type: str = Field(..., description="Creator type: author, editor, translator, etc.")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    name: Optional[str] = Field(None, description="Full name for organizations or single-field names")
        
    @property
    def full_name(self) -> str:
        """Get the full name of the creator"""
        if self.name:
            return self.name
        elif self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.last_name:
            return self.last_name
        elif self.first_name:
            return self.first_name
        return "Unknown"

    @classmethod
    def from_zotero_data(cls, data: Dict[str, Any]) -> "ZoteroCreator":
        """Create ZoteroCreator from Zotero API data"""
        return cls(
            creator_type=data.get("creatorType", "author"),
            first_name=data.get("firstName"),
            last_name=data.get("lastName"),
            name=data.get("name")
        )


class ZoteroTag(BaseModel):
    """Represents a tag in Zotero"""
    tag: str = Field(..., description="Tag text")
    type: int = Field(0, description="Tag type: 0=manual, 1=automatic")
    
    @field_validator('tag')
    @classmethod
    def tag_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Tag cannot be empty')
        return v.strip()

    @classmethod
    def from_zotero_data(cls, data: Union[Dict[str, Any], str]) -> "ZoteroTag":
        """Create ZoteroTag from Zotero API data"""
        if isinstance(data, str):
            return cls(tag=data)
        return cls(
            tag=data.get("tag", ""),
            type=data.get("type", 0)
        )


class ZoteroCollection(BaseModel):
    """Represents a Zotero collection"""
    model_config = ConfigDict(populate_by_name=True)
    
    key: str = Field(..., description="Zotero collection key")
    name: str = Field(..., description="Collection name")
    parent_collection: Optional[str] = Field(None, alias="parentCollection")
    version: Optional[int] = Field(None, description="Collection version")
    library: Optional[str] = Field(None, description="Library identifier")
    links: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def from_zotero_data(cls, data: Dict[str, Any]) -> "ZoteroCollection":
        """Create ZoteroCollection from Zotero API data"""
        collection_data = data.get("data", {})
        
        # Handle parent_collection - convert False to None
        parent_collection = collection_data.get("parentCollection")
        if parent_collection is False:
            parent_collection = None
        
        # Handle library - extract string identifier from dict or use as-is
        library = data.get("library")
        if isinstance(library, dict):
            library = str(library.get("id", "")) if library.get("id") else None
        
        return cls(
            key=data.get("key", ""),
            name=collection_data.get("name", ""),
            parentCollection=parent_collection,
            version=data.get("version"),
            library=library,
            links=data.get("links", {}),
            meta=data.get("meta", {})
        )


class ZoteroItem(BaseModel):
    """
    Represents a Zotero item with standardized fields
    
    This class provides a consistent interface for working with Zotero items
    regardless of their original item type, mapping common fields and providing
    access to item-specific data.
    """
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)
    
    key: str = Field(..., description="Zotero item key")
    item_type: str = Field(..., alias="itemType", description="Zotero item type")
    title: Optional[str] = Field(None, description="Item title")
    creators: List[ZoteroCreator] = Field(default_factory=list, description="Authors, editors, etc.")
    abstract_note: Optional[str] = Field(None, alias="abstractNote", description="Abstract or note")
    publication_title: Optional[str] = Field(None, alias="publicationTitle", description="Journal/venue name")
    volume: Optional[str] = Field(None, description="Volume number")
    issue: Optional[str] = Field(None, description="Issue number")
    pages: Optional[str] = Field(None, description="Page range")
    date: Optional[str] = Field(None, description="Publication date")
    doi: Optional[str] = Field(None, alias="DOI", description="Digital Object Identifier")
    url: Optional[str] = Field(None, description="URL")
    tags: List[ZoteroTag] = Field(default_factory=list, description="Item tags")
    collections: List[str] = Field(default_factory=list, description="Collection keys")
    
    # Metadata
    date_added: Optional[str] = Field(None, alias="dateAdded")
    date_modified: Optional[str] = Field(None, alias="dateModified")
    version: Optional[int] = Field(None, description="Item version")
    library: Optional[str] = Field(None, description="Library identifier")
    
    # Raw data for access to item-specific fields
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="Original Zotero data")
    
    @property
    def authors(self) -> List[str]:
        """Get list of author names"""
        return [creator.full_name for creator in self.creators if creator.creator_type == "author"]
    
    @property
    def first_author(self) -> Optional[str]:
        """Get the first author's name"""
        authors = self.authors
        return authors[0] if authors else None
    
    @property
    def year(self) -> Optional[int]:
        """Extract year from date string"""
        if not self.date:
            return None
        try:
            # Try to parse various date formats
            for fmt in ["%Y", "%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(self.date, fmt).year
                except ValueError:
                    continue
            # If no format matches, try to extract 4-digit year
            match = re.search(r'\b(19|20)\d{2}\b', self.date)
            return int(match.group()) if match else None
        except (ValueError, AttributeError):
            return None
    
    @property
    def citation_key(self) -> str:
        """Generate a citation key for the item"""
        author_part = ""
        if self.first_author:
            # Get last name or first word of name
            author_parts = self.first_author.split()
            author_part = author_parts[-1] if author_parts else "Unknown"
        
        year_part = str(self.year) if self.year else "NoDate"
        title_part = ""
        if self.title:
            # Get first few words of title
            title_words = self.title.split()[:3]
            title_part = "".join(word.capitalize() for word in title_words)
        
        return f"{author_part}{year_part}{title_part}"
    
    @property
    def is_academic_paper(self) -> bool:
        """Check if this item is likely an academic paper"""
        academic_types = {
            ZoteroItemType.JOURNAL_ARTICLE.value,
            ZoteroItemType.CONFERENCE_PAPER.value,
            ZoteroItemType.PREPRINT.value,
            ZoteroItemType.THESIS.value
        }
        return self.item_type in academic_types
    
    def get_field(self, field_name: str, default: Any = None) -> Any:
        """Get a field value from raw data"""
        return self.raw_data.get("data", {}).get(field_name, default)
    
    @classmethod
    def from_zotero_data(cls, data: Dict[str, Any]) -> "ZoteroItem":
        """Create ZoteroItem from Zotero API data"""
        item_data = data.get("data", {})
        
        # Extract creators
        creators = [
            ZoteroCreator.from_zotero_data(creator_data) 
            for creator_data in item_data.get("creators", [])
        ]
        
        # Extract tags
        tags = []
        for tag_data in item_data.get("tags", []):
            tags.append(ZoteroTag.from_zotero_data(tag_data))
        
        return cls(
            key=data.get("key", ""),
            item_type=item_data.get("itemType", "other"),
            title=item_data.get("title"),
            creators=creators,
            abstract_note=item_data.get("abstractNote"),
            publication_title=item_data.get("publicationTitle"),
            volume=item_data.get("volume"),
            issue=item_data.get("issue"),
            pages=item_data.get("pages"),
            date=item_data.get("date"),
            doi=item_data.get("DOI"),
            url=item_data.get("url"),
            tags=tags,
            collections=item_data.get("collections", []),
            date_added=item_data.get("dateAdded"),
            date_modified=item_data.get("dateModified"),
            version=data.get("version"),
            library=str(data.get("library", "")) if data.get("library") else None,
            raw_data=data
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "key": self.key,
            "item_type": self.item_type,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract_note,
            "publication": self.publication_title,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "date": self.date,
            "year": self.year,
            "doi": self.doi,
            "url": self.url,
            "tags": [tag.tag for tag in self.tags],
            "collections": self.collections,
            "citation_key": self.citation_key,
            "is_academic_paper": self.is_academic_paper
        }


class ZoteroAttachment(BaseModel):
    """Represents a Zotero attachment (PDF, snapshot, etc.)"""
    model_config = ConfigDict(populate_by_name=True)
    
    key: str = Field(..., description="Attachment key")
    parent_item: Optional[str] = Field(None, alias="parentItem", description="Parent item key")
    item_type: str = Field("attachment", alias="itemType")
    link_mode: Optional[str] = Field(None, alias="linkMode", description="Link mode: imported_file, imported_url, linked_file, linked_url")
    title: Optional[str] = Field(None, description="Attachment title")
    filename: Optional[str] = Field(None, description="Filename")
    path: Optional[str] = Field(None, description="File path")
    url: Optional[str] = Field(None, description="URL for linked attachments")
    content_type: Optional[str] = Field(None, alias="contentType", description="MIME type")
    charset: Optional[str] = Field(None, description="Character encoding")
    md5: Optional[str] = Field(None, description="MD5 hash")
    mtime: Optional[int] = Field(None, description="Modification time")
    
    @property
    def is_pdf(self) -> bool:
        """Check if this attachment is a PDF"""
        return (self.content_type == "application/pdf" or 
                (self.filename and self.filename.lower().endswith('.pdf')))
    
    @property
    def is_snapshot(self) -> bool:
        """Check if this attachment is a web snapshot"""
        return self.content_type == "text/html" or self.link_mode == "imported_url"
    
    @classmethod
    def from_zotero_data(cls, data: Dict[str, Any]) -> "ZoteroAttachment":
        """Create ZoteroAttachment from Zotero API data"""
        item_data = data.get("data", {})
        return cls(
            key=data.get("key", ""),
            parent_item=item_data.get("parentItem"),
            item_type=item_data.get("itemType", "attachment"),
            link_mode=item_data.get("linkMode"),
            title=item_data.get("title"),
            filename=item_data.get("filename"),
            path=item_data.get("path"),
            url=item_data.get("url"),
            content_type=item_data.get("contentType"),
            charset=item_data.get("charset"),
            md5=item_data.get("md5"),
            mtime=item_data.get("mtime")
        )


class ZoteroSearchQuery(BaseModel):
    """Represents a search query for Zotero items"""
    
    # Text search fields
    query: Optional[str] = Field(None, description="General search query")
    title: Optional[str] = Field(None, description="Search in title")
    author: Optional[str] = Field(None, description="Search in authors")
    publication: Optional[str] = Field(None, description="Search in publication")
    abstract: Optional[str] = Field(None, description="Search in abstract")
    tags: Optional[List[str]] = Field(None, description="Search for specific tags")
    
    # Filters
    item_types: Optional[List[str]] = Field(None, description="Filter by item types")
    collections: Optional[List[str]] = Field(None, description="Filter by collection keys")
    date_from: Optional[str] = Field(None, description="Filter items from this date")
    date_to: Optional[str] = Field(None, description="Filter items to this date")
    has_pdf: Optional[bool] = Field(None, description="Filter items with PDF attachments")
    has_doi: Optional[bool] = Field(None, description="Filter items with DOI")
    
    # Query options
    limit: int = Field(100, description="Maximum number of results")
    start: int = Field(0, description="Start index for pagination")
    sort_by: str = Field("date", description="Sort field: date, title, author, dateAdded")
    sort_direction: str = Field("desc", description="Sort direction: asc, desc")
    
    @field_validator('sort_by')
    @classmethod
    def sort_by_must_be_valid(cls, v):
        valid_sorts = {"date", "title", "author", "dateAdded", "dateModified", "itemType"}
        if v not in valid_sorts:
            raise ValueError(f'sort_by must be one of {valid_sorts}')
        return v
    
    @field_validator('sort_direction')
    @classmethod
    def sort_direction_must_be_valid(cls, v):
        if v not in ("asc", "desc"):
            raise ValueError('sort_direction must be "asc" or "desc"')
        return v
    
    def to_sql_where_clause(self) -> str:
        """Convert query to SQL WHERE clause for SQLite searches"""
        conditions = []
        
        if self.query:
            conditions.append(
                "(i.title LIKE ? OR ia.abstractNote LIKE ? OR "
                "GROUP_CONCAT(c.firstName || ' ' || c.lastName) LIKE ?)"
            )
        
        if self.title:
            conditions.append("i.title LIKE ?")
        
        if self.author:
            conditions.append(
                "EXISTS (SELECT 1 FROM itemCreators ic "
                "JOIN creators c ON ic.creatorID = c.creatorID "
                "WHERE ic.itemID = i.itemID AND "
                "(c.firstName LIKE ? OR c.lastName LIKE ?))"
            )
        
        if self.publication:
            conditions.append("i.publicationTitle LIKE ?")
        
        if self.abstract:
            conditions.append("ia.abstractNote LIKE ?")
        
        if self.item_types:
            placeholders = ",".join("?" for _ in self.item_types)
            conditions.append(f"it.typeName IN ({placeholders})")
        
        if self.has_doi:
            conditions.append("i.DOI IS NOT NULL AND i.DOI != ''")
        
        if self.date_from:
            conditions.append("i.date >= ?")
        
        if self.date_to:
            conditions.append("i.date <= ?")
        
        return " AND ".join(conditions) if conditions else "1=1"
    
    def get_sql_params(self) -> List[str]:
        """Get parameters for SQL query"""
        params = []
        
        if self.query:
            search_param = f"%{self.query}%"
            params.extend([search_param, search_param, search_param])
        
        if self.title:
            params.append(f"%{self.title}%")
        
        if self.author:
            author_param = f"%{self.author}%"
            params.extend([author_param, author_param])
        
        if self.publication:
            params.append(f"%{self.publication}%")
        
        if self.abstract:
            params.append(f"%{self.abstract}%")
        
        if self.item_types:
            params.extend(self.item_types)
        
        if self.date_from:
            params.append(self.date_from)
        
        if self.date_to:
            params.append(self.date_to)
        
        return params


class ZoteroSearchResult(BaseModel):
    """Represents search results from Zotero"""
    
    items: List[ZoteroItem] = Field(default_factory=list, description="Found items")
    total_results: int = Field(0, description="Total number of matching items")
    start: int = Field(0, description="Start index of this page")
    limit: int = Field(100, description="Items per page")
    query: Optional[ZoteroSearchQuery] = Field(None, description="Original search query")
    
    @property
    def has_more(self) -> bool:
        """Check if there are more results available"""
        return self.start + len(self.items) < self.total_results
    
    @property
    def next_start(self) -> int:
        """Get start index for next page"""
        return self.start + len(self.items)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "items": [item.to_dict() for item in self.items],
            "total_results": self.total_results,
            "start": self.start,
            "limit": self.limit,
            "has_more": self.has_more,
            "item_count": len(self.items)
        }


class ZoteroLibrary(BaseModel):
    """Represents a Zotero library (user or group)"""
    model_config = ConfigDict(populate_by_name=True)
    
    library_id: str = Field(..., description="Zotero library ID")
    library_type: str = Field(..., description="Library type: 'user' or 'group'")
    name: Optional[str] = Field(None, description="Library name")
    description: Optional[str] = Field(None, description="Library description")
    collections: List[ZoteroCollection] = Field(default_factory=list)
    item_count: int = Field(0, alias="numItems", description="Number of items in library")
    
    @field_validator('library_type')
    @classmethod
    def library_type_must_be_valid(cls, v):
        if v not in ('user', 'group'):
            raise ValueError('library_type must be "user" or "group"')
        return v
    
    @classmethod
    def from_zotero_data(cls, data: Dict[str, Any], library_id: str, library_type: str) -> "ZoteroLibrary":
        """Create ZoteroLibrary from Zotero API data"""
        return cls(
            library_id=library_id,
            library_type=library_type,
            name=data.get("name"),
            description=data.get("description"),
            item_count=data.get("numItems", 0)
        )