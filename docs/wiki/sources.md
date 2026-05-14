# Sources

Prisma uses a 1–5 star quality system to classify and prioritize academic sources. Higher-rated sources are searched first when `prefer_high_quality: true` (default).

## Source Registry

| Source | Stars | Access | Content | Notes |
|--------|-------|--------|---------|-------|
| `semanticscholar` | ⭐⭐⭐⭐⭐ | REST API | Papers, abstracts, citations | 214M+ papers; no key needed (rate-limited) |
| `arxiv` | ⭐⭐⭐⭐⭐ | REST API | Preprints, PDFs | Free; includes PDF links |
| `openlibrary` | ⭐⭐⭐⭐ | REST API | Academic books | Internet Archive database |
| `googlebooks` | ⭐⭐⭐⭐ | REST API | Books, monographs | Rich publisher metadata, cover images |
| `zotero` | ⭐⭐⭐ | Local HTTP / Web API | Your library | Used for deduplication and stream discovery |
| `academia_rss` | ⭐⭐ | RSS | Researcher feeds | Requires LLM extraction; not yet implemented |
| `academia_search` | ⭐ | HTML scraping | Academia.edu results | Framework present, parsing not implemented |
| `researchgate` | ⭐ | HTML scraping | ResearchGate results | Not implemented |

## Academic Validation

Every result — regardless of source — is validated before entering the pipeline.

### Required fields (configurable)

```yaml
validation:
  require_authors: true
  require_title: true
  require_venue_or_publisher: true
  min_authors: 1
  min_title_length: 10
  min_abstract_length: 0        # 0 = no requirement
  min_publication_year: 1990
  max_publication_year: 2030
  exclude_non_academic: true    # filters blogs, news, social media
```

### Confidence score

Each result receives a score between 0.0 and 1.0 based on:

- **Source quality (30%)** — star rating of the source
- **Required fields (40%)** — presence of title, authors, venue
- **Academic indicators (30%)** — journal keywords, abstract presence, citation signals

Results below `min_confidence_score` (default `0.3`) are discarded. The threshold for auto-saving to Zotero is separate (`min_confidence_for_save`, default `0.5`).

### Validation output (debug mode)

```
[ACCEPTED] arXiv paper confidence: 0.80
[REJECTED] Paper rejected: Missing venue/journal/publisher information
[REJECTED] Low confidence: 0.25
```

## Deduplication

Within a single search run, duplicates are removed by normalized title (lowercased, stripped). Across sources, a paper appearing in both arXiv and Semantic Scholar is kept once.

Against Zotero, deduplication is done by exact title match via a Zotero search query (limit 10 results per paper checked).

## Adding a New Source

1. Add a `SourceMetadata` entry to `SOURCE_REGISTRY` in `prisma/storage/models/source_quality.py`
2. Implement `_search_<source>(query, limit)` in `prisma/agents/search_agent.py`
3. Add the source name to the `elif` dispatch in `SearchAgent.search()`
4. Add it to `sources` in your config
