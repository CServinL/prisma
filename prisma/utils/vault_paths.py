"""Shared vault-relative path relevance/exclusion logic.

Both the knowledge graph indexer and the ChromaDB indexer watch the vault
root and need to decide "is this path something I should process," and both
had grown their own independently-drifting inline copy of the same base
check (confirmed 2026-07-26 — see `knowledge_graph_service.py`'s
`is_relevant_path` docstring for the concrete incident this caused once
already: a watcher/mark_stale mismatch left the KG's "stale" state stuck
forever). `extensions`/`extra_exclude_dirs` let each indexer keep its own
scope (the KG indexes chats, ChromaDB deliberately does not) while sharing
one base exclusion set, instead of three copies of the same three lines.
"""
from __future__ import annotations

from pathlib import Path

_ALWAYS_EXCLUDE_DIRS = frozenset({".vault-files", "streams"})


def is_relevant_vault_path(
    path: Path,
    extensions: frozenset[str] | set[str],
    extra_exclude_dirs: frozenset[str] = frozenset(),
) -> bool:
    """Whether `path` is something a vault-watching indexer should process."""
    exclude_dirs = _ALWAYS_EXCLUDE_DIRS | extra_exclude_dirs
    if any(p in path.parts for p in exclude_dirs) or path.name.startswith("."):
        return False
    return path.suffix in extensions
