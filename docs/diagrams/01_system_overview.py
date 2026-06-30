"""prisma — system overview (layered architecture).

Run: .venv/bin/python docs/diagrams/01_system_overview.py

Shows all layers from clients down to external dependencies.
Re-run after adding/removing major components.
"""
from pathlib import Path
from sysatlas import SystemMap

OUT = Path(__file__).with_suffix(".html")

m = SystemMap(title="prisma — system overview")

# Presentation layer
m.add_component("tauri_shell",  label="Tauri Shell",      layer="client",   group="Desktop",    tech="Rust / Tauri v2")
m.add_component("pwa_browser",  label="Browser / PWA",    layer="client",   group="Web",        tech="Chrome / Safari")

# API layer
m.add_component("fastapi",      label="FastAPI app",       layer="api",      group="prisma serve :8765", tech="Python 3.14")
m.add_component("ui_serve",     label="UI static /app",   layer="api",      group="prisma serve :8765", tech="StaticFiles")
m.add_component("ui_watcher",   label="UI watcher",       layer="api",      group="prisma serve :8765", tech="mtime → npm build")

# Service layer
m.add_component("vault_svc",    label="VaultService",     layer="services", group="Services",   tech="Markdown CRUD")
m.add_component("zotero_svc",   label="ZoteroService",    layer="services", group="Services",   tech="Hybrid client")
m.add_component("graphify_svc", label="GraphifyService",  layer="services", group="Services",   tech="Watchdog + Ollama")
m.add_component("chroma_svc",   label="ChromaService",    layer="services", group="Services",   tech="Watchdog + embeddings")
m.add_component("stream_mgr",   label="StreamManager",    layer="services", group="Services",   tech="Scheduler + agents")

# Storage layer
m.add_component("vault_fs",     label="Vault (Markdown)", layer="storage",  group="Local",      tech="~/prisma-vault/")
m.add_component("chromadb",     label="ChromaDB",         layer="storage",  group="Local",      tech="~/prisma-vault/chromadb/")
m.add_component("graphify_out", label="Graphify index",   layer="storage",  group="Local",      tech="graphify-out/")
m.add_component("ui_build",     label="ui/build/",        layer="storage",  group="Local",      tech="SvelteKit static")

# External
m.add_component("ollama",       label="Ollama",           layer="external", group="Windows",    tech=":11434")
m.add_component("zotero_local", label="Zotero Desktop",   layer="external", group="Windows",    tech=":23119 (read)")
m.add_component("zotero_web",   label="Zotero Web API",   layer="external", group="Internet",   tech="api.zotero.org")
m.add_component("search_apis",  label="Search APIs",      layer="external", group="Internet",   tech="arXiv / S2 / OpenLibrary")

# Client → API
m.connect("tauri_shell",  "fastapi",      label="HTTP :8765")
m.connect("pwa_browser",  "fastapi",      label="HTTP :8765")
m.connect("fastapi",      "ui_serve",     label="mounts /app")
m.connect("fastapi",      "ui_watcher",   label="daemon thread")
m.connect("ui_watcher",   "ui_build",     label="npm run build →")

# API → services
m.connect("fastapi",      "vault_svc",    label="")
m.connect("fastapi",      "zotero_svc",   label="")
m.connect("fastapi",      "graphify_svc", label="")
m.connect("fastapi",      "chroma_svc",   label="")
m.connect("fastapi",      "stream_mgr",   label="")

# Services → storage
m.connect("vault_svc",    "vault_fs",     label="read/write")
m.connect("graphify_svc", "graphify_out", label="read/write")
m.connect("chroma_svc",   "chromadb",     label="upsert/query")
m.connect("ui_serve",     "ui_build",     label="serves")

# Services → external
m.connect("graphify_svc", "ollama",       label="graph extraction")
m.connect("chroma_svc",   "ollama",       label="nomic-embed-text")
m.connect("zotero_svc",   "zotero_local", label="reads (offline)")
m.connect("zotero_svc",   "zotero_web",   label="reads + writes")
m.connect("stream_mgr",   "search_apis",  label="paper search")
m.connect("stream_mgr",   "zotero_svc",   label="save results")

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
