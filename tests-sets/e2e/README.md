# E2E Tests

End-to-end tests that exercise complete flows against real services.
All tests in this directory are automatically skipped when dependencies are absent.

## Dependencies

| Dependency | Required for |
|---|---|
| Internet access (arxiv reachable) | All stream tests, review flow |
| Ollama at `localhost:11434` | Review flow, source evaluation |
| `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` (or configured in `~/.config/prisma/config.toml`) | Zotero collection creation checks |

Prisma only talks to Zotero via its Web API — there is no local Zotero
Desktop dependency (see ADR-008's follow-up).

## Test files

### `test_review_flow.py`

Full literature review via the API: search → analysis → output file.

| Test | What it verifies |
|---|---|
| `test_review_produces_output_file` | `POST /review` completes and writes an `.md` output file |

---

### `test_stream_flow.py`

Stream lifecycle from creation through repeated runs and source evaluation,
against the real app (`TestClient`) and the real Zotero Web API.

| Test | What it verifies |
|---|---|
| `test_create_stream_returns_slug` | `POST /streams` returns a stream with a slug and active status |
| `test_run_stream_finds_papers` | `POST /streams/{slug}/run` finds and saves real papers from arxiv |
| `test_run_stream_creates_zotero_collection` | A collection named after the stream exists in Zotero after the first run |
| `test_run_stream_saves_items_to_zotero` | The Zotero collection's item count matches `papers_saved` |
| `test_rerun_stream_deduplicates` | A second run saves 0 duplicates |
| `test_rerun_with_force_bypasses_schedule` | An unforced rerun reports "not due"; `?force=true` bypasses it |
| `test_stream_metadata_updated_after_run` | `total_papers`, `last_updated`, `next_update` are all set post-run |
| `test_zotero_items_have_required_fields` | Saved items have title, authors, and a non-trivial abstract |
| `test_zotero_items_above_confidence_threshold` | Saved items passed `SearchAgent`'s confidence filter |
| `test_delete_stream_removes_from_listing` | `DELETE /streams/{slug}` removes it from `GET /streams` |

## Skip logic

`conftest.py` applies a module-wide skip when Ollama and Zotero Web API creds
are absent (stream flow tests are exempted — they manage their own
internet-only skip gate directly in `test_stream_flow.py`).

## Running

```bash
bash tests-sets/run-e2e.sh
# or just the stream suite:
.venv/bin/python -m pytest tests-sets/e2e/test_stream_flow.py -v
```
