# Architecture

## Package Structure

```
prisma/                        # Python package (pip install prisma)
├── coordinator.py             # Pipeline orchestrator
├── connectivity.py            # Network monitor (online/offline detection)
├── agents/
│   ├── search_agent.py        # Multi-source paper/book search
│   ├── analysis_agent.py      # LLM relevance + deep analysis
│   ├── report_agent.py        # Report synthesis and generation
│   └── zotero_agent.py        # Zotero search and item creation
├── integrations/
│   └── zotero/
│       ├── client.py          # ZoteroClient factory (from_config)
│       ├── hybrid_client.py   # Online: Web API reads+writes / Local API reads
│       ├── local_api_client.py  # Offline reads via Zotero Desktop HTTP
│       ├── desktop_client.py  # Desktop-specific operations
│       └── unified_client.py  # Common interface all clients implement
├── services/
│   └── research_stream_manager.py  # Stream lifecycle management
├── storage/
│   ├── models/
│   │   ├── agent_models.py          # PaperMetadata, BookMetadata, SearchResult, CoordinatorResult
│   │   ├── research_stream_models.py  # ResearchStream, StreamStatus, RefreshFrequency
│   │   ├── zotero_models.py         # ZoteroItem, ZoteroCollection, ZoteroSearchQuery
│   │   ├── api_response_models.py   # Typed API response models (Pydantic)
│   │   └── source_quality.py        # SourceQuality enum, SOURCE_REGISTRY, validation
│   └── pending_queue.py       # Offline write queue (flushed on next online start)
├── cli/
│   ├── prisma_cli.py          # Click root group + global options
│   └── commands/
│       ├── streams.py         # prisma streams subcommands
│       ├── zotero.py          # prisma zotero subcommands
│       └── cleanup.py         # prisma cleanup subcommands
└── utils/
    └── config.py              # YAML config loader with dot-path access
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

## Key Design Decisions

- **No message queue or microservices** — direct function calls between components (ADR-001, ADR-003, ADR-005)
- **SQLite not used for streams** — streams stored as JSON in `data/research_streams.json`
- **Pydantic models throughout** — all API responses and internal data validated with Pydantic v2
- **Config accessed via dot-path** — `config.get('sources.zotero.enabled', False)`
- **Offline-first for reads** — writes queued, reads degrade gracefully to local Zotero HTTP
- **Entry point** — `prisma.cli.prisma_cli:cli` registered in `pyproject.toml [project.scripts]`

## Desktop App Architecture (Tauri)

The planned desktop app wraps Prisma + Graphify in a Tauri shell. Responsibility is split between Rust (Tauri backend) and Python (Prisma sidecar):

| Rust (Tauri backend)     | Python (Prisma sidecar)    |
|--------------------------|----------------------------|
| File system access       | Zotero API (local + web)   |
| Window/tray management   | Ollama/LLM calls           |
| Graph rendering commands | Graphify corpus extraction |
| Caching, config          | Prisma stream coordination |

The frontend (JS/Svelte) calls Tauri commands → Rust handles natively or delegates to the Python sidecar over a local socket. Python is never called directly from the frontend.
