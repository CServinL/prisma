# Job

## What it is

A **Job** is an async server-side task tracking a `prisma review` pipeline run.
Because the full pipeline (search → analysis → report) is synchronous and can take
minutes, the server offloads it to a `ThreadPoolExecutor` and returns a `job_id`
immediately. The client polls until the job is done.

## Fields

| Field | Type | Description |
|---|---|---|
| `job_id` | str | UUID assigned at creation |
| `status` | str | `pending` \| `running` \| `done` \| `error` |
| `papers_analyzed` | int | Papers that completed analysis |
| `authors_found` | int | Unique authors across all analyzed papers |
| `output_file` | str | Path to the saved `.md` report file |
| `content_html` | str | HTML-rendered report content (for the UI) |
| `errors` | list[str] | Any errors encountered during the run |

## Lifecycle

```
POST /review  →  job_id (202 Accepted)
  │
  │  ThreadPoolExecutor
  ▼
  _run_review()
    SearchAgent → AnalysisAgent → ReportAgent → LiteratureReviewReport
    result saved as Note in vault
    job status updated to "done"

GET /review/{job_id}  →  poll until status == "done" or "error"
```

## Relations

- Created by `POST /review`.
- On completion, produces a [LiteratureReviewReport](literature-review-report.md)
  saved as a [Note](note.md).
- Jobs are in-memory only — they do not survive server restart.
