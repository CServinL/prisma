"""Public knowledge-graph capability endpoints (/graph/*).

Distinct from /admin/kg/* (diagnostic, the UI never calls it): this is a
real public capability surface — the "usable another way" counterpart to
the chat tool loop, and what a future MCP server would wrap. Every Phase-A
Kùzu-backed capability gets a route here regardless of whether it also has
a chat ToolSpec.

Built via a factory (`build_graph_router`) taking a getter callable rather
than the raw client, same reasoning as admin_routes.py: app.py's
`/reload/indexer` rebinds its `_indexer` module global, so a router that
captured it by value would keep talking to a stale instance after a reload.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Query

from prisma.services.kg_queries import (
    AUTHORS_MAX,
    DEFAULT_AUTHORS,
    DEFAULT_EXPAND,
    DEFAULT_TIMELINE,
    DEFAULT_TOP_ENTITIES,
    EXPAND_MAX,
    GOD_NODES_MAX,
    SURPRISING_CONNECTIONS_MAX,
    TIMELINE_MAX,
    VAULT_HEALTH_MAX,
)
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.storage.models.kg_models import (
    AuthorSummary,
    ExpandNodeResponse,
    SurprisingConnection,
    TimelineEntry,
    TopEntity,
    VaultHealthResponse,
)


def build_graph_router(get_client: Callable[[], KnowledgeGraphClient]) -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["graph"])

    @router.get("/expand_node", response_model=ExpandNodeResponse)
    def expand_node(id: str = Query(..., min_length=1, max_length=512),
                    limit: int = Query(DEFAULT_EXPAND, ge=1, le=EXPAND_MAX)):
        """One-hop neighbourhood of a knowledge-graph entity id — its direct
        neighbours and the relationships connecting them. `limit` caps each
        direction (outgoing/incoming)."""
        return get_client().expand_node(id, limit=limit)

    @router.get("/god_nodes", response_model=list[TopEntity])
    def god_nodes(limit: int = Query(DEFAULT_TOP_ENTITIES, ge=1, le=GOD_NODES_MAX)):
        """Most-connected hub entities across the whole vault, each with its
        source files and a few sample relation strings. Cache-only read."""
        return get_client().god_nodes(limit=limit)

    @router.get("/surprising_connections", response_model=list[SurprisingConnection])
    def surprising_connections(limit: int = Query(DEFAULT_TOP_ENTITIES, ge=1, le=SURPRISING_CONNECTIONS_MAX)):
        """2-hop links between entities that no single document ever
        asserted directly — cached, background-computed (see
        KnowledgeGraphService.surprising_connections())."""
        return get_client().surprising_connections(limit=limit)

    @router.get("/authors", response_model=list[AuthorSummary])
    def authors(limit: int = Query(DEFAULT_AUTHORS, ge=1, le=AUTHORS_MAX)):
        """Distinct entity authors grouped across the vault, by how many
        source files name each. Cache-only read."""
        return get_client().authors(limit=limit)

    @router.get("/vault_health", response_model=VaultHealthResponse)
    def vault_health(limit: int = Query(VAULT_HEALTH_MAX, ge=1, le=VAULT_HEALTH_MAX)):
        """First-cut vault health: entities with no relationship edges.
        Cache-only read; `orphan_count` is the true total, `orphans` is
        sliced to `limit`."""
        return get_client().vault_health(limit=limit)

    @router.get("/timeline", response_model=list[TimelineEntry])
    def timeline(q: str = Query(..., min_length=1, max_length=512),
                 limit: int = Query(DEFAULT_TIMELINE, ge=1, le=TIMELINE_MAX)):
        """Entities matching `q`, joined to their Source publication year,
        sorted chronologically. `limit` caps matched entities and entries."""
        return get_client().timeline(q, limit=limit)

    return router
