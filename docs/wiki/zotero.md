# Zotero Integration

Prisma talks to Zotero via its **Web API only** (`api.zotero.org`) — both reads and
writes. There is no local Zotero Desktop integration; an earlier
local-API-primary architecture (ADR-008) was reversed once the server started
running on a separate machine from the user's own — see ADR-008's follow-up
section for the full story.

## Configuration

```toml
[sources.zotero]
enabled = true
api_key = "YOUR_API_KEY"        # https://www.zotero.org/settings/keys/new
library_id = "YOUR_USER_ID"     # https://www.zotero.org/settings/keys
library_type = "user"           # "user" | "group"
```

## Connectivity

`services/zotero.py::check_web_api_reachable()` is the canonical live-reachability
check — validates the configured library is actually reachable with these
credentials, not just that a key is present. Backs `ZoteroService.status()`'s
`reachable` field (surfaced in the UI's status panel), `prisma zotero status`,
and `prisma status`.

## Offline Write Queue

When Prisma tries to write to Zotero while offline, the operation is added to
a local pending queue (`PendingWriteQueue`, `data/pending_writes.json`). On
the next startup where `connectivity.is_online` is true and a Zotero client
is available, the queue is automatically flushed.

Manual flush via the API:
```bash
curl -X POST http://127.0.0.1:8765/zotero/sync-pending
```

## Client Hierarchy

```
ZoteroClient.from_config(config)   ← facade (unified_client.py)
       │
       └─ client.py's Web API client (pyzotero-backed)
```

`ZoteroClient` is a thin wrapper — there's only one backend to route to now.
Kept as a facade (rather than using `client.py` directly) because
`ResearchStreamManager` and other callers depend on its `from_config()`/
`client_type`/`client_info` surface.

## Smart Tags Applied to Saved Items

When Prisma saves a paper to Zotero it applies:

| Tag | Example | Meaning |
|-----|---------|---------|
| `Prisma-Discovery` | — | Added by Prisma |
| `Confidence-X.XX` | `Confidence-0.82` | Academic confidence score |
| `Source-<name>` | `Source-arxiv` | Where the paper was found |
| `Topic-<topic>` | `Topic-neural networks` | The search topic |

For research streams, additional smart tags are applied:

| Tag | Meaning |
|-----|---------|
| `prisma-<stream-id>` | Identifies the stream |
| `prisma-auto` | Added automatically |
| `recent` | Published in last 2 years |
| `year-YYYY` | Publication year |
| `survey` / `empirical` / `theoretical` | Methodology (auto-detected) |
