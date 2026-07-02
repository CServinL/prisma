"""Prisma Knowledge Graph process — owns the sole Kùzu connection and does
all LLM extraction, isolated from the API process (see ADR-012's follow-up
section and TODO.md).

Runs independently: a native-extension crash in Kùzu, or a wedged
extraction call, doesn't take REST/WebSocket traffic down with it, and this
process can be restarted on its own. Kùzu itself only allows one process to
ever hold its database open (verified empirically — see
knowledge_graph_service.py's module docstring), so this process is the only
place `KnowledgeGraphService` may run.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query

from prisma.server import log_setup as _log_setup
from prisma.services.knowledge_graph_service import KnowledgeGraphService
from prisma.services.vault import VaultService

_LOG_PATHS = _log_setup.configure()
_log = logging.getLogger("prisma.knowledge_graph")


# ── Vault root / config helpers — duplicated from app.py/supervisor.py's
# small private resolvers rather than introducing a shared module for a
# one-liner each; same existing pattern in this codebase. ────────────────────

def _resolve_vault_root() -> Path:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        root = cfg.get("vault_root", "").strip()
        if root:
            return Path(root).expanduser().resolve()
    except Exception:
        pass
    return Path.home() / "prisma-vault"


def _ollama_model() -> str:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        return cfg.get("llm", {}).get("model", "prisma-kg:7b")
    except Exception:
        return "prisma-kg:7b"


def _index_extensions() -> tuple[str, ...]:
    from prisma.services.knowledge_graph_service import DEFAULT_INDEX_EXTENSIONS
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        exts = cfg.get("kg", {}).get("index_extensions")
        if exts and isinstance(exts, list):
            return tuple(e if e.startswith(".") else f".{e}" for e in exts)
    except Exception:
        pass
    return DEFAULT_INDEX_EXTENSIONS


_vault = VaultService(vault_root=_resolve_vault_root())
_kg = KnowledgeGraphService(_vault, ollama_model=_ollama_model(), index_extensions=_index_extensions())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _vault.ensure_dirs()
    _kg.start()
    _log.info("knowledge graph process ready")
    yield
    _kg.stop()


app = FastAPI(title="Prisma Knowledge Graph", lifespan=_lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return _kg.status()


@app.post("/mark_stale")
def mark_stale():
    _kg.mark_stale()
    return {"status": "stale"}


@app.post("/drop_index")
def drop_index():
    _kg.drop_index()
    return {"status": "dropped"}


@app.get("/search")
def search(q: str = Query(...), top_k: int = Query(20)):
    return _kg.search(q, top_k=top_k)


@app.get("/ranked_nodes")
def ranked_nodes(q: str = Query(...), top_k: int = Query(20)):
    return _kg.ranked_nodes(q, top_k=top_k)


@app.get("/query")
def query(q: str = Query(...), budget: int = Query(1500)):
    return _kg.query(q, budget=budget)


@app.get("/ollama_ready")
def ollama_ready():
    return {"reachable": _kg._ollama_ready()}
