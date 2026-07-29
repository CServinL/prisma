# Sources

Prisma uses a 1–5 star quality system to classify and prioritize academic sources. Higher-rated sources are searched first when `prefer_high_quality: true` (default).

## Source Registry

| Source | Stars | Access | Content | Notes |
|--------|-------|--------|---------|-------|
| `semanticscholar` | ⭐⭐⭐⭐⭐ | REST API | Papers, abstracts, citations | 214M+ papers; no key needed (rate-limited) |
| `arxiv` | ⭐⭐⭐⭐⭐ | REST API | Preprints, PDFs | Free; includes PDF links |
| `pubmed` | ⭐⭐⭐⭐⭐ | REST API | Biomedical papers | Free NCBI E-utilities; no key needed (rate-limited) |
| `openlibrary` | ⭐⭐⭐⭐ | REST API | Academic books | Internet Archive database |
| `googlebooks` | ⭐⭐⭐⭐ | REST API | Books, monographs | Rich publisher metadata, cover images |
| `ieee_xplore` | ⭐⭐⭐⭐ | REST API | Engineering/CS papers | **Requires an API key** (no anonymous mode); real rate limit unverified as of 2026-07-29, a conservative default is used until confirmed |
| `zotero` | ⭐⭐⭐ | Web API | Your library | Used for deduplication and stream discovery |

Each source (except `zotero`, which is the bookmark layer, not a discovery
source) enforces its own quota via `prisma.services.rate_limiter.RateLimiter`
-- a thread-safe token bucket, with defaults verified against each API's own
published policy. Override a source's rate limit, daily cap, or API key from
`config.toml` under `[search.source_overrides.<name>]` (see
`config.example.toml`) without touching code.

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

Sources are independent modules under `prisma/integrations/sources/`, each
implementing the `Source` interface (`.../sources/base.py`) and owning its
own `RateLimiter`. `SearchAgent` never needs to change:

1. Create `prisma/integrations/sources/<name>.py` implementing `Source`
   (`name`, `search()`, optionally `probe()`), using its own `RateLimiter`
   instance for that API's real published rate limit.
2. Register it in `build_sources()` in `prisma/integrations/sources/__init__.py`.
3. Add a `SourceMetadata` entry to `SOURCE_REGISTRY` in
   `prisma/storage/models/source_quality.py` (same key as `name`).
4. Add the name to `valid_sources` in `SearchConfig`
   (`prisma/utils/config.py`) and to `sources` in your config.

`tests/unit/integrations/sources/test_registry.py` checks these three
places (`build_sources()`, `SOURCE_REGISTRY`, `SearchConfig.valid_sources`)
stay consistent -- a mismatch used to silently degrade a source to the
lowest quality tier instead of raising (this happened for real with
`semanticscholar`/`semantic_scholar` before it was caught and fixed
2026-07-29).
