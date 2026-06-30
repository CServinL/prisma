# Architecture

## Repository Structure

```
prisma/                        # repo root
├── prisma/                    # Python package (pip install prisma)
│   ├── coordinator.py         # Literature review pipeline orchestrator
│   ├── connectivity.py        # Network monitor (online/offline detection)
│   ├── agents/
│   │   ├── search_agent.py        # Multi-source paper/book search
│   │   ├── analysis_agent.py      # LLM relevance + deep analysis
│   │   ├── report_agent.py        # Report synthesis and generation
│   │   └── zotero_agent.py        # Zotero search and item creation
│   ├── integrations/
│   │   └── zotero/
│   │       ├── client.py          # ZoteroClient factory (from_config)
│   │       ├── hybrid_client.py   # Online: Web API reads+writes / Local API reads
│   │       ├── local_api_client.py  # Offline reads via Zotero Desktop HTTP
│   │       ├── desktop_client.py  # Desktop-specific operations
│   │       └── unified_client.py  # Common interface all clients implement
│   ├── server/
│   │   ├── app.py                 # FastAPI application — all HTTP endpoints + UI serving
│   │   └── log_setup.py           # Rotating log files per concern (server, chroma, ollama…)
│   ├── services/
│   │   ├── vault.py               # Vault CRUD: notes, sources, chats, streams
│   │   ├── zotero_service.py      # Zotero integration (offline/online)
│   │   ├── graphify_service.py    # Graphify knowledge graph indexer (watchdog + Ollama)
│   │   ├── chroma_service.py      # ChromaDB semantic index (watchdog + nomic-embed-text)
│   │   └── research_stream_manager.py  # Stream lifecycle management
│   ├── storage/
│   │   ├── models/
│   │   │   ├── agent_models.py          # PaperMetadata, BookMetadata, SearchResult
│   │   │   ├── research_stream_models.py  # ResearchStream, StreamStatus, RefreshFrequency
│   │   │   ├── vault_models.py          # VaultNode, RenderedNode, VaultListing, StreamStatus
│   │   │   ├── zotero_models.py         # ZoteroItem, ZoteroCollection
│   │   │   ├── api_response_models.py   # Typed API response models (Pydantic)
│   │   │   └── source_quality.py        # SourceQuality enum, SOURCE_REGISTRY, validation
│   │   └── pending_queue.py       # Offline write queue (flushed on next online start)
│   ├── cli/
│   │   ├── prisma_cli.py          # Click root group + global options
│   │   └── commands/
│   │       ├── streams.py         # prisma streams subcommands
│   │       ├── zotero.py          # prisma zotero subcommands
│   │       └── cleanup.py         # prisma cleanup subcommands
│   └── utils/
│       ├── config.py              # YAML config loader, Pydantic-validated models
│       └── text.py                # Text utilities (significant_words, etc.)
└── ui/                        # SvelteKit frontend (source of truth for all clients)
    ├── src/routes/+page.svelte  # Single-page app — vault tree, viewer, Zotero sidebar
    ├── vite.config.js           # Vite build config (no Tauri-specific overrides)
    ├── svelte.config.js         # adapter-static (SPA mode, fallback: index.html)
    └── build/                   # Output of `npm run build` — served at /app by prisma serve
```

## Pipeline Data Flow

```
prisma review "topic"
       │
       ▼
PrismaCoordinator.run_review()
       │
       ├─ SearchAgent.search()
       │      ├─ arXiv API  ──────────────────┐
       │      ├─ Semantic Scholar API ─────────┤
       │      ├─ OpenLibrary API ──────────────┤─→ validate → deduplicate → PaperMetadata[]
       │      ├─ Google Books API ─────────────┤
       │      └─ (Zotero — dedup only) ────────┘
       │
       ├─ AnalysisAgent.assess_relevance()  (per paper, via Ollama)
       │      └─ discard irrelevant papers
       │
       ├─ ZoteroAgent._check_zotero_duplicate_simple()  (per paper)
       │      └─ skip papers already in Zotero
       │
       ├─ AnalysisAgent.analyze()  (deep LLM analysis on remaining papers)
       │
       ├─ ZoteroAgent / unified_client.save_items()  (if auto_save enabled)
       │
       └─ ReportAgent.generate() → Markdown file
```

## Research Streams Data Flow

```
prisma streams update --all
       │
       ▼
ResearchStreamManager.update_stream()
       │
       ├─ SearchAgent.search()  (using stream's query)
       │
       ├─ Deduplication against existing stream papers
       │
       ├─ ZoteroClient.create_collection()  (if collection missing)
       │      └─ if offline: enqueue to PendingWriteQueue
       │
       ├─ ZoteroClient.save_items()  (new papers → Zotero collection)
       │      └─ if offline: enqueue to PendingWriteQueue
       │
       └─ Smart tag application + stream state saved to data/research_streams.json
```

## Server (HTTP API + UI)

`prisma serve` starts a FastAPI server on `localhost:8765`. It serves both the API and the SvelteKit UI.

| Path | Purpose |
|------|---------|
| `/app` | SvelteKit SPA (static files from `ui/build/`) |
| `/ui/dev/version` | Dev hot-reload signal — version counter incremented after each UI rebuild |

Key API endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness check |
| GET | `/status` | Config, vault stats, Graphify state, ChromaDB state, Zotero, Ollama reachability |
| GET | `/logs` | Tail a log file (`?concern=server\|chroma\|ollama\|activity\|stream&slug=…`) |
| GET | `/notes` | List vault notes (filterable by type) |
| GET | `/notes/{slug}` | Fetch and render a note (HTML or raw) |
| PUT | `/notes/{slug}` | Save note content |
| POST | `/notes` | Create note |
| DELETE | `/notes/{slug}` | Delete note |
| GET | `/streams` | List research streams |
| GET | `/streams/{slug}/view` | Render a stream as HTML (stream YAML → RenderedNode) |
| GET | `/tree` | Vault directory tree |
| GET | `/search` | Fast text search (in-memory index, OR scoring with title boost) |
| GET | `/search/deep` | Semantic search via ChromaDB + Graphify re-ranking |
| GET | `/home` | Render the vault home/dashboard note |
| POST | `/render` | Render arbitrary markdown to HTML |
| POST | `/graphify/taint` | Force full re-index of knowledge graph |
| GET | `/vault/assets/{path}` | Serve vault static assets |
| POST | `/reload` | Reinitialize all backend services + remount UI |
| POST | `/reload/ui` | Remount `ui/build/` at `/app` (after a UI rebuild) |
| POST | `/reload/vault` | Reinitialize VaultService from config |
| POST | `/reload/zotero` | Reinitialize Zotero client |
| POST | `/reload/indexer` | Restart Graphify indexer |
| POST | `/reload/chroma` | Restart ChromaDB indexer |

## Background Services

Four daemon threads start at server startup:

| Service | What it does |
|---------|--------------|
| Graphify indexer | Watchdog on vault root; on change, extracts knowledge-graph nodes via Ollama and persists to `graphify-out/`. Retries every 60 s if Ollama is unreachable. |
| ChromaDB indexer | Watchdog on vault root; on change, embeds changed `.md` files via `nomic-embed-text` and upserts into a persistent ChromaDB collection at `{vault_root}/chromadb/`. |
| Stream scheduler | Polls every 5 min; runs active streams whose `next_update` is past. |
| UI watcher | Polls `ui/src/` mtime hash every 1 s. When source changes, debounces 500 ms, runs `npm run build` in `ui/`, then increments the dev version counter (exposed via `GET /ui/dev/version`). Only active when `ui/src/` exists (dev environment). |

Both indexers wait 20 s after startup before the initial full scan, so the server is responsive immediately.

## Search Strategy

**Regular search (`GET /search`):** keyword scoring against an in-memory mtime-keyed index. Files are stat'd on every request; only files whose mtime changed are re-read from disk. Scoring: each matching term +1.0, title match +4.0, all-terms match (AND bonus) +3.0. Returns up to 30 results sorted by score.

**Deep search (`GET /search/deep`):** ChromaDB semantic query (top 60 chunks) → file-level best-chunk scoring → Graphify node titles used for title-boost re-ranking → top 20 results. Slower but semantics-aware.

## Key Design Decisions

- **No message queue or microservices** — direct function calls between components (ADR-001, ADR-003, ADR-005)
- **Vault stored as flat Markdown files** — no database; `VaultService` reads/writes `.md` files in a structured folder layout
- **Pydantic models throughout** — all API responses and internal data validated with Pydantic v2
- **Offline-first for reads** — Zotero writes queued, reads degrade gracefully to local Zotero HTTP
- **Entry points** — `prisma.cli.prisma_cli:cli` (CLI) and `prisma.server.app:app` (ASGI server) in `pyproject.toml`

## Client Architecture

The SvelteKit UI (`ui/`) is the single source for all clients. `prisma serve` builds and serves it; clients differ only in how they wrap it.

| Platform | Client | How UI is delivered |
|----------|--------|---------------------|
| Linux | Tauri shell (`prisma-desktop`) | Native window → `http://127.0.0.1:8765/app` |
| Windows / WSL2 | Tauri shell (`prisma-desktop`) | Native window → `http://127.0.0.1:8765/app` |
| macOS / iOS / Android | Browser PWA | `http://<host>:8765/app` → install via browser |

**Tauri shell** (`prisma-desktop/src-tauri/`) is thin — Rust handles only:
- Window lifecycle (create, resize, minimize, maximize, close, drag)
- Settings persistence (`~/.config/prisma-desktop/settings.json`) — server URL, zoom scale, window state
- WSL2-aware URL opener (`open_url` command)

The SvelteKit app detects its runtime via `"__TAURI_INTERNALS__" in window`:
- **Tauri**: uses `@tauri-apps/api` for window commands and settings; `apiBase` from `localStorage`
- **Browser/PWA**: uses `window.open`, `localStorage` for settings; `apiBase = window.location.origin`

**Dev hot-reload**: `ui/src/` changes trigger an auto-rebuild on the server. The client polls `GET /ui/dev/version` every 2 s and calls `window.location.reload()` when the version bumps — works in both Tauri and browser without a Vite dev server.
