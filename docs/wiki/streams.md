# Research Streams

A Research Stream is a named, persistent research topic. Once created, it can be updated on demand or on a schedule to discover new papers and save them to a dedicated Zotero collection.

## Concept

```
Stream = name + search query + frequency + Zotero collection + smart tags
```

Stream state is stored locally in `data/research_streams.json`. Each stream tracks:
- Paper count and IDs found so far
- Last update time and next scheduled update
- Zotero collection key (created on first update)
- Update history

## Creating a Stream

```bash
prisma streams create "Neural Networks" "neural networks transformer attention" \
  --frequency weekly \
  --description "Transformer-based architectures for vision and language" \
  --parent-collection "AI Research"
```

The stream is saved immediately. No Zotero collection is created yet — that happens on first `update`.

## Updating Streams

```bash
prisma streams update --all           # all active streams
prisma streams update neural-networks # specific stream by ID
prisma streams update --all --force   # ignore frequency, update now
```

On each update:
1. External sources (arXiv, Semantic Scholar, etc.) are queried with the stream's search query
2. Results are deduplicated against papers already in the stream
3. New papers are saved to the stream's Zotero collection (created if missing)
4. Smart tags are applied
5. Stream state (paper count, last updated, next update) is saved

If Zotero is offline, the collection creation and item writes are queued in `PendingWriteQueue` and applied on next online startup.

## Frequencies

| Value | Meaning |
|-------|---------|
| `daily` | Update every 24 hours |
| `weekly` | Update every 7 days (default) |
| `monthly` | Update every 30 days |
| `manual` | Never auto-update; only on explicit `update` command |

## Listing and Monitoring

```bash
prisma streams list               # all streams with status
prisma streams list --status active
prisma streams info neural-networks   # full detail for one stream
prisma streams summary            # overview counts
```

### Status values

| Status | Meaning |
|--------|---------|
| 🟢 `active` | Monitored and auto-updated |
| 🟡 `paused` | Exists but not auto-updated |
| 🔴 `archived` | Soft-deleted |

## Stream → Literature Review

A stream populates a Zotero collection over time. You can generate a review from that collection:

```bash
prisma review "neural networks" --zotero-only --output nn_review.md
```

Or combine stream + external sources:

```bash
prisma review "neural networks" --output nn_review.md
```

## Storage

Stream data is in `data/research_streams.json` relative to the working directory. This file is gitignored. Back it up if you want to preserve stream history across machines.
