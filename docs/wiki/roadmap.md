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

## Phase 5 — Collaboration (Long-term)

- Optional web interface for report viewing
- Shared research projects and multi-user Zotero group support
- API endpoints for external tool integration
- Distributed processing for large-scale reviews

---

## Development Principles

- MVP first — get core working before adding features
- No cloud dependencies for core functionality — local LLM, local Zotero reads
- Simple by default — complex features are opt-in via config
- Academic integrity — maintain reproducibility and source attribution
