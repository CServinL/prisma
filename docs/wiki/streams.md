# Research Streams

A Research Stream is a named, persistent research topic. Once created, it can be updated on
demand or on a schedule to discover new papers and save them to a dedicated Zotero collection.

Streams are API-only (no CLI) — see `docs/wiki/cli.md`'s "Moved to the API" section, which
`prisma streams`/`prisma review` were part of (removed 2026-07-27). All examples below are
`curl` against `prisma serve`'s API process (`:8765` by default); the same routes back the UI's
own Streams panel.

## Concept

```
Stream = title + search query + refresh frequency + Zotero collection
```

A stream is a real vault node (`streams/<slug>.yaml`, `type: stream`) — not a separate JSON
file. `VaultService` reads/writes it the same way as any Note/Source/Chat. Fields
(`prisma.storage.models.vault_models.Stream`): `query`, `description`, `status`
(`active`/`paused`/`archived`), `refresh_frequency` (`daily`/`weekly`/`monthly`/`manual`),
`collection_key` (the Zotero collection, created on first run), `total_papers`, `last_updated`,
`next_update`.

## Creating a Stream

```bash
curl -X POST http://127.0.0.1:8765/streams \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Neural Networks",
    "query": "neural networks transformer attention",
    "refresh_frequency": "weekly",
    "description": "Transformer-based architectures for vision and language"
  }'
```

The stream is saved immediately. Prisma attempts to create the Zotero collection at this point;
if offline, the creation is queued (`PendingWriteQueue`) and flushed on next online startup.

## Running a Stream

```bash
curl -X POST http://127.0.0.1:8765/streams/neural-networks/run
curl -X POST "http://127.0.0.1:8765/streams/neural-networks/run?force=true"  # ignore refresh_frequency, run now
```

`StreamScheduler` (`prisma/server/streams_routes.py`, a daemon thread in the API process) also
runs any active stream whose `next_update` is past, polling every 5 minutes — `force=true` is
only needed to run one out of schedule.

On each run:
1. External sources (arXiv, Semantic Scholar, etc.) are queried with the stream's search query.
2. Results are deduplicated against papers already in the stream/collection.
3. New papers are saved to the stream's Zotero collection (created if missing) via
   `ZoteroClient.add_paper()` — **no tags are applied** (`add_paper()` sends `tags: []`; the
   richer per-stream/methodology/recency tagging model is defined in the ontology only, not
   built — see [SmartTag](../concepts/smart-tag.md#not-yet-implemented)). This is different
   from `POST /review`'s `auto_save_papers` path, which does tag what it saves — see
   [Zotero Integration](zotero.md#smart-tags-applied-to-saved-items).
4. Stream state (`total_papers`, `last_updated`, `next_update`) is saved back to the vault node.

If Zotero is offline, the collection creation and item writes are queued in `PendingWriteQueue`
and applied on next online startup.

## Frequencies

| Value | Meaning |
|-------|---------|
| `daily` | Update every 24 hours |
| `weekly` | Update every 7 days (default) |
| `monthly` | Update every 30 days |
| `manual` | Never auto-update; only via an explicit `POST /streams/{slug}/run` |

## Listing, Status, and Pause/Archive

```bash
curl http://127.0.0.1:8765/streams                          # all streams
curl http://127.0.0.1:8765/streams/neural-networks           # one stream's metadata
curl http://127.0.0.1:8765/streams/neural-networks/view      # rendered vault node (for the UI)

# Pause/resume/archive via PATCH — status only, other fields (title/query/description/
# refresh_frequency) can be patched the same way
curl -X PATCH http://127.0.0.1:8765/streams/neural-networks \
  -H 'Content-Type: application/json' -d '{"status": "paused"}'
```

### Status values

| Status | Meaning |
|--------|---------|
| 🟢 `active` | Monitored and auto-updated |
| 🟡 `paused` | Exists but not auto-updated |
| 🔴 `archived` | Soft-deleted |

## Stream → Literature Review

A stream populates a Zotero collection over time. You can generate a review from that
collection via `POST /review` (see `docs/wiki/cli.md`'s API-route table):

```bash
curl -X POST http://127.0.0.1:8765/review \
  -H 'Content-Type: application/json' \
  -d '{"topic": "neural networks", "zotero_only": true}'
# poll: curl http://127.0.0.1:8765/review/{job_id}
```

Omit `zotero_only` (or set it `false`) to combine the stream's saved papers with a fresh
external-source search on the same query.

## Storage

A stream is a vault node at `streams/<slug>.yaml` (`VaultService`, flat-file, no database) —
back up/sync the vault the same way as the rest of it, nothing stream-specific to remember.
