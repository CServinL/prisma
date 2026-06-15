# PaperMetadata

## What it is

**PaperMetadata** is the raw, normalised output of `SearchAgent` for a single academic paper.
It is an intermediate object — never stored on disk directly. It is either:
- Written to Zotero as a [ZoteroItem](zotero-item.md) during a stream run, or
- Passed to `AnalysisAgent` → `ReportAgent` during a literature review.

`BookMetadata` is the equivalent for books (open library, Google Books). It has the same role
but different fields (ISBN, publisher, edition).

## Fields — PaperMetadata

| Field | Type | Description |
|---|---|---|
| `title` | str | Paper title |
| `authors` | list[str] | Author names |
| `abstract` | str | Abstract |
| `source` | str | Source database: `arxiv`, `semanticscholar`, `pubmed`, etc. |
| `url` | str | Primary URL |
| `pdf_url` | str \| None | Direct PDF URL |
| `published_date` | str \| None | `YYYY-MM-DD` |
| `arxiv_id` | str \| None | arXiv identifier |
| `doi` | str \| None | DOI |
| `journal` | str \| None | Journal or venue |
| `connected_papers_url` | str \| None | Connected Papers exploration URL |

## Confidence filtering

Before a `PaperMetadata` is written to Zotero, `SearchAgent` computes an
`academic_confidence_score` (0.0–1.0). Items below `min_confidence_score` (default 0.5) are
discarded. Only items that pass this gate become [ZoteroItem](zotero-item.md)s.

The score is not persisted to Zotero or the vault today — see `Not yet implemented` in
[ontologia.md](../ontologia.md).

## Relations

- Produced by `SearchAgent.search()` in response to a [Stream](stream.md) query.
- Passed to `AnalysisAgent` to produce a [PaperSummary](paper-summary.md) during reviews.
- If it passes confidence filtering, written to Zotero as a [ZoteroItem](zotero-item.md).
