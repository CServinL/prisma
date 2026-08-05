"""Prisma-specific type registry -- thin glue over the generic
`schema_gov.TypeRegistry`, keyed by `NodeType`. See ADR-019.
"""
from __future__ import annotations

from typing import Callable, Iterator

from prisma.schema_gov import TypeRegistry
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import (
    Chat, Note, NodeType, Source, Stream, VaultNodeBase,
)

REGISTRY: TypeRegistry[NodeType] = TypeRegistry()
REGISTRY.register(NodeType.note, Note)
REGISTRY.register(NodeType.source, Source)
REGISTRY.register(NodeType.chat, Chat)
REGISTRY.register(NodeType.stream, Stream)

_GETTERS: dict[NodeType, Callable[[VaultService, str], VaultNodeBase]] = {
    NodeType.note: VaultService.get_note,
    NodeType.source: VaultService.get_source,
    NodeType.chat: VaultService.get_chat,
    NodeType.stream: VaultService.get_stream,
}


def get_by_type(vault: VaultService, node_type: NodeType, slug: str) -> VaultNodeBase:
    getter = _GETTERS.get(node_type)
    if getter is None:
        raise NotImplementedError(f"get_by_type not wired for {node_type} yet")
    return getter(vault, slug)


def find(
    vault: VaultService, node_type: NodeType, predicate: Callable[[VaultNodeBase], bool] | None = None,
) -> Iterator[VaultNodeBase]:
    """Full typed instances of one type, filterable -- built on
    list_nodes() for slug discovery + get_by_type() for full loading, not a
    second directory walk. This is the capability list_nodes() (lightweight
    VaultNodeMeta summaries, no body) and get_any() (resolves exactly one
    known slug) don't provide on their own."""
    listing = vault.list_nodes(node_type)
    metas = {
        NodeType.note: listing.notes,
        NodeType.source: listing.sources,
        NodeType.chat: listing.chats,
        NodeType.stream: listing.streams,
    }[node_type]
    for meta in metas:
        obj = get_by_type(vault, node_type, meta.slug)
        if predicate is None or predicate(obj):
            yield obj
