"""Knowledge-graph admin/diagnostic endpoints (/admin/kg/*).

Built via a factory (`build_admin_router`) taking a getter callable rather
than the raw object, same reasoning as sync_routes.py's `build_sync_router`:
app.py's `/reload/indexer` endpoint rebinds its `_indexer` module global at
runtime, so a router that captured it by value at include_router() time
would keep talking to a stale, replaced instance after a reload.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Query
from pydantic import BaseModel

from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.storage.models.kg_models import DeadLetterEntry, EntitiesForFileResponse
from prisma.storage.models.search_models import GraphSearchResult


class AdminStatusResponse(BaseModel):
    status: str


class AdminRemovedResponse(BaseModel):
    removed: int


def build_admin_router(get_indexer: Callable[[], KnowledgeGraphClient]) -> APIRouter:
    router = APIRouter(prefix="/admin/kg", tags=["admin"])

    @router.post("/taint", response_model=AdminStatusResponse)
    def admin_kg_taint():
        """Mark the index stale so the next cycle re-indexes changed files."""
        get_indexer().mark_stale()
        return {"status": "stale"}

    @router.post("/drop", response_model=AdminStatusResponse)
    def admin_kg_drop():
        """Drop the entire Kùzu graph and tracked manifest, forcing a full reindex from scratch."""
        get_indexer().drop_index()
        return {"status": "dropped"}

    @router.get("/dead-letters", response_model=list[DeadLetterEntry])
    def admin_kg_list_dead_letters():
        """List failed-extraction ("dead letter") records without discarding
        them — see what failed and why before deciding to clear it."""
        return get_indexer().list_dead_letters()

    @router.delete("/dead-letters", response_model=AdminRemovedResponse)
    def admin_kg_clear_dead_letters():
        """Discard recorded dead-letter records so the next incremental cycle
        retries them fresh. Returns the number cleared."""
        removed = get_indexer().clear_dead_letters()
        return {"removed": removed}

    @router.get("/entities", response_model=EntitiesForFileResponse)
    def admin_kg_entities(path: str = Query(...)):
        """Raw entities and relationship edges the knowledge graph extracted
        from one specific vault-relative file path — for inspecting extraction
        quality directly (unlike /search or /search/deep, which only ever
        return file-level scores, never the underlying nodes)."""
        return get_indexer().entities_for_file(path)

    @router.get("/search", response_model=list[GraphSearchResult])
    def admin_kg_search(q: str = Query(..., min_length=1), top_k: int = Query(20)):
        """Raw graph query — keyword match over Entity nodes only, bypassing
        Ollama reasoning and ChromaDB entirely (unlike /search/deep). Isolates
        the KG layer for diagnosis: a bad /search/deep result could be
        extraction, ranking, or the LLM's fault — this narrows it down."""
        return get_indexer().search(q, top_k=top_k)

    return router
