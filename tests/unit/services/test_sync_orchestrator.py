"""Unit tests for sync_orchestrator.diff_manifest -- pure logic, no I/O.
Mirrors prisma-desktop's manifest::reconcile test suite (same
tracked/untracked lifecycle table, server's point of view instead of the
client's).
"""
import pytest

from prisma.services.sync_orchestrator import SyncDecision, diff_manifest

_PATH = "notes/a.md"

# Each row is one branch of diff_manifest's tracked/untracked lifecycle
# table for a single path -- same table prisma-desktop's manifest.rs tests
# cover from the client's point of view. expected=None means the path
# produces no decision at all (not present in the returned dict).
_CASES = [
    pytest.param(
        {}, {_PATH: ("h1", 100.0)}, {}, SyncDecision.ASK_CLIENT_TO_PUSH,
        id="new_client_file_asks_client_to_push",
    ),
    pytest.param(
        {_PATH: ("h1", 100.0)}, {}, {}, SyncDecision.PUSH_TO_CLIENT,
        id="new_server_file_pushes_to_client",
    ),
    pytest.param(
        {_PATH: ("h1", 100.0)}, {_PATH: ("h1", 200.0)}, {}, None,
        id="matching_hash_is_a_noop",  # mtime differs, hash doesn't -- still in sync
    ),
    pytest.param(
        {_PATH: ("h1", 100.0)}, {_PATH: ("h2", 150.0)}, {_PATH: ("h1", 100.0)},
        SyncDecision.ASK_CLIENT_TO_PUSH,
        id="differing_hash_with_server_unchanged_since_baseline_asks_client_to_push",
    ),
    pytest.param(
        {_PATH: ("h2", 150.0)}, {_PATH: ("h1", 100.0)}, {_PATH: ("h1", 100.0)},
        SyncDecision.PUSH_TO_CLIENT,
        id="differing_hash_with_client_unchanged_since_baseline_pushes_to_client",
    ),
    pytest.param(
        {_PATH: ("h2", 150.0)}, {_PATH: ("h3", 160.0)}, {_PATH: ("h1", 100.0)},
        SyncDecision.ASK_CLIENT_TO_PUSH,
        id="both_changed_since_baseline_asks_client_to_push_letting_409_resolve_it",
    ),
    pytest.param(
        {_PATH: ("h1", 100.0)}, {_PATH: ("h2", 100.0)}, {}, SyncDecision.ASK_CLIENT_TO_PUSH,
        id="no_baseline_but_both_present_and_differ_asks_client_to_push",
    ),
    pytest.param(
        {_PATH: ("h1", 100.0)}, {}, {_PATH: ("h1", 100.0)}, SyncDecision.DELETE_ON_SERVER,
        id="client_deleted_file_server_unchanged_deletes_on_server",
    ),
    pytest.param(
        {_PATH: ("h2", 150.0)}, {}, {_PATH: ("h1", 100.0)}, SyncDecision.PUSH_TO_CLIENT,
        id="client_deleted_file_but_server_changed_recreates_on_client",
    ),
    pytest.param(
        {}, {_PATH: ("h1", 100.0)}, {_PATH: ("h1", 100.0)}, SyncDecision.TELL_CLIENT_TO_DELETE,
        id="server_deleted_file_client_unchanged_tells_client_to_delete",
    ),
    pytest.param(
        {}, {_PATH: ("h2", 150.0)}, {_PATH: ("h1", 100.0)}, SyncDecision.ASK_CLIENT_TO_PUSH,
        id="server_deleted_file_but_client_changed_recreates_on_server",
    ),
    pytest.param(
        {}, {}, {"notes/ghost.md": ("h1", 100.0)}, None,
        id="absent_everywhere_is_a_noop",
    ),
]


@pytest.mark.parametrize("server, client, baseline, expected", _CASES)
def test_diff_manifest_single_path_decision(server, client, baseline, expected):
    decisions = diff_manifest(server, client, baseline)
    assert decisions == ({_PATH: expected} if expected is not None else {})


def test_multiple_paths_are_each_diffed_independently():
    server = {"notes/server-only.md": ("h1", 100.0), "notes/both.md": ("h2", 100.0)}
    client = {"notes/client-only.md": ("h3", 100.0), "notes/both.md": ("h2", 100.0)}
    decisions = diff_manifest(server, client, {})
    assert decisions == {
        "notes/server-only.md": SyncDecision.PUSH_TO_CLIENT,
        "notes/client-only.md": SyncDecision.ASK_CLIENT_TO_PUSH,
    }
