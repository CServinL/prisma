"""Vault file sync endpoints (/sync/*) for the desktop (Tauri) client.

Whole-file, path-based (not slug-based) — the desktop mirrors the vault's
`.md` files 1:1 onto local disk (see the vault-sync plan / TODO.md's
"Deferred feature: desktop<->server sync"). KG/Chroma stay server-side only;
desktop never touches them — this router is the entire surface desktop
needs.

Built via a factory (`build_sync_router`) taking getter callables rather
than raw objects: app.py's `/reload`-style endpoints rebind its module
globals (`global _vault; _vault = VaultService(...)`) at runtime, so a
router that captured `_vault` by value at include_router() time would keep
talking to a stale, replaced instance after a reload. Getters re-read the
current global on every request, same as every other endpoint in app.py
already does implicitly by referencing the module-level name directly.
"""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from prisma.services.vault import VaultService
from prisma.utils.text import content_hash

_CLIENT_ID_HEADER = "x-sync-client-id"

# mtime equality tolerance for the optimistic-concurrency check below. Unix
# timestamps at today's magnitude (~1.78e9) leave float64 only ~238ns of
# resolution (confirmed live 2026-07-25: two mtimes one ULP apart --
# 1785018422.3829463 vs .3829465 -- compared unequal forever after a round
# trip through JSON serialization, Python -> Rust -> Python, causing an
# eternal single-file 409 loop that never resolved on its own). Exact `==`
# is fundamentally unsafe here; 1ms is orders of magnitude looser than the
# ULP-scale noise while still far tighter than any real edit-timing window.
_MTIME_TOLERANCE_SECONDS = 1e-3


class SyncManifestEntry(BaseModel):
    path: str
    mtime: float
    size: int


class SyncFileResponse(BaseModel):
    path: str
    body: str
    mtime: float


class SyncFileWriteRequest(BaseModel):
    path: str
    body: str
    expected_mtime: Optional[float] = None


def build_sync_router(
    get_vault: Callable[[], VaultService],
    broadcast_fn: Callable[..., None],
    mark_stale_fn: Callable[[str], None],
    update_baseline_fn: Callable[[str, str, str, float], None],
    clear_baseline_fn: Callable[[str, str], None],
) -> APIRouter:
    """`update_baseline_fn(client_id, path, hash, mtime)` / `clear_baseline_fn(client_id, path)`
    keep app.py's server-side sync_orchestrator baseline (the per-client
    "last known agreed state") in sync with what actually landed here — a
    successful PUT/DELETE is itself the ACK for an ASK_CLIENT_TO_PUSH
    decision (the HTTP response already proves it completed), unlike a
    PUSH_TO_CLIENT decision, which needs an explicit `file_synced` message
    back over the WS since there's no request/response round trip for that
    direction. See sync_orchestrator.py's own module doc comment."""
    router = APIRouter(prefix="/sync", tags=["sync"])

    @router.get("/manifest", response_model=list[SyncManifestEntry])
    def manifest():
        return [
            SyncManifestEntry(path=path, mtime=mtime, size=size)
            for path, mtime, size in get_vault().list_md_manifest()
        ]

    @router.get("/file", response_model=SyncFileResponse)
    def get_file(path: str = Query(...)):
        try:
            result = get_vault().read_by_path(path)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if result is None:
            raise HTTPException(status_code=404, detail=f"not found: {path!r}")
        body, mtime = result
        return SyncFileResponse(path=path, body=body, mtime=mtime)

    @router.put("/file", response_model=SyncFileResponse)
    def put_file(req: SyncFileWriteRequest, request: Request):
        vault = get_vault()
        try:
            current = vault.read_by_path(req.path)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        if current is not None:
            body, mtime = current
            # Either an explicit mtime mismatch, or the client believed
            # this path was brand new (expected_mtime is None) but the
            # server already has a file there — same ambiguity either way,
            # resolved identically client-side (compare mtimes, keep newer).
            if req.expected_mtime is None or abs(mtime - req.expected_mtime) > _MTIME_TOLERANCE_SECONDS:
                raise HTTPException(
                    status_code=409,
                    detail={"path": req.path, "body": body, "mtime": mtime},
                )

        try:
            new_mtime = vault.write_by_path(req.path, req.body)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        # mark_stale_fn checks the path itself (KnowledgeGraphService.
        # is_relevant_path) -- streams/*.yaml (the one other synced type,
        # see _safe_sync_path) is excluded from the KG's own file watcher,
        # so a bare unconditional mark_stale() here would set "stale" with
        # nothing ever able to clear it (confirmed live 2026-07-25 on Forge,
        # right after the vault-sync engine pushed a stream file).
        mark_stale_fn(req.path)
        client_id = request.headers.get(_CLIENT_ID_HEADER)
        if client_id:
            # This PUT succeeding is itself the ACK for an
            # ASK_CLIENT_TO_PUSH decision -- see build_sync_router's own
            # docstring for why this direction doesn't need a separate
            # WS message the way a server-initiated push-down does.
            update_baseline_fn(client_id, req.path, content_hash(req.body), new_mtime)
        broadcast_fn(
            {"type": "vault_change", "action": "sync_write", "path": req.path},
            exclude_client_id=client_id,
        )
        return SyncFileResponse(path=req.path, body=req.body, mtime=new_mtime)

    @router.delete("/file")
    def delete_file(request: Request, path: str = Query(...)):
        try:
            get_vault().delete_by_path(path)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        mark_stale_fn(path)
        client_id = request.headers.get(_CLIENT_ID_HEADER)
        if client_id:
            clear_baseline_fn(client_id, path)
        broadcast_fn(
            {"type": "vault_change", "action": "sync_delete", "path": path},
            exclude_client_id=client_id,
        )
        return {"status": "deleted", "path": path}

    return router
