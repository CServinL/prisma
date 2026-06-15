# E2E Tests

End-to-end tests that exercise complete flows against real services.
All tests in this directory are automatically skipped when dependencies are absent.

## Dependencies

| Dependency | Required for |
|---|---|
| Internet access (arxiv reachable) | All stream tests |
| Ollama at `localhost:11434` | Review flow, source evaluation |
| `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` | Zotero collection creation checks |
| Zotero Desktop at `localhost:23119` | Local-API collection checks |

## Test files

### `test_review_flow.py`

Full literature review via the CLI: search → analysis → output file.

| Test | What it verifies |
|---|---|
| `test_review_produces_output_file` | CLI `prisma review` exits 0 and writes an `.md` output |

---

### `test_stream_flow.py` *(planned)*

Stream lifecycle from creation through repeated runs and source evaluation.

| # | Test | Dependencies | What it verifies |
|---|---|---|---|
| 1 | `test_create_stream_returns_slug` | internet | POST /streams returns a stream with a slug and active status |
| 2 | `test_run_stream_finds_papers` | internet | POST /streams/{slug}/run returns papers_found > 0 for a real query |
| 3 | `test_run_stream_saves_sources_to_vault` | internet | Sources appear in GET /notes after a run |
| 4 | `test_rerun_stream_deduplicates` | internet | Second run on same stream saves 0 duplicates |
| 5 | `test_rerun_with_force_finds_new_sources` | internet | ?force=true reruns even before next_update |
| 6 | `test_zotero_collection_created_on_run` | internet + Zotero local API | A collection named after the stream exists in Zotero after first run |
| 7 | `test_stream_metadata_updated_after_run` | internet | `total_papers`, `last_updated`, `next_update` are all set post-run |
| 8 | `test_source_evaluation_quality` | internet | Saved papers have title, authors, abstract; abstract is non-trivial |
| 9 | `test_source_confidence_above_threshold` | internet | All saved papers have confidence_score >= config `min_confidence_score` |
| 10 | `test_delete_stream_removes_from_listing` | — | DELETE /streams/{slug} → stream no longer in GET /streams |

## Skip logic

`conftest.py` applies a module-wide skip when Ollama and Zotero Web API creds are
absent. Individual tests that also need Zotero local API use a `pytest.mark.skipif`
on `_zotero_local_reachable()`.

## Running

```bash
bash tests-sets/run-e2e.sh
# or just the stream suite:
.venv/bin/python -m pytest tests-sets/e2e/test_stream_flow.py -v
```
