"""Unit tests for the shared vault-path relevance check (prisma.utils.vault_paths)
— consolidates what used to be three independently-drifting inline copies in
KnowledgeGraphService's is_relevant_path/watcher and ChromaIndexer's watcher."""
from pathlib import Path

from prisma.utils.vault_paths import is_relevant_vault_path


def test_accepts_matching_extension_in_scope():
    assert is_relevant_vault_path(Path("notes/a.md"), {".md"}) is True


def test_rejects_non_matching_extension():
    assert is_relevant_vault_path(Path("notes/a.txt"), {".md"}) is False


def test_rejects_dotfile():
    assert is_relevant_vault_path(Path("notes/.hidden.md"), {".md"}) is False


def test_rejects_vault_files_dir():
    assert is_relevant_vault_path(Path(".vault-files/kg-out/a.md"), {".md"}) is False


def test_rejects_streams_dir():
    assert is_relevant_vault_path(Path("streams/topic.md"), {".md"}) is False


def test_extra_exclude_dirs_are_additive_not_replacing_base_set():
    # ChromaIndexer's actual usage: base exclusions still apply alongside its
    # own "chats" exclusion.
    extra = frozenset({"chats"})
    assert is_relevant_vault_path(Path("chats/session.md"), {".md"}, extra_exclude_dirs=extra) is False
    assert is_relevant_vault_path(Path("streams/topic.md"), {".md"}, extra_exclude_dirs=extra) is False
    assert is_relevant_vault_path(Path("notes/a.md"), {".md"}, extra_exclude_dirs=extra) is True


def test_chats_dir_allowed_when_no_extra_exclusion_given():
    # KnowledgeGraphService's actual usage — chats ARE KG-indexed, unlike Chroma.
    assert is_relevant_vault_path(Path("chats/session.md"), {".md"}) is True


def test_multiple_extensions_supported():
    exts = {".md", ".yaml"}
    assert is_relevant_vault_path(Path("notes/a.yaml"), exts) is True
    assert is_relevant_vault_path(Path("notes/a.json"), exts) is False
