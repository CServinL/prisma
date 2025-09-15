"""
Test Zotero data models
"""

import pytest
from datetime import datetime
from src.storage.models.zotero_models import (
    ZoteroItem, 
    ZoteroCollection, 
    ZoteroCreator, 
    ZoteroTag,
    ZoteroItemType
)


class TestZoteroCreator:
    """Test ZoteroCreator data model"""
    
    def test_creator_initialization(self):
        """Test basic creator initialization"""
        creator = ZoteroCreator(
            creator_type="author",
            first_name="John",
            last_name="Doe"
        )
        
        assert creator.creator_type == "author"
        assert creator.first_name == "John"
        assert creator.last_name == "Doe"
        assert creator.full_name == "John Doe"
    
    def test_creator_single_name(self):
        """Test creator with single name field"""
        creator = ZoteroCreator(
            creator_type="author",
            name="University of Science"
        )
        
        assert creator.full_name == "University of Science"
    
    def test_creator_from_zotero_data(self):
        """Test creation from Zotero API data"""
        data = {
            "creatorType": "author",
            "firstName": "Jane",
            "lastName": "Smith"
        }
        
        creator = ZoteroCreator.from_zotero_data(data)
        assert creator.creator_type == "author"
        assert creator.first_name == "Jane"
        assert creator.last_name == "Smith"
        assert creator.full_name == "Jane Smith"


class TestZoteroTag:
    """Test ZoteroTag data model"""
    
    def test_tag_initialization(self):
        """Test basic tag initialization"""
        tag = ZoteroTag(tag="machine learning", type=0)
        
        assert tag.tag == "machine learning"
        assert tag.type == 0
    
    def test_tag_from_string(self):
        """Test creation from string data"""
        tag = ZoteroTag.from_zotero_data("artificial intelligence")
        
        assert tag.tag == "artificial intelligence"
        assert tag.type == 0
    
    def test_tag_from_dict(self):
        """Test creation from dictionary data"""
        data = {
            "tag": "neural networks",
            "type": 1
        }
        
        tag = ZoteroTag.from_zotero_data(data)
        assert tag.tag == "neural networks"
        assert tag.type == 1


class TestZoteroCollection:
    """Test ZoteroCollection data model"""
    
    def test_collection_initialization(self):
        """Test basic collection initialization"""
        collection = ZoteroCollection(
            key="ABC123",
            name="AI Papers"
        )
        
        assert collection.key == "ABC123"
        assert collection.name == "AI Papers"
        assert collection.parent_collection is None
    
    def test_collection_from_zotero_data(self):
        """Test creation from Zotero API data"""
        data = {
            "key": "DEF456",
            "version": 5,
            "data": {
                "name": "Machine Learning",
                "parentCollection": "ABC123"
            },
            "links": {"self": "https://api.zotero.org/..."},
            "meta": {"numItems": 15}
        }
        
        collection = ZoteroCollection.from_zotero_data(data)
        assert collection.key == "DEF456"
        assert collection.name == "Machine Learning"
        assert collection.parent_collection == "ABC123"
        assert collection.version == 5


class TestZoteroItem:
    """Test ZoteroItem data model"""
    
    def test_item_initialization(self):
        """Test basic item initialization"""
        creators = [
            ZoteroCreator(creator_type="author", first_name="John", last_name="Doe")
        ]
        tags = [
            ZoteroTag(tag="machine learning")
        ]
        
        item = ZoteroItem(
            key="ITEM123",
            item_type="journalArticle",
            title="A Study of Neural Networks",
            creators=creators,
            tags=tags,
            date="2023"
        )
        
        assert item.key == "ITEM123"
        assert item.item_type == "journalArticle"
        assert item.title == "A Study of Neural Networks"
        assert len(item.creators) == 1
        assert len(item.tags) == 1
        assert item.year == 2023
    
    def test_item_properties(self):
        """Test computed properties"""
        creators = [
            ZoteroCreator(creator_type="author", first_name="John", last_name="Doe"),
            ZoteroCreator(creator_type="editor", first_name="Jane", last_name="Smith")
        ]
        
        item = ZoteroItem(
            key="ITEM123",
            item_type="journalArticle",
            title="Neural Networks",
            creators=creators,
            date="2023-05-15"
        )
        
        assert item.authors == ["John Doe"]
        assert item.first_author == "John Doe"
        assert item.year == 2023
        assert item.is_academic_paper is True
    
    def test_citation_key_generation(self):
        """Test citation key generation"""
        creators = [
            ZoteroCreator(creator_type="author", first_name="John", last_name="Doe")
        ]
        
        item = ZoteroItem(
            key="ITEM123",
            item_type="journalArticle",
            title="A Study of Neural Networks",
            creators=creators,
            date="2023"
        )
        
        citation_key = item.citation_key
        assert "Doe" in citation_key
        assert "2023" in citation_key
        assert "Study" in citation_key or "Neural" in citation_key
    
    def test_year_extraction_formats(self):
        """Test year extraction from various date formats"""
        test_cases = [
            ("2023", 2023),
            ("2023-05-15", 2023),
            ("05/15/2023", 2023),
            ("May 2023", 2023),
            ("Published in 2023", 2023),
            ("invalid date", None),
            ("", None)
        ]
        
        for date_str, expected_year in test_cases:
            item = ZoteroItem(key="TEST", item_type="article", date=date_str)
            assert item.year == expected_year, f"Failed for date: {date_str}"
    
    def test_academic_paper_detection(self):
        """Test academic paper detection"""
        academic_types = [
            "journalArticle",
            "conferencePaper", 
            "preprint",
            "thesis"
        ]
        
        non_academic_types = [
            "book",
            "webpage",
            "blogPost",
            "newspaperArticle"
        ]
        
        for item_type in academic_types:
            item = ZoteroItem(key="TEST", item_type=item_type)
            assert item.is_academic_paper is True, f"Failed for type: {item_type}"
        
        for item_type in non_academic_types:
            item = ZoteroItem(key="TEST", item_type=item_type)
            assert item.is_academic_paper is False, f"Failed for type: {item_type}"
    
    def test_from_zotero_data(self):
        """Test creation from Zotero API data"""
        data = {
            "key": "ZOTERO123",
            "version": 10,
            "data": {
                "itemType": "journalArticle",
                "title": "Machine Learning Applications",
                "creators": [
                    {
                        "creatorType": "author",
                        "firstName": "John",
                        "lastName": "Doe"
                    }
                ],
                "abstractNote": "This paper discusses...",
                "publicationTitle": "Journal of AI",
                "volume": "10",
                "issue": "2",
                "pages": "123-145",
                "date": "2023-03-15",
                "DOI": "10.1000/example",
                "tags": [
                    {"tag": "machine learning", "type": 0}
                ],
                "collections": ["COLLECTION1"],
                "dateAdded": "2023-03-16",
                "dateModified": "2023-03-17"
            }
        }
        
        item = ZoteroItem.from_zotero_data(data)
        
        assert item.key == "ZOTERO123"
        assert item.item_type == "journalArticle"
        assert item.title == "Machine Learning Applications"
        assert len(item.creators) == 1
        assert item.creators[0].full_name == "John Doe"
        assert item.abstract_note == "This paper discusses..."
        assert item.publication_title == "Journal of AI"
        assert item.volume == "10"
        assert item.issue == "2" 
        assert item.pages == "123-145"
        assert item.date == "2023-03-15"
        assert item.doi == "10.1000/example"
        assert len(item.tags) == 1
        assert item.tags[0].tag == "machine learning"
        assert item.collections == ["COLLECTION1"]
        assert item.version == 10
    
    def test_to_dict_serialization(self):
        """Test dictionary serialization"""
        creators = [
            ZoteroCreator(creator_type="author", first_name="John", last_name="Doe")
        ]
        tags = [
            ZoteroTag(tag="machine learning")
        ]
        
        item = ZoteroItem(
            key="ITEM123",
            item_type="journalArticle",
            title="A Study",
            creators=creators,
            tags=tags,
            date="2023",
            doi="10.1000/test"
        )
        
        item_dict = item.to_dict()
        
        assert item_dict["key"] == "ITEM123"
        assert item_dict["title"] == "A Study"
        assert item_dict["authors"] == ["John Doe"]
        assert item_dict["year"] == 2023
        assert item_dict["doi"] == "10.1000/test"
        assert item_dict["tags"] == ["machine learning"]
        assert item_dict["is_academic_paper"] is True
        assert "citation_key" in item_dict