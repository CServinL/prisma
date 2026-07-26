"""Server-side sync orchestration (2026-07-26 redesign): the server is now
the sole authority deciding push vs. pull vs. conflict for the desktop's
local vault mirror. See prisma-desktop's sync/pull.rs module doc comment
for the full rationale -- the previous design let the desktop's own fs
watcher decide unilaterally when to push, which caused a real, sustained
bug: the watcher firing was never proof content actually changed, and with
two independent sides each free to act, nothing arbitrated a spurious or
duplicate event, and it looped hundreds of times against unchanged content.

`diff_manifest` is pure, allocation-only logic (no I/O, no locks) so it's
unit-testable on its own -- the actual WebSocket message dispatch lives in
app.py's websocket_endpoint, the thin I/O shell around it. Same split as
prisma-desktop's manifest.rs (reconcile vs. the code that used to call it).

Comparisons are by content hash (SHA256, matching prisma-desktop's
content_hash()), not mtime. mtime alone isn't safe for this: see prisma#40,
where two mtimes one float64 ULP apart (a real, reproducible case at
today's Unix-timestamp magnitude) compared unequal forever. Hashes have no
such precision-boundary failure mode.
"""
from __future__ import annotations

from enum import Enum


class SyncDecision(Enum):
    ASK_CLIENT_TO_PUSH = "ask_client_to_push"
    PUSH_TO_CLIENT = "push_to_client"
    TELL_CLIENT_TO_DELETE = "tell_client_to_delete"
    DELETE_ON_SERVER = "delete_on_server"


def diff_manifest(
    server_files: dict[str, tuple[str, float]],
    client_files: dict[str, tuple[str, float]],
    baseline: dict[str, tuple[str, float]],
) -> dict[str, SyncDecision]:
    """`server_files`/`client_files`/`baseline` map vault-relative path to
    (content_hash, mtime). `baseline` is the last-known-agreed state for
    this specific client (per-client, see app.py's _client_baseline) --
    what both sides had the last time they were confirmed in sync, used to
    tell "who changed since then" apart from "who's just behind."

    Mirrors prisma-desktop's manifest::reconcile's tracked/untracked
    lifecycle table exactly, just from the server's point of view: what
    Rust's client called "push" (local -> remote) is ASK_CLIENT_TO_PUSH
    here, and what it called "pull" (remote -> local) is PUSH_TO_CLIENT.
    """
    decisions: dict[str, SyncDecision] = {}
    for path in set(server_files) | set(client_files) | set(baseline):
        s = server_files.get(path)
        c = client_files.get(path)
        b = baseline.get(path)

        if s and c:
            if s[0] == c[0]:
                continue  # already in sync
            if b and b[0] == s[0]:
                # Server unchanged since baseline, client differs -> client has a new edit.
                decisions[path] = SyncDecision.ASK_CLIENT_TO_PUSH
            elif b and b[0] == c[0]:
                # Client unchanged since baseline, server differs -> server has a new edit.
                decisions[path] = SyncDecision.PUSH_TO_CLIENT
            else:
                # Both changed since baseline (or no baseline at all) --
                # ambiguous. Ask the client to push rather than guess a
                # winner here: its own expected_mtime/409 conflict
                # machinery (PUT /sync/file) already safely resolves this,
                # preserving the losing side as a .conflict-<ts> copy.
                decisions[path] = SyncDecision.ASK_CLIENT_TO_PUSH
        elif s and not c:
            if b and b[0] == s[0]:
                # Client deleted it; server hasn't changed since -> propagate the delete.
                decisions[path] = SyncDecision.DELETE_ON_SERVER
            else:
                # No baseline, or server changed since -> don't lose data, recreate on client.
                decisions[path] = SyncDecision.PUSH_TO_CLIENT
        elif c and not s:
            if b and b[0] == c[0]:
                # Server deleted it; client hasn't changed since -> propagate the delete.
                decisions[path] = SyncDecision.TELL_CLIENT_TO_DELETE
            else:
                # No baseline, or client changed since -> don't lose data, recreate on server.
                decisions[path] = SyncDecision.ASK_CLIENT_TO_PUSH
        # else: neither side has it -- nothing to do (and it naturally
        # falls out of baseline on the next confirmed-in-sync update).
    return decisions
