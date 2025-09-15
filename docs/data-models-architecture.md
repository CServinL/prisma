# Data Models Architecture

## Overview

Prisma uses **Pydantic v2** for all data models, providing robust type validation, automatic serialization, and superior error handling. This architectural choice ensures data integrity and developer productivity throughout the literature review pipeline.

## Why Pydantic Over Dataclasses?

### Previous Architecture (Dataclasses)
- Basic type hints with no runtime validation
- Manual serialization/deserialization methods
- Minimal error reporting
- No schema generation capabilities

### Current Architecture (Pydantic v2)
- ✅ **Automatic validation**: Runtime type checking and validation
- ✅ **Field aliases**: Support for API field name mappings
- ✅ **JSON schema generation**: Automatic API documentation
- ✅ **Superior error messages**: Detailed validation feedback
- ✅ **Data transformation**: Automatic cleaning and conversion
- ✅ **IDE support**: Enhanced type hints and autocompletion
- ✅ **Industry standard**: Widely adopted for API data models

## Zotero Models

### Core Models

#### `ZoteroCreator`
```python
creator = ZoteroCreator(
    creator_type="author",
    first_name="Jane",
    last_name="Doe"
)
# Supports both field names and Zotero API aliases
creator_api = ZoteroCreator(
    creator_type="author",
    firstName="Jane",  # Zotero API format
    lastName="Doe"
)
```

#### `ZoteroItem`
```python
item = ZoteroItem(
    key="ITEM123",
    item_type="journalArticle",
    title="Machine Learning Applications",
    creators=[creator],
    tags=[ZoteroTag(tag="ML")],
    date="2024-01-15"
)

# Automatic computed properties
print(item.year)  # 2024
print(item.citation_key)  # "Doe2024MachineLearningApplications"
print(item.is_academic_paper)  # True
```

#### `ZoteroCollection`
```python
collection = ZoteroCollection(
    key="COLL123",
    name="AI Research",
    parent_collection="PARENT456"
)
```

## Validation Features

### Automatic Type Validation
```python
# This will raise a validation error
invalid_item = ZoteroItem(
    # Missing required 'key' field
    item_type="article",
    creators="not a list"  # Wrong type
)
```

### Field Aliases
```python
# Both formats work
item1 = ZoteroItem(item_type="article")  # Python format
item2 = ZoteroItem(itemType="article")   # Zotero API format
```

### Data Transformation
```python
tag = ZoteroTag(tag="  machine learning  ")
print(tag.tag)  # "machine learning" (trimmed)
```

## Serialization

### JSON Export/Import
```python
# Export to JSON
json_data = item.model_dump_json(indent=2)

# Import from dict
item_dict = item.model_dump()
recreated_item = ZoteroItem.model_validate(item_dict)
```

### Dictionary Conversion
```python
# Custom serialization for reports
item_dict = item.to_dict()  # Flattened format for analysis
```

## Schema Generation

```python
# Automatic JSON schema for API documentation
schema = ZoteroItem.model_json_schema()
```

## Error Handling

Pydantic provides detailed validation errors with:
- Field names and types
- Expected vs actual values
- Helpful error messages
- Links to documentation

```python
try:
    invalid_item = ZoteroItem(creators="invalid")
except ValidationError as e:
    print(e.errors())  # Detailed error information
```

## Migration Benefits

### Before (Dataclasses)
```python
@dataclass
class ZoteroCreator:
    creator_type: str
    first_name: Optional[str] = None
    
    @classmethod
    def from_zotero_data(cls, data):
        # Manual validation and parsing
        return cls(...)
```

### After (Pydantic)
```python
class ZoteroCreator(BaseModel):
    creator_type: str
    first_name: Optional[str] = Field(None, alias="firstName")
    
    @classmethod
    def from_zotero_data(cls, data):
        return cls(**data)  # Automatic validation
```

## Best Practices

### Model Definition
- Use descriptive field descriptions
- Implement proper validators for complex fields
- Leverage field aliases for API compatibility
- Add computed properties for derived data

### Error Handling
- Catch `ValidationError` for data validation issues
- Use `model_validate()` for safe parsing
- Implement fallbacks for optional data

### Performance
- Use `model_dump()` for serialization
- Cache expensive computed properties
- Leverage Pydantic's optimized C extensions

## Testing

All models include comprehensive test coverage:
- Field validation
- Type checking
- Serialization/deserialization
- Computed properties
- Error handling

Run model tests:
```bash
pipenv run pytest tests/unit/integrations/zotero/test_models.py -v
```

## Future Enhancements

- **Custom validators**: Domain-specific validation rules
- **Computed fields**: Advanced derived properties
- **Serialization modes**: Different output formats for different use cases
- **Plugin system**: Extensible model architecture