# Architecture Decision Records

Each ADR documents a significant design decision: what was decided, why, and what alternatives were considered.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-simple-pipeline-architecture.md) | Enhanced Pipeline Architecture | Evolved |
| [ADR-002](ADR-002-research-documentation-standards.md) | Research Documentation Standards | Active |
| [ADR-003](ADR-003-direct-composition.md) | Direct Composition (no message bus) | Active |
| [ADR-004](ADR-004-simple-cli-interface.md) | Simple CLI Interface | Active |
| [ADR-005](ADR-005-sequential-processing.md) | Sequential Processing | Active |
| [ADR-006](ADR-006-simple-folder-structure.md) | Simple Folder Structure | Active |
| [ADR-007](ADR-007-research-streams-architecture.md) | Research Streams Architecture | Active |
| [ADR-008](ADR-008-enhanced-zotero-integration.md) | Enhanced Zotero Integration | Active |
| [ADR-009](ADR-009-hybrid-retrieval-architecture.md) | Hybrid Retrieval — Graphify + ChromaDB (Graphify since replaced, see follow-up) | Evolved |
| [ADR-010](ADR-010-transport-layer-strategy.md) | Transport Layer Strategy — REST + WebSocket | Accepted |
| [ADR-011](ADR-011-authentication-strategy.md) | Authentication Strategy | Accepted |
| [ADR-012](ADR-012-process-supervision.md) | Process Supervision — Independent, Crash-Isolated Components | Accepted |
| [ADR-013](ADR-013-native-knowledge-graph.md) | Native Knowledge Graph — Replacing Graphify with Kùzu | Accepted |
| [ADR-014](ADR-014-chat-llm-backend-interface.md) | Chat Module's LLM Backend Interface — `openai` SDK, multi-`base_url` | Accepted |
| [ADR-015](ADR-015-chat-excerpt-context-model.md) | Chat Excerpt & Context Model — one Excerpt per chat, compressed vs. verbatim pinning by backend context budget | Accepted |
| [ADR-016](ADR-016-chunking-and-structured-extraction-tooling.md) | Chunking and Structured-Extraction Tooling — `semchunk` over Chonkie, Instructor over Outlines | Accepted |
