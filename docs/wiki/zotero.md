# Zotero Integration

Prisma talks to Zotero via its **Web API only** (`api.zotero.org`) — both reads and
writes. There is no local Zotero Desktop integration; an earlier
local-API-primary architecture (ADR-008) was reversed once the server started
running on a separate machine from the user's own — see ADR-008's follow-up
section for the full story. Until 2026-07-28 a second, hand-rolled client
(`services/zotero.py`) still carried a dormant local-Zotero-Desktop-SQLite
read path left over from that era; it has since been deleted, so this claim
is now literally true of every code path, not just the primary one.

## Configuration

```toml
[sources.zotero]
enabled = true
api_key = "YOUR_API_KEY"        # https://www.zotero.org/settings/keys/new
library_id = "YOUR_USER_ID"     # https://www.zotero.org/settings/keys
library_type = "user"           # "user" | "group"
```

For a deployment where config.toml itself isn't a safe place for a real secret
or identifying info (e.g. rendered into a Kubernetes ConfigMap, which isn't
encrypted at rest), use `api_key_env`/`library_id_env` instead — same pattern
as `llm.api_key_env`/`chat.api_key_env`:

```toml
[sources.zotero]
enabled = true
api_key_env = "ZOTERO_API_KEY"        # takes priority over api_key when set
library_id_env = "ZOTERO_LIBRARY_ID"  # takes priority over library_id when set
library_type = "user"
```

Both then only need to exist as environment variables — sourced from a K8s
Secret, for example — and never touch the config file at all.

## Connectivity

`integrations/zotero/client.py::check_web_api_reachable()` is the canonical
live-reachability check — validates the configured library is actually
reachable with these credentials, not just that a key is present. Backs
`ZoteroClient.status()`'s `reachable` field (surfaced in the UI's status
panel) and `prisma status`.

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

There is a single Zotero client: `integrations/zotero/client.py::ZoteroClient`,
built via `ZoteroClient.from_config(config)`, wrapping `pyzotero` and reading/
writing the typed `ZoteroItem`/`ZoteroCollection` models in
`storage/models/zotero_models.py`.

Until 2026-07-28 there were two independent implementations: this one, and a
hand-rolled `urllib.request` client in `services/zotero.py` (with its own
flatter data model and a 429-retry loop duplicated three times in the same
file) used by `server/app.py`, `services/stream_runner.py`, and
`services/dedup.py`. There was also a `unified_client.py` facade in front of
this file that did `hasattr`-based capability dispatch onto a single,
statically-known backend — ceremonial even before the consolidation, since no
second backend existed to dispatch to. Both were merged into this one file;
all callers now depend on `ZoteroClient` directly.

`agents/zotero_agent.py::ZoteroAgent` is a legitimate third layer on top —
adds search-criteria filtering/caching (`search_papers`,
`get_academic_papers`, `get_recent_papers`) — not a duplicate client, it only
ever talks to `ZoteroClient`.

## Smart Tags Applied to Saved Items

Only via `POST /review`'s `auto_save_papers` config flag (`coordinator.py`) — a paper that
passes the confidence threshold there gets tagged:

| Tag | Example | Meaning |
|-----|---------|---------|
| `Prisma-Discovery` | — | Added by Prisma |
| `Confidence-X.XX` | `Confidence-0.82` | Academic confidence score |
| `Source-<name>` | `Source-arxiv` | Where the paper was found |
| `Topic-<topic>` | `Topic-neural networks` | The search topic |

**Research Streams do not apply any tags** (`stream_runner.py` saves via
`ZoteroClient.add_paper()`, which sends `tags: []`) — the richer per-stream/methodology/
recency tagging model sketched below is defined in the ontology only, not built. See
[SmartTag](../concepts/smart-tag.md#not-yet-implemented).

| Tag (not implemented) | Meaning |
|-----|---------|
| `prisma-<stream-id>` | Identifies the stream |
| `prisma-auto` | Added automatically |
| `recent` | Published in last 2 years |
| `year-YYYY` | Publication year |
| `survey` / `empirical` / `theoretical` | Methodology (auto-detected) |
