# SearchCriteria

## What it is

**SearchCriteria** is the query and filter configuration that drives `SearchAgent` on each
stream run. In the current implementation it is represented as a plain `query` string on
[Stream](stream.md) plus the `sources` and `default_limit` from `SearchConfig`.

A richer `SearchCriteria` model (tags, date filters, item types) is defined in the ontology
but not yet implemented in code.

## Fields (intended model)

| Field | Type | Description |
|---|---|---|
| `query` | str | Free-text search string |
| `tags` | list[str] | Must-have tags to filter results |
| `exclude_tags` | list[str] | Tags that disqualify a result |
| `item_types` | list[str] | Zotero item types to include (journalArticle, preprint, …) |
| `since_date` | date \| None | Only results published after this date |
| `max_results` | int | Upper bound per run (default from `SearchConfig.default_limit`) |

## Current implementation

`Stream.query` is the only search criterion stored. `SearchAgent` receives:
- `query` — the stream's query string
- `sources` — list of academic backends from `SearchConfig.sources` (e.g. `["arxiv"]`)
- `limit` — `SearchConfig.default_limit`

Preflight checks (`SearchAgent.preflight()`) verify which sources are reachable before the run.
Unreachable sources are listed in `StreamRunResult.sources_skipped`.

## Relations

- Owned by a [Stream](stream.md) (`Stream.query`).
- Consumed by `SearchAgent` to produce [PaperMetadata](paper-metadata.md).
