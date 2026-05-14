# Zotero Integration

Prisma splits Zotero access into two separate concerns: **reads** come from Zotero Desktop's local HTTP API, **writes** go through the Zotero Web API. This separation is deliberate — the local API is read-only by design, and Web API writes guarantee cloud sync.

## Read / Write Split

| Operation | Client | Requires |
|-----------|--------|----------|
| Search items | Local HTTP API (`WINDOWS_IP:23119`) | Zotero Desktop running |
| Get collections | Local HTTP API | Zotero Desktop running |
| Get item metadata | Local HTTP API | Zotero Desktop running |
| Create collection | Zotero Web API (`api.zotero.org`) | Internet + API key |
| Create item | Zotero Web API | Internet + API key |
| Add to collection | Zotero Web API | Internet + API key |
| Delete / modify | Zotero Web API | Internet + API key |

## Connection Modes

### `hybrid` (recommended)

- **Online reads**: local HTTP API (`WINDOWS_IP:23119`) — always used for reads regardless of internet status
- **Writes**: Zotero Web API — requires internet; queued offline
- **Offline**: reads still work via local HTTP; writes queued until next online startup

```yaml
sources:
  zotero:
    mode: "hybrid"
    server_url: "http://172.x.x.x:23119"   # Windows host IP from WSL (ZoteroConfig field name)
    api_key: "YOUR_API_KEY"
    library_id: "YOUR_USER_ID"
    library_type: "user"
```

### `local_api`

Read-only. No writes, no API key needed.

```yaml
sources:
  zotero:
    mode: "local_api"
    server_url: "http://172.x.x.x:23119"
```

## WSL Setup

Zotero Desktop runs on **Windows**, not inside WSL. Its local HTTP API is reachable from WSL via the Windows host IP:

```bash
# Find the Windows host IP
WINDOWS_IP=$(ip route show | grep default | awk '{print $3}')

# Test (Zotero Desktop must be open)
curl http://${WINDOWS_IP}:23119/api/
```

Use that IP in `local_server_url` in your config.

## Offline Write Queue

When Prisma tries to write to Zotero while offline, the operation is added to a local pending queue (`PendingWriteQueue`). On the next startup where `connectivity.is_online` is true and a Zotero client is available, the queue is automatically flushed.

Manual flush via CLI:
```bash
prisma sync
```

## Client Hierarchy

```
ZoteroClient.from_config(config)   ← factory, reads mode from config
       │
       ├─ HybridClient             ← mode: "hybrid"
       │      ├─ WebAPIClient      ← writes + preferred reads online
       │      └─ LocalAPIClient    ← fallback reads / offline reads
       │
       └─ LocalAPIClient           ← mode: "local_api"
```

All clients implement the same interface (`unified_client.py`):
- `search_items(query)` 
- `get_collections()`
- `save_items(items, collection_key)`
- `create_collection(name, parent_key)`

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
