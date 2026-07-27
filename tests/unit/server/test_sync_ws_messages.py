"""Unit tests for the WS sync protocol's Pydantic message models
(prisma.server.app) -- previously these messages were parsed as raw dicts
with manual .get()/"key" in dict checks; a manifest_response entry missing
"mtime" raised an uncaught KeyError that dropped the entire message rather
than just that one bad entry.
"""
import pytest
from pydantic import ValidationError

from prisma.server.app import (
    FileChangedMsg,
    FileDeletedMsg,
    FileSyncedMsg,
    SyncManifestFileEntry,
)


def test_sync_manifest_file_entry_accepts_valid_data():
    entry = SyncManifestFileEntry.model_validate({"path": "notes/a.md", "hash": "abc123", "mtime": 100.0})
    assert entry.path == "notes/a.md"
    assert entry.hash == "abc123"
    assert entry.mtime == 100.0


def test_sync_manifest_file_entry_rejects_missing_mtime():
    # The exact case that used to raise an uncaught KeyError deep inside a
    # dict comprehension, dropping the whole manifest_response message.
    with pytest.raises(ValidationError):
        SyncManifestFileEntry.model_validate({"path": "notes/a.md", "hash": "abc123"})


def test_sync_manifest_file_entry_rejects_missing_path():
    with pytest.raises(ValidationError):
        SyncManifestFileEntry.model_validate({"hash": "abc123", "mtime": 100.0})


def test_sync_manifest_file_entry_rejects_wrong_type():
    with pytest.raises(ValidationError):
        SyncManifestFileEntry.model_validate({"path": "notes/a.md", "hash": "abc123", "mtime": "not-a-number"})


def test_file_changed_msg_accepts_valid_data():
    msg = FileChangedMsg.model_validate({"type": "file_changed", "path": "notes/a.md", "hash": "h1", "mtime": 1.0})
    assert msg.path == "notes/a.md"
    assert msg.hash == "h1"
    assert msg.mtime == 1.0


def test_file_changed_msg_rejects_missing_hash():
    with pytest.raises(ValidationError):
        FileChangedMsg.model_validate({"type": "file_changed", "path": "notes/a.md", "mtime": 1.0})


def test_file_deleted_msg_only_requires_path():
    msg = FileDeletedMsg.model_validate({"type": "file_deleted", "path": "notes/a.md"})
    assert msg.path == "notes/a.md"


def test_file_deleted_msg_rejects_missing_path():
    with pytest.raises(ValidationError):
        FileDeletedMsg.model_validate({"type": "file_deleted"})


def test_file_synced_msg_defaults_hash_and_mtime():
    msg = FileSyncedMsg.model_validate({"type": "file_synced", "path": "notes/a.md"})
    assert msg.path == "notes/a.md"
    assert msg.hash == ""
    assert msg.mtime == 0.0


def test_file_synced_msg_accepts_explicit_hash_and_mtime():
    msg = FileSyncedMsg.model_validate({"type": "file_synced", "path": "notes/a.md", "hash": "h1", "mtime": 5.0})
    assert msg.hash == "h1"
    assert msg.mtime == 5.0
