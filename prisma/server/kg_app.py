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
from prisma.storage.models.kg_models import (
    ClearDeadLettersResponse,
    DeadLetterEntry,
    EntitiesForFileResponse,
    GraphQueryResult,
    GraphSearchResult,
    KGStatus,
    MarkStaleResponse,
    OllamaReadyResponse,
    RankedNode,
    StatusResponse,
    TaintFileResponse,
    TopEntity,
)

_LOG_PATHS = _log_setup.configure()
_log = logging.getLogger("prisma.knowledge_graph")


# ── Config — loaded once here; supervisor.py keeps its own separate,
# deliberately stdlib-only resolver (see its module docstring's "stdlib
# only" constraint) since it can't depend on Pydantic. ─────────────────────

def _load_config():
    """Returns (ConfigLoader-or-None, PrismaConfig). A broken/unreadable
    config.toml falls back to an in-memory default PrismaConfig() rather
    than stopping this process from starting at all -- every field below
    already has a sensible default in the Pydantic model, so a load
    failure and "config.toml not present" should behave identically."""
    from prisma.utils.config import ConfigLoader, PrismaConfig
    try:
        loader = ConfigLoader()
        return loader, loader.config
    except Exception as exc:
        _log.warning("config load failed, falling back to in-memory defaults: %s", exc)
        return None, PrismaConfig()


def _resolve_vault_root(loader) -> Path:
    if loader is not None:
        try:
            return loader.get_vault_root()
        except Exception as exc:
            _log.warning("get_vault_root() failed, falling back to ~/prisma-vault: %s", exc)
    return Path.home() / "prisma-vault"


def _resolve_kg_api_key(llm_config) -> str:
    try:
        return llm_config.resolve_api_key()
    except Exception:
        _log.warning("could not resolve openrouter API key for KG extraction", exc_info=True)
        return "ollama"


def _normalize_index_extensions(exts: list[str]) -> tuple[str, ...]:
    from prisma.services.knowledge_graph_service import DEFAULT_INDEX_EXTENSIONS
    if not exts:
        return DEFAULT_INDEX_EXTENSIONS
    return tuple(e if e.startswith(".") else f".{e}" for e in exts)


_loader, _cfg = _load_config()

_vault = VaultService(vault_root=_resolve_vault_root(_loader))
_kg = KnowledgeGraphService(
    _vault,
    ollama_model=_cfg.llm.model,
    ollama_base_url=_cfg.llm.base_url,
    provider=_cfg.llm.provider,
    api_key=_resolve_kg_api_key(_cfg.llm),
    context_window_override=_cfg.llm.context_window,
    max_output_fraction=_cfg.kg.max_output_fraction,
    index_extensions=_normalize_index_extensions(_cfg.kg.index_extensions),
    extraction_concurrency=_cfg.kg.extraction_concurrency,
    token_budget=_cfg.kg.token_budget,
    max_entities=_cfg.kg.max_entities,
    max_relationships=_cfg.kg.max_relationships,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _vault.ensure_dirs()
    _kg.start()
    _log.info("knowledge graph process ready")
    yield
    _kg.stop()


app = FastAPI(title="Prisma Knowledge Graph", lifespan=_lifespan)


@app.get("/health", response_model=StatusResponse)
def health():
    return {"status": "ok"}


@app.get("/status", response_model=KGStatus)
def status():
    return _kg.status()


@app.post("/mark_stale", response_model=MarkStaleResponse)
def mark_stale(path: str | None = None):
    _kg.mark_stale(path)
    return {"status": _kg.status().state}


@app.post("/drop_index", response_model=StatusResponse)
def drop_index():
    _kg.drop_index()
    return {"status": "dropped"}


@app.post("/taint_file", response_model=TaintFileResponse)
def taint_file(rel: str = Query(...)):
    tainted = _kg.taint_file(rel)
    return {"tainted": tainted}


@app.get("/list_dead_letters", response_model=list[DeadLetterEntry])
def list_dead_letters():
    return _kg.list_dead_letters()


@app.post("/clear_dead_letters", response_model=ClearDeadLettersResponse)
def clear_dead_letters():
    removed = _kg.clear_dead_letters()
    return {"removed": removed}


@app.get("/entities_for_file", response_model=EntitiesForFileResponse)
def entities_for_file(rel: str = Query(...)):
    return _kg.entities_for_file(rel)


@app.get("/search", response_model=list[GraphSearchResult])
def search(q: str = Query(...), top_k: int = Query(20)):
    """Raw graph query — keyword match over Entity nodes only, bypassing
    Ollama reasoning and ChromaDB entirely. Diagnostic tool: isolates the KG
    layer so a bad /search/deep result can be attributed to extraction vs.
    ranking vs. the LLM, rather than treated as one opaque failure."""
    return _kg.search(q, top_k=top_k)


@app.get("/ranked_nodes", response_model=list[RankedNode])
def ranked_nodes(q: str = Query(...), top_k: int = Query(20)):
    return _kg.ranked_nodes(q, top_k=top_k)


@app.get("/query", response_model=list[GraphQueryResult])
def query(q: str = Query(...), budget: int = Query(1500)):
    return _kg.query(q, budget=budget)


@app.get("/top_entities", response_model=list[TopEntity])
def top_entities(limit: int = Query(15)):
    """Cached ranking only -- no live Cypher call on this request path, see
    KnowledgeGraphService.top_entities()."""
    return _kg.top_entities(limit=limit)


@app.get("/ollama_ready", response_model=OllamaReadyResponse)
def ollama_ready():
    return {"reachable": _kg._ollama_ready()}
