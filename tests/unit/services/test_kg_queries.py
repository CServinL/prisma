"""Unit tests for prisma.services.kg_queries — pure retrieval over a real
embedded Kùzu graph (same fixture pattern as test_knowledge_graph_service.py:
tmp_path-backed Kùzu, nothing mocked here since there's no LLM call).
"""
from unittest.mock import patch

import pytest

from prisma.services import kg_queries
from prisma.services.knowledge_graph_service import KnowledgeGraphService
from prisma.storage.models.kg_models import ExpandNodeResponse


@pytest.fixture
def vault(tmp_path):
    from prisma.services.vault import VaultService
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


@pytest.fixture
def kg(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    service._ensure_connection()
    return service


@pytest.fixture
def conn(kg):
    return kg._conn


def _add(kg, rel, trust_tier, nodes, edges=None):
    with kg._lock:
        kg._upsert(rel, trust_tier, nodes, edges or [])


class _MidStreamFailConn:
    """A conn whose result raises during iteration -- Kùzu can fail while
    streaming rows, not only on execute()."""

    class _Result:
        def has_next(self):
            return True

        def get_next(self):
            raise RuntimeError("kùzu stream died")

    def execute(self, *a, **k):
        return _MidStreamFailConn._Result()


@pytest.mark.parametrize("call,empty", [
    (lambda c: kg_queries.search(c, "x"), []),
    (lambda c: kg_queries.compute_top_entities(c), []),
    (lambda c: kg_queries.god_nodes(c), []),
    (lambda c: kg_queries.authors(c), []),
    (lambda c: kg_queries.surprising_connections(c, hub_ids=set()), []),
    (lambda c: kg_queries.suggest_questions(c), []),
    (lambda c: kg_queries.distinct_entity_labels(c), []),
    (lambda c: kg_queries.timeline_scan(c, "x"), ([], {})),
    (lambda c: kg_queries.expand_node(c, "x"), ExpandNodeResponse(entities=[], edges=[])),
])
def test_scans_return_safe_default_on_a_mid_stream_error(call, empty):
    assert call(_MidStreamFailConn()) == empty


# ── search ────────────────────────────────────────────────────────────────────

def test_search_ranks_by_term_match(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a_neural_networks", "label": "Neural Networks"}])
    _add(kg, "notes/b.md", "note", [{"id": "b_recipes", "label": "Cooking Recipes"}])
    results = kg_queries.search(conn, "neural networks")
    assert results
    assert results[0].source_file == "notes/a.md"


def test_search_excludes_chat_trust_tier(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "c_neural_networks", "label": "Neural Networks"}])
    assert kg_queries.search(conn, "neural networks") == []


def test_search_returns_empty_for_no_matching_terms(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a_thing", "label": "Thing"}])
    assert kg_queries.search(conn, "completely unrelated xyz") == []


def test_search_none_conn_is_empty():
    assert kg_queries.search(None, "anything") == []


# ── entities_for_file ─────────────────────────────────────────────────────────

def test_entities_for_file_returns_nodes_and_edges(kg, conn):
    _add(
        kg, "notes/x.md", "source",
        [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        [{"source": "a", "target": "b", "relation": "cites", "confidence": "EXTRACTED"}],
    )
    data = kg_queries.entities_for_file(conn, "notes/x.md", extracted_by="qwen2.5:7b")
    assert {e.id for e in data.entities} == {"a", "b"}
    assert len(data.edges) == 1
    assert data.edges[0].relation == "cites"
    assert data.extracted_by == "qwen2.5:7b"
    assert all(e.source_file == "notes/x.md" for e in data.entities)
    assert data.edges[0].source_file == "notes/x.md"


def test_entities_for_file_empty_for_untracked_file(kg, conn):
    data = kg_queries.entities_for_file(conn, "notes/never.md")
    assert data.entities == [] and data.edges == []


# ── compute_top_entities ──────────────────────────────────────────────────────

def test_compute_top_entities_ranks_by_undirected_degree(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "hub", "label": "Hub"}, {"id": "l1", "label": "L1"}, {"id": "l2", "label": "L2"}],
        [{"source": "hub", "target": "l1"}, {"source": "hub", "target": "l2"}],
    )
    top = kg_queries.compute_top_entities(conn)
    assert top[0].id == "hub"
    assert top[0].degree == 2


def test_compute_top_entities_excludes_chat_tier_on_either_endpoint(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "real", "label": "Real"}, {"id": "other", "label": "Other"}],
        [{"source": "real", "target": "other"}],
    )
    _add(
        kg, "chats/c.md", "chat",
        [{"id": "chatty", "label": "Chatty"}],
        [{"source": "real", "target": "chatty"}],
    )
    top = kg_queries.compute_top_entities(conn)
    assert next(e for e in top if e.id == "real").degree == 1
    assert all(e.id != "chatty" for e in top)


# ── hub_ids ───────────────────────────────────────────────────────────────────

def test_hub_ids_returns_every_entity_over_the_threshold_not_a_top_slice(kg, conn):
    # 20 hubs each of degree 3 -- a 15-entry top slice would miss the last 5.
    for h in range(20):
        nodes = [{"id": f"h{h}", "label": f"H{h}"}] + [{"id": f"h{h}_l{i}", "label": "L"} for i in range(3)]
        edges = [{"source": f"h{h}", "target": f"h{h}_l{i}"} for i in range(3)]
        _add(kg, f"notes/{h}.md", "note", nodes, edges)

    hubs = kg_queries.hub_ids(conn, min_degree=3)

    assert {f"h{h}" for h in range(20)} <= hubs
    assert "h0_l0" not in hubs  # degree-1 leaf


def test_hub_ids_excludes_chat_tier_on_both_ends(kg, conn):
    _add(kg, "chats/c.md", "chat",
         [{"id": "cx", "label": "CX"}] + [{"id": f"cx_l{i}", "label": "L"} for i in range(6)],
         [{"source": "cx", "target": f"cx_l{i}"} for i in range(6)])
    assert kg_queries.hub_ids(conn, min_degree=3) == set()


# ── god_nodes ─────────────────────────────────────────────────────────────────

def test_god_nodes_adds_source_files_and_sample_relations(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "hub", "label": "Hub"}, {"id": "l1", "label": "L1"}],
        [{"source": "hub", "target": "l1", "relation": "cites"}],
    )
    _add(
        kg, "notes/b.md", "note",
        [{"id": "hub", "label": "Hub"}, {"id": "l2", "label": "L2"}],
        [{"source": "hub", "target": "l2", "relation": "builds_on"}],
    )
    # re-upsert the hub id from an unrelated doc with no edge -- this
    # overwrites Entity.source_file but asserts none of hub's relations
    _add(kg, "notes/latewriter.md", "note", [{"id": "hub", "label": "Hub"}])

    top = kg_queries.god_nodes(conn)
    hub = next(e for e in top if e.id == "hub")
    assert hub.degree == 2
    # the documents behind the edges, not the entity's last-writer source_file
    assert set(hub.source_files) == {"notes/a.md", "notes/b.md"}
    assert set(hub.sample_relations) == {"cites", "builds_on"}


def test_god_nodes_caps_sample_relations_at_three(kg, conn):
    edges = [
        {"source": "hub", "target": f"l{i}", "relation": f"rel_{i}"} for i in range(6)
    ]
    nodes = [{"id": "hub", "label": "Hub"}] + [{"id": f"l{i}", "label": f"L{i}"} for i in range(6)]
    _add(kg, "notes/a.md", "note", nodes, edges)
    hub = next(e for e in kg_queries.god_nodes(conn) if e.id == "hub")
    assert len(hub.sample_relations) == 3


def test_god_nodes_excludes_chat_tier(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
         [{"source": "x", "target": "y"}])
    assert kg_queries.god_nodes(conn) == []


# ── expand_node ───────────────────────────────────────────────────────────────

def test_expand_node_returns_one_hop_neighbours(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "center", "label": "Center"}, {"id": "n1", "label": "N1"}, {"id": "n2", "label": "N2"}],
        [
            {"source": "center", "target": "n1", "relation": "cites"},
            {"source": "n2", "target": "center", "relation": "extends"},
        ],
    )
    resp = kg_queries.expand_node(conn, "center")
    assert {e.id for e in resp.entities} == {"n1", "n2"}
    assert {edge.relation for edge in resp.edges} == {"cites", "extends"}
    by_relation = {edge.relation: edge for edge in resp.edges}
    # "center cites n1" is outgoing, but "n2 extends center" is incoming --
    # reporting it as "center extends n2" would be a false inverse claim.
    assert (by_relation["cites"].source, by_relation["cites"].target) == ("center", "n1")
    assert (by_relation["extends"].source, by_relation["extends"].target) == ("n2", "center")
    # provenance for the grounding Sources: header
    assert {e.source_file for e in resp.entities} == {"notes/a.md"}
    assert {edge.source_file for edge in resp.edges} == {"notes/a.md"}


def test_expand_node_excludes_chat_tier_neighbours(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "center", "label": "Center"}])
    _add(kg, "chats/c.md", "chat", [{"id": "chatty", "label": "Chatty"}],
         [{"source": "center", "target": "chatty"}])
    resp = kg_queries.expand_node(conn, "center")
    assert resp.entities == []


def test_expand_node_excludes_a_chat_tier_center(kg, conn):
    # The center "shared" is chat-tier; its neighbour "chatty" is later
    # re-upserted as a note, so filtering only the neighbour would leak the
    # chat-asserted relationship (and its chat source_file) into a grounding
    # header.
    _add(kg, "chats/c.md", "chat",
         [{"id": "shared", "label": "Shared"}, {"id": "chatty", "label": "Chatty"}],
         [{"source": "shared", "target": "chatty", "relation": "in"}])
    _add(kg, "notes/n.md", "note", [{"id": "chatty", "label": "Chatty"}])

    resp = kg_queries.expand_node(conn, "shared")

    assert resp.entities == [] and resp.edges == []


def test_expand_node_respects_limit_per_direction(kg, conn):
    edges = [{"source": "hub", "target": f"n{i}", "relation": "cites"} for i in range(8)]
    nodes = [{"id": "hub", "label": "Hub"}] + [{"id": f"n{i}", "label": f"N{i}"} for i in range(8)]
    _add(kg, "notes/a.md", "note", nodes, edges)

    resp = kg_queries.expand_node(conn, "hub", limit=3)

    assert len(resp.edges) == 3


def test_expand_node_drops_a_self_loop(kg, conn):
    _add(kg, "notes/a.md", "note",
         [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
         [{"source": "x", "target": "x", "relation": "refines"},
          {"source": "x", "target": "y", "relation": "cites"}])

    resp = kg_queries.expand_node(conn, "x")

    assert {e.id for e in resp.entities} == {"y"}
    assert all(edge.source != edge.target for edge in resp.edges)


def test_expand_node_empty_for_unknown_id(kg, conn):
    resp = kg_queries.expand_node(conn, "nope")
    assert resp.entities == [] and resp.edges == []


def test_expand_node_empty_id_is_empty(conn):
    assert kg_queries.expand_node(conn, "").entities == []


# ── surprising_connections ────────────────────────────────────────────────────
# A link where the two hops came from different documents, the endpoints
# don't share a document, and no document asserted a direct edge. Bridges by
# normalised label, not id: extraction mints a document-scoped `{stem}_{entity}`
# id, so these fixtures use distinct ids with a shared label, as production does.

def test_surprising_connections_finds_cross_document_bridge(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
         [{"source": "a", "target": "a_bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
         [{"source": "b_bridge", "target": "c", "relation": "extends"}])

    results = kg_queries.surprising_connections(conn, hub_ids=set())

    assert len(results) == 1
    link = results[0]
    assert link.bridge == "Bridge"  # the shared label (as-cased in the data), not either instance's id
    assert {link.entity_a, link.entity_b} == {"a", "c"}
    assert {link.relation_a, link.relation_b} == {"cites", "extends"}
    # the document that asserted each hop -- the citable pair for the claim
    assert {link.source_file_a, link.source_file_b} == {"notes/a.md", "notes/b.md"}


def test_surprising_connections_cites_the_edge_document_not_the_entity_last_writer(kg, conn):
    # Entity rows merge by id and a later upsert overwrites source_file
    # (KnowledgeGraphService._upsert). Here entity "a" is first extracted
    # from notes/a.md (which asserts a--Bridge), then re-upserted from an
    # unrelated notes/latewriter.md -- so a.source_file now points at
    # latewriter, but the a--Bridge *edge* is still notes/a.md. The
    # citation must follow the edge, not the entity.
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
         [{"source": "a", "target": "a_bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
         [{"source": "b_bridge", "target": "c", "relation": "extends"}])
    _add(kg, "notes/latewriter.md", "note", [{"id": "a", "label": "A"}])

    link = kg_queries.surprising_connections(conn, hub_ids=set())[0]

    by_entity = {link.entity_a: link.source_file_a, link.entity_b: link.source_file_b}
    assert by_entity["a"] == "notes/a.md"
    assert "notes/latewriter.md" not in by_entity.values()


def test_surprising_connections_excludes_directly_asserted_pairs(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
         [{"source": "a", "target": "a_bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
         [{"source": "b_bridge", "target": "c", "relation": "extends"},
          {"source": "a", "target": "c", "relation": "already_known"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_direct_edge_asserted_by_a_third_document(kg, conn):
    # doc3 asserts "A relates to C" using its own doc3-scoped ids, never
    # the doc1_a/doc2_c ids the bridge candidate actually has.
    _add(kg, "notes/doc1.md", "note", [{"id": "doc1_a", "label": "A"}, {"id": "doc1_bridge", "label": "Bridge"}],
         [{"source": "doc1_a", "target": "doc1_bridge", "relation": "cites"}])
    _add(kg, "notes/doc2.md", "note", [{"id": "doc2_c", "label": "C"}, {"id": "doc2_bridge", "label": "Bridge"}],
         [{"source": "doc2_bridge", "target": "doc2_c", "relation": "extends"}])
    _add(kg, "notes/doc3.md", "note", [{"id": "doc3_a", "label": "A"}, {"id": "doc3_c", "label": "C"}],
         [{"source": "doc3_a", "target": "doc3_c", "relation": "already_known"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_endpoints_that_co_occur_in_a_third_document(kg, conn):
    # doc3 mentions both concept A and concept C (each linked to a shared
    # node), but never links them directly. That's still "one paper mentions
    # both", so the A--Bridge--C candidate isn't emergent.
    _add(kg, "notes/doc1.md", "note", [{"id": "doc1_a", "label": "A"}, {"id": "doc1_bridge", "label": "Bridge"}],
         [{"source": "doc1_a", "target": "doc1_bridge", "relation": "cites"}])
    _add(kg, "notes/doc2.md", "note", [{"id": "doc2_c", "label": "C"}, {"id": "doc2_bridge", "label": "Bridge"}],
         [{"source": "doc2_bridge", "target": "doc2_c", "relation": "extends"}])
    _add(kg, "notes/doc3.md", "note",
         [{"id": "doc3_a", "label": "A"}, {"id": "doc3_c", "label": "C"}, {"id": "doc3_s", "label": "Shared"}],
         [{"source": "doc3_a", "target": "doc3_s", "relation": "in"},
          {"source": "doc3_c", "target": "doc3_s", "relation": "in"}])

    links = kg_queries.surprising_connections(conn, hub_ids=set())

    # the only pair a "Bridge"-labelled node can connect is (A, C), and they
    # co-occur in doc3 -- so nothing should bridge on "Bridge"
    assert not any(link.bridge == "Bridge" for link in links)


def test_surprising_connections_excludes_same_document_hops(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a", "label": "A"}, {"id": "bridge", "label": "Bridge"}, {"id": "c", "label": "C"}],
        [
            {"source": "a", "target": "bridge", "relation": "cites"},
            {"source": "bridge", "target": "c", "relation": "extends"},
        ],
    )
    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_endpoints_sharing_a_document(kg, conn):
    _add(kg, "notes/shared.md", "note", [{"id": "a", "label": "A"}, {"id": "c", "label": "C"}])
    _add(kg, "notes/x.md", "note", [{"id": "x_bridge", "label": "Bridge"}],
         [{"source": "a", "target": "x_bridge", "relation": "cites"}])
    _add(kg, "notes/y.md", "note", [{"id": "y_bridge", "label": "Bridge"}],
         [{"source": "y_bridge", "target": "c", "relation": "extends"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_hub_mediated_links(kg, conn):
    # Hub exclusion is per-instance (by id), not per-label: excluding
    # a_bridge's specific id leaves only b_bridge in the "bridge" label
    # group -- one entry can't form a pair, so the result is empty exactly
    # as if the whole label had been excluded.
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "a_bridge", "label": "Bridge"}],
         [{"source": "a", "target": "a_bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}, {"id": "b_bridge", "label": "Bridge"}],
         [{"source": "b_bridge", "target": "c", "relation": "extends"}])

    assert kg_queries.surprising_connections(conn, hub_ids={"a_bridge"}) == []


def test_surprising_connections_excludes_the_same_physical_node_seen_twice(kg, conn):
    # Bug found while fixing the label-bridging change above: an entity with
    # degree >= 2 shows up twice in its OWN label group (once per edge that
    # touches it, from the undirected scan) -- without a same-node check,
    # that looked like "two different documents' instances sharing a
    # label" when it's really just one real node connecting two neighbours
    # directly, which expand_node already covers and isn't "surprising".
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a", "label": "A"}, {"id": "neighbour1", "label": "N1"}],
        [{"source": "a", "target": "neighbour1", "relation": "cites"}],
    )
    _add(
        kg, "notes/b.md", "note",
        [{"id": "neighbour2", "label": "N2"}],
        [{"source": "a", "target": "neighbour2", "relation": "already_known"}],
    )
    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_endpoints_that_are_the_same_concept(kg, conn):
    # Two documents each assert "<concept> Transformer — Bridge" using their
    # own doc-scoped ids. The endpoints have different ids and come from
    # different documents, but both normalise to the label "Transformer" --
    # "Transformer — Bridge — Transformer" is not a connection between two
    # distinct things and must not be reported.
    _add(kg, "notes/a.md", "note",
         [{"id": "a_transformer", "label": "Transformer"}, {"id": "a_bridge", "label": "Bridge"}],
         [{"source": "a_transformer", "target": "a_bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note",
         [{"id": "b_transformer", "label": "transformer"}, {"id": "b_bridge", "label": "Bridge"}],
         [{"source": "b_bridge", "target": "b_transformer", "relation": "extends"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_none_conn_is_empty():
    assert kg_queries.surprising_connections(None, hub_ids=set()) == []


def test_surprising_connections_respects_limit(kg, conn):
    for i in range(3):
        _add(kg, f"notes/a{i}.md", "note", [{"id": f"a{i}", "label": f"A{i}"}, {"id": f"a{i}_bridge", "label": "Bridge"}],
             [{"source": f"a{i}", "target": f"a{i}_bridge", "relation": "cites"}])
        _add(kg, f"notes/b{i}.md", "note", [{"id": f"c{i}", "label": f"C{i}"}, {"id": f"b{i}_bridge", "label": "Bridge"}],
             [{"source": f"b{i}_bridge", "target": f"c{i}", "relation": "extends"}])

    assert len(kg_queries.surprising_connections(conn, hub_ids=set(), limit=2)) == 2


# ── suggest_questions ─────────────────────────────────────────────────────────

def test_suggest_questions_phrases_a_grounded_question_from_an_edge(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a_x", "label": "X"}, {"id": "a_y", "label": "Y"}],
        [{"source": "a_x", "target": "a_y", "relation": "causes"}],
    )
    questions = kg_queries.suggest_questions(conn)
    assert len(questions) == 1
    assert questions[0].question == "What connects 'X' and 'Y'?"
    assert questions[0].grounding_source_file == "notes/a.md"


def test_suggest_questions_excludes_chat_tier(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
         [{"source": "x", "target": "y", "relation": "cites"}])
    assert kg_queries.suggest_questions(conn) == []


def test_suggest_questions_dedupes_the_undirected_double_read(kg, conn):
    # The undirected `-` scan returns one real edge from both directions --
    # a naive read would otherwise phrase the same question twice.
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a_x", "label": "X"}, {"id": "a_y", "label": "Y"}],
        [{"source": "a_x", "target": "a_y", "relation": "causes"}],
    )
    assert len(kg_queries.suggest_questions(conn)) == 1


def test_suggest_questions_dedupes_the_same_concept_pair_across_documents(kg, conn):
    # Each document mints its own `{stem}_{entity}` id namespace (see
    # surprising_connections' own docstring) -- two papers independently
    # discussing "Transformer"/"Attention" produce two different id pairs
    # for the same real-world concept pair. Deduping by id (a real bug,
    # caught in self-review rather than by the original test suite) let
    # the identical question through once per paper instead of once total.
    _add(
        kg, "papers/doc1.md", "source",
        [{"id": "doc1_transformer", "label": "Transformer"}, {"id": "doc1_attention", "label": "Attention"}],
        [{"source": "doc1_transformer", "target": "doc1_attention", "relation": "uses"}],
    )
    _add(
        kg, "papers/doc2.md", "source",
        [{"id": "doc2_transformer", "label": "Transformer"}, {"id": "doc2_attention", "label": "Attention"}],
        [{"source": "doc2_transformer", "target": "doc2_attention", "relation": "uses"}],
    )
    questions = kg_queries.suggest_questions(conn)
    assert len(questions) == 1
    assert questions[0].question == "What connects 'Transformer' and 'Attention'?"


def test_suggest_questions_drops_a_self_referential_pair(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a_x", "label": "X"}],
        [{"source": "a_x", "target": "a_x", "relation": "self"}],
    )
    assert kg_queries.suggest_questions(conn) == []


def test_suggest_questions_caps_at_one_per_source_file_before_filling_remaining_slots(kg, conn):
    # Two edges from the same document, one from another -- the single-doc
    # document must not crowd out the other document's question when the
    # limit only allows one question per document on the first pass.
    _add(
        kg, "notes/big.md", "note",
        [{"id": "b_x", "label": "X"}, {"id": "b_y", "label": "Y"}, {"id": "b_z", "label": "Z"}],
        [
            {"source": "b_x", "target": "b_y", "relation": "causes"},
            {"source": "b_y", "target": "b_z", "relation": "extends"},
        ],
    )
    _add(
        kg, "notes/small.md", "note",
        [{"id": "s_p", "label": "P"}, {"id": "s_q", "label": "Q"}],
        [{"source": "s_p", "target": "s_q", "relation": "cites"}],
    )
    questions = kg_queries.suggest_questions(conn, limit=2)
    assert len(questions) == 2
    assert {q.grounding_source_file for q in questions} == {"notes/big.md", "notes/small.md"}


def test_suggest_questions_respects_limit(kg, conn):
    for i in range(5):
        _add(
            kg, f"notes/{i}.md", "note",
            [{"id": f"{i}_x", "label": f"X{i}"}, {"id": f"{i}_y", "label": f"Y{i}"}],
            [{"source": f"{i}_x", "target": f"{i}_y", "relation": "cites"}],
        )
    assert len(kg_queries.suggest_questions(conn, limit=3)) == 3


def test_suggest_questions_ranks_by_confidence_score(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "a_x", "label": "X"}, {"id": "a_y", "label": "Y"},
         {"id": "a_p", "label": "P"}, {"id": "a_q", "label": "Q"}],
        [
            {"source": "a_x", "target": "a_y", "relation": "cites", "confidence_score": 0.2},
            {"source": "a_p", "target": "a_q", "relation": "cites", "confidence_score": 0.9},
        ],
    )
    questions = kg_queries.suggest_questions(conn)
    assert questions[0].question == "What connects 'P' and 'Q'?"


def test_suggest_questions_uses_endpoint_degree_as_a_tiebreak(kg, conn):
    # Same confidence_score on both edges -- the pair touching the
    # higher-degree ("Hub") entity should rank first. The isolated pair is
    # upserted FIRST, hub edges upserted AFTER -- insertion order alone
    # (what an unranked scan would incidentally follow) would then put the
    # isolated pair ahead, so this only passes if degree is actually
    # driving the order, not scan-order luck agreeing with the assertion.
    _add(
        kg, "notes/a.md", "note",
        [{"id": "iso_a", "label": "A"}, {"id": "iso_b", "label": "B"}],
        [{"source": "iso_a", "target": "iso_b", "relation": "cites", "confidence_score": 0.5}],
    )
    _add(
        kg, "notes/a.md", "note",
        [{"id": "hub", "label": "Hub"}, {"id": "l1", "label": "L1"}, {"id": "l2", "label": "L2"}],
        [
            {"source": "hub", "target": "l1", "relation": "cites", "confidence_score": 0.5},
            {"source": "hub", "target": "l2", "relation": "cites", "confidence_score": 0.5},
        ],
    )
    questions = kg_queries.suggest_questions(conn)
    hub_positions = [i for i, q in enumerate(questions) if "Hub" in q.question]
    iso_position = next(i for i, q in enumerate(questions) if "'A'" in q.question)
    assert all(pos < iso_position for pos in hub_positions)


def test_suggest_questions_diversity_guarantee_survives_ranking(kg, conn):
    # A document with many high-confidence edges must not push a document
    # with exactly one modestly-ranked edge out of the result entirely --
    # the one-per-document guarantee must hold regardless of how that one
    # edge ranks against everything else.
    big_nodes = [{"id": f"big_{i}", "label": f"Big{i}"} for i in range(6)]
    big_edges = [
        {"source": f"big_{i}", "target": f"big_{i + 1}", "relation": "cites", "confidence_score": 0.95}
        for i in range(5)
    ]
    _add(kg, "papers/big.md", "source", big_nodes, big_edges)
    _add(
        kg, "papers/small.md", "source",
        [{"id": "small_p", "label": "P"}, {"id": "small_q", "label": "Q"}],
        [{"source": "small_p", "target": "small_q", "relation": "cites", "confidence_score": 0.1}],
    )

    questions = kg_queries.suggest_questions(conn, limit=3)

    assert any(q.grounding_source_file == "papers/small.md" for q in questions)


# ── distinct_entity_labels ────────────────────────────────────────────────────

def test_distinct_entity_labels_returns_unique_labels(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a1", "label": "Neural Networks"}])
    _add(kg, "notes/b.md", "note", [{"id": "b1", "label": "Neural Networks"}, {"id": "b2", "label": "Transformers"}])
    assert set(kg_queries.distinct_entity_labels(conn)) == {"Neural Networks", "Transformers"}


def test_distinct_entity_labels_excludes_chat_tier(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "c1", "label": "Ghost"}])
    assert kg_queries.distinct_entity_labels(conn) == []


def test_distinct_entity_labels_respects_limit(kg, conn):
    for i in range(5):
        _add(kg, f"notes/{i}.md", "note", [{"id": f"n{i}", "label": f"Label{i}"}])
    assert len(kg_queries.distinct_entity_labels(conn, limit=3)) == 3


# ── authors ───────────────────────────────────────────────────────────────────

def test_authors_groups_by_distinct_author(kg, conn):
    _add(kg, "notes/a.md", "source", [
        {"id": "a1", "label": "A1", "author": "Ada Lovelace"},
        {"id": "a2", "label": "A2", "author": "Ada Lovelace"},
    ])
    _add(kg, "notes/b.md", "source", [
        {"id": "b1", "label": "B1", "author": "Ada Lovelace"},
        {"id": "b2", "label": "B2", "author": "Alan Turing"},
    ])
    summaries = {s.author: s for s in kg_queries.authors(conn)}
    assert summaries["Ada Lovelace"].file_count == 2
    assert summaries["Alan Turing"].file_count == 1
    assert set(summaries["Ada Lovelace"].sample_entities) <= {"a1", "a2", "b1"}


def test_authors_ignores_null_and_empty_authors(kg, conn):
    _add(kg, "notes/a.md", "note", [
        {"id": "a1", "label": "A1"},
        {"id": "a2", "label": "A2", "author": ""},
    ])
    assert kg_queries.authors(conn) == []


def test_authors_excludes_chat_tier(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "c1", "label": "C1", "author": "Ghost"}])
    assert kg_queries.authors(conn) == []


# ── vault_health ──────────────────────────────────────────────────────────────

def test_vault_health_lists_zero_edge_entities(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "linked_a", "label": "LA"}, {"id": "linked_b", "label": "LB"}, {"id": "lonely", "label": "Lonely"}],
        [{"source": "linked_a", "target": "linked_b"}],
    )
    resp = kg_queries.vault_health(conn)
    assert resp.orphan_count == 1
    assert resp.orphans[0].id == "lonely"
    assert resp.orphans[0].source_file == "notes/a.md"


def test_vault_health_excludes_chat_tier_orphans(kg, conn):
    _add(kg, "chats/c.md", "chat", [{"id": "chat_orphan", "label": "CO"}])
    resp = kg_queries.vault_health(conn)
    assert all(o.id != "chat_orphan" for o in resp.orphans)


def test_vault_health_reports_an_orphan_that_shares_an_id_with_a_chat_edge(kg, conn):
    # "topic" is a note entity with no note relationships. A chat session
    # then extracts the same id with an edge -- if the connectivity scan
    # doesn't filter chat tier, "topic" counts as connected and the orphan
    # is silently under-reported.
    _add(kg, "chats/c.md", "chat",
         [{"id": "topic", "label": "Topic"}, {"id": "chatty", "label": "Chatty"}],
         [{"source": "topic", "target": "chatty", "relation": "in"}])
    _add(kg, "notes/n.md", "note", [{"id": "topic", "label": "Topic"}])  # re-tier to note, no edge

    resp = kg_queries.vault_health(conn)

    assert any(o.id == "topic" for o in resp.orphans)


def test_vault_health_empty_graph(conn):
    resp = kg_queries.vault_health(conn)
    assert resp.orphans == [] and resp.orphan_count == 0


# ── timeline ──────────────────────────────────────────────────────────────────

def _write_source(vault, slug, year):
    p = vault.root / "sources" / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntype: source\ntitle: {slug}\nyear: {year}\n---\nbody", encoding="utf-8")


def test_timeline_sorts_by_source_year(kg, conn, vault):
    _write_source(vault, "old-paper", 1990)
    _write_source(vault, "new-paper", 2020)
    _add(kg, "sources/old-paper.md", "source", [{"id": "old_transformers", "label": "Transformers"}])
    _add(kg, "sources/new-paper.md", "source", [{"id": "new_transformers", "label": "Transformers"}])

    entries = kg_queries.timeline(conn, vault, "transformers")

    assert [e.year for e in entries] == [1990, 2020]


def test_timeline_year_less_entities_sort_last(kg, conn, vault):
    _write_source(vault, "dated", 2000)
    _add(kg, "sources/dated.md", "source", [{"id": "d_topic", "label": "Topic"}])
    _add(kg, "notes/undated.md", "note", [{"id": "u_topic", "label": "Topic"}])

    entries = kg_queries.timeline(conn, vault, "topic")

    assert entries[0].year == 2000
    assert entries[-1].year is None


def test_timeline_emits_an_entry_per_document_a_concept_appears_in(kg, conn, vault):
    # Realistic collapse: same filename in two directories, so extraction
    # mints the same `{stem}_topic` id and _upsert MERGEs them into one row
    # whose source_file is just the last writer. Each document's edge still
    # carries its own source_file, so the concept must surface at both years.
    _write_source(vault, "paper", 1990)  # -> sources/paper.md
    (vault.root / "archive").mkdir(parents=True, exist_ok=True)
    (vault.root / "archive" / "paper.md").write_text(
        "---\ntype: source\ntitle: paper\nyear: 2020\n---\nbody", encoding="utf-8",
    )
    _add(kg, "sources/paper.md", "source",
         [{"id": "paper_topic", "label": "Topic"}, {"id": "paper_x", "label": "X"}],
         [{"source": "paper_topic", "target": "paper_x", "relation": "cites"}])
    _add(kg, "archive/paper.md", "source",
         [{"id": "paper_topic", "label": "Topic"}, {"id": "paper_y", "label": "Y"}],
         [{"source": "paper_topic", "target": "paper_y", "relation": "cites"}])

    entries = kg_queries.timeline(conn, vault, "topic")

    dated = {(e.source_file, e.year) for e in entries if e.id == "paper_topic"}
    assert dated == {("sources/paper.md", 1990), ("archive/paper.md", 2020)}


def test_timeline_walks_edges_for_a_year_the_entity_row_lost(kg, conn, vault):
    # The collapsed entity row's own source_file is the 2020 paper, but an
    # edge is still tagged with the 1990 one -- that year must not vanish.
    _write_source(vault, "recent", 2020)
    _write_source(vault, "seminal", 1990)
    _add(kg, "sources/seminal.md", "source",
         [{"id": "t", "label": "Transformers"}, {"id": "other", "label": "Other"}],
         [{"source": "t", "target": "other", "relation": "cites"}])
    _add(kg, "sources/recent.md", "source", [{"id": "t", "label": "Transformers"}])

    years = {e.year for e in kg_queries.timeline(conn, vault, "transformers")}

    assert 1990 in years


def test_timeline_empty_for_no_terms(conn, vault):
    assert kg_queries.timeline(conn, vault, "  ") == []


def test_timeline_excludes_chat_tier(kg, conn, vault):
    _add(kg, "chats/c.md", "chat", [{"id": "c_topic", "label": "Topic"}])
    assert kg_queries.timeline(conn, vault, "topic") == []


def test_timeline_edge_scan_ignores_chat_tier_neighbours(kg, conn, vault):
    # A note entity linked to a chat-tier entity by an edge asserted in a
    # chat session -- that chat file's source_file must not become a
    # timeline document for the note concept.
    _write_source(vault, "paper", 2019)
    _add(kg, "sources/paper.md", "source", [{"id": "n_topic", "label": "Topic"}])
    _add(kg, "chats/c.md", "chat",
         [{"id": "n_topic", "label": "Topic"}, {"id": "c_thing", "label": "Thing"}],
         [{"source": "n_topic", "target": "c_thing", "relation": "mentions"}])
    # re-assert the note tier so n_topic isn't itself chat-tier
    _add(kg, "sources/paper.md", "source", [{"id": "n_topic", "label": "Topic"}])

    entries = kg_queries.timeline(conn, vault, "topic")

    assert {e.source_file for e in entries} == {"sources/paper.md"}


def test_timeline_reads_frontmatter_directly_not_via_get_any(kg, conn, vault):
    # get_any() walks the whole vault and builds a full node model per
    # lookup -- timeline must resolve the year from the known relative path.
    _write_source(vault, "paper", 2015)
    _add(kg, "sources/paper.md", "source", [{"id": "p_topic", "label": "Topic"}])

    with patch.object(vault, "get_any", side_effect=AssertionError("get_any must not be called")):
        entries = kg_queries.timeline(conn, vault, "topic")

    assert entries[0].year == 2015


def test_timeline_limit_caps_matched_entities_and_entries(kg, conn, vault):
    for i in range(10):
        _write_source(vault, f"p{i}", 2000 + i)
        _add(kg, f"sources/p{i}.md", "source", [{"id": f"p{i}_topic", "label": f"Topic {i}"}])

    assert len(kg_queries.timeline(conn, vault, "topic", limit=3)) == 3
