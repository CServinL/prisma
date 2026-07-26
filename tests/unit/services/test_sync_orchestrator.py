"""Unit tests for sync_orchestrator.diff_manifest -- pure logic, no I/O.
Mirrors prisma-desktop's manifest::reconcile test suite (same
tracked/untracked lifecycle table, server's point of view instead of the
client's).
"""
from prisma.services.sync_orchestrator import SyncDecision, diff_manifest


def test_new_client_file_asks_client_to_push():
    client = {"notes/a.md": ("h1", 100.0)}
    decisions = diff_manifest({}, client, {})
    assert decisions == {"notes/a.md": SyncDecision.ASK_CLIENT_TO_PUSH}


def test_new_server_file_pushes_to_client():
    server = {"notes/a.md": ("h1", 100.0)}
    decisions = diff_manifest(server, {}, {})
    assert decisions == {"notes/a.md": SyncDecision.PUSH_TO_CLIENT}


def test_matching_hash_is_a_noop():
    server = {"notes/a.md": ("h1", 100.0)}
    client = {"notes/a.md": ("h1", 200.0)}  # mtime differs, hash doesn't -- still in sync
    decisions = diff_manifest(server, client, {})
    assert decisions == {}


def test_differing_hash_with_server_unchanged_since_baseline_asks_client_to_push():
    baseline = {"notes/a.md": ("h1", 100.0)}
    server = {"notes/a.md": ("h1", 100.0)}  # unchanged since baseline
    client = {"notes/a.md": ("h2", 150.0)}  # client edited
    decisions = diff_manifest(server, client, baseline)
    assert decisions == {"notes/a.md": SyncDecision.ASK_CLIENT_TO_PUSH}


def test_differing_hash_with_client_unchanged_since_baseline_pushes_to_client():
    baseline = {"notes/a.md": ("h1", 100.0)}
    server = {"notes/a.md": ("h2", 150.0)}  # server edited
    client = {"notes/a.md": ("h1", 100.0)}  # unchanged since baseline
    decisions = diff_manifest(server, client, baseline)
    assert decisions == {"notes/a.md": SyncDecision.PUSH_TO_CLIENT}


def test_both_changed_since_baseline_asks_client_to_push_letting_409_resolve_it():
    baseline = {"notes/a.md": ("h1", 100.0)}
    server = {"notes/a.md": ("h2", 150.0)}
    client = {"notes/a.md": ("h3", 160.0)}
    decisions = diff_manifest(server, client, baseline)
    assert decisions == {"notes/a.md": SyncDecision.ASK_CLIENT_TO_PUSH}


def test_no_baseline_but_both_present_and_differ_asks_client_to_push():
    server = {"notes/a.md": ("h1", 100.0)}
    client = {"notes/a.md": ("h2", 100.0)}
    decisions = diff_manifest(server, client, {})
    assert decisions == {"notes/a.md": SyncDecision.ASK_CLIENT_TO_PUSH}


def test_client_deleted_file_server_unchanged_deletes_on_server():
    baseline = {"notes/a.md": ("h1", 100.0)}
    server = {"notes/a.md": ("h1", 100.0)}  # server unchanged since baseline
    decisions = diff_manifest(server, {}, baseline)
    assert decisions == {"notes/a.md": SyncDecision.DELETE_ON_SERVER}


def test_client_deleted_file_but_server_changed_recreates_on_client():
    baseline = {"notes/a.md": ("h1", 100.0)}
    server = {"notes/a.md": ("h2", 150.0)}  # server changed since baseline
    decisions = diff_manifest(server, {}, baseline)
    assert decisions == {"notes/a.md": SyncDecision.PUSH_TO_CLIENT}


def test_server_deleted_file_client_unchanged_tells_client_to_delete():
    baseline = {"notes/a.md": ("h1", 100.0)}
    client = {"notes/a.md": ("h1", 100.0)}  # client unchanged since baseline
    decisions = diff_manifest({}, client, baseline)
    assert decisions == {"notes/a.md": SyncDecision.TELL_CLIENT_TO_DELETE}


def test_server_deleted_file_but_client_changed_recreates_on_server():
    baseline = {"notes/a.md": ("h1", 100.0)}
    client = {"notes/a.md": ("h2", 150.0)}  # client changed since baseline
    decisions = diff_manifest({}, client, baseline)
    assert decisions == {"notes/a.md": SyncDecision.ASK_CLIENT_TO_PUSH}


def test_absent_everywhere_is_a_noop():
    baseline = {"notes/ghost.md": ("h1", 100.0)}
    decisions = diff_manifest({}, {}, baseline)
    assert decisions == {}


def test_multiple_paths_are_each_diffed_independently():
    server = {"notes/server-only.md": ("h1", 100.0), "notes/both.md": ("h2", 100.0)}
    client = {"notes/client-only.md": ("h3", 100.0), "notes/both.md": ("h2", 100.0)}
    decisions = diff_manifest(server, client, {})
    assert decisions == {
        "notes/server-only.md": SyncDecision.PUSH_TO_CLIENT,
        "notes/client-only.md": SyncDecision.ASK_CLIENT_TO_PUSH,
    }
