# Roadmap

## Current State (Phase 0 — MVP)

Core pipeline is working:

| Feature | Status |
|---------|--------|
| arXiv, Semantic Scholar, OpenLibrary, Google Books search | ✅ Done |
| Academic validation + confidence scoring | ✅ Done |
| LLM relevance assessment (Ollama) | ✅ Done |
| Duplicate detection | ✅ Done |
| Literature review report generation | ✅ Done |
| Research Streams | ✅ Done |
| Zotero hybrid client (read local / write web) | ✅ Done |
| Offline write queue | ✅ Done |
| PubMed search | ❌ Not started |
| Academia.edu search | ⚠️ Stub only |
| ResearchGate search | ❌ Not started |

---

## Phase 1 — Enhanced Analysis

- Better comparative analysis and trend detection across papers
- Improved deduplication (fuzzy matching, DOI-based)
- Multiple output formats: HTML, PDF, LaTeX, Word
- Performance: concurrent source search, LLM batching
- Better CLI error messages and progress output
- **Ollama resilience** — graceful degradation when Ollama is unavailable at startup or drops mid-session: ChromaDB full index currently silently skips if Ollama is offline during the 20s startup window and never retries; Graphify retries every 60s (already handles it). Both services should expose clear status to the server health endpoint, and ChromaDB should schedule a retry when Ollama becomes reachable again rather than waiting for the next file-change event.
- **WebSocket push events** — ✅ Done (see ADR-010). Rather than replacing REST, the server keeps REST for all CRUD/search/asset endpoints and adds one `/ws` channel purely for server-initiated push: `hot_reload`, `vault_change`, `stream_progress`. This replaces the old 2 s `/ui/dev/version` poll (kept only as a fallback when WS is unavailable — e.g. a restrictive proxy). Full REST→WS replacement was considered and rejected: it would cost `curl`-ability of the API for a use case (single client, localhost/LAN) where REST's caching/CDN advantages don't matter anyway. Remaining work: extend push coverage to note-content live-updates across multiple open clients, and stream the future chat feature's LLM tokens over the same channel.

---

## Phase 2 — Conversational Chat & On-Demand Knowledge Graphs

- **Chat** — ask Prisma questions about your vault (papers, notes, sources). Answers
  are grounded via ChromaDB semantic retrieval + Graphify context, synthesized by the
  local LLM (Ollama), with citations back to source notes. Chat sessions are saved to
  the vault (`chats/` — already modeled in `VaultService`, currently always empty
  since no chat UI exists yet).
- **Knowledge graphs from chat context** — ask Prisma to generate a knowledge graph
  for a chat's subject. Graphify already builds a knowledge graph internally to
  re-rank search results (`GraphifyService`, `graphify-out/`); this exposes that
  capability as a user-facing artifact scoped to a specific topic/conversation,
  rather than only an internal search index.

---

## Phase 3 — Sources

- **PubMed** — biomedical literature
- **IEEE Xplore** — engineering and CS
- **Academia.edu** — complete the HTML parsing stub
- **ResearchGate** — scraping or API if available
- **JSTOR, Web of Science** — subscription databases (institutional access)
- **Grey literature** — theses, technical reports, government publications

---

## Phase 4 — Zotero & Library

- Scheduled stream updates (cron-based, not just on-demand)
- "What's new" delta reports between stream update runs
- Better collection hierarchy management
- Mendeley, EndNote, RefWorks integration

---

## Phase 5 — Analytics & Visualization

- **ConnectedPapers integration** — auto-generate links using DOI/arXiv ID/Semantic Scholar URL for citation network visualization. ConnectedPapers has no public API, but direct URL construction works
- Citation network analysis
- Author intelligence: profiles, collaboration networks, research trajectories, institution mapping
- Trend monitoring: emerging topics, topic drift detection across updates
- Geographic distribution of research activity

---

## Phase 6 — Multi-platform (Long-term)

Platform matrix:

| Target | Client |
|--------|--------|
| Linux | Tauri desktop (primary) |
| Windows (WSL2) | Tauri desktop — server runs in WSL2, UI is native Windows |
| macOS / iOS / iPadOS / Android | Web client — browser points at a Linux/WSL2 host |

- **Server** (`prisma serve`) — Linux only, including WSL2. No macOS or Windows native server planned.
- **Tauri desktop** — Linux and Windows only. No native Mac/iOS build planned.
- **Web client (PWA)** — ✅ Done. SvelteKit static build with `@vite-pwa/sveltekit` (manifest + Workbox service worker), served alongside `prisma serve` at `/app`. On Android, iOS, and macOS, users install it from the browser ("Add to home screen") and it runs as a standalone app — own icon, no browser chrome, appears in the app launcher. No store, no fee, no review. Remote access (outside the home LAN) is covered by the zone-based deployment model — see [deployment-models.md](deployment-models.md) and ADR-011 — rather than Tailscale specifically.
- Shared research projects and multi-user Zotero group support
- Distributed processing for large-scale reviews

---

## Development Principles

- MVP first — get core working before adding features
- No cloud dependencies for core functionality — local LLM, local Zotero reads
- Simple by default — complex features are opt-in via config
- Academic integrity — maintain reproducibility and source attribution
