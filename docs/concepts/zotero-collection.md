# ZoteroCollection

## What it is

A **ZoteroCollection** is a stream's acceptance journal in Zotero. It records which papers
the stream's LLM relevance gate approved, from which perspective, and over which runs.

Each stream owns exactly one collection. The collection is created in Zotero on the first run
of a stream and its key is stored on the stream as `Stream.collection_key`.

A collection is NOT a folder of every paper related to a topic — it is the record of
**which papers this stream judged relevant to its own query**. The same paper can appear in
multiple collections because relevance is per-stream, per-perspective.

## The library vs the collection

```
Zotero Library (global, shared)
├── ZoteroItem: "Attention Is All You Need"
│     belongs to → Collection "Transformers" (stream A accepted it)
│     belongs to → Collection "NLP Survey" (stream B also accepted it)
│
└── ZoteroItem: "U-Net for Image Segmentation"
      belongs to → Collection "Super Resolution" (stream C accepted it)
      NOT in     → Collection "NLP Survey"  (stream B rejected it or hasn't seen it)
```

Being in the library means: discovered. Being in a collection means: accepted by that stream.

## Fields

| Field | Type | Description |
|---|---|---|
| `key` | str | Zotero collection key |
| `name` | str | Collection name (matches `Stream.title`) |
| `parent_key` | str \| None | Parent collection key if nested |

## Relations

- Owned 1-to-1 by a [Stream](stream.md).
- Contains the [ZoteroItem](zotero-item.md)s that passed this stream's LLM relevance gate.
- An item being in another collection does not affect whether it belongs here — each collection
  is evaluated independently.
- Items in this collection can be imported to the vault as [Source](source.md)s, but
  the collection itself stays in Zotero regardless.

## Relevant axioms

> Stream runs write to Zotero, not to the vault. See [Axiom 4](../ontologia.md).
> Relevance is per-stream. See [Axiom 13](../ontologia.md).
> Collection membership is the acceptance record. See [Axiom 15](../ontologia.md).
