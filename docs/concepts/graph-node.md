# GraphNode

## What it is

A **GraphNode** is a vault node ([Source](source.md), [Note](note.md), [Chat](chat.md))
represented as a vertex in the knowledge graph maintained by Graphify.

Graphify indexes all `.md` files in the vault and extracts DSL links ([WikiLink](wiki-link.md),
[Transclusion](transclusion.md), [Citation](citation.md)) as directed edges between nodes.
It also derives implicit edges from co-authorship, co-citation, and semantic similarity.

The graph is used for:
- **Search** — `GET /search` (text) and `GET /search/deep` (semantic via Ollama)
- **Home dashboard** — recent nodes, god nodes, cluster summaries
- **Suggestions** — related sources, surprising connections

## Graph entities

| Entity | Description |
|---|---|
| `GraphNode` | One vault node as a vertex |
| `GraphEdge` | One DSL link or implicit relation as a directed edge |
| `GraphCluster` | Community of related nodes (Leiden / community detection) |
| `GodNode` | Most connected / central node — a key concept in the research area |

## Implicit edge types

| Type | Derived from |
|---|---|
| Co-authorship | Two Sources sharing an author |
| Co-citation | Two Sources cited together in the same Note or Chat |
| Semantic similarity | Embedding distance above threshold (ChromaDB — not yet implemented) |

## Relations

- Built from [Source](source.md), [Note](note.md), [Chat](chat.md) `.md` files.
- Edges come from [WikiLink](wiki-link.md), [Transclusion](transclusion.md), [Citation](citation.md).
- Re-indexed whenever `mark_stale()` is called after a vault write.

## Relevant axioms

> Graphify re-indexes on save. See [Axiom 8](../ontologia.md).

## Not yet implemented

- Semantic similarity edges via ChromaDB (ADR-009).
- Streams are `.yaml` — intentionally excluded from graph indexing.
