# Prisma Wiki

**Prisma** is a research library assistant that discovers academic papers and books, assesses their relevance using a local LLM, and organizes them into Zotero.

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

### Developer Reference
- [Architecture](architecture.md) — Components, data flow, and design decisions
- [Data Models](data-models.md) — Pydantic models reference
- [Roadmap](roadmap.md) — Planned features and phases
- [ADRs](adr/README.md) — Architecture Decision Records

---

## Implementation Status

| Component | Status |
|-----------|--------|
| arXiv, Semantic Scholar, OpenLibrary, Google Books | ✅ Implemented |
| Academic validation + confidence scoring | ✅ Implemented |
| LLM relevance assessment (Ollama) | ✅ Implemented |
| Duplicate detection | ✅ Implemented |
| Literature review report generation | ✅ Implemented |
| Research Streams | ✅ Implemented |
| Zotero hybrid client (read local / write web) | ✅ Implemented |
| Offline write queue | ✅ Implemented |
| Academia.edu search | ⚠️ Stub — HTTP request made, parsing not implemented |
| PubMed search | ❌ Not started |
| ResearchGate search | ❌ Not started |
