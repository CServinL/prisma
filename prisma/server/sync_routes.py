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

_CLIENT_ID_HEADER = "x-sync-client-id"


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
    mark_stale_fn: Callable[[], None],
) -> APIRouter:
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
            if req.expected_mtime is None or mtime != req.expected_mtime:
                raise HTTPException(
                    status_code=409,
                    detail={"path": req.path, "body": body, "mtime": mtime},
                )

        try:
            new_mtime = vault.write_by_path(req.path, req.body)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        mark_stale_fn()
        broadcast_fn(
            {"type": "vault_change", "action": "sync_write", "path": req.path},
            exclude_client_id=request.headers.get(_CLIENT_ID_HEADER),
        )
        return SyncFileResponse(path=req.path, body=req.body, mtime=new_mtime)

    @router.delete("/file")
    def delete_file(request: Request, path: str = Query(...)):
        try:
            get_vault().delete_by_path(path)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        mark_stale_fn()
        broadcast_fn(
            {"type": "vault_change", "action": "sync_delete", "path": path},
            exclude_client_id=request.headers.get(_CLIENT_ID_HEADER),
        )
        return {"status": "deleted", "path": path}

    return router
