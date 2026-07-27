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
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from pydantic import BaseModel

from prisma.server import log_setup as _log_setup
from prisma.services.knowledge_graph_service import KnowledgeGraphService
from prisma.services.vault import VaultService

_LOG_PATHS = _log_setup.configure()
_log = logging.getLogger("prisma.knowledge_graph")


# ── Vault root / config helpers — vault_root and the kg: section both go
# through ConfigLoader/KGConfig (utils/config.py) now; supervisor.py keeps
# its own separate, deliberately stdlib-only resolver (see its module
# docstring's "stdlib + yaml only" constraint) since it can't depend on
# Pydantic. ───────────────────────────────────────────────────────────────

def _resolve_vault_root() -> Path:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_vault_root()
    except Exception:
        return Path.home() / "prisma-vault"


def _ollama_model() -> str:
    try:
        from prisma.utils.config import ConfigLoader
        return ConfigLoader().get_llm_config().model
    except Exception:
        return "qwen2.5:7b-32k"


def _llm_base_url() -> str:
    # Delegates to LLMConfig.base_url (utils/config.py) rather than
    # re-deriving the per-provider URL shape here — that property already
    # knows ollama/llama_cpp are OpenAI-compatible on {host}/v1 while
    # openrouter's is the fixed https://openrouter.ai/api/v1, so this stays
    # correct as providers are added instead of drifting from it.
    try:
        from prisma.utils.config import ConfigLoader
        return ConfigLoader().get_llm_config().base_url
    except Exception:
        return "http://localhost:11434"


def _llm_provider() -> str:
    try:
        from prisma.utils.config import ConfigLoader
        return ConfigLoader().get_llm_config().provider
    except Exception:
        return "ollama"


def _llm_api_key() -> str:
    # Only meaningful for provider=openrouter — ollama/llama_cpp's local
    # OpenAI-compat servers don't check the key at all (dummy value kept for
    # API compatibility with the openai SDK, which requires a non-empty
    # string). Mirrors ChatLLM._resolve_api_key's same env-var-by-name
    # pattern (ADR-014) — the real key never lives in config.yaml itself.
    try:
        from prisma.utils.config import ConfigLoader
        cfg = ConfigLoader().get_llm_config()
        if cfg.provider == "openrouter":
            if not cfg.api_key_env:
                raise RuntimeError("llm.provider is 'openrouter' but llm.api_key_env is not set")
            key = os.environ.get(cfg.api_key_env)
            if not key:
                raise RuntimeError(f"llm.api_key_env={cfg.api_key_env!r} is not set in the environment")
            return key
    except Exception:
        _log.warning("could not resolve openrouter API key for KG extraction", exc_info=True)
    return "ollama"


def _llm_context_window() -> int | None:
    # Static override for providers with no live-queryable endpoint
    # (openrouter) — see LLMConfig.context_window's own docstring.
    try:
        from prisma.utils.config import ConfigLoader
        return ConfigLoader().get_llm_config().context_window
    except Exception:
        return None


def _max_output_fraction() -> float:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_kg_config().max_output_fraction
    except Exception:
        return 0.25


def _max_entities() -> int:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_kg_config().max_entities
    except Exception:
        return 15


def _max_relationships() -> int:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_kg_config().max_relationships
    except Exception:
        return 20


def _index_extensions() -> tuple[str, ...]:
    from prisma.services.knowledge_graph_service import DEFAULT_INDEX_EXTENSIONS
    from prisma.utils.config import ConfigLoader
    try:
        exts = ConfigLoader().get_kg_config().index_extensions
        if exts:
            return tuple(e if e.startswith(".") else f".{e}" for e in exts)
    except Exception:
        pass
    return DEFAULT_INDEX_EXTENSIONS


def _extraction_concurrency() -> int:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_kg_config().extraction_concurrency
    except Exception:
        return 3


def _token_budget() -> int:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_kg_config().token_budget
    except Exception:
        return 1000


_vault = VaultService(vault_root=_resolve_vault_root())
_kg = KnowledgeGraphService(
    _vault,
    ollama_model=_ollama_model(),
    ollama_base_url=_llm_base_url(),
    provider=_llm_provider(),
    api_key=_llm_api_key(),
    context_window_override=_llm_context_window(),
    max_output_fraction=_max_output_fraction(),
    index_extensions=_index_extensions(),
    extraction_concurrency=_extraction_concurrency(),
    token_budget=_token_budget(),
    max_entities=_max_entities(),
    max_relationships=_max_relationships(),
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _vault.ensure_dirs()
    _kg.start()
    _log.info("knowledge graph process ready")
    yield
    _kg.stop()


# ── Response models ───────────────────────────────────────────────────────
# Every route below previously returned whatever KnowledgeGraphService's
# dict-typed query methods handed back verbatim -- no response_model, no
# OpenAPI schema, no validation that a shape change on the service side is
# actually still what a route claims to return. Same underlying data, just
# now declared and checked, mirroring the same dict keys these already had.

class StatusResponse(BaseModel):
    status: str


class MarkStaleResponse(BaseModel):
    status: str


class TaintFileResponse(BaseModel):
    tainted: bool


class ClearDeadLettersResponse(BaseModel):
    removed: int


class DeadLetterEntry(BaseModel):
    file: str
    source_file: str | None = None
    reason: str | None = None
    error: str | None = None
    retries: str | None = None
    time: str | None = None


class DroppedChunkInfo(BaseModel):
    source_file: str
    error: str
    retries: int
    reason: str
    time: str
    dead_letter_path: str | None = None


class KGStatus(BaseModel):
    state: str
    last_indexed: str | None = None
    last_error: str | None = None
    current_activity: str | None = None
    sync_total: int
    sync_done: int
    current_file: str | None = None
    current_file_chunks_done: int
    current_file_chunks_total: int
    chunk_avg_duration_ms: float | None = None
    chunk_duration_samples: int
    chunk_avg_retries: float | None = None
    chunk_avg_size_tokens: float | None = None
    dropped_chunks_total: int
    dropped_chunks_recent: list[DroppedChunkInfo]


class EntityInfo(BaseModel):
    id: str
    label: str
    file_type: str | None = None
    trust_tier: str | None = None
    source_location: str | None = None


class EdgeInfo(BaseModel):
    source: str
    relation: str
    target: str
    confidence: str | None = None
    confidence_score: float | None = None


class EntitiesForFileResponse(BaseModel):
    entities: list[EntityInfo]
    edges: list[EdgeInfo]
    extracted_by: str | None = None


class GraphSearchResult(BaseModel):
    source_file: str
    score: float


class RankedNode(BaseModel):
    source_file: str
    score: float
    label: str = ""


class GraphQueryResult(BaseModel):
    text: str


class OllamaReadyResponse(BaseModel):
    reachable: bool


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
    return {"status": _kg.status()["state"]}


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


@app.get("/ollama_ready", response_model=OllamaReadyResponse)
def ollama_ready():
    return {"reachable": _kg._ollama_ready()}
