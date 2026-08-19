# Roadmap

## Current State

Prisma is a production system, not a prototype — the phases below track
active feature work, not "is this usable yet." Core pipeline:

| Feature | Status |
|---------|--------|
| arXiv, Semantic Scholar, OpenLibrary, Google Books search | ✅ Done |
| PubMed, IEEE Xplore search | ✅ Done |
| Academic validation + confidence scoring | ✅ Done |
| LLM relevance assessment (Ollama) | ✅ Done |
| Duplicate detection | ✅ Done |
| Literature review report generation | ✅ Done |
| Research Streams | ✅ Done |
| Zotero Web API client (Web API only, everywhere — no local Desktop API path) | ✅ Done |
| Offline write queue | ✅ Done |
| Academia.edu, ResearchGate, JSTOR/Web of Science, grey literature | 🚫 Not planned — no reliable API for any of them, see Phase 3 |

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

- **Chat** — ✅ Done on `main`: ask Prisma questions about your vault (papers, notes,
  sources), grounded via ChromaDB semantic retrieval + native knowledge-graph context,
  synthesized by a backend-agnostic LLM interface (Ollama, llama.cpp, or OpenRouter —
  ADR-014), with tool-calling (`SEARCH_VAULT`/`GRAPH_CONTEXT`/`RECALL`), injection
  sanitization, and trust tiers (chat content is never citable as fact material). Chat
  sessions persist to the vault (`chats/*.sess`, pure JSON, versioned) as a session graph,
  not flat prose — a main line of turns with tool calls and per-claim citations as branches
  off each one, plus a pinning/Excerpt model (ADR-015) that compresses or keeps pinned turns
  verbatim depending on the backend's real context budget.
  Also on `main`: per-claim citations with real APA formatting (ADR-020, PR #74).
  **Not yet merged** (branch `chat-schema-v3-toulmin-media-attachments`,
  `CHAT_SCHEMA_VERSION=4`): the `THINK` tool + reasoning-step branches, Toulmin argumentation
  fields, media attachments, and the `citation`/`paraphrase` relation split — see
  `docs/concepts/chat-session-graph.md`'s Status section for exactly what's shipped vs. still
  on that branch.
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

Done as of 2026-07-29: **PubMed** and **IEEE Xplore** are implemented (see
`docs/wiki/sources.md`), alongside a real per-source quota-control system
(`prisma.services.rate_limiter.RateLimiter`) and a source-module registry
(`prisma/integrations/sources/`) that replaced the old monolithic
`SearchAgent` dispatch. IEEE Xplore's rate limit is a conservative,
unverified placeholder until the user has a registered key and IEEE's real
API user guide — don't advertise it as fully reliable until that's
confirmed.

Not planned initially: Academia.edu, ResearchGate, JSTOR/Web of Science, and
grey literature were all considered and dropped (2026-07-29) — no reliable
API for any of them (HTML scraping / anti-bot measures / institutional-only
access), not worth the maintenance burden versus the API-backed sources
above. The half-implemented Academia.edu stub and the aspirational
`academia_rss`/`academia_search`/`researchgate` `SOURCE_REGISTRY` entries
were removed from the codebase the same day. Research Rabbit was also
evaluated and dropped the same day — no public API and no viable
integration path exists.

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

- **✅ Author Analysis / Research Directory — done 2026-08-02.**
  `ReportAgent.analyze_authors()`/`.create_research_directory()` build a
  per-author profile (paper count, specialization keywords from titles/key
  findings, key publications ranked by `analysis_confidence`) and render it
  as a Markdown section, opt-in via `POST /review`'s `include_authors`
  flag. Scope cut deliberately from the original sketch: **no institutional
  affiliation** — no search source Prisma indexes captures it anywhere in
  the pipeline (`PaperMetadata`/`PaperSummary` both lack it), and guessing
  it from an LLM reading the abstract risked fabricating exactly the kind
  of detail an academic tool shouldn't invent. `map_collaboration_networks`
  (co-authorship/network analysis) stays unbuilt, a separate increment —
  see below. Not meant to be a standalone report — it's an enrichment step
  that could feed the stream newsletter in Phase 4, once that exists.
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
| Windows / macOS | Planned, native Tauri builds once I've got hardware to test on — not started |
| iOS / iPadOS / Android | Web client — browser points at a Linux host |

`prisma-desktop` briefly supported WSL2 as a stopgap before native Linux hardware was
available, then dropped it (2026-07-30) once that stopgap was no longer needed — Linux-only
for now. That was never a real multi-platform story (WSL2 just runs the same Linux binary
under Windows), so it isn't a step toward this Phase; genuine native Windows/macOS builds
are separate, not-yet-started work.

- **Server** (`prisma serve`) — Linux only. No macOS or Windows native server planned.
- **Tauri desktop** — Linux only today. Native Windows/macOS builds planned once hardware
  exists to build/test them on — not a port of the old WSL2-aware code.
- **Web client (PWA)** — ✅ Done. SvelteKit static build with `@vite-pwa/sveltekit` (manifest + Workbox service worker), served alongside `prisma serve` at `/app`. On Android, iOS, and macOS, users install it from the browser ("Add to home screen") and it runs as a standalone app — own icon, no browser chrome, appears in the app launcher. No store, no fee, no review. Remote access (outside the home LAN) is covered by the zone-based deployment model — see [deployment-models.md](deployment-models.md) and ADR-011 — rather than Tailscale specifically.
- Shared research projects and multi-user Zotero group support
- Distributed processing for large-scale reviews

---

## Development Principles

- Core first — get a feature solidly working before layering the next one on
- No cloud dependencies for core functionality — local LLM, local Zotero reads
- Simple by default — complex features are opt-in via config
- Academic integrity — maintain reproducibility and source attribution
