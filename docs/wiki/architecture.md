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
│   │   ├── supervisor.py          # Process supervisor — spawns/monitors api, web, chroma (ADR-012)
│   │   ├── app.py                 # API process — REST + WebSocket, no UI mount
│   │   ├── web_app.py             # Web process — serves ui/build/ at /app, dev watcher
│   │   ├── static.py              # CleanUrlStaticFiles — shared by app.py and web_app.py
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

## Server (Supervisor + API + Web + ChromaDB)

`prisma serve` starts a **supervisor** process (`prisma.server.supervisor`), which
spawns and monitors three independent worker processes — see ADR-012 for the
full rationale. A crash in any one of them no longer takes down the others,
and the supervisor auto-restarts a worker that dies unexpectedly (with
backoff), or on request via its control API.

| Process | Default port | Purpose |
|---------|--------------|---------|
| Supervisor | `8760` (loopback only) | Spawns/monitors workers; control API |
| API | `8765` | REST + WebSocket (`prisma.server.app`) |
| Web | `8766` | Serves the built UI at `/app` (`prisma.server.web_app`) |
| ChromaDB | `8767` (loopback only) | Standalone `chroma run` server — not embedded |

### Supervisor control API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/supervisor/status` | PID, liveness, restart count per worker |
| POST | `/supervisor/restart/{name}` | Deliberately restart one worker (`api`, `web`, or `chroma`) — this is what actually reloads new code, since `/reload/*` below only resets in-process object state |

### Web process

| Path | Purpose |
|------|---------|
| `/app` | SvelteKit SPA (static files from `ui/build/`) |
| `/ui/dev/version` | Dev hot-reload signal (polled) — version counter incremented after each UI rebuild |
| `POST /reload/ui` | Remount `ui/build/` at `/app` (after a UI rebuild) |

### API process

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
| POST | `/reload` | Reinitialize vault, Zotero, Graphify, ChromaDB client (in-process state, not a restart) |
| POST | `/reload/vault` | Reinitialize VaultService from config |
| POST | `/reload/zotero` | Reinitialize Zotero client |
| POST | `/reload/indexer` | Restart Graphify indexer |
| POST | `/reload/chroma` | Rebuild the ChromaDB client (reconnects to the Chroma server process) |
| GET | `/ws` | WebSocket — server push events (`vault_change`, `stream_progress`) |

## Background Services

Three daemon threads start in the **API process**:

| Service | What it does |
|---------|--------------|
| Graphify indexer | Watchdog on vault root; on change, spawns a subprocess that extracts knowledge-graph nodes via Ollama and persists to `graphify-out/`. Retries every 60 s if Ollama is unreachable. The subprocess runs in its own session so it isn't killed by a signal sent to the API process — the indexer's `stop()` terminates it deliberately (SIGTERM, escalating to SIGKILL) instead. |
| ChromaDB indexer | Watchdog on vault root; on change, embeds changed `.md` files via `nomic-embed-text` and upserts into the ChromaDB **server process** (`chromadb.HttpClient`, not embedded — see ADR-012) at `{vault_root}/chromadb/`. Skips files whose mtime hasn't changed since the last upsert, even if a spurious filesystem event re-queues them. |
| Stream scheduler | Polls every 5 min; runs active streams whose `next_update` is past. |

One daemon thread starts in the **Web process**:

| Service | What it does |
|---------|--------------|
| UI watcher | Polls `ui/src/` mtime hash every 1 s. When source changes, debounces 500 ms, runs `npm run build` in `ui/`, then increments the dev version counter (exposed via `GET /ui/dev/version`). Only active when `ui/src/` exists (dev environment). |

Both indexers wait 20 s after startup before the initial full scan, so the API process is responsive immediately.

## Search Strategy

**Regular search (`GET /search`):** keyword scoring against an in-memory mtime-keyed index. Files are stat'd on every request; only files whose mtime changed are re-read from disk. Scoring: each matching term +1.0, title match +4.0, all-terms match (AND bonus) +3.0. Returns up to 30 results sorted by score.

**Deep search (`GET /search/deep`):** ChromaDB semantic query (top 60 chunks) → file-level best-chunk scoring → Graphify node titles used for title-boost re-ranking → top 20 results. Slower but semantics-aware.

## Key Design Decisions

- **No message queue or microservices** — direct function calls between components (ADR-001, ADR-003, ADR-005)
- **Vault stored as flat Markdown files** — no database; `VaultService` reads/writes `.md` files in a structured folder layout
- **Pydantic models throughout** — all API responses and internal data validated with Pydantic v2
- **Offline-first for reads** — Zotero writes queued, reads degrade gracefully to local Zotero HTTP
- **Entry points** — `prisma.cli.prisma_cli:cli` (CLI, `prisma serve` launches the supervisor); `prisma.server.app:app` and `prisma.server.web_app:app` are the two ASGI apps the supervisor runs under `uvicorn`

## Client Architecture

The SvelteKit UI (`ui/`) is the single source for all clients. The Web
process (`prisma.server.web_app`, port `8766`) builds and serves it; the API
process (port `8765`) is a separate origin the client calls for REST/WS —
see ADR-012. Clients differ only in how they wrap the page.

| Platform | Client | How UI is delivered |
|----------|--------|---------------------|
| Linux | Tauri shell (`prisma-desktop`) | Native window → `http://127.0.0.1:8766/app` |
| Windows / WSL2 | Tauri shell (`prisma-desktop`) | Native window → `http://127.0.0.1:8766/app` |
| macOS / iOS / Android | Browser PWA | `http://<host>:8766/app` → install via browser |

> **Follow-up needed:** `prisma-desktop`'s window URL is currently configured
> against the old single-port assumption (`:8765/app`). It needs updating to
> point at the Web process's port (`8766`) now that UI serving and the API
> are separate processes. Out of scope for this (Python-side) change —
> tracked as a `prisma-desktop` repo follow-up.

**Tauri shell** (`prisma-desktop/src-tauri/`) is thin — Rust handles only:
- Window lifecycle (create, resize, minimize, maximize, close, drag)
- Settings persistence (`~/.config/prisma-desktop/settings.json`) — server URL, zoom scale, window state
- WSL2-aware URL opener (`open_url` command)

The SvelteKit app detects its runtime via `"__TAURI_INTERNALS__" in window`:
- **Tauri**: uses `@tauri-apps/api` for window commands and settings; `apiBase` from `localStorage` (defaults to the API port, `8765`)
- **Browser/PWA**: `apiBase` defaults to the page's own host on the API's port (`8765`) rather than the page's own origin, since the Web process serving the page and the API are different origins now; overridable via `localStorage` for reverse-proxied deployments

**Dev hot-reload**: `ui/src/` changes trigger an auto-rebuild in the Web process. The client polls `GET /ui/dev/version` on the Web process's own origin every 2 s and calls `window.location.reload()` when the version bumps — a dev-only, self-contained mechanism that doesn't involve the API process or WebSocket at all.
