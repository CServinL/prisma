# Test Sets

Tests are organized by what they need to run, not by layer.

| Set | Dependencies | Run |
|-----|-------------|-----|
| `mocked/` | Nothing — all boundaries mocked | `bash tests-sets/run-mocked.sh` |
| `web-api/` | `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` env vars | `bash tests-sets/run-web-api.sh` |
| `e2e/` | Internet + Ollama + Zotero Web API creds | `bash tests-sets/run-e2e.sh` |

`bash tests-sets/run-all.sh` runs everything; missing dependencies produce clean skips.

See [`e2e/README.md`](e2e/README.md) for the full index of E2E tests (existing + planned).

Removed 2026-07-27: `local-zotero/` (tested the local-API/hybrid/desktop-connector
clients against a real running Zotero Desktop) — prisma only talks to Zotero via
its Web API now, there is no local-API client left to test.

## Rule

**Only our code is tested.** The mocked set does not assert on Pydantic
validation, stdlib behavior, or that Zotero's API returns correct data. Exception: e2e
tests verify whole flows end-to-end and deliberately use real services.

## Secrets

Secrets are never committed. `web-api/conftest.py` builds a temp config from
`ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID`. The `*.yaml` files in this directory hold
placeholders only.
