# Transclusion

## What it is

A **Transclusion** embeds the full content (or a named section) of another vault node inline
into the current node. Written as `![[slug]]` or `![[slug#section]]`.

The renderer resolves transclusions recursively before producing HTML, with a depth limit
to prevent infinite loops from circular embeds.

## Notation

| Notation | Meaning |
|---|---|
| `![[slug]]` | Embed entire node content inline |
| `![[slug#section]]` | Embed only the content under a specific heading |

## Fields

| Field | Type | Description |
|---|---|---|
| `source_slug` | str | Node containing the transclusion directive |
| `target_slug` | str | Node whose content is embedded |
| `section` | str \| None | Heading section to embed (None = full content) |
| `depth` | int | Current recursion depth (renderer enforces max 5) |

## Relations

- Appears in the body of [Note](note.md), [Source](source.md), or [Chat](chat.md).
- Creates an embedding edge in the [GraphNode](graph-node.md) graph.

## Relevant axioms

> Transclusion depth ≤ 5. See [Axiom 7](../ontologia.md).
