"""Typed shapes for the knowledge graph process's HTTP API.

Shared between server/kg_app.py (declares these as response_model= on its
routes) and services/knowledge_graph_client.py (the api process's HTTP
client to kg_app.py, which now deserializes into these same models instead
of handing back raw dict/list[dict] -- one shape, validated on both ends of
the wire, not just the server side.
"""
from __future__ import annotations

from pydantic import BaseModel


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
    # Vault node slugs the answer synthesizes across -- surfaced so chat's
    # footnote attribution (ADR-017) can label GRAPH_CONTEXT-derived claims
    # `relation=relational` with the real documents involved, instead of
    # having no source list for cross-document graph answers at all.
    sources: list[str] = []


class OllamaReadyResponse(BaseModel):
    reachable: bool


class TopEntity(BaseModel):
    """One entity in the vault-overview priming block -- top-N by undirected
    RelatesTo degree (chat-tier excluded). See
    KnowledgeGraphService.top_entities()."""
    id: str
    label: str
    degree: int
