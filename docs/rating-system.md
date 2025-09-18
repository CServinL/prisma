# Quality-Based Source Rating System

Prisma uses a **1-5 star rating system** to ensure high-quality academic content and prioritize reliable academic databases.

## Rating Criteria

The rating system evaluates sources based on:
- **Content Quality**: Academic rigor and peer review processes
- **Metadata Richness**: Availability of structured bibliographic data
- **API Reliability**: Consistent access and data quality
- **Coverage Scope**: Breadth and depth of academic content
- **Academic Validation**: Built-in quality controls and filtering

## Source Ratings

### ⭐⭐⭐⭐⭐ (5-star): Premium APIs with Curated Content

**Semantic Scholar**
- AI-powered search with 214M+ papers
- Advanced semantic understanding and paper relationships
- High-quality metadata and citation graphs
- Research influence metrics and author disambiguation

**arXiv**
- High-quality preprint server with full metadata
- Rigorous submission standards in STEM fields
- Complete PDF access and structured abstracts
- Immediate access to cutting-edge research

### ⭐⭐⭐⭐ (4-star): Good APIs with Structured Data

**Open Library**
- Internet Archive's millions of academic books
- Comprehensive book metadata and full-text access
- Historical academic publications and rare texts
- Structured bibliographic information

**Google Books**
- Comprehensive book catalog with rich metadata
- Academic publisher partnerships
- Preview access and citation information
- Cross-reference capabilities

**PubMed**
- Authoritative biomedical literature database
- MEDLINE indexing with controlled vocabularies
- High-quality abstracts and full bibliographic records
- Integration with clinical and research databases

### ⭐⭐⭐ (3-star): Basic APIs and Reliable Sources

**Zotero**
- User's personal research library
- Community-curated bibliographic data
- Flexible metadata schema
- Integration with academic workflows

**CrossRef**
- DOI resolution and metadata services
- Publisher-provided bibliographic information
- Citation linking and reference validation
- Academic content verification

## Academic Validation Filters

Prisma automatically applies quality filters regardless of source rating:

### ✅ **Required Elements**
- **Authors**: Must have identifiable authors or creators
- **Publication Venue**: Journal, conference, or institutional affiliation
- **Academic Indicators**: Proper citations, abstracts, or academic formatting
- **Bibliographic Metadata**: Title, date, and publication information

### ❌ **Excluded Content**
- **Blog Posts**: Personal or commercial blog content
- **News Articles**: Journalistic reporting without academic rigor
- **Social Media**: Twitter, LinkedIn, or social platform posts
- **Marketing Content**: Commercial or promotional materials
- **Unverified Sources**: Content without proper attribution

## Source Selection Strategy

### Multi-Source Approach
Prisma combines multiple sources to maximize content discovery:

1. **Start with 5-star sources** for the highest quality baseline
2. **Supplement with 4-star sources** for comprehensive coverage
3. **Include 3-star sources** for specialized or personal collections
4. **Apply consistent filtering** across all sources

### Quality Scoring
Each discovered document receives a quality score based on:
- **Source rating** (1-5 stars)
- **Academic validation** (pass/fail filters)
- **Metadata completeness** (bibliographic richness)
- **Content confidence** (LLM assessment)

### Deduplication Priority
When multiple sources provide the same document:
1. Higher-rated source takes precedence
2. More complete metadata is preferred
3. PDF availability increases priority
4. Recent publication dates are favored

## Implementation

### Configuration
```yaml
sources:
  priority_order:
    - semanticscholar  # 5-star
    - arxiv           # 5-star
    - pubmed          # 4-star
    - openlibrary     # 4-star
    - zotero          # 3-star
  
  quality_filters:
    require_authors: true
    require_venue: true
    exclude_blogs: true
    exclude_news: true
    min_confidence: 0.7
```

### API Integration
Each source integration implements quality-aware features:
- **Metadata validation** during content ingestion
- **Quality scoring** for search results
- **Filtering pipelines** to exclude low-quality content
- **Confidence metrics** for LLM assessment

### User Interface
The CLI reflects quality information:
```bash
📊 Search Results Quality Summary:
   ⭐⭐⭐⭐⭐ 15 papers from Semantic Scholar
   ⭐⭐⭐⭐⭐ 8 papers from arXiv  
   ⭐⭐⭐⭐   12 papers from PubMed
   ⭐⭐⭐     5 papers from Zotero
   
🛡️ Quality Filters Applied:
   ✅ Academic validation: 40/45 papers passed
   ✅ Metadata completeness: 38/40 papers complete
   ✅ Deduplication: 35/38 unique papers
```

## Future Enhancements

### Dynamic Rating Updates
- **Performance monitoring** of source reliability
- **User feedback integration** on content quality
- **Automatic rating adjustments** based on success metrics

### Custom Rating Profiles
- **Research domain-specific** rating adjustments
- **Institution-specific** source preferences
- **User-customizable** quality thresholds

### Quality Analytics
- **Source performance dashboards** in reports
- **Quality trend analysis** over time
- **Recommendation engines** for source optimization

## See Also

- [Configuration Guide](configuration.md) - Source configuration and settings
- [Architecture Overview](architecture.md) - System design and integration patterns
- [Source Configuration](source-configuration.md) - Detailed API setup and management