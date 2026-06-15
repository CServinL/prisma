# Test Sets

Tests are organized by what they need to run, not by layer.

| Set | Dependencies | Run |
|-----|-------------|-----|
| `mocked/` | Nothing — all boundaries mocked | `bash tests-sets/run-mocked.sh` |
| `local-zotero/` | Zotero Desktop at `localhost:23119` | `bash tests-sets/run-local-zotero.sh` |
| `web-api/` | `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` env vars | `bash tests-sets/run-web-api.sh` |
| `e2e/` | Internet + Ollama + Zotero Web API creds | `bash tests-sets/run-e2e.sh` |

`bash tests-sets/run-all.sh` runs everything; missing dependencies produce clean skips.

See [`e2e/README.md`](e2e/README.md) for the full index of E2E tests (existing + planned).

## Rule

**Only our code is tested.** Mocked and local-zotero sets do not assert on Pydantic
validation, stdlib behavior, or that Zotero's API returns correct data. Exception: e2e
tests verify whole flows end-to-end and deliberately use real services.

## Secrets

Secrets are never committed. `web-api/conftest.py` builds a temp config from
`ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID`. The `*.yaml` files in this directory hold
placeholders only.
