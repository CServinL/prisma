"""Prisma-specific type registry -- thin glue over the generic
`schema_gov.TypeRegistry`, keyed by `NodeType`. See ADR-019.

`NodeType.chat` is registered against `ChatSession` (the target shape),
not `VaultService.get_chat()`'s still-current `Chat` (the .md/markdown
shape) -- schema export (below) should describe where chats are headed,
even before the API/frontend cutover phase makes `get_chat()` return
`ChatSession` for real. `find()`/`get_by_type()` deliberately don't wire a
getter for chats yet for the same reason: wiring one now would either
return the wrong type (`Chat`, mismatching what's registered) or silently
do nothing (`list_nodes()` only scans `.md` files today, and chats haven't
moved to `.sess` yet) -- clearer to raise than to paper over either.
"""
from __future__ import annotations

from typing import Callable, Iterator

from prisma.schema_gov import TypeRegistry
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import (
    ChatSession, Note, NodeType, Source, Stream, VaultNodeBase,
)

REGISTRY: TypeRegistry[NodeType] = TypeRegistry()
REGISTRY.register(NodeType.note, Note)
REGISTRY.register(NodeType.source, Source)
REGISTRY.register(NodeType.chat, ChatSession)
REGISTRY.register(NodeType.stream, Stream)

_GETTERS: dict[NodeType, Callable[[VaultService, str], VaultNodeBase]] = {
    NodeType.note: VaultService.get_note,
    NodeType.source: VaultService.get_source,
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
