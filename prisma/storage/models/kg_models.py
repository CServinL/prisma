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
    # The vault-relative path of the document this entity was extracted
    # from -- provenance, so a caller (chat's grounding check, the UI) can
    # resolve it to a citable slug. Optional: not every read path projects
    # it, and a chat-tier-free graph always has one in practice.
    source_file: str | None = None


class EdgeInfo(BaseModel):
    source: str
    relation: str
    target: str
    confidence: str | None = None
    confidence_score: float | None = None
    # Which document asserted this relationship -- the precise citation for
    # a claim about the edge, distinct from either endpoint's own
    # source_file. (In entities_for_file this is always the queried file.)
    source_file: str | None = None


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
    KnowledgeGraphService.top_entities().

    `source_file`/`sample_relations` are populated only by the richer
    `god_nodes()` path (kg_queries.god_nodes); the cache-only
    `top_entities()` priming read leaves them at their defaults, so a
    payload without them still validates on both ends of the wire."""
    id: str
    label: str
    degree: int
    source_file: str | None = None
    sample_relations: list[str] = []


class ExpandNodeResponse(BaseModel):
    """One-hop neighbourhood of a single Entity — the neighbours plus the
    RelatesTo edges connecting them to the queried node. Mirrors
    EntitiesForFileResponse's shape (chat-tier neighbours excluded)."""
    entities: list[EntityInfo]
    edges: list[EdgeInfo]


class AuthorSummary(BaseModel):
    """Distinct `Entity.author` value grouped across the vault — how many
    source files name that author, plus a few example entity ids."""
    author: str
    file_count: int
    sample_entities: list[str] = []


class OrphanEntity(BaseModel):
    id: str
    label: str
    source_file: str | None = None


class VaultHealthResponse(BaseModel):
    """First-cut vault health: entities with zero RelatesTo edges. Full
    disconnected-cluster detection (connected components) is a noted stretch
    follow-up, not part of this cut."""
    orphans: list[OrphanEntity]
    orphan_count: int


class TimelineEntry(BaseModel):
    """An entity whose `source_file` resolves to a Source with a `year` —
    the year comes from vault frontmatter (VaultService), not the graph."""
    id: str
    label: str
    source_file: str | None = None
    year: int | None = None


class SurprisingConnection(BaseModel):
    """A link between two entities (`entity_a`/`entity_b`, real entity ids)
    that no single document ever asserted directly -- see
    kg_queries.surprising_connections() for the exact definition (cservinl:
    "emerges from the KG itself, with no prior knowledge of it anywhere").

    `bridge` is a **label**, not an entity id: the two hops are asserted by
    two different documents' own entity instances (each with its own
    `{stem}_{entity}` id -- see `_extraction_system_prompt`), which share
    the same normalised concept name but are never literally the same
    graph node. There is no single id to report, since two distinct
    instances participated -- the label is what they have in common."""
    entity_a: str
    entity_b: str
    bridge: str
    relation_a: str
    relation_b: str
    score: float
    # The documents `entity_a` / `entity_b` were each extracted from --
    # the citable provenance for a `relational` claim about this link
    # (the bridge label spans documents by construction, so it has no
    # single source to report).
    source_file_a: str | None = None
    source_file_b: str | None = None


class ReadSourceResponse(BaseModel):
    """A bounded slice of one vault document's own raw text — never the
    whole file. `mode` is one of summary/section/literal."""
    slug: str
    mode: str
    query: str | None = None
    text: str
    # section mode: every heading found, so a missed `query` still tells the
    # caller what it could have asked for.
    available_sections: list[str] = []
    # literal mode: total matching lines found (may exceed what's actually
    # returned -- see `truncated`).
    match_count: int | None = None
    # literal mode: True if either more matches existed than were included,
    # or a per-line/total-size budget cut the output short. Found live (PR
    # #104 review): match_count alone caps how many *blocks* are considered,
    # not the total bytes returned -- a single arbitrarily long matching or
    # context line could otherwise still blow the "bounded slice" contract.
    truncated: bool = False
