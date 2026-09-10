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


def test_expand_node_empty_for_unknown_id(kg, conn):
    resp = kg_queries.expand_node(conn, "nope")
    assert resp.entities == [] and resp.edges == []


def test_expand_node_empty_id_is_empty(conn):
    assert kg_queries.expand_node(conn, "").entities == []


# ── surprising_connections ────────────────────────────────────────────────────
# "Emerges from the KG itself, with no prior knowledge of it anywhere" (cservinl's
# definition): a link where the two hops came from different documents, the
# endpoints don't already share a document, and no document ever asserted a
# direct edge between them. Bridges by normalised *label*, not entity id (PR
# #104 review): real extraction mints a document-scoped id per
# `_extraction_system_prompt`'s `{stem}_{entity}` format, so the same concept
# in two documents is always two different ids -- these fixtures use distinct
# ids with a shared label throughout, matching what production extraction
# actually produces, not a single id manually reused across documents.

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


def test_timeline_resolves_year_by_directory_not_just_filename(kg, conn, vault):
    # Same filename ("paper") in two different directories -- a bare
    # `Path(source_file).stem` lookup would resolve both entities to
    # whichever one `vault.get_any("paper")` happens to find, silently
    # attaching the wrong year to one of them.
    _write_source(vault, "paper", 1990)
    (vault.root / "archive").mkdir(parents=True, exist_ok=True)
    (vault.root / "archive" / "paper.md").write_text(
        "---\ntype: source\ntitle: paper\nyear: 2020\n---\nbody", encoding="utf-8",
    )
    _add(kg, "sources/paper.md", "source", [{"id": "old_topic", "label": "Topic"}])
    _add(kg, "archive/paper.md", "source", [{"id": "new_topic", "label": "Topic"}])

    entries = kg_queries.timeline(conn, vault, "topic")

    years = {e.id: e.year for e in entries}
    assert years["old_topic"] == 1990
    assert years["new_topic"] == 2020


def test_timeline_empty_for_no_terms(conn, vault):
    assert kg_queries.timeline(conn, vault, "  ") == []


def test_timeline_excludes_chat_tier(kg, conn, vault):
    _add(kg, "chats/c.md", "chat", [{"id": "c_topic", "label": "Topic"}])
    assert kg_queries.timeline(conn, vault, "topic") == []
