# PaperMetadata

## What it is

**PaperMetadata** is the transient, normalised output of `SearchAgent` for a single academic
paper. It is never stored on disk. It exists only between the moment it is found (from any
source) and the moment it is either bookmarked as a [ZoteroItem](zotero-item.md) or discarded.

`BookMetadata` is the equivalent for books (open library, Google Books). Same role, different
fields (ISBN, publisher, edition).

## Sources

`PaperMetadata` can come from:

| Source | Type | Notes |
|---|---|---|
| arxiv | Internet | Preprints; `arxiv_id` populated |
| semanticscholar | Internet | Peer-reviewed; `doi` usually populated |
| openlibrary | Internet | Books only |
| googlebooks | Internet | Books only |
| Zotero library | Local cache | Already enriched; cheaper to query |

The library is a valid source. A `PaperMetadata` produced from a `ZoteroItem` has the same
role as one produced from arxiv — it enters the same per-candidate pipeline.

## Fields — PaperMetadata

| Field | Type | Description |
|---|---|---|
| `title` | str | Paper title |
| `authors` | list[str] | Author names |
| `abstract` | str | Abstract |
| `source` | str | Source identifier: `arxiv`, `semanticscholar`, `zotero`, etc. |
| `url` | str | Primary URL |
| `pdf_url` | str \| None | Direct PDF URL |
| `published_date` | str \| None | `YYYY-MM-DD` |
| `arxiv_id` | str \| None | arXiv identifier |
| `doi` | str \| None | DOI |
| `journal` | str \| None | Journal or venue |
| `connected_papers_url` | str \| None | Connected Papers exploration URL |

## Confidence filtering (pre-bookmark)

Before entering the stream's per-candidate pipeline, `SearchAgent` computes an
`academic_confidence_score` (0.0–1.0) based on title, abstract, venue, and author list.
Items below `min_confidence_score` (default 0.5) are discarded at the source — they never
reach the bookmark or relevance gate.

This filter is heuristic (no LLM). It catches clearly non-academic content (no abstract,
no authors, single-word titles). The LLM relevance gate (Gate 3) handles topic-specific
filtering for items that passed academic quality screening.

## Lifecycle in a stream run

```
SearchAgent.search(query, sources=[internet…, zotero])
    → PaperMetadata[]
        → Gate 0: cross-source dedup (same paper from arxiv + Zotero → one candidate)
        → Gate 1: collection check (already accepted by this stream?)
        → Step 2: bookmark (add to Zotero library if not already there)
        → Gate 3: LLM relevance gate (title + abstract vs stream.query)
        → Step 4: add to stream's ZoteroCollection
```

## Relations

- Produced by `SearchAgent.search()` from internet sources or Zotero library.
- Discarded if it fails academic confidence screening.
- Written to Zotero as a [ZoteroItem](zotero-item.md) at Step 2 (before relevance gate).
- Passed to `AnalysisAgent` to produce a [PaperSummary](paper-summary.md) during reviews.
