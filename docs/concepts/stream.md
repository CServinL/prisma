# Stream

## What it is

A **Stream** is a named, persistent search subscription. You define a topic and a query once;
the stream remembers it and re-runs automatically on a schedule, accumulating papers over time.

Each run adds new items to a [ZoteroCollection](zotero-collection.md) — it never removes
what was found in prior runs. The stream is the only entity in Prisma that drives automatic
discovery.

Streams are stored as `.yaml` files in `vault/streams/`. They are vault nodes (`NodeType.stream`)
but are deliberately not `.md` files — Graphify indexes only markdown, and stream metadata
should not pollute the knowledge graph.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier, derived from title at creation |
| `title` | str | Human name |
| `query` | str | Search string sent to `SearchAgent` on each run |
| `description` | str \| None | Optional longer description |
| `status` | `StreamStatus` | `active` \| `paused` \| `archived` |
| `refresh_frequency` | `RefreshFrequency` | `daily` \| `weekly` \| `monthly` \| `manual` |
| `collection_key` | str \| None | Zotero collection key (set on first run) |
| `total_papers` | int | Cumulative count of items found across all runs |
| `last_updated` | datetime \| None | Timestamp of last completed run |
| `next_update` | datetime \| None | Scheduled timestamp for next automatic run |

## Status values

| Status | Meaning |
|---|---|
| `active` | Scheduler will run this stream when due |
| `paused` | Skipped by scheduler; can be resumed |
| `archived` | Permanently inactive; kept for history |

## Lifecycle

1. **Create** — `POST /streams` sets status `active`, `next_update = None` (runs immediately on first tick).
2. **Run** — `POST /streams/{slug}/run?force=true` or scheduler tick calls `_run_stream`.
3. **Result** — papers added to `ZoteroCollection`; `total_papers`, `last_updated`, `next_update` updated.
4. **Pause / archive** — `PATCH /streams/{slug}` with `status`.
5. **Delete** — `DELETE /streams/{slug}` removes the `.yaml`; does not touch the ZoteroCollection.

## Relations

- Owns a [ZoteroCollection](zotero-collection.md) (one per stream, created on first run).
- Uses [SearchCriteria](search-criteria.md) / query string to drive `SearchAgent`.
- Discovered [ZoteroItem](zotero-item.md)s live in its collection.
- Does **not** create [Source](source.md) nodes — that is a deliberate user action.

## Relevant axioms

> Streams expand, never contract. See [Axiom 2](../ontologia.md).
> Stream runs write to Zotero, not to the vault. See [Axiom 4](../ontologia.md).

## Not yet implemented

- `collection_key` is a field but `_run_stream` does not yet create the ZoteroCollection
  or add items. This violates Axiom 4. Tracking in `Not yet implemented` section of ontologia.md.
