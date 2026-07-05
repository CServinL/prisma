"""Unit tests for KnowledgeGraphService — the native, Kùzu-backed knowledge
graph module that replaces the third-party `graphify` pip dependency.
See TODO.md and docs/wiki/adr/ADR-012-process-supervision.md.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from prisma.services.knowledge_graph_service import (
    KnowledgeGraphService,
    _parse_extraction_response,
)


def test_parse_extraction_response_valid_json():
    text = json.dumps({"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "b"}]})
    nodes, edges = _parse_extraction_response(text)
    assert nodes == [{"id": "a"}]
    assert edges == [{"source": "a", "target": "b"}]


def test_parse_extraction_response_malformed_json_returns_empty():
    nodes, edges = _parse_extraction_response("not json at all {{{")
    assert nodes == []
    assert edges == []


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _mock_ollama_response(nodes=None, edges=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": json.dumps({"nodes": nodes or [], "edges": edges or []})}
    return resp


# ── Extraction + upsert ───────────────────────────────────────────────────────

def test_extract_file_upserts_nodes(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\n# Title\nSome content about neural networks.", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "test_neural_networks", "label": "Neural Networks"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        changed = kg._extract_file(f, "note")

    assert changed is True
    result = kg._conn.execute("MATCH (e:Entity) RETURN e.id, e.trust_tier")
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    assert ["test_neural_networks", "note"] in rows


def test_extract_file_upserts_edges(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: source\n---\nPaper A relates to Paper B.", encoding="utf-8")
    resp = _mock_ollama_response(
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        edges=[{"source": "a", "target": "b", "relation": "cites", "confidence": "EXTRACTED"}],
    )

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "source")

    result = kg._conn.execute("MATCH (a:Entity)-[r:RelatesTo]->(b:Entity) RETURN a.id, r.relation, b.id")
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    assert ["a", "cites", "b"] in rows


def test_extract_file_skips_call_when_lease_denied(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with patch("prisma.services.knowledge_graph_service.requests.post") as mock_post, \
         patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()):
        kg._extract_file(f, "note")

    assert not mock_post.called


def test_extract_file_does_not_advance_manifest_when_lease_denied(kg, vault):
    # Real bug this guards against: a file that changed while Ollama/the
    # compute pool was unreachable must not be marked processed — otherwise
    # it's silently never retried unless it changes again (roadmap.md's
    # Ollama resilience item).
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with patch("prisma.services.knowledge_graph_service.requests.post"), \
         patch("prisma.services.resource_lock.acquire", return_value=(False, None, None)), \
         patch("prisma.services.resource_lock.backoff.retry_with_backoff",
               side_effect=lambda attempt, is_success, **kw: attempt()):
        changed = kg._extract_file(f, "note")

    assert changed is False
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None


def test_extract_file_retries_after_connection_error_on_next_call(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")

    with patch("prisma.services.knowledge_graph_service.requests.post", side_effect=requests.ConnectionError("down")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None

    good = _mock_ollama_response(nodes=[{"id": "ok", "label": "OK"}])
    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=good), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is True
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is not None


def test_extract_file_advances_manifest_when_section_legitimately_finds_nothing(kg, vault):
    # A successful call that finds no entities is not the same as a failed
    # call — it must still count as "processed" so it isn't retried forever.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    empty = _mock_ollama_response(nodes=[], edges=[])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=empty), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is False  # nothing to upsert
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is not None  # but genuinely processed, not retried


def test_extract_file_one_bad_section_does_not_abort_others(kg, vault):
    # Force a small token budget so this modest test body still splits into
    # multiple sections — the service's real default is much larger now.
    kg._token_budget = 1500
    f = vault.root / "notes" / "test.md"
    body = "# One\n" + ("First section content. " * 400) + "\n# Two\n" + ("Second section content. " * 400)
    f.write_text(f"---\ntype: note\n---\n{body}", encoding="utf-8")
    good = _mock_ollama_response(nodes=[{"id": "ok", "label": "OK"}])
    bad = MagicMock(status_code=200)
    bad.json.return_value = {"response": "not valid json"}
    # First section's response is malformed; every later section (however many
    # semchunk produces for this body) succeeds — one bad section must not
    # abort the rest.
    responses = iter([bad] + [good] * 20)

    with patch("prisma.services.knowledge_graph_service.requests.post", side_effect=lambda *a, **kw: next(responses)), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is True
    result = kg._conn.execute("MATCH (e:Entity {id: 'ok'}) RETURN e.id")
    assert result.has_next()


def test_extract_file_survives_response_json_raising(kg, vault):
    # Regression: resp.json() and _parse_extraction_response() used to run
    # outside the request try/except, so a truncated/non-JSON HTTP body
    # raised unhandled inside the thread-pool worker instead of being
    # treated as "this section failed, retry next cycle" like every other
    # failure mode in _call_ollama_extract.
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content.", encoding="utf-8")
    broken = MagicMock(status_code=200)
    broken.json.side_effect = json.JSONDecodeError("bad", "doc", 0)

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=broken), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        changed = kg._extract_file(f, "note")

    assert changed is False
    with kg._lock:
        assert kg._indexed_hash("notes/test.md") is None


# ── Incremental caching ───────────────────────────────────────────────────────

def test_extract_file_skips_unchanged_content(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSame content.", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a", "label": "A"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp) as mock_post, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        first = kg._extract_file(f, "note")
        calls_after_first = mock_post.call_count
        second = kg._extract_file(f, "note")

    assert first is True
    assert second is False
    assert mock_post.call_count == calls_after_first  # no new calls on unchanged content


def test_extract_file_reextracts_on_content_change(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nOriginal.", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a", "label": "A"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp) as mock_post, \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")
        calls_after_first = mock_post.call_count
        f.write_text("---\ntype: note\n---\nCompletely different text now.", encoding="utf-8")
        changed = kg._extract_file(f, "note")

    assert changed is True
    assert mock_post.call_count > calls_after_first


# ── Deletion ──────────────────────────────────────────────────────────────────

def test_delete_file_removes_nodes(kg, vault):
    f = vault.root / "notes" / "gone.md"
    f.write_text("---\ntype: note\n---\nContent.", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "gone_node", "label": "Gone"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    assert kg._delete_file(f) is True
    result = kg._conn.execute("MATCH (e:Entity {id: 'gone_node'}) RETURN e.id")
    assert not result.has_next()
    with kg._lock:
        assert kg._indexed_hash("notes/gone.md") is None


# ── Trust tier ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node_type,expected_tier", [
    ("source", "source"),
    ("note", "note"),
    ("chat", "chat"),
    ("stream", "note"),
])
def test_trust_tier_for_maps_node_type(kg, vault, node_type, expected_tier):
    f = vault.root / "x.md"
    f.write_text(f"---\ntype: {node_type}\n---\ncontent", encoding="utf-8")
    assert kg._trust_tier_for(f) == expected_tier


def test_trust_tier_defaults_to_note_when_unreadable(kg, vault):
    missing = vault.root / "does-not-exist.md"
    assert kg._trust_tier_for(missing) == "note"


# ── Retrieval ─────────────────────────────────────────────────────────────────

def test_search_ranks_by_term_match(kg, vault):
    f1 = vault.root / "notes" / "a.md"
    f1.write_text("---\ntype: note\n---\nAbout neural networks.", encoding="utf-8")
    f2 = vault.root / "notes" / "b.md"
    f2.write_text("---\ntype: note\n---\nAbout cooking recipes.", encoding="utf-8")
    resp_a = _mock_ollama_response(nodes=[{"id": "a_neural_networks", "label": "Neural Networks"}])
    resp_b = _mock_ollama_response(nodes=[{"id": "b_recipes", "label": "Recipes"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", side_effect=[resp_a, resp_b]), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f1, "note")
        kg._extract_file(f2, "note")

    results = kg.search("neural networks")
    assert results
    assert results[0]["source_file"] == "notes/a.md"


def test_search_excludes_chat_trust_tier(kg, vault):
    f = vault.root / "chats" / "conversation.md"
    f.write_text("---\ntype: chat\n---\nDiscussed neural networks here.", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "chat_neural_networks", "label": "Neural Networks"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "chat")

    # search_vault-equivalent must never surface chat content — see TODO.md
    # "Chat trust tiers" section.
    assert kg.search("neural networks") == []


def test_search_returns_empty_for_no_matching_terms(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a_thing", "label": "Thing"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    assert kg.search("completely unrelated query xyz") == []


# ── Status / lifecycle ────────────────────────────────────────────────────────

def test_status_starts_stale(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    status = service.status()
    assert status["state"] == "stale"
    assert status["last_indexed"] is None
    assert status["last_error"] is None
    assert status["current_activity"] is None


def test_full_index_clears_activity_when_done(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a_thing", "label": "Thing"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    assert kg.status()["current_activity"] is None


def test_extract_file_sets_activity_during_extraction(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a_thing", "label": "Thing"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch.object(kg, "_set_activity", wraps=kg._set_activity) as mock_set_activity:
        kg._extract_file(f, "note")

    activities = [c.args[0] for c in mock_set_activity.call_args_list]
    assert any(a and "extracting notes/a.md" in a for a in activities)


def test_mark_stale_does_not_override_indexing_state(kg):
    with kg._lock:
        kg._state = "indexing"
    kg.mark_stale()
    assert kg.status()["state"] == "indexing"


def test_full_index_sets_idle_and_last_indexed(kg, vault):
    f = vault.root / "notes" / "a.md"
    f.write_text("---\ntype: note\n---\ncontent", encoding="utf-8")
    resp = _mock_ollama_response(nodes=[{"id": "a_thing", "label": "Thing"}])

    with patch("prisma.services.knowledge_graph_service.requests.post", return_value=resp), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._full_index()

    status = kg.status()
    assert status["state"] == "idle"
    assert status["last_indexed"] is not None
    assert status["last_error"] is None
