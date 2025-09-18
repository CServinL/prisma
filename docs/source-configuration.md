# Source Configuration Guide

Prisma's **quality-based source management system** ensures high-quality academic content by rating sources from 1-5 stars and applying rigorous academic validation.

## 🌟 Source Quality Classification

### ⭐⭐⭐⭐⭐ **Five Star Sources** (Premium APIs + Curated Content)

#### **Semantic Scholar** 
- **Access**: Free JSON API with optional API key for higher limits
- **Content**: 214M+ papers, 2.4B+ citations, 79M+ authors
- **Strengths**: AI-powered search, citation analysis, author disambiguation
- **Rate Limits**: 1000 req/sec public, higher with API key
- **Configuration**: None required, works out of the box

```yaml
# Optional: Add API key for higher rate limits
semantic_scholar:
  api_key: "your_api_key_here"
```

#### **arXiv**
- **Access**: Free XML API, no authentication required
- **Content**: High-quality preprints in STEM fields
- **Strengths**: Excellent metadata, direct PDF access, real-time updates
- **Rate Limits**: Reasonable limits, no hard restrictions
- **Configuration**: None required

### ⭐⭐⭐⭐ **Four Star Sources** (Good APIs + Structured Data)

#### **Open Library**
- **Access**: Free JSON API from Internet Archive
- **Content**: Millions of books including academic texts
- **Strengths**: ISBN lookups, subject classifications, full metadata
- **Rate Limits**: Reasonable API limits
- **Configuration**: None required

#### **Google Books**
- **Access**: JSON API with daily quotas
- **Content**: Comprehensive book catalog from publishers
- **Strengths**: Rich metadata, preview links, cover images
- **Rate Limits**: Daily quotas apply
- **Configuration**: Optional API key for higher quotas

```yaml
# Optional: Add API key for higher quotas
google_books:
  api_key: "your_google_api_key"
```

### ⭐⭐⭐ **Three Star Sources** (Basic APIs)

#### **Zotero Local Database**
- **Access**: Local API through Zotero desktop application
- **Content**: User's personal research library
- **Strengths**: No rate limits, user-curated content, full control
- **Limitations**: Limited to existing collection
- **Configuration**: Requires Zotero desktop with Local API

```yaml
sources:
  zotero:
    enabled: true
    mode: "local_api"
    server_url: "http://127.0.0.1:23119"
    default_collections: []  # Search all collections
```

### ⭐⭐ **Two Star Sources** (RSS/Basic Scraping)

#### **Academia.edu RSS Feeds**
- **Access**: Individual researcher RSS feeds
- **Content**: Papers, theses, presentations from specific researchers
- **Strengths**: Real-time updates, XML structure
- **Limitations**: Requires knowing usernames, limited metadata
- **Configuration**: Requires LLM for content extraction

```yaml
# Note: Requires LLM extraction (not yet implemented)
academia_rss:
  enabled: false  # Enable when LLM extraction is ready
  researchers: ["username1", "username2"]  # Specific researchers to follow
```

### ⭐ **One Star Sources** (HTML Scraping Only)

#### **Academia.edu Search** & **ResearchGate**
- **Access**: HTML scraping of search results
- **Content**: Academic papers, theses, datasets
- **Strengths**: Large academic repositories
- **Limitations**: No APIs, anti-bot measures, requires LLM extraction
- **Configuration**: Not recommended due to ToS and reliability issues

```yaml
# Not recommended - use Semantic Scholar instead
academia_search:
  enabled: false  # Disabled due to scraping limitations
researchgate:
  enabled: false  # Disabled due to ToS concerns
```

## 📊 Source Selection Strategies

### **High-Quality Research** (Recommended)
Prioritize reliability and academic rigor:

```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks']
  prefer_high_quality: true
  min_confidence_score: 0.5
  
  validation:
    require_authors: true
    require_venue_or_publisher: true
    min_abstract_length: 100
    min_publication_year: 2000
```

**Best for**: Systematic reviews, meta-analyses, high-impact research

### **Comprehensive Coverage**
Include broader sources for maximum coverage:

```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero']
  prefer_high_quality: false
  min_confidence_score: 0.2
  
  validation:
    require_authors: true
    require_venue_or_publisher: false
    exclude_non_academic: false
```

**Best for**: Exploratory research, interdisciplinary topics

### **Books and Monographs Focus**
Emphasize academic books and comprehensive texts:

```yaml
search:
  sources: ['openlibrary', 'googlebooks', 'semanticscholar', 'arxiv']
  default_limit: 20
  
  validation:
    require_venue_or_publisher: true
    min_publication_year: 1980  # Include classic texts
```

**Best for**: Historical research, foundational knowledge reviews

### **Personal Library Integration**
Combine external sources with your Zotero library:

```yaml
search:
  sources: ['zotero', 'semanticscholar', 'arxiv', 'openlibrary']
  prefer_high_quality: true
  
sources:
  zotero:
    enabled: true
    mode: "local_api"
    default_collections: ["Current Research", "To Read"]
```

**Best for**: Building on existing research, avoiding duplicates

## 🛡️ Academic Validation Configuration

### **Validation Criteria**

```yaml
search:
  validation:
    # Required fields
    require_authors: true             # Must have at least one author
    require_title: true              # Must have a title
    require_venue_or_publisher: true # Must have journal/conference/publisher
    
    # Quality thresholds
    min_authors: 1                   # Minimum author count
    min_title_length: 10             # Minimum title length (chars)
    min_abstract_length: 50          # Minimum abstract length (0 = disabled)
    
    # Publication filters
    require_publication_date: false  # Require publication date
    min_publication_year: 1990       # Earliest acceptable year
    max_publication_year: 2030       # Latest acceptable year
    
    # Content quality
    exclude_non_academic: true       # Filter blogs, news, social media
```

### **Confidence Scoring**

Papers are scored 0.0-1.0 based on:
- **Source Quality (30%)**: Higher star rating = higher score
- **Required Fields (40%)**: Title, authors, venue presence
- **Academic Indicators (30%)**: Journal keywords, abstracts, citations

### **Exclusion Keywords**

Automatically filtered content types:
- Blog posts, news articles, social media
- Advertisements, spam, test documents
- Non-academic web content

### **Academic Venue Keywords**

Boost confidence for content from:
- Journals, conferences, symposiums
- Workshops, proceedings, reviews
- Transactions, letters, communications

## 🔧 Migration Guide

### **From Legacy Configuration**

**Old Format:**
```yaml
search:
  sources: ['arxiv', 'zotero', 'pubmed']
```

**New Format:**
```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero']
  prefer_high_quality: true
  min_confidence_score: 0.3
  validation:
    require_authors: true
    require_venue_or_publisher: true
```

### **Benefits of Migration**

1. **Higher Quality Results**: Academic validation filters non-scholarly content
2. **Better Source Coverage**: Access to millions more papers and books
3. **Reliability**: Prioritizes stable APIs over scraping
4. **Performance**: Faster searches with better rate limits
5. **Reproducibility**: Consistent results across runs

## 📈 Performance Optimization

### **Quality-First Search**
Sources are automatically ordered by quality rating:
1. 5-star sources searched first (fastest, most reliable)
2. 4-star sources for comprehensive coverage
3. 3-star sources for personal libraries
4. 2-1 star sources only when needed

### **Rate Limit Management**
- Built-in rate limiting for all sources
- Respectful delays between requests
- Automatic retry logic for transient failures
- Optional API keys for higher limits

### **Validation Performance**
- Fast rejection of low-quality content
- Confidence scoring prevents LLM processing of poor content
- Duplicate detection across sources
- Minimal overhead for high-quality sources

The quality-based system ensures **reliable academic content** while maintaining **high performance** and **comprehensive coverage** of scholarly literature.