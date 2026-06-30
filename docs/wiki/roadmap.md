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
- **WebSocket migration** — replace the HTTP REST + polling model with a single WebSocket connection. The server already runs a filesystem watcher; it should push events (vault tree changed, stream updated, index progress, Ollama state change) directly to the client instead of waiting for the 30 s poll. The desktop is the only consumer — no 3rd-party integrations to support — so there is no reason to maintain a dual REST + WS surface. All commands (open note, run stream, import from Zotero, etc.) go over the socket as typed messages; all state updates arrive as server-initiated events. Replaces `fetchStatus`, `loadTree`, and every `fetch()` call in the desktop. FastAPI supports WebSocket natively (`@app.websocket`).

---

## Phase 2 — Sources

- **PubMed** — biomedical literature
- **IEEE Xplore** — engineering and CS
- **Academia.edu** — complete the HTML parsing stub
- **ResearchGate** — scraping or API if available
- **JSTOR, Web of Science** — subscription databases (institutional access)
- **Grey literature** — theses, technical reports, government publications

---

## Phase 3 — Zotero & Library

- Scheduled stream updates (cron-based, not just on-demand)
- "What's new" delta reports between stream update runs
- Better collection hierarchy management
- Mendeley, EndNote, RefWorks integration

---

## Phase 4 — Analytics & Visualization

- **ConnectedPapers integration** — auto-generate links using DOI/arXiv ID/Semantic Scholar URL for citation network visualization. ConnectedPapers has no public API, but direct URL construction works
- Citation network analysis
- Author intelligence: profiles, collaboration networks, research trajectories, institution mapping
- Trend monitoring: emerging topics, topic drift detection across updates
- Geographic distribution of research activity

---

## Phase 5 — Multi-platform (Long-term)

Platform matrix:

| Target | Client |
|--------|--------|
| Linux | Tauri desktop (primary) |
| Windows (WSL2) | Tauri desktop — server runs in WSL2, UI is native Windows |
| macOS / iOS / iPadOS / Android | Web client — browser points at a Linux/WSL2 host |

- **Server** (`prisma serve`) — Linux only, including WSL2. No macOS or Windows native server planned.
- **Tauri desktop** — Linux and Windows only. No native Mac/iOS build planned.
- **Web client (PWA)** — SvelteKit static build with `vite-plugin-pwa`. Served alongside `prisma serve`. Once the WebSocket migration is done, any browser is a first-class client. On Android, iOS, and macOS, users install it from the browser ("Add to home screen") and it runs as a standalone app — own icon, no browser chrome, appears in the app launcher. No store, no fee, no review. Add: `manifest.json` (name, icons, `display: standalone`) + service worker via `vite-plugin-pwa`. Access remotely via Tailscale or a reverse proxy.
- Shared research projects and multi-user Zotero group support
- Distributed processing for large-scale reviews

---

## Development Principles

- MVP first — get core working before adding features
- No cloud dependencies for core functionality — local LLM, local Zotero reads
- Simple by default — complex features are opt-in via config
- Academic integrity — maintain reproducibility and source attribution
