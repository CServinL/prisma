"""prisma — system architecture (multi-view collection).

Run: .venv/bin/python docs/diagrams/01_system_overview.py

Three views in one HTML file (sidebar navigator):
  - Overview     : all layers client → API → services → storage → external
  - Service layer: services and their internal responsibility split
  - Data layer   : storage components and what writes/reads them
"""
from pathlib import Path
from sysatlas import SystemMap

OUT = Path(__file__).with_suffix(".html")

# ── View 1: Overview (all layers) ─────────────────────────────────────────────
ov = SystemMap(title="prisma — system overview")

ov.group("Desktop",    color="#6366f1", label="Desktop clients")
ov.group("Web",        color="#8b5cf6", label="Web / PWA clients")
ov.group("Supervisor", color="#f43f5e", label="Supervisor (:8760, dependency-free)")
ov.group("API",        color="#0ea5e9", label="API process (:8765)")
ov.group("WebProc",    color="#a78bfa", label="Web process (:8766)")
ov.group("Chroma",     color="#22c55e", label="ChromaDB server (:8767)")
ov.group("Services",   color="#10b981", label="Service layer")
ov.group("Local",      color="#f59e0b", label="Local storage")
ov.group("Windows",    color="#ef4444", label="Windows host")
ov.group("Internet",   color="#64748b", label="Internet")

ov.add_component("tauri_shell",  label="Tauri Shell",      layer="clients",   group="Desktop",   tech="Rust / Tauri v2")
ov.add_component("pwa_browser",  label="Browser / PWA",    layer="clients",   group="Web",       tech="Chrome / Safari")
ov.add_component("svc_worker",   label="Service Worker",   layer="clients",   group="Web",       tech="Workbox — offline cache")

ov.add_component("supervisor",   label="Supervisor",        layer="supervisor", group="Supervisor", tech="stdlib only — spawns/monitors workers")

ov.add_component("fastapi",      label="API app",           layer="api",       group="API",       tech="prisma.server.app")
ov.add_component("ws_endpoint",  label="WebSocket /ws",     layer="api",       group="API",       tech="push: vault_change / stream_progress")

ov.add_component("web_app",      label="Web app",           layer="webproc",   group="WebProc",   tech="prisma.server.web_app")
ov.add_component("ui_static",    label="Static /app",       layer="webproc",   group="WebProc",   tech="ui/build/ → StaticFiles")
ov.add_component("ui_watcher",   label="UI watcher",        layer="webproc",   group="WebProc",   tech="mtime poll → npm build (dev only)")

ov.add_component("chroma_server", label="chroma run",       layer="chroma",    group="Chroma",    tech="ChromaDB's own server — not embedded")

ov.add_component("vault_svc",    label="VaultService",      layer="services",  group="Services",  tech="Markdown CRUD")
ov.add_component("zotero_svc",   label="ZoteroService",     layer="services",  group="Services",  tech="Hybrid client")
ov.add_component("graphify_svc", label="GraphifyService",   layer="services",  group="Services",  tech="Watchdog + subprocess + Ollama")
ov.add_component("chroma_svc",   label="ChromaService",     layer="services",  group="Services",  tech="Watchdog + HttpClient")
ov.add_component("stream_mgr",   label="StreamManager",     layer="services",  group="Services",  tech="Scheduler + agents")

ov.add_component("vault_fs",     label="Vault (Markdown)",  layer="storage",   group="Local",     tech="~/prisma-vault/")
ov.add_component("chromadb",     label="ChromaDB data",     layer="storage",   group="Local",     tech="vault/chromadb/")
ov.add_component("graphify_out", label="Graphify index",    layer="storage",   group="Local",     tech="vault/graphify-out/")
ov.add_component("ui_build",     label="ui/build/",         layer="storage",   group="Local",     tech="SvelteKit static")
ov.add_component("pending_q",    label="PendingQueue",      layer="storage",   group="Local",     tech="JSON write buffer")

ov.add_component("ollama",       label="Ollama",            layer="external",  group="Windows",   tech=":11434 (GPU)")
ov.add_component("zotero_local", label="Zotero Desktop",    layer="external",  group="Windows",   tech=":23119 read-only")
ov.add_component("zotero_web",   label="Zotero Web API",    layer="external",  group="Internet",  tech="api.zotero.org")
ov.add_component("search_apis",  label="Search APIs",       layer="external",  group="Internet",  tech="arXiv / S2 / OpenLibrary")

ov.connect("tauri_shell",  "fastapi",      label="REST HTTP")
ov.connect("tauri_shell",  "ws_endpoint",  label="WS push")
ov.connect("tauri_shell",  "web_app",      label="loads /app")
ov.connect("pwa_browser",  "fastapi",      label="REST HTTP")
ov.connect("pwa_browser",  "ws_endpoint",  label="WS push")
ov.connect("pwa_browser",  "web_app",      label="loads /app")
ov.connect("pwa_browser",  "svc_worker",   label="cache")
ov.connect("supervisor",   "fastapi",      label="spawns + monitors", style="dashed")
ov.connect("supervisor",   "web_app",      label="spawns + monitors", style="dashed")
ov.connect("supervisor",   "chroma_server",label="spawns + monitors", style="dashed")
ov.connect("web_app",      "ui_static",    label="mounts /app")
ov.connect("web_app",      "ui_watcher",   label="daemon thread")
ov.connect("ui_watcher",   "ui_build",     label="npm run build")
ov.connect("fastapi",      "ws_endpoint",  label="broadcast")
ov.connect("fastapi",      "vault_svc")
ov.connect("fastapi",      "zotero_svc")
ov.connect("fastapi",      "graphify_svc")
ov.connect("fastapi",      "chroma_svc")
ov.connect("fastapi",      "stream_mgr")
ov.connect("vault_svc",    "vault_fs",     label="r/w")
ov.connect("graphify_svc", "graphify_out", label="r/w")
ov.connect("chroma_svc",   "chroma_server",label="HttpClient upsert")
ov.connect("chroma_server","chromadb",     label="persists")
ov.connect("zotero_svc",   "pending_q",    label="enqueue")
ov.connect("ui_static",    "ui_build",     label="serves")
ov.connect("graphify_svc", "ollama",       label="extract (subprocess)")
ov.connect("chroma_svc",   "ollama",       label="embed")
ov.connect("zotero_svc",   "zotero_local", label="reads")
ov.connect("zotero_svc",   "zotero_web",   label="r/w")
ov.connect("stream_mgr",   "search_apis",  label="search")
ov.connect("stream_mgr",   "zotero_svc",   label="save")

# ── View 2: Service layer ──────────────────────────────────────────────────────
sl = SystemMap(title="prisma — service layer detail")

sl.group("API",          color="#0ea5e9", label="API boundary")
sl.group("Research",     color="#6366f1", label="Research pipeline")
sl.group("Knowledge",    color="#10b981", label="Knowledge indexing")
sl.group("Persistence",  color="#f59e0b", label="Persistence")
sl.group("Zotero",       color="#ec4899", label="Zotero integration")

sl.add_component("api_router",   label="API router",       layer="api",       group="API",        tech="FastAPI routes")
sl.add_component("vault_svc",    label="VaultService",     layer="research",  group="Research",   tech="note / source / chat / stream CRUD")
sl.add_component("stream_mgr",   label="StreamManager",    layer="research",  group="Research",   tech="scheduler + run_update()")
sl.add_component("search_agent", label="SearchAgent",      layer="research",  group="Research",   tech="arXiv / S2 / Books / Google")
sl.add_component("analysis_agt", label="AnalysisAgent",    layer="research",  group="Research",   tech="relevance + deep analysis via Ollama")
sl.add_component("report_agent", label="ReportAgent",      layer="research",  group="Research",   tech="Markdown synthesis")
sl.add_component("zotero_agent", label="ZoteroAgent",      layer="research",  group="Research",   tech="dedup + save to Zotero")

sl.add_component("graphify_svc", label="GraphifyService",  layer="knowledge", group="Knowledge",  tech="watchdog → Ollama graph extraction")
sl.add_component("chroma_svc",   label="ChromaService",    layer="knowledge", group="Knowledge",  tech="watchdog → nomic-embed-text")

sl.add_component("vault_fs",     label="Vault files",      layer="persist",   group="Persistence",tech="~/prisma-vault/ (Markdown)")
sl.add_component("chromadb",     label="ChromaDB",         layer="persist",   group="Persistence",tech="vault/chromadb/")
sl.add_component("graphify_out", label="Graphify index",   layer="persist",   group="Persistence",tech="vault/graphify-out/")

sl.add_component("hybrid_client",label="HybridClient",     layer="zotero",    group="Zotero",     tech="online: web+local / offline: local")
sl.add_component("pending_q",    label="PendingQueue",     layer="zotero",    group="Zotero",     tech="offline write buffer")
sl.add_component("zotero_local", label="Zotero Desktop",   layer="zotero",    group="Zotero",     tech=":23119 read-only")
sl.add_component("zotero_web",   label="Zotero Web API",   layer="zotero",    group="Zotero",     tech="api.zotero.org read+write")

sl.connect("api_router",   "vault_svc")
sl.connect("api_router",   "stream_mgr")
sl.connect("api_router",   "graphify_svc", label="taint")
sl.connect("api_router",   "chroma_svc",   label="search")
sl.connect("api_router",   "hybrid_client",label="zotero")
sl.connect("stream_mgr",   "search_agent")
sl.connect("stream_mgr",   "analysis_agt")
sl.connect("stream_mgr",   "zotero_agent")
sl.connect("stream_mgr",   "report_agent")
sl.connect("vault_svc",    "vault_fs")
sl.connect("graphify_svc", "graphify_out")
sl.connect("chroma_svc",   "chromadb")
sl.connect("zotero_agent", "hybrid_client")
sl.connect("hybrid_client","pending_q",    label="offline")
sl.connect("hybrid_client","zotero_local", label="reads")
sl.connect("hybrid_client","zotero_web",   label="r/w")

# ── View 3: Indexing pipeline ──────────────────────────────────────────────────
ix = SystemMap(title="prisma — knowledge indexing pipeline")

ix.group("Trigger",    color="#6366f1", label="Change triggers")
ix.group("Graphify",   color="#10b981", label="Graphify pipeline")
ix.group("Chroma",     color="#0ea5e9", label="ChromaDB pipeline")
ix.group("LLM",        color="#ef4444", label="LLM (Ollama on Windows)")
ix.group("Index",      color="#f59e0b", label="Index storage")

ix.add_component("vault_watchdog", label="Vault watchdog",      layer="trigger",   group="Trigger",  tech="inotify on ~/prisma-vault/")
ix.add_component("startup_scan",   label="Startup scan",        layer="trigger",   group="Trigger",  tech="20s delay → full scan")

ix.add_component("graphify_svc",   label="GraphifyService",     layer="graphify",  group="Graphify", tech="queue changed files")
ix.add_component("graph_prompt",   label="Graph extractor",     layer="graphify",  group="Graphify", tech="entity/relation prompt")
ix.add_component("graphify_store", label="Graphify index",      layer="graphify",  group="Graphify", tech="graphify-out/ (JSON)")

ix.add_component("chroma_svc",     label="ChromaService",       layer="chroma",    group="Chroma",   tech="queue changed .md files")
ix.add_component("chunk_split",    label="Chunker",             layer="chroma",    group="Chroma",   tech="fixed-size / overlap")
ix.add_component("chroma_store",   label="ChromaDB",            layer="chroma",    group="Chroma",   tech="vault/chromadb/ (HNSW)")

ix.add_component("ollama_graph",   label="Ollama (graph)",      layer="llm",       group="LLM",      tech="qwen2.5-graphify:7b")
ix.add_component("ollama_embed",   label="Ollama (embed)",      layer="llm",       group="LLM",      tech="nomic-embed-text")

ix.connect("vault_watchdog", "graphify_svc",   label="changed")
ix.connect("vault_watchdog", "chroma_svc",     label="changed")
ix.connect("startup_scan",   "graphify_svc",   label="scan")
ix.connect("startup_scan",   "chroma_svc",     label="scan")
ix.connect("graphify_svc",   "graph_prompt",   label="content")
ix.connect("graph_prompt",   "ollama_graph",   label="extract", style="dashed")
ix.connect("ollama_graph",   "graph_prompt",   label="JSON", style="dashed")
ix.connect("graph_prompt",   "graphify_store", label="persist")
ix.connect("chroma_svc",     "chunk_split",    label="content")
ix.connect("chunk_split",    "ollama_embed",   label="chunks", style="dashed")
ix.connect("ollama_embed",   "chroma_store",   label="vectors", style="dashed")

SystemMap.save_collection(
    {"Overview": ov, "Service layer": sl, "Indexing pipeline": ix},
    str(OUT),
    title="prisma — architecture",
)
print(f"[sysatlas] wrote {OUT}")
