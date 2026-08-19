# Prisma Wiki

**Prisma** is a research library assistant that discovers academic papers and books, assesses their relevance using an LLM (local or cloud-capable), organizes them into Zotero, and provides a flat-Markdown vault workspace with grounded chat over your notes and sources.

---

## Pages

### Using Prisma
- [Features](features.md) — What Prisma does and how
- [CLI Reference](cli.md) — All commands and options
- [Configuration](configuration.md) — Full YAML reference
- [Installation](installation.md) — User and developer setup

### Core Concepts
- [Research Streams](streams.md) — Persistent topic monitoring
- [Sources](sources.md) — Academic sources, quality ratings, and validation
- [Zotero Integration](zotero.md) — Read/write split, hybrid mode, offline behavior
- [Chat](../concepts/chat.md) — Grounded Q&A over the vault, tool-calling, per-claim citations
- [Chat Session Graph](../concepts/chat-session-graph.md) — Turn/tool-call/reasoning/claim graph, `RECALL`, `SessionOrchestrator`

### Developer Reference
- [Architecture](architecture.md) — Components, data flow, and design decisions
- [Data Models](data-models.md) — Pydantic models reference
- [Roadmap](roadmap.md) — Planned features and phases
- [ADRs](adr/README.md) — Architecture Decision Records

---

## Implementation Status

| Component | Status |
|-----------|--------|
| arXiv, Semantic Scholar, PubMed, OpenLibrary, Google Books | ✅ Implemented |
| Per-source quota control (rate limiting + daily caps) | ✅ Implemented |
| IEEE Xplore search | ⚠️ Implemented, but real rate limit unverified (requires your own API key) |
| Academic validation + confidence scoring | ✅ Implemented |
| LLM relevance assessment (local or cloud-capable) | ✅ Implemented |
| Duplicate detection | ✅ Implemented |
| Literature review report generation | ✅ Implemented |
| Research Streams | ✅ Implemented |
| Zotero Web API client | ✅ Implemented |
| Offline write queue | ✅ Implemented |
| Vault workspace (notes/sources/chats/streams, PWA + desktop) | ✅ Implemented |
| Chat (session graph, tool-calling, per-claim citations, `RECALL`) | ✅ Implemented |
| Native knowledge graph (Kùzu, no third-party dependency) | ✅ Implemented |
| Vault sync (server ↔ desktop, offline-first) | ✅ Implemented |
