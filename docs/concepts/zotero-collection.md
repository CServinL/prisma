# ZoteroCollection

## What it is

A **ZoteroCollection** is a folder in Zotero that groups the items discovered by one stream.
Each stream owns exactly one collection. The collection is the canonical, durable store for
everything a stream has ever found.

The collection is created in Zotero on the first run of a stream. Its key is stored on the
stream as `Stream.collection_key`.

## Fields

| Field | Type | Description |
|---|---|---|
| `key` | str | Zotero collection key |
| `name` | str | Collection name (matches `Stream.title`) |
| `parent_key` | str \| None | Parent collection key if nested |

## Relations

- Owned 1-to-1 by a [Stream](stream.md).
- Contains many [ZoteroItem](zotero-item.md)s — one per paper discovered by the stream.
- Items in this collection can be imported to the vault as [Source](source.md)s, but
  the collection itself stays in Zotero regardless.

## Relevant axioms

> Stream runs write to Zotero, not to the vault. The ZoteroCollection is the canonical
> store for stream papers. See [Axiom 4](../ontologia.md).

## Not yet implemented

`_run_stream` does not yet create this collection or add items to it.
`Stream.collection_key` field is defined but unused in the current implementation.
