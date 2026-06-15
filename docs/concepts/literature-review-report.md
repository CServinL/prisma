# LiteratureReviewReport

## What it is

A **LiteratureReviewReport** is the output of the full `prisma review` pipeline:
`SearchAgent` → `AnalysisAgent` → `ReportAgent`. It is a structured Markdown document
containing an executive summary, per-paper summaries, key findings, and bibliography.

Every report is saved as a [Note](note.md) in the vault. It is never ephemeral.

## Fields

| Field | Type | Description |
|---|---|---|
| `title` | str | Report title |
| `content` | str | Full formatted report in Markdown |
| `summary_count` | int | Number of papers summarised |
| `bibliography` | list[str] \| None | Bibliography entries |
| `executive_summary` | str \| None | Short overview |
| `metadata` | `ReportMetadata` | Generation timestamp, query, sources used, timing |

### ReportMetadata fields

| Field | Type | Description |
|---|---|---|
| `search_query` | str | Original search query |
| `sources_used` | list[str] | Academic sources queried (arxiv, semanticscholar, etc.) |
| `papers_analyzed` | int | Number of papers that went through `AnalysisAgent` |
| `total_processing_time` | float \| None | Wall-clock seconds for the full pipeline |

## Pipeline

```
POST /review  { topic }
  └── Job created (async)
       └── SearchAgent.search(topic)
            └── AnalysisAgent.analyze(papers)
                 └── ReportAgent.generate(summaries)
                      └── LiteratureReviewReport
                           └── saved as Note in vault/notes/
```

The server runs the pipeline in a `ThreadPoolExecutor` to avoid blocking the async event loop.
Status is polled via `GET /review/{job_id}`.

## Relations

- Produced by `ReportAgent` from a list of [PaperSummary](paper-summary.md)s.
- Always saved as a [Note](note.md).
- The [Job](job.md) tracks pipeline progress.

## Relevant axioms

> Every LiteratureReviewReport becomes a Note. See [Axiom 3](../ontologia.md).
