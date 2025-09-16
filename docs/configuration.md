# Configuration Guide

Prisma uses YAML configuration files with **quality-based source management** and **academic validation** to ensure high-quality, reproducible literature reviews.

## Basic Configuration Structure

```yaml
# prisma-config.yaml
sources:
  zotero:
    enabled: true
    mode: "local_api"
    server_url: "http://127.0.0.1:23119"
    default_collections: []

search:
  default_limit: 10
  # Quality-based source selection (1-5 stars)
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero']
  prefer_high_quality: true
  min_confidence_score: 0.3
  
  # Academic validation criteria
  validation:
    require_authors: true
    require_venue_or_publisher: true
    min_publication_year: 1990
    exclude_non_academic: true

llm:
  provider: 'ollama'
  model: 'llama3.1:8b'
  host: 'localhost:11434'

output:
  directory: './outputs'
  format: 'markdown'
```

## Source Quality Classification

Prisma uses a **1-5 star rating system** to classify academic sources by API quality and content curation:

### ⭐⭐⭐⭐⭐ **Five Star Sources** (Premium APIs + Curated Content)
- **semanticscholar**: AI-powered academic search with 214M+ papers
- **arxiv**: High-quality preprint server with comprehensive metadata

### ⭐⭐⭐⭐ **Four Star Sources** (Good APIs + Structured Data)  
- **openlibrary**: Internet Archive book database with millions of academic books
- **googlebooks**: Comprehensive book catalog with rich publisher metadata

### ⭐⭐⭐ **Three Star Sources** (Basic APIs)
- **zotero**: User's personal research library with local API access

### ⭐⭐ **Two Star Sources** (RSS/Basic Scraping)
- **academia_rss**: Individual researcher RSS feeds (requires LLM extraction)

### ⭐ **One Star Sources** (HTML Scraping Only)
- **academia_search**: Direct HTML scraping (requires LLM extraction)
- **researchgate**: Academic social network (requires LLM extraction)

## Search Configuration Options

### **Source Selection**
```yaml
search:
  # Recommended: Use high-quality sources (4-5 stars)
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks']
  
  # Alternative: Include all available sources
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero', 'academia_rss']
  
  # Quality controls
  prefer_high_quality: true          # Search 5-star sources first
  min_confidence_score: 0.3          # Minimum academic confidence (0.0-1.0)
```

### **Academic Validation**
```yaml
search:
  validation:
    # Required fields for academic content
    require_authors: true             # Must have at least one author
    require_title: true              # Must have a title  
    require_venue_or_publisher: true # Must have venue/journal/publisher
    
    # Minimum quality thresholds
    min_authors: 1                   # Minimum number of authors
    min_title_length: 10             # Minimum title length in characters
    min_abstract_length: 50          # Minimum abstract length (0 = no requirement)
    
    # Publication date filters
    require_publication_date: false  # Require publication date
    min_publication_year: 1990       # Minimum publication year
    max_publication_year: 2030       # Maximum publication year
    
    # Content quality filters
    exclude_non_academic: true       # Filter out blogs, news, social media
```

## Advanced Configuration Examples

### **High-Quality Research Configuration**
For comprehensive academic research prioritizing quality and reliability:

```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks']
  prefer_high_quality: true
  min_confidence_score: 0.5          # Higher threshold for quality
  
  validation:
    require_authors: true
    require_venue_or_publisher: true  
    min_abstract_length: 100         # Require substantial abstracts
    min_publication_year: 2000       # Focus on recent research
    exclude_non_academic: true
```

### **Comprehensive Coverage Configuration**  
For broader coverage including lower-quality sources:

```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero', 'academia_rss']
  prefer_high_quality: false        # Search all sources equally
  min_confidence_score: 0.2         # Lower threshold for inclusion
  
  validation:
    require_authors: true
    require_venue_or_publisher: false # Allow self-published content
    min_abstract_length: 0           # No abstract requirement
    exclude_non_academic: false     # Include broader content types
```

### **Books and Monographs Focus**
For research emphasizing academic books and comprehensive texts:

```yaml
search:
  sources: ['openlibrary', 'googlebooks', 'semanticscholar', 'arxiv']
  default_limit: 20                # More results for book searches
  
  validation:
    require_venue_or_publisher: true # Essential for books
    min_publication_year: 1980      # Include classic texts
```

## Source-Specific Configuration

### **Semantic Scholar (⭐⭐⭐⭐⭐)**
```yaml
# No additional configuration needed - works out of the box
# Optional: Add API key for higher rate limits
semantic_scholar:
  api_key: "your_api_key_here"  # Optional for higher limits
```

### **arXiv (⭐⭐⭐⭐⭐)**
```yaml
# No configuration needed - free API access
# Automatically includes:
# - Full paper metadata with abstracts
# - Direct PDF links
# - Subject classifications
```

### **Zotero (⭐⭐⭐)**
```yaml
sources:
  zotero:
    enabled: true
    mode: "local_api"              # Use Zotero Local API
    server_url: "http://127.0.0.1:23119"
    default_collections: []       # Search all collections
    include_notes: false          # Exclude notes from search
```

## Quality Control Features

### **Automatic Quality Assessment**
Prisma automatically scores each paper/book on academic quality:

- **Source Quality (30%)**: Based on source star rating
- **Required Fields (40%)**: Title, authors, venue presence  
- **Academic Indicators (30%)**: Journal keywords, abstracts, citations

### **Validation Reporting**
The system provides detailed feedback on content filtering:

```
[ACCEPTED] arXiv paper confidence: 0.80
[REJECTED] Paper rejected: Missing venue/journal/publisher information
[REJECTED] Low confidence: 0.25
```

### **Quality Summary**
After each search, view source performance:

```
📊 Search Quality Summary:
   Total Results: 15 papers, 8 books
   Sources Used:
   • semanticscholar: ⭐⭐⭐⭐⭐ - 8P + 0B
   • arxiv: ⭐⭐⭐⭐⭐ - 5P + 0B  
   • openlibrary: ⭐⭐⭐⭐ - 0P + 6B
   • googlebooks: ⭐⭐⭐⭐ - 0P + 2B
```

## Migration from Legacy Configuration

### **Old Format** (Pre-Quality System)
```yaml
search:
  sources: ['arxiv', 'zotero', 'pubmed', 'google_scholar']
```

### **New Format** (Quality-Based)
```yaml
search:
  sources: ['semanticscholar', 'arxiv', 'openlibrary', 'googlebooks', 'zotero']
  prefer_high_quality: true
  min_confidence_score: 0.3
  validation:
    require_authors: true
    require_venue_or_publisher: true
```

The quality-based system ensures **higher reliability**, **better academic content**, and **improved research outcomes** through intelligent source prioritization and validation.
  parallel_agents: 4
  model: "llama3.1:8b"
```

### CLI Interface
```bash
# Submit new job
prisma submit --config ./configs/edge-ai-review.yaml

# Check job status
prisma status --job edge-ai-review-2024

# List all jobs
prisma list

# View logs
prisma logs --job edge-ai-review-2024 --tail

# Cancel running job
prisma cancel --job edge-ai-review-2024
```

### File System Structure
```
prisma-workspace/
├── configs/           # User configuration files
├── jobs/             # Active job tracking
├── results/          # Generated reports and artifacts
├── logs/             # Execution logs
├── cache/            # API response cache
└── models/           # Local model storage
```

### Benefits of Config-Driven Approach
- **Version control**: Configurations can be tracked in git
- **Reproducibility**: Exact parameters preserved for replication
- **Batch processing**: Multiple jobs easily queued
- **Automation**: Integration with CI/CD pipelines
- **Simplicity**: No web server dependencies or UI complexity