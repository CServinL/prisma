"""Verifies kg_app.py's new response_model= Pydantic models actually match
what KnowledgeGraphService's dict-typed methods really return -- these
models were hand-written by reading the service's dict-construction code,
so this is a real check against real service output, not just "does the
model parse example data I made up."

Only imports kg_app.py for its response-model *classes*; never touches its
module-level `_kg`/`_vault` globals (which point at whatever vault_root the
real config resolves to) -- a fresh KnowledgeGraphService against a tmp_path
vault is used instead, same fixtures as test_knowledge_graph_service.py.
"""
from unittest.mock import patch

import pytest

from prisma.server.kg_app import (
    DeadLetterEntry,
    EntitiesForFileResponse,
    GraphQueryResult,
    GraphSearchResult,
    KGStatus,
    RankedNode,
)
from prisma.services.knowledge_graph_service import Edge, Extraction, KnowledgeGraphService, Node
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


@pytest.fixture
def kg(vault, tmp_path):
    service = KnowledgeGraphService(vault, kg_dir=tmp_path / "kg-out")
    service._ensure_connection()
    return service


def _extraction(nodes=None, edges=None) -> Extraction:
    return Extraction(
        nodes=[Node(**n) for n in (nodes or [])],
        edges=[Edge(**e) for e in (edges or [])],
    )


def test_status_matches_response_model_when_empty(kg):
    KGStatus.model_validate(kg.status())


def test_status_matches_response_model_with_a_dropped_chunk(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")
    with patch.object(kg._instructor_client.chat.completions, "create", side_effect=ValueError("boom")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    KGStatus.model_validate(kg.status())


def test_entities_for_file_matches_response_model_when_empty(kg):
    EntitiesForFileResponse.model_validate(kg.entities_for_file("notes/never-extracted.md"))


def test_entities_for_file_matches_response_model_with_real_data(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: source\n---\nPaper A relates to Paper B.", encoding="utf-8")
    result = _extraction(
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        edges=[{"source": "a", "target": "b", "relation": "cites", "confidence": "EXTRACTED"}],
    )
    with patch.object(kg._instructor_client.chat.completions, "create", return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "source")

    EntitiesForFileResponse.model_validate(kg.entities_for_file("notes/test.md"))


def test_search_and_ranked_nodes_match_response_models(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nContent about quantum computing.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "quantum_computing", "label": "Quantum Computing"}])
    with patch.object(kg._instructor_client.chat.completions, "create", return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    search_results = kg.search("quantum")
    assert search_results  # non-empty, otherwise this test isn't checking anything
    for item in search_results:
        GraphSearchResult.model_validate(item)

    ranked = kg.ranked_nodes("quantum")
    assert ranked
    for item in ranked:
        RankedNode.model_validate(item)


def test_query_matches_response_model(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nContent about quantum computing.", encoding="utf-8")
    result = _extraction(nodes=[{"id": "quantum_computing", "label": "Quantum Computing"}])
    with patch.object(kg._instructor_client.chat.completions, "create", return_value=result), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")):
        kg._extract_file(f, "note")

    results = kg.query("quantum")
    assert results
    for item in results:
        GraphQueryResult.model_validate(item)


def test_list_dead_letters_matches_response_model(kg, vault):
    f = vault.root / "notes" / "test.md"
    f.write_text("---\ntype: note\n---\nSome content that will fail extraction.", encoding="utf-8")
    with patch.object(kg._instructor_client.chat.completions, "create", side_effect=ValueError("boom")), \
         patch("prisma.services.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
         patch("prisma.services.resource_lock.release"):
        kg._extract_file(f, "note")

    entries = kg.list_dead_letters()
    assert entries
    for entry in entries:
        DeadLetterEntry.model_validate(entry)
