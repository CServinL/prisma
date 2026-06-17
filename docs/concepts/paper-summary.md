# PaperSummary

## What it is

A **PaperSummary** is a [PaperMetadata](paper-metadata.md) enriched by `AnalysisAgent` via
an LLM call. It adds a summary, extracted key findings, and a methodology description to the
raw metadata.

`PaperSummary` objects are collected into an `AnalysisResult` which feeds into `ReportAgent`
to produce a [LiteratureReviewReport](literature-review-report.md).

`PaperSummary` is an in-memory intermediate — it is not stored on disk individually.
It appears inside `LiteratureReviewReport.content` and may be reflected in the final Note body.

## Fields

| Field | Type | Description |
|---|---|---|
| `title` | str | Paper title |
| `authors` | list[str] | Author names |
| `abstract` | str | Original abstract |
| `summary` | str | AI-generated concise summary |
| `key_findings` | list[str] | Key contributions extracted by the LLM |
| `methodology` | str | Research methodology description |
| `url` | str | Paper URL |
| `analysis_confidence` | float \| None | 0.0–1.0 score for the LLM analysis quality |
| `processing_time` | float \| None | Seconds taken to analyse |

## Relations

- Derived from [PaperMetadata](paper-metadata.md) by `AnalysisAgent`.
- Aggregated into `AnalysisResult` alongside other summaries.
- Feeds into `ReportAgent` → [LiteratureReviewReport](literature-review-report.md).

## Not yet implemented

`PaperSummary` is produced during `prisma review` only. During stream runs, papers are
written to Zotero without LLM analysis. Per-item analysis during stream runs is a future feature.
