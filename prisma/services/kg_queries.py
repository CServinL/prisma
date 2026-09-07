"""Pure retrieval functions over the Kùzu knowledge graph.

Split out of `knowledge_graph_service.py` (which already does extraction +
storage + background-loop + progress-tracking in one class — its actual
single responsibility) so most future retrieval work only needs this
bounded file in view, not the whole service. Same reasoning `dedup.py` was
split out of `stream_runner.py`.

Every function takes a live `kuzu.Connection` (the service's sole
persistent one) and returns typed models. No FastAPI/HTTP awareness here —
`kg_app.py` routes call these via the service; `graph_routes.py` reaches
them through `KnowledgeGraphClient`.

`timeline()` additionally takes a `VaultService`: an entity's publication
year is Source frontmatter, deliberately not something the extraction
pipeline emits per entity (see the plan's "Concept timeline" note).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from prisma.storage.models.kg_models import (
    AuthorSummary,
    EdgeInfo,
    EntitiesForFileResponse,
    EntityInfo,
    ExpandNodeResponse,
    OrphanEntity,
    SurprisingConnection,
    TimelineEntry,
    TopEntity,
    VaultHealthResponse,
)
from prisma.storage.models.search_models import GraphSearchResult

_log = logging.getLogger("prisma.knowledge_graph")

DEFAULT_TOP_ENTITIES = 15


def _terms(question: str) -> list[str]:
    """Same tokenisation `search()` has always used — lowercase alnum/underscore
    runs longer than two chars."""
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9_]+", question) if len(t) > 2]


# ── moved verbatim from KnowledgeGraphService (behaviour unchanged) ────────────

def search(conn, question: str, top_k: int = 20) -> list[GraphSearchResult]:
    terms = _terms(question)
    if not terms or conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' RETURN e.id, e.label, e.source_file"
        )
    except Exception as exc:
        _log.warning("search failed: %s", exc)
        return []
    file_scores: dict[str, float] = {}
    while result.has_next():
        eid, label, source_file = result.get_next()
        if not source_file:
            continue
        haystack = f"{eid} {label}".lower()
        score = sum(1.0 for t in terms if t in haystack)
        if score > 0:
            file_scores[source_file] = file_scores.get(source_file, 0.0) + score
    ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
    return [GraphSearchResult(source_file=sf, score=score) for sf, score in ranked]


def entities_for_file(conn, rel_path: str, extracted_by: str | None = None) -> EntitiesForFileResponse:
    if conn is None:
        return EntitiesForFileResponse(entities=[], edges=[])
    entities: list[EntityInfo] = []
    try:
        result = conn.execute(
            "MATCH (e:Entity {source_file: $rel}) "
            "RETURN e.id, e.label, e.file_type, e.trust_tier, e.source_location",
            {"rel": rel_path},
        )
        while result.has_next():
            eid, label, file_type, trust_tier, source_location = result.get_next()
            entities.append(EntityInfo(
                id=eid, label=label, file_type=file_type,
                trust_tier=trust_tier, source_location=source_location,
            ))
    except Exception as exc:
        _log.warning("entities_for_file failed for %s: %s", rel_path, exc)
        return EntitiesForFileResponse(entities=[], edges=[])
    edges: list[EdgeInfo] = []
    try:
        result = conn.execute(
            "MATCH (a:Entity)-[r:RelatesTo {source_file: $rel}]->(b:Entity) "
            "RETURN a.id, r.relation, b.id, r.confidence, r.confidence_score",
            {"rel": rel_path},
        )
        while result.has_next():
            src, relation, dst, confidence, confidence_score = result.get_next()
            edges.append(EdgeInfo(
                source=src, relation=relation, target=dst,
                confidence=confidence, confidence_score=confidence_score,
            ))
    except Exception as exc:
        _log.warning("entities_for_file edges failed for %s: %s", rel_path, exc)
    return EntitiesForFileResponse(entities=entities, edges=edges, extracted_by=extracted_by)


def compute_top_entities(conn, limit: int = DEFAULT_TOP_ENTITIES) -> list[TopEntity]:
    """The priming block's ranking — top-N by undirected RelatesTo degree,
    chat-tier excluded on either endpoint. Moved verbatim; still the
    live-Cypher call the background index thread runs (never a request
    thread — see KnowledgeGraphService.top_entities())."""
    if conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, e.label, count(r) AS degree "
            "ORDER BY degree DESC LIMIT $limit",
            {"limit": limit},
        )
    except Exception as exc:
        _log.warning("top_entities computation failed: %s", exc)
        return []
    out: list[TopEntity] = []
    while result.has_next():
        eid, label, degree = result.get_next()
        out.append(TopEntity(id=eid, label=label, degree=degree))
    return out


# ── Phase A additive capabilities ─────────────────────────────────────────────

def god_nodes(conn, limit: int = DEFAULT_TOP_ENTITIES) -> list[TopEntity]:
    """`compute_top_entities` plus, per top entity, its `source_file` and up
    to 3 sample `relation` strings (TODO.md's sketch:
    `[{entity, connection_count, sample_relations}]`). Aggregated in Python
    off a flat row scan rather than trusting Kùzu list-aggregation
    portability, so behaviour is deterministic across Kùzu versions."""
    if conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, e.label, e.source_file, r.relation"
        )
    except Exception as exc:
        _log.warning("god_nodes computation failed: %s", exc)
        return []
    degree: dict[str, int] = {}
    label: dict[str, str] = {}
    source_file: dict[str, str | None] = {}
    relations: dict[str, list[str]] = {}
    while result.has_next():
        eid, elabel, esrc, relation = result.get_next()
        degree[eid] = degree.get(eid, 0) + 1
        label[eid] = elabel
        source_file[eid] = esrc
        seen = relations.setdefault(eid, [])
        if relation and relation not in seen:
            seen.append(relation)
    ranked = sorted(degree, key=lambda e: -degree[e])[:limit]
    return [
        TopEntity(
            id=eid, label=label[eid], degree=degree[eid],
            source_file=source_file.get(eid), sample_relations=relations.get(eid, [])[:3],
        )
        for eid in ranked
    ]


def expand_node(conn, node_id: str) -> ExpandNodeResponse:
    """One-hop traversal — the queried entity's direct neighbours and the
    RelatesTo edges to them, chat-tier neighbours excluded. Edge direction is
    normalised outward from the queried node (source = `node_id`)."""
    if conn is None or not node_id:
        return ExpandNodeResponse(entities=[], edges=[])
    entities: dict[str, EntityInfo] = {}
    edges: list[EdgeInfo] = []
    try:
        result = conn.execute(
            "MATCH (e:Entity {id: $id})-[r:RelatesTo]-(o:Entity) "
            "WHERE o.trust_tier <> 'chat' "
            "RETURN o.id, o.label, o.file_type, o.trust_tier, o.source_location, "
            "r.relation, r.confidence, r.confidence_score",
            {"id": node_id},
        )
    except Exception as exc:
        _log.warning("expand_node failed for %s: %s", node_id, exc)
        return ExpandNodeResponse(entities=[], edges=[])
    while result.has_next():
        oid, olabel, file_type, trust_tier, source_location, relation, confidence, confidence_score = result.get_next()
        entities.setdefault(oid, EntityInfo(
            id=oid, label=olabel, file_type=file_type,
            trust_tier=trust_tier, source_location=source_location,
        ))
        edges.append(EdgeInfo(
            source=node_id, relation=relation, target=oid,
            confidence=confidence, confidence_score=confidence_score,
        ))
    return ExpandNodeResponse(entities=list(entities.values()), edges=edges)


_SURPRISING_CANDIDATE_CAP = 500  # soft cap on 2-hop candidates before Python-side dedup/hub-filter


def surprising_connections(
    conn, hub_ids: "set[str] | frozenset[str]", limit: int = 15,
) -> list[SurprisingConnection]:
    """A 2-hop link between two entities that emerges from the graph itself
    with no prior knowledge of it anywhere (cservinl's definition) -- i.e.
    no document ever asserted a direct edge between the two endpoints, and
    the two hops came from *different* source documents (so the link isn't
    just "this one paper mentions both"). `hub_ids` (the cached
    top_entities ids) are excluded as the middle/bridge entity: a hub
    bridges everything, so a hub-mediated link is the least surprising
    kind, and the exclusion also keeps the result from being dominated by
    god-node noise.

    Direct-edge exclusion is a Python set-membership check on a separate
    flat edge scan, not a `NOT (a)-[:RelatesTo]-(c)` Cypher pattern
    predicate -- same reasoning as `vault_health()`: that predicate form
    isn't portable across Kùzu versions (confirmed live building this
    module). Called only from the background index thread (see
    `KnowledgeGraphService._refresh_surprising_connections()`), never a
    request thread -- 2-hop enumeration is materially heavier than this
    module's other flat-scan queries."""
    if conn is None:
        return []
    try:
        direct_result = conn.execute("MATCH (a:Entity)-[:RelatesTo]-(c:Entity) RETURN a.id, c.id")
    except Exception as exc:
        _log.warning("surprising_connections direct-edge scan failed: %s", exc)
        return []
    direct_pairs: set[frozenset] = set()
    while direct_result.has_next():
        a_id, c_id = direct_result.get_next()
        direct_pairs.add(frozenset((a_id, c_id)))

    try:
        result = conn.execute(
            "MATCH (a:Entity)-[r1:RelatesTo]-(b:Entity)-[r2:RelatesTo]-(c:Entity) "
            "WHERE a.id <> c.id "
            "AND a.trust_tier <> 'chat' AND b.trust_tier <> 'chat' AND c.trust_tier <> 'chat' "
            "AND r1.source_file <> r2.source_file "
            "AND a.source_file <> c.source_file "
            "RETURN a.id, b.id, c.id, r1.relation, r2.relation, "
            "(r1.confidence_score + r2.confidence_score) / 2 AS score "
            "ORDER BY score DESC LIMIT $cap",
            {"cap": _SURPRISING_CANDIDATE_CAP},
        )
    except Exception as exc:
        _log.warning("surprising_connections query failed: %s", exc)
        return []
    seen_pairs: set[frozenset] = set()
    out: list[SurprisingConnection] = []
    while result.has_next():
        a_id, b_id, c_id, rel_a, rel_b, score = result.get_next()
        pair_key = frozenset((a_id, c_id))
        if b_id in hub_ids or pair_key in direct_pairs or pair_key in seen_pairs:
            continue  # hub-mediated, already directly asserted, or the
                       # undirected MATCH's mirror (c-b-a) of a row already kept
        seen_pairs.add(pair_key)
        out.append(SurprisingConnection(
            entity_a=a_id, entity_b=c_id, bridge=b_id,
            relation_a=rel_a, relation_b=rel_b, score=score,
        ))
        if len(out) >= limit:
            break
    return out


def authors(conn, limit: int = 100) -> list[AuthorSummary]:
    """Distinct `Entity.author` grouped across the vault. Aggregated in
    Python (see `god_nodes`' rationale)."""
    if conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity) "
            "WHERE e.author IS NOT NULL AND e.author <> '' AND e.trust_tier <> 'chat' "
            "RETURN e.author, e.source_file, e.id"
        )
    except Exception as exc:
        _log.warning("authors query failed: %s", exc)
        return []
    files: dict[str, set[str]] = {}
    ids: dict[str, list[str]] = {}
    while result.has_next():
        author, source_file, eid = result.get_next()
        if source_file:
            files.setdefault(author, set()).add(source_file)
        entry = ids.setdefault(author, [])
        if eid not in entry:
            entry.append(eid)
    ranked = sorted(files, key=lambda a: -len(files[a]))[:limit]
    return [
        AuthorSummary(author=a, file_count=len(files[a]), sample_entities=ids.get(a, [])[:5])
        for a in ranked
    ]


def vault_health(conn) -> VaultHealthResponse:
    """Entities with zero RelatesTo edges (in either direction). Computed as
    a set difference in Python rather than a `NOT (e)-[:RelatesTo]-()`
    pattern predicate, which isn't portable across Kùzu versions."""
    if conn is None:
        return VaultHealthResponse(orphans=[], orphan_count=0)
    try:
        connected: set[str] = set()
        result = conn.execute("MATCH (a:Entity)-[:RelatesTo]-(b:Entity) RETURN a.id")
        while result.has_next():
            connected.add(result.get_next()[0])
        orphans: list[OrphanEntity] = []
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' RETURN e.id, e.label, e.source_file"
        )
        while result.has_next():
            eid, label, source_file = result.get_next()
            if eid not in connected:
                orphans.append(OrphanEntity(id=eid, label=label, source_file=source_file))
    except Exception as exc:
        _log.warning("vault_health query failed: %s", exc)
        return VaultHealthResponse(orphans=[], orphan_count=0)
    return VaultHealthResponse(orphans=orphans, orphan_count=len(orphans))


def timeline(conn, vault, question: str) -> list[TimelineEntry]:
    """Entities matching `question` by the same term-match `search()` uses,
    each joined `source_file` -> Source.year via `VaultService`, sorted
    chronologically (year-less entries last)."""
    terms = _terms(question)
    if not terms or conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' RETURN e.id, e.label, e.source_file"
        )
    except Exception as exc:
        _log.warning("timeline query failed: %s", exc)
        return []
    hits: list[tuple[str, str, str | None]] = []
    while result.has_next():
        eid, label, source_file = result.get_next()
        haystack = f"{eid} {label}".lower()
        if any(t in haystack for t in terms):
            hits.append((eid, label, source_file))

    year_by_slug: dict[str, int | None] = {}

    def _year(source_file: str | None) -> int | None:
        if not source_file:
            return None
        slug = Path(source_file).stem
        if slug not in year_by_slug:
            try:
                node = vault.get_any(slug)
                year_by_slug[slug] = getattr(node, "year", None)
            except Exception as exc:  # one unresolvable node must not sink the whole report
                if not isinstance(exc, FileNotFoundError):
                    _log.debug("timeline: could not resolve %s: %s", slug, exc)
                year_by_slug[slug] = None
        return year_by_slug[slug]

    entries = [
        TimelineEntry(id=eid, label=label, source_file=source_file, year=_year(source_file))
        for eid, label, source_file in hits
    ]
    entries.sort(key=lambda e: (e.year is None, e.year or 0))
    return entries
