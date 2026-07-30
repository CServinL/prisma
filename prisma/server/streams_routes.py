"""Research stream endpoints (/streams/*) plus the background scheduler that
runs them on their own schedule.

Built via a factory (`build_streams_router`) taking getter/callback
callables rather than raw objects, same reasoning as sync_routes.py's
`build_sync_router`/notes_routes.py's `build_notes_router`: app.py's
`/reload`-style endpoints rebind its module globals (`global _vault; _vault
= VaultService(...)`, similarly for `_zotero`) at runtime, so a router (or
`StreamScheduler`, a long-lived background thread that outlives any single
request) that captured them by value would keep talking to a stale,
replaced instance after a reload. `broadcast` is passed in rather than
imported directly because it closes over app.py-local WebSocket connection
state (`_ws_loop`/`_ws_clients`) -- importing it here would be a circular
import.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from prisma.integrations.zotero import ZoteroClient
from prisma.server import log_setup as _log_setup
from prisma.server.notes_routes import render_note
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import RenderedNode, StreamRunResult

_activity = logging.getLogger("prisma.activity")
_maint_log = logging.getLogger("prisma.maintenance")


class StreamMeta(BaseModel):
    slug: str
    title: str
    description: Optional[str] = None
    query: str
    status: str
    refresh_frequency: str
    total_papers: int = 0
    last_updated: Optional[str] = None
    next_update: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class StreamCreateRequest(BaseModel):
    title: str
    query: str
    description: Optional[str] = None
    refresh_frequency: str = "weekly"
    tags: Optional[list[str]] = None


class StreamPatchRequest(BaseModel):
    title: Optional[str] = None
    query: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    refresh_frequency: Optional[str] = None
    tags: Optional[list[str]] = None


def _stream_meta(s) -> StreamMeta:
    return StreamMeta(
        slug=s.slug,
        title=s.title,
        description=s.description,
        query=s.query,
        status=s.status.value,
        refresh_frequency=s.refresh_frequency.value,
        total_papers=s.total_papers,
        last_updated=s.last_updated.isoformat() if s.last_updated else None,
        next_update=s.next_update.isoformat() if s.next_update else None,
        tags=s.tags,
    )


def run_stream_and_notify(
    vault: VaultService, zotero: ZoteroClient, slug: str,
    broadcast_fn: Callable[..., None], *, force: bool = False,
) -> StreamRunResult:
    """Shared by POST /streams/{slug}/run and StreamScheduler's tick -- both
    need the exact same broadcast-progress-then-run-then-broadcast-result
    sequence, just triggered by a request vs. a timer."""
    from prisma.services.stream_runner import run_stream as _runner
    try:
        vault.get_stream(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
    broadcast_fn({"type": "stream_progress", "slug": slug, "status": "running"})
    result = _runner(slug, vault, zotero, force=force, get_stream_logger=_log_setup.get_stream_logger)
    _activity.info(
        "action=run_stream slug=%s found=%d saved=%d skipped_llm=%d errors=%d",
        slug, result.papers_found, result.papers_saved, result.papers_skipped_llm, len(result.errors),
    )
    broadcast_fn({"type": "stream_progress", "slug": slug, "status": "done",
               "found": result.papers_found, "saved": result.papers_saved})
    return result


class StreamScheduler:
    """Background thread that runs streams when their next_update is past."""

    _CHECK_INTERVAL = 5 * 60  # seconds between scans

    def __init__(
        self,
        get_vault: Callable[[], VaultService],
        get_zotero: Callable[[], ZoteroClient],
        broadcast_fn: Callable[..., None],
    ) -> None:
        self._get_vault = get_vault
        self._get_zotero = get_zotero
        self._broadcast = broadcast_fn
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="stream-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        self._stop_event.wait(timeout=30)  # let server finish starting up
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(timeout=self._CHECK_INTERVAL)

    def _tick(self) -> None:
        from datetime import datetime
        from prisma.storage.models.vault_models import StreamStatus
        vault = self._get_vault()
        try:
            streams = vault.list_streams()
        except Exception as exc:
            _maint_log.warning("stream-scheduler: list_streams failed: %s", exc)
            return
        now = datetime.now()
        due = [s for s in streams if s.status == StreamStatus.active
               and s.refresh_frequency.value != "manual"
               and (s.next_update is None or s.next_update <= now)]
        _maint_log.info("stream-scheduler: tick — %d streams checked, %d due", len(streams), len(due))
        for stream in due:
            _maint_log.info("stream-scheduler: running %r", stream.slug)
            try:
                t0 = time.monotonic()
                result = run_stream_and_notify(vault, self._get_zotero(), stream.slug, self._broadcast, force=False)
                elapsed_ms = (time.monotonic() - t0) * 1000
                _maint_log.info(
                    "stream-scheduler: %r done — found=%d saved=%d elapsed_ms=%.0f",
                    stream.slug, result.papers_found, result.papers_saved, elapsed_ms,
                )
            except Exception as exc:
                _maint_log.warning("stream-scheduler: %r failed: %s", stream.slug, exc)


def build_streams_router(
    get_vault: Callable[[], VaultService],
    get_zotero: Callable[[], ZoteroClient],
    broadcast_fn: Callable[..., None],
) -> APIRouter:
    router = APIRouter(prefix="/streams", tags=["streams"])

    @router.get("", response_model=list[StreamMeta])
    def list_streams():
        return [_stream_meta(s) for s in get_vault().list_streams()]

    @router.get("/{slug}", response_model=StreamMeta)
    def get_stream(slug: str):
        try:
            return _stream_meta(get_vault().get_stream(slug))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")

    @router.get("/{slug}/view", response_model=RenderedNode)
    def get_stream_view(slug: str, request: Request, format: str = "html"):
        return render_note(get_vault(), slug, request, format)

    @router.post("", response_model=StreamMeta, status_code=201)
    def create_stream(req: StreamCreateRequest):
        s = get_vault().create_stream(
            title=req.title,
            query=req.query,
            description=req.description,
            refresh_frequency=req.refresh_frequency,
            tags=req.tags,
        )
        # No mark_stale() -- streams/*.yaml is never KG-indexable content (see
        # KnowledgeGraphService.is_relevant_path), so it would just set "stale"
        # with nothing ever able to clear it.
        _activity.info("action=create_stream slug=%s query=%r freq=%s", s.slug, req.query, req.refresh_frequency)
        return _stream_meta(s)

    @router.patch("/{slug}", response_model=StreamMeta)
    def patch_stream(slug: str, req: StreamPatchRequest):
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        try:
            s = get_vault().save_stream(slug, **updates)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
        return _stream_meta(s)

    @router.delete("/{slug}", status_code=204)
    def delete_stream(slug: str):
        try:
            get_vault().delete_stream(slug)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
        # No mark_stale() -- see create_stream's comment above.
        _activity.info("action=delete_stream slug=%s", slug)

    @router.post("/{slug}/run", response_model=StreamRunResult)
    def run_stream(slug: str, force: bool = Query(False)):
        return run_stream_and_notify(get_vault(), get_zotero(), slug, broadcast_fn, force=force)

    return router
