# Roadmap

## Current State

Prisma is a production system, not a prototype — the phases below track
active feature work, not "is this usable yet." Core pipeline:

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
- **Ollama resilience** — graceful degradation when Ollama is unavailable at startup or drops mid-session. ✅ Both indexers now handle the manifest side correctly: ChromaDB's `_upsert_file` and the knowledge graph's `_extract_file` only advance their manifest on genuine success (a section that legitimately found nothing still counts; a denied lease/connection error/bad status doesn't) — a file that changed while Ollama was unreachable is retried next cycle instead of silently skipped forever. Remaining: expose clear Ollama-reachability status on the server health endpoint (not just the indexers' own retry behavior) at startup and mid-session.
- **WebSocket push events** — ✅ Done (see ADR-010). Rather than replacing REST, the server keeps REST for all CRUD/search/asset endpoints and adds one `/ws` channel purely for server-initiated push: `hot_reload`, `vault_change`, `stream_progress`. This replaces the old 2 s `/ui/dev/version` poll (kept only as a fallback when WS is unavailable — e.g. a restrictive proxy). Full REST→WS replacement was considered and rejected: it would cost `curl`-ability of the API for a use case (single client, localhost/LAN) where REST's caching/CDN advantages don't matter anyway. Remaining work: extend push coverage to note-content live-updates across multiple open clients, and stream the future chat feature's LLM tokens over the same channel.

---

## Phase 2 — Conversational Chat & On-Demand Knowledge Graphs

- **Chat** — ✅ Done. Ask Prisma questions about your vault (papers, notes,
  sources); answers are grounded via ChromaDB semantic retrieval + native
  knowledge-graph context, synthesized by a backend-agnostic LLM interface
  (Ollama today, OpenRouter/Anthropic-capable by design — ADR-014), with
  tool-calling, injection sanitization, and trust tiers (chat content is
  never citable as fact material). Chat sessions persist to the vault
  (`chats/`) with a pinning/Excerpt model (ADR-015) that compresses or
  keeps pinned turns verbatim depending on the backend's real context
  budget. Full architecture in `TODO.md`'s "Chat module" section.
- **Native knowledge graph module** — ✅ Done. Entity/relationship extraction
  (Instructor-based structured LLM output, ADR-016) and storage (Kùzu, an
  embedded graph DB) are no longer a third-party dependency — see ADR-013
  for the replacement and ADR-009's follow-up section for why, plus a
  progress UI page (sync status, chunk stats, dead-letter queue for failed
  extractions). `TODO.md` has what's still deferred
  (`ranked_nodes`/`surprising_connections` sophistication, image extraction).
- **Knowledge graphs from chat context** — ask Prisma to generate a knowledge graph
  for a chat's subject. The knowledge graph module builds this internally to
  re-rank search results; this exposes that capability as a user-facing artifact
  scoped to a specific topic/conversation, rather than only an internal search index.

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
- **"What's new" stream newsletter** — when `prisma streams update` finds new
  papers for a stream, generate a digest ("newsletter") of what's new: the
  papers found, why they're relevant to the stream's query, and (once Phase 5's
  author analysis exists) who wrote them and why that might matter. This is
  the actual delivery mechanism the author-analysis work in Phase 5 is for —
  author analysis isn't meant to be a standalone report, it's an enrichment
  step feeding this newsletter.
- Better collection hierarchy management
- Mendeley, EndNote, RefWorks integration

---

## Phase 5 — Analytics & Visualization

- **⚠️ Author Analysis / Research Directory — advertised, not implemented.** The
  README lists this under Key Features ("Identifies key researchers and
  creates academic contact directory"), but `ReportAgent.analyze_authors()`,
  `.create_research_directory()`, and `.map_collaboration_networks()` in
  `prisma/agents/report_agent.py` are all literal `pass` stubs — nothing has
  ever been implemented. This has been silently dropped across multiple past
  sessions; calling it out explicitly here so it isn't missed again. Scope:
  extract unique authors from a corpus of paper summaries, build per-author
  profiles (institutional affiliation, specializations, key publications),
  and render a Markdown "research directory" — the co-authorship/network
  and trajectory analysis below can come later as a separate increment. Not
  meant to be a standalone report — it's an enrichment step feeding the
  stream newsletter in Phase 4.
- **ConnectedPapers integration** — auto-generate links using DOI/arXiv ID/Semantic Scholar URL for citation network visualization. ConnectedPapers has no public API, but direct URL construction works
- Citation network analysis
- Author intelligence (extended): collaboration networks, research trajectories, institution mapping — builds on the author-analysis MVP above
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

- Core first — get a feature solidly working before layering the next one on
- No cloud dependencies for core functionality — local LLM, local Zotero reads
- Simple by default — complex features are opt-in via config
- Academic integrity — maintain reproducibility and source attribution
