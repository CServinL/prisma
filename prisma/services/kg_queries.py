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
    SuggestedQuestion,
    SurprisingConnection,
    TimelineEntry,
    TopEntity,
    VaultHealthResponse,
)
from prisma.storage.models.search_models import GraphSearchResult

_log = logging.getLogger("prisma.knowledge_graph")

DEFAULT_TOP_ENTITIES = 15  # also the god_nodes / surprising_connections / suggest_questions request default
DEFAULT_AUTHORS = 100
# distinct_entity_labels() backs KnowledgeGraphService.graph_relevance()'s
# text-overlap scoring (stream-triage lightweight design) -- not behind a
# public route of its own, so one constant, not a DEFAULT/MAX pair: every
# label in the vault is a candidate match, not just the highest-degree
# ones, so this is generous relative to DEFAULT_TOP_ENTITIES on purpose.
ENTITY_LABELS_MAX = 2000

# kg_app.py's GraphRelevanceRequest validates against these (the kg worker
# is directly reachable, see that module's docstring); zotero_routes.py
# batches its own calls to the same size instead of trusting every future
# caller to stay under the list-length cap -- one shared home for both
# sides of that literal, not two numbers that happen to match today.
GRAPH_RELEVANCE_MAX_TEXTS = 200
GRAPH_RELEVANCE_MAX_TEXT_LENGTH = 512

# timeline_scan() runs its two entity/edge scans under the service's sole
# Kùzu lock (KnowledgeGraphService.timeline() releases it before
# timeline_build()'s frontmatter reads), so bounding the hit count also
# bounds the follow-on per-document I/O. DEFAULT is what a caller gets
# without asking; MAX bounds the public route (graph_routes.py);
# _DOCS_PER_ENTITY caps the read fan-out from a single hub entity.
DEFAULT_TIMELINE = 50
TIMELINE_MAX = 200
_TIMELINE_DOCS_PER_ENTITY = 10

# expand_node caps each direction's neighbour list -- a hub entity has
# thousands of edges, and the whole scan+serialise runs under the lock.
DEFAULT_EXPAND = 100
EXPAND_MAX = 500


def _terms(question: str) -> list[str]:
    """Same tokenisation `search()` has always used — lowercase alnum/underscore
    runs longer than two chars."""
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9_]+", question) if len(t) > 2]


# ── moved verbatim from KnowledgeGraphService (behaviour unchanged) ────────────

def search(conn, question: str, top_k: int = 20) -> list[GraphSearchResult]:
    terms = _terms(question)
    if not terms or conn is None:
        return []
    file_scores: dict[str, float] = {}
    try:
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' RETURN e.id, e.label, e.source_file"
        )
        while result.has_next():  # the stream can raise mid-scan too, not just execute()
            eid, label, source_file = result.get_next()
            if not source_file:
                continue
            haystack = f"{eid} {label}".lower()
            score = sum(1.0 for t in terms if t in haystack)
            if score > 0:
                file_scores[source_file] = file_scores.get(source_file, 0.0) + score
    except Exception as exc:
        _log.warning("search failed: %s", exc)
        return []
    ranked = sorted(file_scores.items(), key=lambda x: -x[1])[:top_k]
    return [GraphSearchResult(source_file=sf, score=score) for sf, score in ranked]


def entities_for_file(conn, rel_path: str, extracted_by: str | None = None) -> EntitiesForFileResponse:
    """Raw entities/edges extracted from one exact file. Deliberately NOT
    trust-tier filtered: it's addressed by `source_file` (no join, no id
    collision), only ever reached from the /admin/kg inspector -- never a
    citation/grounding path -- and inspecting a chat file's own extraction
    is a legitimate diagnostic use that a chat-tier filter would break."""
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
    out: list[TopEntity] = []
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, e.label, count(r) AS degree "
            "ORDER BY degree DESC LIMIT $limit",
            {"limit": limit},
        )
        while result.has_next():
            eid, label, degree = result.get_next()
            out.append(TopEntity(id=eid, label=label, degree=degree))
    except Exception as exc:
        _log.warning("top_entities computation failed: %s", exc)
        return []
    return out


def hub_ids(conn, min_degree: int) -> set[str]:
    """*Every* entity with undirected RelatesTo degree >= `min_degree`
    (chat-tier excluded on both ends) -- not just the priming cache's top
    slice. surprising_connections excludes these as bridges."""
    if conn is None:
        return set()
    out: set[str] = set()
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, count(r) AS degree"
        )
        while result.has_next():
            eid, degree = result.get_next()
            if degree >= min_degree:
                out.add(eid)
    except Exception as exc:
        _log.warning("hub_ids computation failed: %s", exc)
        return set()
    return out


# ── Phase A additive capabilities ─────────────────────────────────────────────

def god_nodes(conn, limit: int = DEFAULT_TOP_ENTITIES) -> list[TopEntity]:
    """`compute_top_entities` plus, per top entity, up to 3 sample `relation`
    strings and the distinct documents that asserted its edges. `source_files`
    is the edges' provenance, not `Entity.source_file` (last-writer -- see
    `SurprisingConnection`). Aggregated in Python off a flat scan rather than
    trusting Kùzu list-aggregation portability."""
    if conn is None:
        return []
    degree: dict[str, int] = {}
    label: dict[str, str] = {}
    relations: dict[str, list[str]] = {}
    sources: dict[str, list[str]] = {}
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, e.label, r.relation, r.source_file"
        )
        while result.has_next():
            eid, elabel, relation, edge_src = result.get_next()
            degree[eid] = degree.get(eid, 0) + 1
            label[eid] = elabel
            seen = relations.setdefault(eid, [])
            if relation and relation not in seen:
                seen.append(relation)
            srcs = sources.setdefault(eid, [])
            if edge_src and edge_src not in srcs:
                srcs.append(edge_src)
    except Exception as exc:
        _log.warning("god_nodes computation failed: %s", exc)
        return []
    ranked = sorted(degree, key=lambda e: -degree[e])[:limit]
    return [
        TopEntity(
            id=eid, label=label[eid], degree=degree[eid],
            sample_relations=relations.get(eid, [])[:3],
            source_files=sources.get(eid, [])[:5],
        )
        for eid in ranked
    ]


_EXPAND_COLS = (
    "o.id, o.label, o.file_type, o.trust_tier, o.source_location, o.source_file, "
    "r.relation, r.confidence, r.confidence_score, r.source_file"
)
# `o.id <> $id` drops a self-loop edge, which would otherwise match both
# directed queries and list the node as its own neighbour.
_EXPAND_WHERE = "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' AND o.id <> $id"


def expand_node(conn, node_id: str, limit: int = DEFAULT_EXPAND) -> ExpandNodeResponse:
    """One-hop traversal — the queried entity's direct neighbours and the
    RelatesTo edges to them, chat tier excluded on both the queried node and
    the neighbour (the result grounds a chat answer's citations).

    Two directed queries (outgoing, incoming) rather than one undirected
    `-` pattern, which would lose the stored edge direction and could
    report a neighbour->node_id edge as its inverse. `limit` caps each
    direction."""
    if conn is None or not node_id:
        return ExpandNodeResponse(entities=[], edges=[])
    entities: dict[str, EntityInfo] = {}
    edges: list[EdgeInfo] = []
    try:
        outgoing = conn.execute(
            f"MATCH (e:Entity {{id: $id}})-[r:RelatesTo]->(o:Entity) {_EXPAND_WHERE} "
            f"RETURN {_EXPAND_COLS} LIMIT $limit",
            {"id": node_id, "limit": limit},
        )
        incoming = conn.execute(
            f"MATCH (o:Entity)-[r:RelatesTo]->(e:Entity {{id: $id}}) {_EXPAND_WHERE} "
            f"RETURN {_EXPAND_COLS} LIMIT $limit",
            {"id": node_id, "limit": limit},
        )
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
    except Exception as exc:
        _log.warning("expand_node failed for %s: %s", node_id, exc)
        return ExpandNodeResponse(entities=[], edges=[])
    return ExpandNodeResponse(entities=list(entities.values()), edges=edges)


# A bridge label shared by more than this many entities is a generic term,
# not a surprising link -- and the pair count is O(n^2) per group.
_MAX_BRIDGE_GROUP_SIZE = 50

# Each pairs a public route's `Query(..., le=...)` with the background cache's
# populate size, so the cache always holds at least what a request can ask
# for. god_nodes/authors/vault_health/suggest_questions are cache-only reads
# on the request path (KnowledgeGraphService) -- their full scans run on the
# index thread.
SURPRISING_CONNECTIONS_MAX = 100
GOD_NODES_MAX = 100
SUGGEST_QUESTIONS_MAX = 100
AUTHORS_MAX = 500
VAULT_HEALTH_MAX = 500


def surprising_connections(
    conn, hub_ids: "set[str] | frozenset[str]", limit: int = 15,
) -> list[SurprisingConnection]:
    """A link between two entities that no single document connects, and
    whose endpoint concepts never even co-occur in one document -- so it
    genuinely emerges from the graph, not from any one paper.

    Bridges by normalised `label`, not entity `id`: each document mints its
    own `{stem}_{entity}` id namespace, so the shared concept is two
    different ids and no 2-hop Cypher pattern can walk through it. `hub_ids`
    are excluded as bridges -- a hub connects to everything, so a
    hub-mediated link is the least surprising kind.

    One flat edge scan aggregated in Python (like god_nodes/authors/
    vault_health): the label-equality bridge join has no portable Cypher
    form. Background-thread only (heavier than this module's other scans)."""
    if conn is None:
        return []
    # Which documents each concept label appears in (as an edge participant).
    # Endpoint pairs sharing a document are excluded below -- that one paper
    # already puts both concepts together, so the link isn't emergent. This
    # subsumes the direct-edge case (a direct a--c edge puts both in that
    # edge's document).
    docs_by_label: dict[str, set[str]] = {}
    by_bridge_label: dict[str, list[tuple]] = {}
    try:
        result = conn.execute(
            "MATCH (a:Entity)-[r:RelatesTo]-(b:Entity) "
            "WHERE a.trust_tier <> 'chat' AND b.trust_tier <> 'chat' "
            "RETURN a.id, a.label, a.source_file, r.relation, r.confidence_score, "
            "r.source_file, b.id, b.label"
        )
        while result.has_next():
            row = result.get_next()
            a_id, a_label, a_source_file, relation, confidence_score, edge_source_file, b_id, b_label = row
            if edge_source_file:
                for lbl in (a_label, b_label):
                    if lbl:
                        docs_by_label.setdefault(lbl.strip().lower(), set()).add(edge_source_file)
            if b_id in hub_ids or not b_label:
                continue
            by_bridge_label.setdefault(b_label.strip().lower(), []).append(row)
    except Exception as exc:
        _log.warning("surprising_connections edge scan failed: %s", exc)
        return []

    candidates: list[tuple] = []
    for rows in by_bridge_label.values():
        if len(rows) > _MAX_BRIDGE_GROUP_SIZE:
            continue
        for i in range(len(rows)):
            a1_id, a1_label, a1_src, rel1, conf1, edge_src1, b1_id, b1_label = rows[i]
            la = a1_label.strip().lower()
            for j in range(i + 1, len(rows)):
                a2_id, a2_label, a2_src, rel2, conf2, edge_src2, b2_id, _ = rows[j]
                lc = a2_label.strip().lower()
                if b1_id == b2_id:
                    continue  # one real node touched twice, not two doc instances
                if a1_id == a2_id or a1_src == a2_src or edge_src1 == edge_src2 or la == lc:
                    continue  # endpoints are the same entity/concept, or both
                               # hops come from the same document
                if docs_by_label.get(la, set()) & docs_by_label.get(lc, set()):
                    continue  # both concepts already appear in one document
                candidates.append((
                    (conf1 + conf2) / 2, a1_id, a2_id, b1_label, rel1, rel2,
                    edge_src1, edge_src2, frozenset((a1_id, a2_id)),
                ))

    candidates.sort(key=lambda c: -c[0])
    seen_pairs: set[frozenset] = set()
    out: list[SurprisingConnection] = []
    for score, a_id, c_id, bridge_label, rel_a, rel_b, edge_a_src, edge_c_src, pair_key in candidates:
        if pair_key in seen_pairs:
            continue  # the same (a, c) pair reached via more than one shared bridge label
        seen_pairs.add(pair_key)
        out.append(SurprisingConnection(
            entity_a=a_id, entity_b=c_id, bridge=bridge_label,
            relation_a=rel_a, relation_b=rel_b, score=score,
            source_file_a=edge_a_src, source_file_b=edge_c_src,  # the edges', not the entities'
        ))
        if len(out) >= limit:
            break
    return out


def suggest_questions(conn, limit: int = DEFAULT_TOP_ENTITIES) -> list[SuggestedQuestion]:
    """Phrases a grounded follow-up question from each of a diverse sample of
    `RelatesTo` edges -- "what connects X and Y?" -- chat tier excluded on
    both endpoints, same flat-scan shape `god_nodes`/`surprising_connections`
    already use. Deduped by unordered entity-id pair (the undirected `-`
    pattern returns each edge from both directions) and capped at one
    question per distinct `source_file` on a first pass, so one large
    document can't crowd out every other document's questions -- remaining
    slots are then filled from any leftover edges."""
    if conn is None:
        return []
    seen_pairs: set[frozenset] = set()
    rows: list[tuple[str, str, str]] = []  # (a_label, b_label, source_file)
    try:
        result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, e.label, o.id, o.label, r.source_file"
        )
        while result.has_next():
            e_id, e_label, o_id, o_label, source_file = result.get_next()
            if not e_label or not o_label or not source_file:
                continue
            pair_key = frozenset((e_id, o_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            rows.append((e_label, o_label, source_file))
    except Exception as exc:
        _log.warning("suggest_questions edge scan failed: %s", exc)
        return []

    by_source: dict[str, list[tuple[str, str, str]]] = {}
    for row in rows:
        by_source.setdefault(row[2], []).append(row)
    ordered = [source_rows[0] for source_rows in by_source.values()]
    if len(ordered) < limit:
        for source_rows in by_source.values():
            ordered.extend(source_rows[1:])
    return [
        SuggestedQuestion(question=f"What connects '{a}' and '{b}'?", grounding_source_file=src)
        for a, b, src in ordered[:limit]
    ]


def authors(conn, limit: int = DEFAULT_AUTHORS) -> list[AuthorSummary]:
    """Distinct `Entity.author` grouped across the vault. Aggregated in
    Python (see `god_nodes`' rationale)."""
    if conn is None:
        return []
    files: dict[str, set[str]] = {}
    ids: dict[str, list[str]] = {}
    try:
        result = conn.execute(
            "MATCH (e:Entity) "
            "WHERE e.author IS NOT NULL AND e.author <> '' AND e.trust_tier <> 'chat' "
            "RETURN e.author, e.source_file, e.id"
        )
        while result.has_next():
            author, source_file, eid = result.get_next()
            if source_file:
                files.setdefault(author, set()).add(source_file)
            entry = ids.setdefault(author, [])
            if eid not in entry:
                entry.append(eid)
    except Exception as exc:
        _log.warning("authors query failed: %s", exc)
        return []
    ranked = sorted(files, key=lambda a: -len(files[a]))[:limit]
    return [
        AuthorSummary(author=a, file_count=len(files[a]), sample_entities=ids.get(a, [])[:5])
        for a in ranked
    ]


def distinct_entity_labels(conn, limit: int = ENTITY_LABELS_MAX) -> list[str]:
    """Every distinct entity label in the vault, chat tier excluded --
    KnowledgeGraphService.graph_relevance()'s cached match list. Deliberately
    just labels, no ids/degree/provenance: the caller only ever needs "is
    this label mentioned in this text," never which entity/document it
    came from."""
    if conn is None:
        return []
    try:
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' "
            "RETURN DISTINCT e.label LIMIT $limit",
            {"limit": limit},
        )
        labels: list[str] = []
        while result.has_next():
            (label,) = result.get_next()
            if label:
                labels.append(label)
        return labels
    except Exception as exc:
        _log.warning("distinct_entity_labels query failed: %s", exc)
        return []


def vault_health(conn) -> VaultHealthResponse:
    """Entities with zero RelatesTo edges (in either direction). Computed as
    a set difference in Python rather than a `NOT (e)-[:RelatesTo]-()`
    pattern predicate, which isn't portable across Kùzu versions."""
    if conn is None:
        return VaultHealthResponse(orphans=[], orphan_count=0)
    try:
        connected: set[str] = set()
        result = conn.execute(
            "MATCH (a:Entity)-[:RelatesTo]-(b:Entity) "
            "WHERE a.trust_tier <> 'chat' AND b.trust_tier <> 'chat' RETURN a.id"
        )
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


# timeline is split into a graph half (timeline_scan, holds the Kùzu lock)
# and a vault half (timeline_build, frontmatter reads, lock released).
# `timeline()` runs both for direct callers/tests.


def timeline_scan(conn, question: str, limit: int = DEFAULT_TIMELINE):
    """The graph half of timeline(): the top-`limit` matching entities
    (scored by term overlap, like `search`) and, per hit, the documents
    that assert its edges. Pure Cypher -- run under the connection lock."""
    terms = _terms(question)
    if not terms or conn is None:
        return [], {}
    scored: list[tuple[int, str, str, str | None]] = []
    try:
        result = conn.execute(
            "MATCH (e:Entity) WHERE e.trust_tier <> 'chat' RETURN e.id, e.label, e.source_file"
        )
        while result.has_next():
            eid, label, source_file = result.get_next()
            haystack = f"{eid} {label}".lower()
            score = sum(1 for t in terms if t in haystack)
            if score:
                scored.append((score, eid, label, source_file))
    except Exception as exc:
        _log.warning("timeline entity scan failed: %s", exc)
        return [], {}
    scored.sort(key=lambda s: -s[0])
    hits = [(eid, label, src) for _, eid, label, src in scored[:limit]]
    hit_ids = {eid for eid, _, _ in hits}

    docs_by_entity: dict[str, list[str]] = {}
    try:
        edge_result = conn.execute(
            "MATCH (e:Entity)-[r:RelatesTo]-(o:Entity) "
            "WHERE e.trust_tier <> 'chat' AND o.trust_tier <> 'chat' "
            "RETURN e.id, r.source_file"
        )
        while edge_result.has_next():
            eid, edge_src = edge_result.get_next()
            if edge_src and eid in hit_ids:
                docs = docs_by_entity.setdefault(eid, [])
                if edge_src not in docs and len(docs) < _TIMELINE_DOCS_PER_ENTITY:
                    docs.append(edge_src)
    except Exception as exc:
        _log.warning("timeline edge scan failed: %s", exc)

    return hits, docs_by_entity


def timeline_build(vault, hits, docs_by_entity, limit: int = DEFAULT_TIMELINE) -> list[TimelineEntry]:
    """The vault half of timeline(): resolve each document's year from its
    frontmatter and emit one entry per (entity, document). Pure vault I/O --
    the connection lock must be *released* before this runs.

    `Entity.source_file` alone is only last-writer -- same-stem files
    collapse into one Entity row -- so an entity's documents are its own
    `source_file` plus every `RelatesTo.source_file` touching it. A concept
    that appears only as a bare mention (no relationship) in a collapsed
    document is still lost; full per-document identity is the deferred
    `{stem}_{entity}` id change (see TODO.md, ADR-021)."""
    year_by_file: dict[str, int | None] = {}

    def _year(source_file: str) -> int | None:
        # Resolve the known relative path directly and read only its
        # frontmatter -- get_any() would walk the whole vault and build a
        # full node model just for `year`.
        if source_file not in year_by_file:
            raw = vault.frontmatter_for_relpath(source_file).get("year")
            try:
                year_by_file[source_file] = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                year_by_file[source_file] = None
        return year_by_file[source_file]

    entries: list[TimelineEntry] = []
    for eid, label, own_source in hits:
        docs = list(dict.fromkeys(([own_source] if own_source else []) + docs_by_entity.get(eid, [])))
        if not docs:
            entries.append(TimelineEntry(id=eid, label=label, source_file=None, year=None))
            continue
        for d in docs:
            entries.append(TimelineEntry(id=eid, label=label, source_file=d, year=_year(d)))
    entries.sort(key=lambda e: (e.year is None, e.year or 0))
    return entries[:limit]


def timeline(conn, vault, question: str, limit: int = DEFAULT_TIMELINE) -> list[TimelineEntry]:
    """Entities matching `question`, one entry per (entity, document it
    appears in), sorted chronologically (year-less last). See timeline_scan/
    timeline_build -- the service splits these across the lock boundary."""
    hits, docs_by_entity = timeline_scan(conn, question, limit)
    return timeline_build(vault, hits, docs_by_entity, limit)
