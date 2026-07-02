# Stream

## What it is

A **Stream** is a named, persistent search subscription. You define a topic and a query once;
the stream remembers it and re-runs automatically on a schedule, accumulating papers over time.

Each run adds new items to a [ZoteroCollection](zotero-collection.md) — it never removes
what was found in prior runs. The stream is the only entity in Prisma that drives automatic
discovery.

Streams are stored as `.yaml` files in `vault/streams/`. They are vault nodes (`NodeType.stream`)
but are deliberately not `.md` files — the knowledge graph indexer indexes only markdown, and stream metadata
should not pollute the knowledge graph.

## Fields

| Field | Type | Description |
|---|---|---|
| `slug` | str | URL-safe identifier, derived from title at creation |
| `title` | str | Human name |
| `query` | str | Search string sent to all search sources on each run |
| `description` | str \| None | Optional longer description |
| `status` | `StreamStatus` | `active` \| `paused` \| `archived` |
| `refresh_frequency` | `RefreshFrequency` | `daily` \| `weekly` \| `monthly` \| `manual` |
| `collection_key` | str \| None | Zotero collection key (set on first run) |
| `total_papers` | int | Cumulative count of items accepted into the collection |
| `last_updated` | datetime \| None | Timestamp of last completed run |
| `next_update` | datetime \| None | Scheduled timestamp for next automatic run |

## Status values

| Status | Meaning |
|---|---|
| `active` | Scheduler will run this stream when due |
| `paused` | Skipped by scheduler; can be resumed |
| `archived` | Permanently inactive; kept for history |

## Search sources

A stream run searches both internet sources and the Zotero library:

| Source type | Examples | Characteristic |
|---|---|---|
| Internet | arxiv, semanticscholar | Fresh papers, may already be in library |
| Library | Zotero search | Cheaper, results already enriched, shared cache |

The library is checked first when possible. A paper found in the library from a prior stream
is a valid candidate for a new stream — relevance evaluation is independent per stream.

## Lifecycle

1. **Create** — `POST /streams` sets status `active`, `next_update = None` (runs on first tick).
2. **Run** — `POST /streams/{slug}/run?force=true` or scheduler tick calls `_run_stream`.
3. **Per-candidate pipeline** — for each paper found (internet or library):
   - Gate 1: already in THIS collection? → skip
   - Step 2: bookmark in Zotero library if new
   - Gate 3: LLM relevance gate vs this stream's query
   - Step 4: add to this stream's collection if relevant
4. **Metadata update** — `total_papers`, `last_updated`, `next_update` updated after run.
5. **Pause / archive** — `PATCH /streams/{slug}` with `status`.
6. **Delete** — `DELETE /streams/{slug}` removes the `.yaml`; does not touch the ZoteroCollection.

## Relations

- Owns a [ZoteroCollection](zotero-collection.md) (one per stream, created on first run).
- Uses `query` to drive `SearchAgent` across internet and library sources.
- Accepted [ZoteroItem](zotero-item.md)s live in its collection.
- Does **not** create [Source](source.md) nodes — that is a deliberate user action.

## A new stream and an existing library

When a new stream is created, the Zotero library may already contain relevant papers
from other streams. The new stream treats library items as regular candidates:
- Each library item is evaluated by the new stream's LLM gate.
- If relevant, it is added to the new stream's collection.
- The item appears in multiple collections — this is expected and correct.

The stream's query may be totally different from the stream that originally discovered the
paper. The paper's relevance is determined fresh for this new perspective.

## Relevant axioms

> Streams expand, never contract. See [Axiom 2](../ontologia.md).
> Stream runs write to Zotero, not to the vault. See [Axiom 4](../ontologia.md).
> Bookmark-first. See [Axiom 12](../ontologia.md).
> Relevance is per-stream. See [Axiom 13](../ontologia.md).
> Library search is a first-class source. See [Axiom 14](../ontologia.md).
