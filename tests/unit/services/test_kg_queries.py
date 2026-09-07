"""Unit tests for prisma.services.kg_queries — pure retrieval over a real
embedded Kùzu graph (same fixture pattern as test_knowledge_graph_service.py:
tmp_path-backed Kùzu, nothing mocked here since there's no LLM call).
"""
import pytest

from prisma.services import kg_queries
from prisma.services.knowledge_graph_service import KnowledgeGraphService


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


# ── god_nodes ─────────────────────────────────────────────────────────────────

def test_god_nodes_adds_source_file_and_sample_relations(kg, conn):
    _add(
        kg, "notes/a.md", "note",
        [{"id": "hub", "label": "Hub"}, {"id": "l1", "label": "L1"}, {"id": "l2", "label": "L2"}],
        [
            {"source": "hub", "target": "l1", "relation": "cites"},
            {"source": "hub", "target": "l2", "relation": "builds_on"},
        ],
    )
    top = kg_queries.god_nodes(conn)
    hub = next(e for e in top if e.id == "hub")
    assert hub.degree == 2
    assert hub.source_file == "notes/a.md"
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
    assert all(edge.source == "center" for edge in resp.edges)


def test_expand_node_excludes_chat_tier_neighbours(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "center", "label": "Center"}])
    _add(kg, "chats/c.md", "chat", [{"id": "chatty", "label": "Chatty"}],
         [{"source": "center", "target": "chatty"}])
    resp = kg_queries.expand_node(conn, "center")
    assert resp.entities == []


def test_expand_node_empty_for_unknown_id(kg, conn):
    resp = kg_queries.expand_node(conn, "nope")
    assert resp.entities == [] and resp.edges == []


def test_expand_node_empty_id_is_empty(conn):
    assert kg_queries.expand_node(conn, "").entities == []


# ── surprising_connections ────────────────────────────────────────────────────
# "Emerges from the KG itself, with no prior knowledge of it anywhere" (cservinl's
# definition): a 2-hop link where the two hops came from different documents, the
# endpoints don't already share a document, and no document ever asserted a
# direct edge between them.

def test_surprising_connections_finds_cross_document_bridge(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "bridge", "label": "Bridge"}],
         [{"source": "a", "target": "bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}],
         [{"source": "bridge", "target": "c", "relation": "extends"}])

    results = kg_queries.surprising_connections(conn, hub_ids=set())

    assert len(results) == 1
    link = results[0]
    assert link.bridge == "bridge"
    assert {link.entity_a, link.entity_b} == {"a", "c"}
    assert {link.relation_a, link.relation_b} == {"cites", "extends"}


def test_surprising_connections_excludes_directly_asserted_pairs(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "bridge", "label": "Bridge"}],
         [{"source": "a", "target": "bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}],
         [{"source": "bridge", "target": "c", "relation": "extends"},
          {"source": "a", "target": "c", "relation": "already_known"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


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
    _add(kg, "notes/x.md", "note", [{"id": "bridge", "label": "Bridge"}],
         [{"source": "a", "target": "bridge", "relation": "cites"}])
    _add(kg, "notes/y.md", "note", [],
         [{"source": "bridge", "target": "c", "relation": "extends"}])

    assert kg_queries.surprising_connections(conn, hub_ids=set()) == []


def test_surprising_connections_excludes_hub_mediated_links(kg, conn):
    _add(kg, "notes/a.md", "note", [{"id": "a", "label": "A"}, {"id": "bridge", "label": "Bridge"}],
         [{"source": "a", "target": "bridge", "relation": "cites"}])
    _add(kg, "notes/b.md", "note", [{"id": "c", "label": "C"}],
         [{"source": "bridge", "target": "c", "relation": "extends"}])

    assert kg_queries.surprising_connections(conn, hub_ids={"bridge"}) == []


def test_surprising_connections_none_conn_is_empty():
    assert kg_queries.surprising_connections(None, hub_ids=set()) == []


def test_surprising_connections_respects_limit(kg, conn):
    for i in range(3):
        _add(kg, f"notes/a{i}.md", "note", [{"id": f"a{i}", "label": f"A{i}"}, {"id": f"bridge{i}", "label": "Bridge"}],
             [{"source": f"a{i}", "target": f"bridge{i}", "relation": "cites"}])
        _add(kg, f"notes/b{i}.md", "note", [{"id": f"c{i}", "label": f"C{i}"}],
             [{"source": f"bridge{i}", "target": f"c{i}", "relation": "extends"}])

    assert len(kg_queries.surprising_connections(conn, hub_ids=set(), limit=2)) == 2


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


def test_timeline_empty_for_no_terms(conn, vault):
    assert kg_queries.timeline(conn, vault, "  ") == []


def test_timeline_excludes_chat_tier(kg, conn, vault):
    _add(kg, "chats/c.md", "chat", [{"id": "c_topic", "label": "Topic"}])
    assert kg_queries.timeline(conn, vault, "topic") == []
