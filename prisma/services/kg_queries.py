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
                source_file=rel_path,
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
                source_file=rel_path,
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
    RelatesTo edges to them, chat-tier neighbours excluded.

    Two directed queries (outgoing, incoming), not one undirected `-`
    pattern: an undirected match loses which side actually stored the
    relation, and unconditionally reporting `source=node_id` regardless
    would falsely invert any edge really stored as `neighbour ->
    node_id` (e.g. a real "neighbour cites node_id" edge would be reported
    as the false inverse "node_id cites neighbour"). `RelatesTo` is a
    directed rel table (`FROM Entity TO Entity`), so `->` here reads the
    true stored direction."""
    if conn is None or not node_id:
        return ExpandNodeResponse(entities=[], edges=[])
    entities: dict[str, EntityInfo] = {}
    edges: list[EdgeInfo] = []
    try:
        outgoing = conn.execute(
            "MATCH (e:Entity {id: $id})-[r:RelatesTo]->(o:Entity) "
            "WHERE o.trust_tier <> 'chat' "
            "RETURN o.id, o.label, o.file_type, o.trust_tier, o.source_location, o.source_file, "
            "r.relation, r.confidence, r.confidence_score, r.source_file",
            {"id": node_id},
        )
        incoming = conn.execute(
            "MATCH (o:Entity)-[r:RelatesTo]->(e:Entity {id: $id}) "
            "WHERE o.trust_tier <> 'chat' "
            "RETURN o.id, o.label, o.file_type, o.trust_tier, o.source_location, o.source_file, "
            "r.relation, r.confidence, r.confidence_score, r.source_file",
            {"id": node_id},
        )
    except Exception as exc:
        _log.warning("expand_node failed for %s: %s", node_id, exc)
        return ExpandNodeResponse(entities=[], edges=[])
    for result, node_is_source in ((outgoing, True), (incoming, False)):
        while result.has_next():
            (oid, olabel, file_type, trust_tier, source_location, o_source_file,
             relation, confidence, confidence_score, edge_source_file) = result.get_next()
            entities.setdefault(oid, EntityInfo(
                id=oid, label=olabel, file_type=file_type,
                trust_tier=trust_tier, source_location=source_location,
                source_file=o_source_file,
            ))
            edges.append(EdgeInfo(
                source=node_id if node_is_source else oid,
                target=oid if node_is_source else node_id,
                relation=relation, confidence=confidence, confidence_score=confidence_score,
                source_file=edge_source_file,
            ))
    return ExpandNodeResponse(entities=list(entities.values()), edges=edges)


# Skip generating pairs for a bridge-label group larger than this -- a label
# shared by this many entities is effectively a generic/hub-like term (the
# same "least surprising" reasoning hub_ids already applies to specific
# entity ids), and the pair count grows O(n^2) per group.
_MAX_BRIDGE_GROUP_SIZE = 50

# The public route's upper bound (graph_routes.py's `Query(..., le=...)`) and
# the background cache's populate size (KnowledgeGraphService.
# _refresh_surprising_connections()) both read this one constant -- a cache
# populated to a lower limit than the route accepts can never serve a
# request asking for more than the cache actually holds.
SURPRISING_CONNECTIONS_MAX = 100


def surprising_connections(
    conn, hub_ids: "set[str] | frozenset[str]", limit: int = 15,
) -> list[SurprisingConnection]:
    """A link between two entities that emerges from the graph itself with
    no prior knowledge of it anywhere (cservinl's definition) -- i.e. no
    document ever asserted a direct edge between the two endpoints, and the
    two hops that connect them came from *different* source documents (so
    the link isn't just "this one paper mentions both").

    Bridges by normalised `label`, not by entity `id`: `_extraction_system_
    prompt`'s ID format is `{stem}_{entity}` -- every document mints its
    own id namespace, so the same concept extracted from two different
    documents ends up as two different ids
    (e.g. `papera_transformer` / `paperb_transformer`) and can never
    literally be "the same node" for a 2-hop Cypher pattern to walk
    through. `label`, unlike `id`, is the human-readable concept name and
    is comparable across documents. `hub_ids` (the cached top_entities ids)
    exclude a specific hub *instance* from playing the bridge role -- a hub
    connects to everything, so a hub-mediated link is the least surprising
    kind.

    Implemented as one flat edge scan (same "aggregate in Python" shape as
    `god_nodes`/`authors`/`vault_health` above) rather than a multi-hop
    Cypher pattern, both because the bridge is now a label-equality join
    Cypher has no portable way to express here, and because it doubles as
    the direct-edge exclusion set for free (every edge is already in hand)
    instead of a second full scan. Called only from the background index
    thread (see `KnowledgeGraphService._refresh_surprising_connections()`),
    never a request thread -- this is materially heavier than this
    module's other flat-scan queries."""
    if conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (a:Entity)-[r:RelatesTo]-(b:Entity) "
            "WHERE a.trust_tier <> 'chat' AND b.trust_tier <> 'chat' "
            "RETURN a.id, a.label, a.source_file, r.relation, r.confidence_score, "
            "r.source_file, b.id, b.label"
        )
    except Exception as exc:
        _log.warning("surprising_connections edge scan failed: %s", exc)
        return []
    # Keyed by label, not id -- see docstring above.
    direct_label_pairs: set[frozenset] = set()
    by_bridge_label: dict[str, list[tuple]] = {}
    while result.has_next():
        row = result.get_next()
        a_id, a_label, a_source_file, relation, confidence_score, edge_source_file, b_id, b_label = row
        if a_label and b_label:
            direct_label_pairs.add(frozenset((a_label.strip().lower(), b_label.strip().lower())))
        if b_id in hub_ids or not b_label:
            continue
        by_bridge_label.setdefault(b_label.strip().lower(), []).append(row)

    candidates: list[tuple] = []
    for rows in by_bridge_label.values():
        if len(rows) > _MAX_BRIDGE_GROUP_SIZE:
            continue
        for i in range(len(rows)):
            a1_id, a1_label, a1_src, rel1, conf1, edge_src1, b1_id, b1_label = rows[i]
            for j in range(i + 1, len(rows)):
                a2_id, a2_label, a2_src, rel2, conf2, edge_src2, b2_id, _ = rows[j]
                if b1_id == b2_id:
                    continue  # same physical bridge node seen from two of
                               # its own edges, not two documents' separate
                               # instances of a shared concept
                if (a1_id == a2_id or a1_src == a2_src or edge_src1 == edge_src2
                        or a1_label.strip().lower() == a2_label.strip().lower()):
                    continue  # same outer entity (by id or normalised label),
                               # same document, or both hops asserted by the
                               # same document -- an `A -- Bridge -- A` where
                               # both A's are the same concept from two
                               # documents isn't a connection between two things
                label_pair_key = frozenset((a1_label.strip().lower(), a2_label.strip().lower()))
                if label_pair_key in direct_label_pairs:
                    continue
                candidates.append((
                    (conf1 + conf2) / 2, a1_id, a2_id, b1_label, rel1, rel2,
                    a1_src, a2_src, frozenset((a1_id, a2_id)),
                ))

    candidates.sort(key=lambda c: -c[0])
    seen_pairs: set[frozenset] = set()
    out: list[SurprisingConnection] = []
    for score, a_id, c_id, bridge_label, rel_a, rel_b, a_src, c_src, pair_key in candidates:
        if pair_key in seen_pairs:
            continue  # the same (a, c) pair reached via more than one shared bridge label
        seen_pairs.add(pair_key)
        out.append(SurprisingConnection(
            entity_a=a_id, entity_b=c_id, bridge=bridge_label,
            relation_a=rel_a, relation_b=rel_b, score=score,
            source_file_a=a_src, source_file_b=c_src,
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
        slug = vault.slug_for_relpath(source_file)
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
