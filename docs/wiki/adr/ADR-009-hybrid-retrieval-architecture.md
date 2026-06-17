# ADR-009: Hybrid Retrieval Architecture — Graphify + ChromaDB

**Date:** 2026-06-14
**Author:** CServinL
**Status:** Accepted

## Context

Prisma's vault search relies on Graphify, which builds a knowledge graph over vault documents
using an Ollama LLM and queries it via keyword scoring and graph walks. This works well for
concept-connected retrieval but fails silently for vocabulary mismatch: a paper using
"interpretability" scores zero for a query containing only "explainability," even though
the concepts are equivalent.

Research in XAI and adjacent fields uses inconsistent terminology across subfields and
languages. Keyword-only retrieval systematically misses synonyms, paraphrases, and
cross-language matches.

## Decision

Add ChromaDB as a second retrieval layer alongside Graphify. The two layers are complementary
and serve different query strengths:

| Layer | Mechanism | Strength | Weakness |
|---|---|---|---|
| Graphify | LLM-extracted graph + keyword walk | Relational chains, concept paths | Vocabulary mismatch |
| ChromaDB | Embedding vectors + cosine similarity | Semantic similarity, synonyms | No cross-document relationships |

At query time, both layers run independently and their results are merged by score before
being passed to the LLM as context. This is the standard GraphRAG retrieval pattern.

### Retrieval flow

```
query
  ├── Graphify.ranked_nodes()   → {source_file, score} list  (graph walk)
  └── ChromaDB.query()          → {source_file, score} list  (embedding search)
         ↓
  score merge + dedup (max of both scores per file)
         ↓
  top-k files → context chunks → LLM
```

### Indexing

- Graphify: existing incremental indexer, triggered by watchdog on vault file changes
- ChromaDB: vault documents chunked (by heading or fixed size) and upserted on the same
  file-change events, keyed by `{relative_path}#{chunk_index}` to support deletion by path

Both indexes are local and offline-first. ChromaDB persists to `{vault_root}/chromadb/`.

### Embedding model

Use a local embedding model via Ollama (e.g., `nomic-embed-text` or `mxbai-embed-large`)
to keep the stack fully offline. The model is configurable in `config.yaml` under a new
`retrieval.embedding_model` key.

## Alternatives Considered

### Graphify alone (status quo)
Rejected because vocabulary mismatch is a real gap for XAI research, where "explainability,"
"interpretability," "transparency," and "post-hoc analysis" refer to overlapping concepts
depending on the paper's subfield.

### ChromaDB alone
Rejected because semantic similarity has no concept of graph relationships. A paper about
SHAP wouldn't surface related work on LIME unless they share vocabulary — the graph walk
is what provides that connective context.

### Remote vector DBs (Pinecone, Weaviate)
Rejected. Prisma is a local-first, offline-capable research tool. External services add
a hard dependency on network availability and expose research data to third parties.

### Neo4j instead of Graphify's in-memory graph
Deferred. At personal vault scale (hundreds of documents), NetworkX + JSON is sufficient.
Neo4j becomes relevant if Prisma evolves into a multi-user server or the graph exceeds
~500k nodes. Revisit as ADR-010 if that threshold is reached.

## Consequences

### Positive
- Closes the vocabulary gap: synonyms and paraphrases surface in results
- No new remote dependencies — ChromaDB runs in-process, Ollama embedding model is local
- Incremental: ChromaDB index updates mirror the Graphify mtime-based incremental strategy
- Scores from both layers are interpretable and mergeable (both produce 0–1 relevance floats)

### Negative
- Ollama must serve two model types simultaneously (generation + embedding), which may
  require adjusting `OLLAMA_MAX_LOADED_MODELS` if VRAM is constrained
- Index storage grows: ChromaDB adds a persistent directory alongside `graphify-out/`
- Query latency increases slightly from running two retrievers, though both are local

## Related ADRs

- ADR-001: Pipeline Architecture (retrieval feeds context into the analysis pipeline)
- ADR-007: Research Streams (streams trigger re-indexing when new papers are added)
- ADR-008: Enhanced Zotero Integration (Zotero papers land in the vault, triggering indexing)
