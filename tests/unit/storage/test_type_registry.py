"""Unit tests for prisma's type registry glue (ADR-019)."""
import pytest

from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import ChatSession, Note, NodeType, Source, Stream
from prisma.storage.type_registry import REGISTRY, find, get_by_type


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_registry_maps_every_node_type():
    assert REGISTRY.get(NodeType.note) is Note
    assert REGISTRY.get(NodeType.source) is Source
    assert REGISTRY.get(NodeType.chat) is ChatSession
    assert REGISTRY.get(NodeType.stream) is Stream


def test_get_by_type_resolves_a_real_note(vault):
    vault.create_note(title="My Note", body="content")
    note = get_by_type(vault, NodeType.note, "my-note")
    assert isinstance(note, Note)
    assert note.title == "My Note"


def test_get_by_type_raises_not_implemented_for_chat():
    vault = VaultService()
    with pytest.raises(NotImplementedError):
        get_by_type(vault, NodeType.chat, "some-slug")


def test_find_returns_full_typed_instances_not_summaries(vault):
    vault.create_note(title="A", body="1")
    vault.create_note(title="B", body="2")
    found = list(find(vault, NodeType.note))
    assert len(found) == 2
    assert all(isinstance(n, Note) for n in found)
    assert {n.body for n in found} == {"1", "2"}


def test_find_applies_predicate(vault):
    vault.create_note(title="Keep", body="keep me")
    vault.create_note(title="Skip", body="skip me")
    found = list(find(vault, NodeType.note, predicate=lambda n: "keep" in n.body))
    assert len(found) == 1
    assert found[0].title == "Keep"
