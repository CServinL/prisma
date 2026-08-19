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
│   │   ├── zotero_agent.py        # Zotero search and item creation
│   │   ├── chat_agent.py          # Bounded, pattern-based tool loop (ADR-014/019) — the chat turn lifecycle
│   │   ├── session_orchestrator.py # Per-turn context assembly + in-memory session graph builder (ADR-019)
│   │   └── session_graph.py       # networkx graph construction from a Chat's TurnNode history
│   ├── integrations/
│   │   └── zotero/
│   │       └── client.py          # ZoteroClient (pyzotero-backed, Web API only) + from_config()
│   ├── server/
│   │   ├── supervisor.py          # Process supervisor — spawns/monitors api, web, chroma, kg (ADR-012)
│   │   ├── app.py                 # API process — REST + WebSocket, no UI mount
│   │   ├── web_app.py             # Web process — serves ui/build/ at /app, dev watcher
│   │   ├── kg_app.py              # Knowledge graph process — owns the sole Kùzu connection
│   │   ├── static.py              # CleanUrlStaticFiles — shared by app.py and web_app.py
│   │   └── log_setup.py           # Rotating log files per concern (server, chroma, kg, ollama…)
│   ├── services/
│   │   ├── vault.py               # Vault CRUD: notes, sources, chats, streams
│   │   ├── stream_runner.py       # Stream refresh execution (search -> dedup -> relevance -> save to Zotero)
│   │   ├── dedup.py               # Shared duplicate-detection logic (stream_runner + /maintenance/deduplicate)
│   │   ├── knowledge_graph_service.py  # Native Kùzu-backed knowledge graph indexer (watchdog, backend-agnostic LLM, per-section) — runs inside kg_app.py
│   │   ├── knowledge_graph_client.py   # Thin HTTP client app.py uses to reach kg_app.py
│   │   ├── chroma_service.py      # ChromaDB semantic index (watchdog, configurable embedding model)
│   │   ├── chat_llm.py            # Backend-agnostic LLM client (ollama/llama_cpp/openrouter/anthropic — ADR-014)
│   │   ├── chat_tools.py          # Chat tool registry (SEARCH_VAULT/GRAPH_CONTEXT/RECALL/THINK) + system prompt assembly
│   │   ├── chat_prompts.py        # User-editable chat system prompt, Excerpt summary prompt
│   │   ├── chat_render.py         # Chat message → sanitized HTML rendering
│   │   ├── chat_migration.py      # `prisma migrate-chats-to-sess`-style helpers
│   │   ├── citation_format.py     # APA formatting for CitedClaimNode.sources / vault Sources (ADR-020)
│   │   ├── resource_lock.py       # Cross-process GPU/compute-pool lease arbitration (ADR-012)
│   │   ├── sync_orchestrator.py   # Server/client vault sync decision logic (prisma-desktop's sync engine)
│   │   ├── injection_defense.py   # wrap_untrusted() — trust-tier fencing for tool results in chat prompts
│   │   ├── html_sanitize.py       # HTML sanitization for rendered notes/chat content
│   │   ├── renderer.py            # Markdown/HTML rendering shared by notes and chat
│   │   ├── source_backfill.py     # `prisma backfill-source-metadata` — retrofits APA fields onto existing Sources
│   │   ├── rate_limiter.py        # Per-source quota control (search sources, IEEE Xplore, etc.)
│   │   └── asset_rewrite.py       # Rewrites relative asset URLs to /vault/assets/... (used by notes/view routes)
│   ├── storage/
│   │   ├── models/
│   │   │   ├── agent_models.py          # PaperMetadata, BookMetadata, SearchResult
│   │   │   ├── vault_models.py          # VaultNode/RenderedNode/VaultListing/StreamStatus, and the chat session graph: Chat, TurnNode, ToolCallNode, ThinkingNode, CitedClaimNode/InferenceNode, MediaNode (ADR-019/ADR-020)
│   │   │   ├── zotero_models.py         # ZoteroItem, ZoteroCollection
│   │   │   ├── chroma_models.py         # ChromaStatus
│   │   │   ├── kg_models.py             # KGStatus, GraphQueryResult
│   │   │   ├── search_models.py         # GraphSearchResult and other search-route response shapes
│   │   │   ├── api_response_models.py   # Typed API response models (Pydantic)
│   │   │   └── source_quality.py        # SourceQuality enum, SOURCE_REGISTRY, validation
│   │   └── pending_queue.py       # Offline write queue (flushed on next online start)
│   ├── cli/
│   │   ├── prisma_cli.py          # `serve`/`status`/`reload-config` -- local-machine-only surface, everything else moved to the API (see docs/wiki/cli.md)
│   │   └── commands/
│   │       ├── auth.py            # prisma auth hash-password
│   │       └── schema.py          # prisma schema export — commits JSON Schema for every VersionedModel to schemas/
│   └── utils/
│       ├── config.py              # TOML config loader, Pydantic-validated models
│       └── text.py                # Text utilities (significant_words, etc.)
└── ui/                        # SvelteKit frontend (source of truth for all clients)
    ├── src/routes/+page.svelte  # Single-page app — vault tree, viewer, Zotero sidebar
    ├── vite.config.js           # Vite build config (no Tauri-specific overrides)
    ├── svelte.config.js         # adapter-static (SPA mode, fallback: index.html)
    └── build/                   # Output of `npm run build` — served at /app by prisma serve
```

## Pipeline Data Flow

```
POST /review {"topic": ...}
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
       ├─ AnalysisAgent.assess_relevance()  (per paper, via the configured [llm] backend)
       │      └─ discard irrelevant papers
       │
       ├─ ZoteroAgent._check_zotero_duplicate_simple()  (per paper)
       │      └─ skip papers already in Zotero
       │
       ├─ AnalysisAgent.analyze()  (deep LLM analysis on remaining papers)
       │
       ├─ ZoteroAgent / ZoteroClient.save_items()  (if auto_save enabled)
       │
       └─ ReportAgent.generate() → Markdown file
```

## Research Streams Data Flow

```
POST /streams/{slug}/run
       │
       ▼
stream_runner.run_stream()
       │
       ├─ SearchAgent.search()  (using stream's query)
       │
       ├─ dedup.py: find_duplicate() against existing collection items
       │      (DOI/title exact match -> ZoteroClient.find_by_identifier() -> stem overlap -> LLM)
       │
       ├─ ZoteroClient.ensure_collection()  (idempotent: existing or newly created)
       │
       ├─ ZoteroClient.add_paper() / add_item_to_collection()  (new papers → Zotero collection)
       │
       └─ Smart tag application + stream state saved via VaultService.save_stream()
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
| Knowledge graph | `8768` (loopback only) | `prisma.server.kg_app` — owns the sole Kùzu connection, does all LLM extraction |

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
| GET | `/status` | Config, vault stats, knowledge graph state, ChromaDB state, Zotero, Ollama reachability |
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
| GET | `/search/deep` | Semantic search via ChromaDB + knowledge graph re-ranking |
| GET | `/home` | Render the vault home/dashboard note |
| POST | `/render` | Render arbitrary markdown to HTML |
| GET | `/vault/assets/{path}` | Serve vault static assets |
| POST | `/reload` | Reinitialize vault, Zotero, knowledge graph, ChromaDB client (in-process state, not a restart) |
| POST | `/reload/vault` | Reinitialize VaultService from config |
| POST | `/reload/zotero` | Reinitialize Zotero client |
| POST | `/reload/indexer` | Restart knowledge graph indexer |
| POST | `/reload/chroma` | Rebuild the ChromaDB client (reconnects to the Chroma server process) |
| GET | `/ws` | WebSocket — server push events (`vault_change`, `stream_progress`) |

### Admin/instrumentation (API process)

Namespaced under `/admin/kg/` rather than sitting alongside the user-facing routes above,
so they read unambiguously as ops/diagnostic tools — the UI never calls any of these. Each
proxies through `KnowledgeGraphClient` to the knowledge graph process (see ADR-009's hybrid
retrieval design and its "Follow-up" section for what the KG layer is actually for).

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/kg/taint` | Mark the whole index stale; next cycle re-indexes changed files |
| POST | `/admin/kg/drop` | Drop the entire Kùzu graph + manifest, forcing a full reindex from scratch |
| GET | `/admin/kg/dead-letters` | List failed-extraction records (file, source, error, retries, time) without discarding them |
| DELETE | `/admin/kg/dead-letters` | Discard dead-letter records so the next cycle retries them fresh |
| GET | `/admin/kg/entities?path=…` | Raw entities + relationship edges extracted from one vault-relative file — inspect extraction quality directly |
| GET | `/admin/kg/search?q=…` | Raw keyword match over Entity nodes only, bypassing Ollama + ChromaDB — isolates the KG layer so a bad `/search/deep` result can be attributed to extraction vs. ranking vs. the LLM |

## Background Services

Two daemon threads start in the **API process**:

| Service | What it does |
|---------|--------------|
| ChromaDB indexer | Watchdog on vault root; on change, embeds changed `.md` files via the configured `[retrieval]` embedding model (`bge-m3`/`nomic-embed-text`/etc., any Ollama- or llama.cpp-compatible model) and upserts into the ChromaDB **server process** (`chromadb.HttpClient`, not embedded — see ADR-012) at `{vault_root}/chromadb/`. Skips files whose mtime hasn't changed since the last upsert, even if a spurious filesystem event re-queues them. Records which model built the collection (`chromadb/embedding_model.json`) and refuses to read/write against it if the configured model ever drifts, rather than silently mixing embedding spaces. |
| Stream scheduler | Polls every 5 min; runs active streams whose `next_update` is past. |

One daemon thread starts in the **Knowledge graph process** (`kg_app.py`, its own supervised worker — see ADR-012's follow-up section):

| Service | What it does |
|---------|--------------|
| Knowledge graph indexer | Watchdog on vault root; on change, extracts entities/relationships via the configured `[llm]` backend (Ollama, llama.cpp, or OpenRouter — same backend-agnostic interface chat uses, ADR-014) **per section** (chunked with `semchunk`, token-budget-aware — not per-file, so no single oversized document can exceed the model's budget) and upserts into an embedded Kùzu graph DB at `{vault_root}/kg-out/`. Owns the sole Kùzu connection for the process's lifetime. `app.py` talks to it over HTTP via `KnowledgeGraphClient`. Replaces the third-party `graphify` dependency — see `TODO.md`. |

One daemon thread starts in the **Web process**:

| Service | What it does |
|---------|--------------|
| UI watcher | Polls `ui/src/` mtime hash every 1 s. When source changes, debounces 500 ms, runs `npm run build` in `ui/`, then increments the dev version counter (exposed via `GET /ui/dev/version`). Only active when `ui/src/` exists (dev environment). |

Both indexers wait 20 s after their process starts before the initial full scan, so that process is responsive immediately.

## Search Strategy

**Regular search (`GET /search`):** keyword scoring against an in-memory mtime-keyed index. Files are stat'd on every request; only files whose mtime changed are re-read from disk. Scoring: each matching term +1.0, title match +4.0, all-terms match (AND bonus) +3.0. Returns up to 30 results sorted by score.

**Deep search (`GET /search/deep`):** ChromaDB semantic query (top 60 chunks) → file-level best-chunk scoring → knowledge graph node titles used for title-boost re-ranking → top 20 results. Slower but semantics-aware.

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
| macOS / iOS / Android | Browser PWA | `http://<host>:8766/app` → install via browser |

> WSL2 support existed in `prisma-desktop` as a stopgap before native Linux
> hardware was available, and was dropped 2026-07-30 — Linux-only for now.
> Native Windows/macOS Tauri builds are planned once I've got hardware to test on,
> but aren't a port of the old WSL2-aware code (see `prisma-desktop`'s own
> `.claude/CLAUDE.md` and its CI workflow comments for the current state).

**Tauri shell** (`prisma-desktop/src-tauri/`) is thin — Rust handles only:
- Window lifecycle (create, resize, minimize, maximize, close, drag)
- Settings persistence (`~/.config/prisma-desktop/settings.json`) — server URL, zoom scale, window state
- URL opener (`open_url` command) — `xdg-open`, Linux-only for now

The SvelteKit app detects its runtime via `"__TAURI_INTERNALS__" in window`:
- **Tauri**: uses `@tauri-apps/api` for window commands and settings; `apiBase` from `localStorage` (defaults to the API port, `8765`)
- **Browser/PWA**: `apiBase` defaults to the page's own host on the API's port (`8765`) rather than the page's own origin, since the Web process serving the page and the API are different origins now; overridable via `localStorage` for reverse-proxied deployments

**Dev hot-reload**: `ui/src/` changes trigger an auto-rebuild in the Web process. The client polls `GET /ui/dev/version` on the Web process's own origin every 2 s and calls `window.location.reload()` when the version bumps — a dev-only, self-contained mechanism that doesn't involve the API process or WebSocket at all.
