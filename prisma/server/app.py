# Python 3.14 bug: importlib.metadata raises NameError inside entry_points()
# when networkx scans for backends at import time. Patch before networkx loads.
import importlib.metadata as _imeta
_ep_orig = _imeta.entry_points
def _ep_safe(**kw):
    try:
        return _ep_orig(**kw)
    except Exception:
        return []
_imeta.entry_points = _ep_safe

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from prisma.server import log_setup as _log_setup
_LOG_PATHS = _log_setup.configure()
_log = logging.getLogger("prisma.server")
_maint_log = logging.getLogger("prisma.maintenance")
_activity = logging.getLogger("prisma.activity")

def _t(label: str, _t0=[0.0]):
    now = time.monotonic()
    if _t0[0] == 0.0:
        _t0[0] = now
    _log.info("startup  %+6.2fs  %s", now - _t0[0], label)

_t("importing fastapi")
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from prisma.server.access_log import AccessLogMiddleware
from prisma.server.auth import (
    AuthMiddleware, LoginRequest, LoginResponse, classify_zone, issue_token, verify_password,
)
_t("fastapi ok")

_t("importing coordinator")
from prisma.coordinator import PrismaCoordinator
_t("coordinator ok")

_t("importing connectivity")
from prisma.connectivity import monitor as connectivity
_t("connectivity ok")

_t("importing vault")
from prisma.services.vault import VaultService
_t("vault ok")

_t("importing renderer")
from prisma.services.renderer import render as vault_render
from prisma.services.asset_rewrite import asset_prefix, rewrite_html
_t("renderer ok")

_t("importing knowledge_graph_client")
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.services import resource_lock
from prisma.storage.models.kg_models import (
    DeadLetterEntry, EntitiesForFileResponse, KGStatus,
)
from prisma.storage.models.search_models import DeepSearchCandidate, GraphSearchResult
_t("knowledge_graph_client ok")

_t("importing chroma_service")
from prisma.services.chroma_service import ChromaIndexer
from prisma.storage.models.chroma_models import ChromaStatus
_t("chroma_service ok")

_t("importing zotero")
from prisma.integrations.zotero import ZoteroClient
from prisma.integrations.zotero.client import ZoteroStatus
from prisma.storage.models.zotero_models import ZoteroCollection, ZoteroItem
_t("zotero ok")

_t("importing sync_orchestrator")
from prisma.services.sync_orchestrator import SyncDecision, diff_manifest
_t("sync_orchestrator ok")

_t("importing vault_models")
from prisma.storage.models.vault_models import (
    Chat, ChatMessage, ChatRole, NodeType, RenderedNode, StreamRunResult, ToolCallRecord,
    VaultListing, VaultTreeNode,
)
_t("vault_models ok")

_t("importing chat")
from prisma.agents.chat_agent import ChatAgent
from prisma.services.chat_llm import ChatLLM
from prisma.services.chat_prompts import load_excerpt_summary_prompt, load_system_prompt
from prisma.services.chat_tools import ChatToolbox
_t("chat ok")


# ── WebSocket connection manager ──────────────────────────────────────────────

_ws_clients: dict[WebSocket, str | None] = {}
_ws_clients_lock = threading.Lock()
_ws_loop: asyncio.AbstractEventLoop | None = None


async def _ws_broadcast(event: dict, exclude_client_id: str | None = None) -> None:
    msg = json.dumps(event)
    dead: set[WebSocket] = set()
    with _ws_clients_lock:
        clients = dict(_ws_clients)
    for ws, client_id in clients.items():
        if exclude_client_id is not None and client_id == exclude_client_id:
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    if dead:
        with _ws_clients_lock:
            for ws in dead:
                _ws_clients.pop(ws, None)


def broadcast(event: dict, exclude_client_id: str | None = None) -> None:
    """Thread-safe fire-and-forget broadcast to all connected WS clients.

    `exclude_client_id` skips the connection that identified itself with
    that same id on connect (`/ws?client_id=...`) — used by /sync/file
    writes so a client's own push doesn't echo straight back to it as an
    incoming server-side change."""
    if _ws_loop is not None and _ws_loop.is_running():
        asyncio.run_coroutine_threadsafe(_ws_broadcast(event, exclude_client_id), _ws_loop)


# ── Sync orchestration (2026-07-26 redesign) ──────────────────────────────────
# The server is the sole authority deciding push/pull/conflict for the
# desktop's local vault mirror — see prisma-desktop's sync/pull.rs and
# services/sync_orchestrator.py's own module doc comments for the full
# rationale. _client_baseline is the server-side equivalent of the
# desktop's sync_state.json: the last-known-agreed (hash, mtime) per path,
# per client_id — rebuilt from scratch each connection via a full
# request_manifest/manifest_response exchange rather than persisted, since
# a fresh full diff on every connect is cheap for a personal vault and
# means there's nothing to get out of sync across a restart.

_client_baseline: dict[str, dict[str, tuple[str, float]]] = {}
_client_baseline_lock = threading.Lock()


def _server_manifest() -> dict[str, tuple[str, float]]:
    """Every synced file's (content_hash, mtime), read fresh from the vault."""
    manifest: dict[str, tuple[str, float]] = {}
    for path, mtime, _size in _vault.list_md_manifest():
        result = _vault.read_by_path(path)
        if result is None:
            continue
        body, _mtime = result
        manifest[path] = (_content_hash(body), mtime)
    return manifest


def _server_file_entry(path: str) -> tuple[str, float] | None:
    """Single-path version of _server_manifest — used for the live
    file_changed/file_deleted notifications, where re-hashing the entire
    vault on every keystroke-adjacent edit would be wasteful."""
    try:
        result = _vault.read_by_path(path)
    except ValueError:
        return None
    if result is None:
        return None
    body, mtime = result
    return (_content_hash(body), mtime)


# ── WS sync protocol message shapes ───────────────────────────────────────────
# Previously parsed straight out of json.loads() as a raw dict with manual
# .get()/"key" in dict checks -- unlike the HTTP /sync/* routes, which model
# the exact same manifest-diff data with Pydantic. A malformed manifest_response
# entry missing "mtime" used to raise an uncaught KeyError inside the dict
# comprehension, dropping the *entire* message (caught by the broad except at
# the WS receive loop, per-entry validation below is strictly better: one bad
# entry is skipped, the rest of the manifest is still processed.

class SyncManifestFileEntry(BaseModel):
    path: str
    hash: str
    mtime: float


class FileChangedMsg(BaseModel):
    path: str
    hash: str
    mtime: float


class FileDeletedMsg(BaseModel):
    path: str


class FileSyncedMsg(BaseModel):
    path: str
    hash: str = ""
    mtime: float = 0.0


async def _dispatch_sync_decisions(ws: WebSocket, client_id: str, decisions: dict[str, "SyncDecision"]) -> None:
    for path, decision in decisions.items():
        if decision == SyncDecision.ASK_CLIENT_TO_PUSH:
            await ws.send_text(json.dumps({"type": "request_file", "path": path}))
        elif decision == SyncDecision.PUSH_TO_CLIENT:
            await ws.send_text(json.dumps({"type": "vault_change", "action": "sync_write", "path": path}))
        elif decision == SyncDecision.TELL_CLIENT_TO_DELETE:
            await ws.send_text(json.dumps({"type": "vault_change", "action": "sync_delete", "path": path}))
            with _client_baseline_lock:
                _client_baseline.setdefault(client_id, {}).pop(path, None)
        elif decision == SyncDecision.DELETE_ON_SERVER:
            try:
                _vault.delete_by_path(path)
            except ValueError:
                continue
            _indexer.mark_stale(path)
            broadcast({"type": "vault_change", "action": "sync_delete", "path": path}, exclude_client_id=client_id)
            with _client_baseline_lock:
                _client_baseline.setdefault(client_id, {}).pop(path, None)


async def _handle_sync_message(ws: WebSocket, client_id: str, msg: dict) -> None:
    kind = msg.get("type")
    with _client_baseline_lock:
        baseline = dict(_client_baseline.get(client_id, {}))

    if kind == "manifest_response":
        # Validated per-entry, not as one list model: a single malformed
        # entry should be skipped, not drop the entire manifest (which is
        # what used to happen -- a missing "mtime" raised an uncaught
        # KeyError inside the old dict comprehension, caught by the WS
        # loop's broad except, discarding every other file's decision too).
        client_files: dict[str, tuple[str, float]] = {}
        for raw_entry in msg.get("files", []):
            try:
                entry = SyncManifestFileEntry.model_validate(raw_entry)
            except ValidationError:
                continue
            client_files[entry.path] = (entry.hash, entry.mtime)
        server_files = _server_manifest()
        decisions = diff_manifest(server_files, client_files, baseline)
        await _dispatch_sync_decisions(ws, client_id, decisions)
        # Confirm the baseline for everything that's already in sync (not
        # flagged above) — self-heals cases the ack-based updates below
        # can't see directly, e.g. a client-side conflict resolution that
        # overwrote its own copy to match the server without any PUT.
        with _client_baseline_lock:
            bl = _client_baseline.setdefault(client_id, {})
            for path, entry in client_files.items():
                if path not in decisions and server_files.get(path) == entry:
                    bl[path] = entry

    elif kind in ("file_changed", "file_deleted"):
        try:
            if kind == "file_deleted":
                path = FileDeletedMsg.model_validate(msg).path
                client_entry = None
            else:
                changed = FileChangedMsg.model_validate(msg)
                path, client_entry = changed.path, (changed.hash, changed.mtime)
        except ValidationError:
            _log.warning("malformed %s message from client_id=%s", kind, client_id)
            return
        server_entry = _server_file_entry(path)
        decisions = diff_manifest(
            {path: server_entry} if server_entry else {},
            {path: client_entry} if client_entry else {},
            {path: baseline[path]} if path in baseline else {},
        )
        if path in decisions:
            await _dispatch_sync_decisions(ws, client_id, decisions)
        else:
            with _client_baseline_lock:
                bl = _client_baseline.setdefault(client_id, {})
                if client_entry:
                    bl[path] = client_entry
                else:
                    bl.pop(path, None)
            await ws.send_text(json.dumps({"type": "ack", "path": path}))

    elif kind == "file_synced":
        try:
            synced = FileSyncedMsg.model_validate(msg)
        except ValidationError:
            _log.warning("malformed file_synced message from client_id=%s", client_id)
            return
        with _client_baseline_lock:
            _client_baseline.setdefault(client_id, {})[synced.path] = (synced.hash, synced.mtime)


# ── Vault root / config helpers ───────────────────────────────────────────────

def _resolve_vault_root() -> Path:
    from prisma.utils.config import ConfigLoader
    try:
        return ConfigLoader().get_vault_root()
    except Exception:
        return Path.home() / "prisma-vault"


def _build_zotero() -> ZoteroClient:
    from prisma.utils.config import ConfigLoader
    try:
        return ZoteroClient.from_config(ConfigLoader().config)
    except Exception:
        # Fall back to an unconfigured client rather than crashing startup --
        # is_available()/status() degrade gracefully on missing/bad credentials,
        # no separate "offline mode" construction path needed.
        from prisma.integrations.zotero.client import ZoteroAPIConfig
        return ZoteroClient(ZoteroAPIConfig(api_key="", library_id="", library_type="user"))


def _kg_port() -> int:
    """Knowledge graph worker's port — set by the supervisor when it spawns
    the api process, so this client talks to the same kg instance even if
    --kg-port was customized. ollama_model/index_extensions config resolution
    now lives in kg_app.py itself (that process owns extraction), not here."""
    try:
        return int(os.environ.get("PRISMA_KG_PORT", "8768"))
    except ValueError:
        return 8768


def _build_chroma(vault: "VaultService") -> ChromaIndexer:
    from prisma.utils.config import ConfigLoader
    try:
        rcfg = ConfigLoader().get_retrieval_config()
        return ChromaIndexer(vault, embedding_model=rcfg.embedding_model,
                              ollama_base_url=rcfg.ollama_base_url, provider=rcfg.provider,
                              chroma_port=rcfg.chroma_port)
    except Exception:
        return ChromaIndexer(vault)


def _chat_blocked_reason(chroma: ChromaIndexer, kg: KnowledgeGraphClient) -> str | None:
    """Why the shared local-ollama pool might be denying chat's model right
    now — model_affinity makes "busy with a different model" look identical
    to "unreachable" from ChatLLM's own point of view, so this checks the
    two other Ollama callers directly to give a real answer instead of a
    generic failure message."""
    try:
        if kg.status().state == "indexing":
            return "the knowledge graph is currently indexing your vault"
    except Exception:
        pass
    try:
        if chroma.status().current_activity:
            return "the semantic search index is currently updating"
    except Exception:
        pass
    return None


def _build_chat_agent(vault: "VaultService", chroma: ChromaIndexer, kg: KnowledgeGraphClient) -> ChatAgent:
    from prisma.utils.config import ConfigLoader
    cfg = ConfigLoader()
    llm = ChatLLM(cfg.get_chat_config(), ollama_host=cfg.get_llm_config().host)
    toolbox = ChatToolbox(chroma, kg, vault)
    return ChatAgent(
        llm, toolbox, system_prompt=load_system_prompt(),
        blocked_reason=lambda: _chat_blocked_reason(chroma, kg),
    )


from prisma.utils.text import content_hash as _content_hash
from prisma.utils.text import significant_words as _significant_words


_t("building vault")
_vault = VaultService(vault_root=_resolve_vault_root())
_t(f"vault root: {_vault.root}")
_t("building indexer")
_indexer = KnowledgeGraphClient(port=_kg_port())
_t("building chroma")
_chroma = _build_chroma(_vault)
_t("building chat agent")
_chat_agent = _build_chat_agent(_vault, _chroma, _indexer)
_t("building zotero")
_zotero = _build_zotero()
_t("module-level init done")

from prisma.utils.config import ConfigLoader as _ConfigLoader

_active_config = _ConfigLoader().config
"""Snapshot of the config sections that were actually applied to the
running singletons below (_vault/_zotero/_chroma/_chat_agent) — the
baseline `POST /reload`'s smart diff compares a fresh disk-read against.
Kept in sync by every reload path (targeted or smart), not just the smart
one, so a mix of `/reload/zotero` then `/reload` still diffs correctly."""


class _StreamScheduler:
    """Background thread that runs streams when their next_update is past."""

    _CHECK_INTERVAL = 5 * 60  # seconds between scans

    def __init__(self) -> None:
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
        try:
            streams = _vault.list_streams()
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
                result = _run_stream(stream.slug, force=False)
                elapsed_ms = (time.monotonic() - t0) * 1000
                _maint_log.info(
                    "stream-scheduler: %r done — found=%d saved=%d elapsed_ms=%.0f",
                    stream.slug, result.papers_found, result.papers_saved, elapsed_ms,
                )
            except Exception as exc:
                _maint_log.warning("stream-scheduler: %r failed: %s", stream.slug, exc)


_scheduler = _StreamScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_loop
    _ws_loop = asyncio.get_event_loop()
    _log.info("startup  lifespan: starting indexer + chroma")
    _indexer.start()
    _chroma.start()
    _scheduler.start()
    _log.info("startup  lifespan: indexer + chroma + stream scheduler started — server ready")
    yield
    _scheduler.stop()
    _chroma.stop()
    _indexer.stop()


app = FastAPI(title="Prisma", version="0.1.0", lifespan=lifespan)

# Registered before CORSMiddleware so it ends up as the *innermost* layer —
# Starlette applies middlewares in reverse-of-registration order, so CORS
# (added next) wraps this and answers browser preflight (OPTIONS, no
# Authorization header) before it ever reaches auth gating. Getting this
# order backwards silently breaks all browser/PWA access once
# server.auth.mode is "password" (see ADR-011).
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost"],
    # Any port on localhost/127.0.0.1 — covers the API's own port, the Web
    # process's port (ADR-012), and whichever hostname variant the browser
    # resolved (CORS origin matching is exact-string, so both "localhost"
    # and "127.0.0.1" must be covered, not just one).
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AccessLogMiddleware)

# Getter callables, not the objects themselves — /reload-style endpoints
# below rebind the _vault/_indexer module globals at runtime (`global
# _vault; _vault = VaultService(...)`), and a router that captured them by
# value at include_router() time would keep talking to a stale, replaced
# instance after a reload.
from prisma.server.sync_routes import build_sync_router  # noqa: E402
def _update_client_baseline(client_id: str, path: str, content_hash: str, mtime: float) -> None:
    with _client_baseline_lock:
        _client_baseline.setdefault(client_id, {})[path] = (content_hash, mtime)


def _clear_client_baseline(client_id: str, path: str) -> None:
    with _client_baseline_lock:
        _client_baseline.setdefault(client_id, {}).pop(path, None)


app.include_router(build_sync_router(
    get_vault=lambda: _vault,
    broadcast_fn=broadcast,
    mark_stale_fn=lambda path: _indexer.mark_stale(path),
    update_baseline_fn=_update_client_baseline,
    clear_baseline_fn=_clear_client_baseline,
))

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, object] = {}  # review jobs: dict (JobStatus-shaped); dedup jobs: DedupJobState instance


# ── Request / response models ─────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    topic: str
    sources: Optional[list[str]] = None
    limit: Optional[int] = None
    zotero_only: bool = False


class RenderRequest(BaseModel):
    markdown: str


class RenderResponse(BaseModel):
    html: str


class ChatRequest(BaseModel):
    message: str
    chat_slug: str  # create via POST /chats first — /chat only ever sends a message


class ChatResponse(BaseModel):
    chat_slug: str
    reply: str
    tool_calls: list[ToolCallRecord]


class CreateChatRequest(BaseModel):
    title: Optional[str] = None  # None auto-generates a timestamp title


class SetTurnPinnedRequest(BaseModel):
    pinned: bool


class JobStatus(BaseModel):
    job_id: str
    status: str            # pending | running | done | error
    papers_analyzed: int = 0
    authors_found: int = 0
    output_file: str = ""
    content_html: str = ""
    errors: list[str] = Field(default_factory=list)


# ── Background worker ─────────────────────────────────────────────────────────

def _run_review(job_id: str, req: ReviewRequest) -> None:
    _jobs[job_id]["status"] = "running"
    try:
        from prisma.utils.config import ConfigLoader
        cfg = ConfigLoader()
        search_cfg = cfg.get_search_config()
        output_cfg = cfg.get_output_config()

        topic_safe = req.topic.replace(" ", "_").replace("/", "_")
        review_config = {
            "topic": req.topic,
            "sources": req.sources or search_cfg.sources,
            "limit": req.limit or search_cfg.default_limit,
            "output_file": f"{output_cfg.directory}/literature_review_{topic_safe}.md",
            "stream_name": None,
            "include_authors": False,
            "zotero_collections": None,
            "zotero_recent_years": None,
        }

        result = PrismaCoordinator().run_review(review_config)

        content_html = ""
        if result.success and result.output_file:
            try:
                html, _, _ = vault_render(Path(result.output_file).read_text(encoding="utf-8"), _vault)
                content_html = html
            except Exception:
                pass

        _jobs[job_id].update(
            status="done" if result.success else "error",
            papers_analyzed=result.papers_analyzed,
            authors_found=result.authors_found,
            output_file=result.output_file,
            content_html=content_html,
            errors=result.errors,
        )
    except Exception as exc:
        _jobs[job_id].update(status="error", errors=[str(exc)])


# ── Reload helpers ────────────────────────────────────────────────────────────
# Each helper rebuilds its subsystem's global AND updates the matching slice
# of _active_config, so the smart POST /reload's diff (below) stays accurate
# regardless of whether a targeted /reload/* route or the smart one ran last.

def _reload_vault(new_config: "PrismaConfig | None" = None) -> None:
    global _vault, _active_config
    _vault = VaultService(vault_root=_resolve_vault_root())
    if new_config is not None:
        _active_config = _active_config.model_copy(update={"vault_root": new_config.vault_root})


def _reload_zotero(new_config: "PrismaConfig | None" = None) -> None:
    global _zotero, _active_config
    _zotero = _build_zotero()
    if new_config is not None:
        new_sources = _active_config.sources.model_copy(update={"zotero": new_config.sources.zotero})
        _active_config = _active_config.model_copy(update={"sources": new_sources})


def _reload_chroma(new_config: "PrismaConfig | None" = None) -> None:
    global _chroma, _active_config
    _chroma.stop()
    _chroma = _build_chroma(_vault)
    _chroma.start()
    if new_config is not None:
        _active_config = _active_config.model_copy(update={"retrieval": new_config.retrieval})


def _reload_chat(new_config: "PrismaConfig | None" = None) -> None:
    global _chat_agent, _active_config
    _chat_agent = _build_chat_agent(_vault, _chroma, _indexer)
    if new_config is not None:
        new_llm = _active_config.llm.model_copy(update={"host": new_config.llm.host})
        _active_config = _active_config.model_copy(update={"chat": new_config.chat, "llm": new_llm})


# ── Routes ────────────────────────────────────────────────────────────────────

class ReloadVaultResponse(BaseModel):
    status: str
    vault_root: str


class ReloadZoteroResponse(BaseModel):
    status: str
    mode: str
    available: bool
    reachable: bool


class ReloadedResponse(BaseModel):
    status: str


@app.post("/reload/vault", response_model=ReloadVaultResponse)
def reload_vault():
    _reload_vault()
    return {"status": "reloaded", "vault_root": str(_vault.root)}


@app.post("/reload/zotero", response_model=ReloadZoteroResponse)
def reload_zotero():
    _reload_zotero()
    zs = _zotero.status()
    return {"status": "reloaded", "mode": zs.mode, "available": zs.available, "reachable": zs.reachable}


@app.post("/reload/indexer", response_model=ReloadedResponse)
def reload_indexer():
    global _indexer
    _indexer.stop()
    _indexer = KnowledgeGraphClient(port=_kg_port())
    _indexer.start()
    return {"status": "reloaded"}


@app.post("/reload/chroma", response_model=ReloadedResponse)
def reload_chroma():
    _reload_chroma()
    return {"status": "reloaded"}


@app.post("/reload/chat", response_model=ReloadedResponse)
def reload_chat():
    """Rebuilds _chat_agent from the current config — closes the one gap
    found when auditing which config sections actually need an explicit
    reload path: chat.* / llm.host are cached in _chat_agent at startup
    with no prior way to pick up a change short of a full process restart."""
    _reload_chat()
    return {"status": "reloaded"}


@app.post("/supervisor/restart/{name}")
def restart_worker(name: str):
    """Proxies to the supervisor's own POST /supervisor/restart/{name} —
    lets the UI restart a single worker process (api/web/chroma/kg) without
    needing direct access to the supervisor's loopback-only control port,
    same pattern as resource_lock.status()/process_status() already use for
    read-only supervisor data on /status."""
    return resource_lock.restart_worker(
        "127.0.0.1", resource_lock.default_port(), name,
    )


class ReloadConfigResponse(BaseModel):
    changed: list[str]
    reloaded: list[str]
    compute_pools_reloaded: bool


_RELOAD_FNS = {
    "vault_root": _reload_vault,
    "sources.zotero": _reload_zotero,
    "retrieval": _reload_chroma,
    "chat": _reload_chat,
}


@app.post("/reload", response_model=ReloadConfigResponse)
def reload_server():
    """Smart config reload (backs `prisma reload-config`): diffs the
    currently-active config against a fresh read from disk, rebuilds only
    the subsystems whose section actually changed (see
    prisma.services.config_reload for which sections those are and why),
    and always proxies to the supervisor's own idempotent
    /supervisor/resources/reload for compute_pools. Unlike the old
    unconditional "rebuild everything" behavior, a config file that fails
    to parse/validate is rejected outright rather than silently falling
    back to defaults — ConfigLoader's own fallback-to-defaults behavior is
    correct for startup but would be a dangerous silent full reset here."""
    global _active_config
    from prisma.utils.config import ConfigLoader
    from prisma.services.config_reload import diff_config_sections

    try:
        new_config = ConfigLoader().config
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid config: {exc}")

    changed = diff_config_sections(_active_config, new_config)
    reloaded: list[str] = []
    for section in changed:
        _RELOAD_FNS[section](new_config)
        reloaded.append(section)

    result = resource_lock.reload_resources("127.0.0.1", resource_lock.default_port())
    compute_pools_reloaded = "error" not in result

    return ReloadConfigResponse(
        changed=changed, reloaded=reloaded, compute_pools_reloaded=compute_pools_reloaded,
    )


class HealthResponse(BaseModel):
    status: str
    online: bool


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "online": connectivity.is_online}


@app.post("/auth/login", response_model=LoginResponse)
def auth_login(req: LoginRequest, request: Request):
    """Exempt from AuthMiddleware's own zone gating (chicken-and-egg — you
    need to reach this before you have a token), so the wan/mode checks are
    repeated here directly rather than relying on the middleware."""
    from datetime import datetime, timezone

    from prisma.utils.config import ConfigLoader
    server_cfg = ConfigLoader().get_server_config()
    auth_cfg = server_cfg.auth
    if auth_cfg.mode != "password":
        raise HTTPException(status_code=404, detail="password auth is not enabled")

    client_host = request.client.host if request.client else "127.0.0.1"
    forwarded_for = request.headers.get("x-forwarded-for")
    zone = classify_zone(client_host, forwarded_for, server_cfg.trusted_proxies)
    if zone == "wan":
        raise HTTPException(status_code=403, detail="wan access is not permitted")

    if not verify_password(req.password, auth_cfg.password_hash):
        raise HTTPException(status_code=401, detail="invalid password")

    token, expires_at = issue_token(auth_cfg.password_hash, auth_cfg.session_ttl_hours)
    return LoginResponse(
        token=token,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, client_id: str | None = Query(None)):
    # Echo the "bearer" subprotocol back when the client offered one (see
    # AuthMiddleware/_bearer_from_ws) — strict browser WebSocket clients
    # reject a handshake response that doesn't confirm one of the
    # subprotocols they offered. `client_id` (desktop sends a persisted
    # UUID) lets broadcast() skip echoing a sync push back to its own
    # sender — see _ws_broadcast/exclude_client_id — and is what makes
    # this connection a sync-orchestration participant at all (see
    # _handle_sync_message): a browser/PWA tab connects with no client_id
    # and just receives ordinary vault_change broadcasts as before.
    if "bearer" in ws.scope.get("subprotocols", []):
        await ws.accept(subprotocol="bearer")
    else:
        await ws.accept()
    with _ws_clients_lock:
        _ws_clients[ws] = client_id

    if client_id:
        # Kick off a full sync as soon as this client connects — see
        # sync_orchestrator's module doc comment for why the server (not
        # the client) now always initiates this.
        try:
            await ws.send_text(json.dumps({"type": "request_manifest"}))
        except Exception:
            pass

    try:
        while True:
            text = await ws.receive_text()
            if not client_id:
                continue  # not a sync participant — nothing to parse/act on
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            try:
                await _handle_sync_message(ws, client_id, msg)
            except Exception:
                _log.exception("error handling sync message from client_id=%s: %r", client_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_clients_lock:
            _ws_clients.pop(ws, None)


class ConfigStatus(BaseModel):
    ok: bool
    error: Optional[str] = None


class VaultStats(BaseModel):
    root: str
    notes: int
    sources: int
    chats: int
    streams: int


class OllamaStatus(BaseModel):
    reachable: bool


class ChatConfigStatus(BaseModel):
    provider: str
    model: str
    pool: str


class SystemStatusResponse(BaseModel):
    online: bool
    config: ConfigStatus
    pending_jobs: int
    knowledge_graph: KGStatus
    chroma: ChromaStatus
    vault: VaultStats
    zotero: Optional[ZoteroStatus] = None
    ollama: OllamaStatus
    # resources/processes are proxied verbatim from the supervisor's own
    # stdlib-only control API (see resource_lock.py's module docstring and
    # ADR-012's finding #6 -- supervisor.py deliberately can't import
    # pydantic, so there's no schema on the producing side to validate
    # against here either) -- left as raw dicts, not a gap.
    resources: dict
    processes: dict
    chat_config: ChatConfigStatus


@app.get("/status", response_model=SystemStatusResponse)
def status():
    from prisma.utils.config import ConfigLoader
    try:
        ConfigLoader()
        config_ok = True
        config_error = None
    except Exception as exc:
        config_ok = False
        config_error = str(exc)

    try:
        listing = _vault.list_nodes()
        vault_stats = VaultStats(
            root=str(_vault.root),
            notes=len(listing.notes),
            sources=len(listing.sources),
            chats=len(listing.chats),
            streams=len(listing.streams),
        )
    except Exception:
        vault_stats = VaultStats(root=str(_vault.root), notes=0, sources=0, chats=0, streams=0)

    zotero_info = None
    try:
        zotero_info = _zotero.status()
    except Exception:
        pass

    return {
        "online": connectivity.is_online,
        "config": {"ok": config_ok, "error": config_error},
        "pending_jobs": sum(
            1 for j in _jobs.values()
            if (j["status"] if isinstance(j, dict) else j.status) in ("pending", "running")
        ),
        "knowledge_graph": _indexer.status(),
        "chroma": _chroma.status(),
        "vault": vault_stats,
        "zotero": zotero_info,
        "ollama": {"reachable": _indexer._ollama_ready()},
        "resources": resource_lock.status("127.0.0.1", resource_lock.default_port()),
        "processes": resource_lock.process_status("127.0.0.1", resource_lock.default_port()),
        # The chat.model/pool actually configured right now — the UI shows
        # this instead of a chat's own stored frontmatter model, which is
        # only a snapshot from whenever that chat last saved a turn (see
        # vault.py's save_chat docstring) and can otherwise go stale across
        # a model rename/merge.
        "chat_config": {"provider": _chat_agent.provider, "model": _chat_agent.model, "pool": _chat_agent.pool},
    }


class LogsResponse(BaseModel):
    path: str
    lines: list[str]
    total: int


@app.get("/logs", response_model=LogsResponse)
def get_logs(
    concern: str = Query("server", description="server|access|maintenance|ollama|activity|chroma|kg|supervisor|stream"),
    slug: Optional[str] = Query(None, description="stream slug (required when concern=stream)"),
    n: int = Query(200, ge=1, le=5000),
):
    lp = _LOG_PATHS
    path_map = {
        "server": lp.server,
        "access": lp.access,
        "maintenance": lp.maintenance,
        "ollama": lp.ollama,
        "activity": lp.activity,
        "chroma": lp.chroma,
        "kg": lp.kg,
        "supervisor": lp.supervisor,
    }
    if concern == "stream":
        if not slug:
            raise HTTPException(status_code=400, detail="slug required when concern=stream")
        log_path = lp.streams_dir / f"{slug}.log"
    else:
        log_path = path_map.get(concern)
        if log_path is None:
            raise HTTPException(status_code=400, detail=f"unknown concern: {concern!r}")
    try:
        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"path": str(log_path), "lines": all_lines[-n:], "total": len(all_lines)}
    except FileNotFoundError:
        return {"path": str(log_path), "lines": [], "total": 0}


# ── KG admin/instrumentation ──────────────────────────────────────────────
# Namespaced under /admin/kg/ rather than /knowledge-graph/ so these read
# unambiguously as ops/diagnostic tools, not user-facing features — the UI
# never calls any of these (confirmed: it only ever reads status()'s
# knowledge_graph fields), they're for direct/curl admin use.

class AdminStatusResponse(BaseModel):
    status: str


class AdminRemovedResponse(BaseModel):
    removed: int


@app.post("/admin/kg/taint", response_model=AdminStatusResponse)
def admin_kg_taint():
    """Mark the index stale so the next cycle re-indexes changed files."""
    _indexer.mark_stale()
    return {"status": "stale"}


@app.post("/admin/kg/drop", response_model=AdminStatusResponse)
def admin_kg_drop():
    """Drop the entire Kùzu graph and tracked manifest, forcing a full reindex from scratch."""
    _indexer.drop_index()
    return {"status": "dropped"}


@app.get("/admin/kg/dead-letters", response_model=list[DeadLetterEntry])
def admin_kg_list_dead_letters():
    """List failed-extraction ("dead letter") records without discarding
    them — see what failed and why before deciding to clear it."""
    return _indexer.list_dead_letters()


@app.delete("/admin/kg/dead-letters", response_model=AdminRemovedResponse)
def admin_kg_clear_dead_letters():
    """Discard recorded dead-letter records so the next incremental cycle
    retries them fresh. Returns the number cleared."""
    removed = _indexer.clear_dead_letters()
    return {"removed": removed}


@app.get("/admin/kg/entities", response_model=EntitiesForFileResponse)
def admin_kg_entities(path: str = Query(...)):
    """Raw entities and relationship edges the knowledge graph extracted
    from one specific vault-relative file path — for inspecting extraction
    quality directly (unlike /search or /search/deep, which only ever
    return file-level scores, never the underlying nodes)."""
    return _indexer.entities_for_file(path)


@app.get("/admin/kg/search", response_model=list[GraphSearchResult])
def admin_kg_search(q: str = Query(..., min_length=1), top_k: int = Query(20)):
    """Raw graph query — keyword match over Entity nodes only, bypassing
    Ollama reasoning and ChromaDB entirely (unlike /search/deep). Isolates
    the KG layer for diagnosis: a bad /search/deep result could be
    extraction, ranking, or the LLM's fault — this narrows it down."""
    return _indexer.search(q, top_k=top_k)


@app.post("/render", response_model=RenderResponse)
def render_markdown(req: RenderRequest):
    html, _, _ = vault_render(req.markdown, _vault)
    return RenderResponse(html=html)


@app.post("/chats", response_model=Chat, status_code=201)
def create_chat(req: CreateChatRequest):
    from datetime import datetime
    title = req.title or f"Chat — {datetime.now():%Y-%m-%d %H:%M}"
    chat_node = _vault.create_chat(title=title, model=_chat_agent.model)
    _activity.info("action=create_chat slug=%s", chat_node.slug)
    return _with_context_usage(chat_node)


_excerpt_regenerating_lock = threading.Lock()
_excerpt_regenerating: dict[str, bool] = {}
# Monotonic per-slug counter so a slower, stale regeneration thread can tell
# it's been superseded by a newer pin/unpin before it overwrites the Excerpt
# with outdated content, and so the *older* thread never clears
# excerpt_regenerating out from under a still-running newer one (which would
# make the UI stop polling before the real latest result is ready).
_excerpt_generation: dict[str, int] = {}


def _excerpt_summary_html(note_body: str) -> str | None:
    """Splits the Excerpt note's raw markdown on the "## Pinned turns"
    marker _render_excerpt_body always emits, and renders only the Summary
    portion. None if there's no "## Summary" heading at all (verbatim
    mode — see ADR-015 — produces no Summary). The UI shows this on its
    own; the raw pinned turns are a separate clickable list built from
    pinned_turns + messages directly, not from re-rendering this note's
    own "Pinned turns" section."""
    before, _, _ = note_body.partition("\n## Pinned turns")
    before = before.strip()
    if not before.startswith("## Summary"):
        return None
    summary_md = before[len("## Summary"):].strip()
    html, _, _ = vault_render(summary_md, _vault)
    return html


def _with_context_usage(chat_node: Chat) -> Chat:
    """Attaches response-only fields (ADR-015) — not persisted, computed
    fresh on every response since they depend on the live-configured
    ChatAgent / in-memory regeneration state, not stored chat data."""
    excerpt_notes = []
    if chat_node.excerpt_slug:
        try:
            note = _vault.get_note(chat_node.excerpt_slug)
            excerpt_notes.append(note)
            chat_node.excerpt_summary_html = _excerpt_summary_html(note.body)
        except FileNotFoundError:
            pass
    used, maximum = _chat_agent.context_usage(chat_node.messages, excerpt_notes=excerpt_notes)
    chat_node.context_tokens_used = used
    chat_node.context_tokens_max = maximum
    with _excerpt_regenerating_lock:
        chat_node.excerpt_regenerating = _excerpt_regenerating.get(chat_node.slug, False)
    return chat_node


@app.get("/chats/{slug}", response_model=Chat)
def get_chat(slug: str):
    try:
        return _with_context_usage(_vault.get_chat(slug))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat not found: {slug!r}")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        chat_node = _vault.get_chat(req.chat_slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat not found: {req.chat_slug!r}")
    history = chat_node.messages
    # The chat's single Excerpt (ADR-015) is durable context — always
    # included, independent of the (bounded, rolling) raw history, so the
    # model doesn't re-litigate what's already been settled.
    excerpt_notes = []
    if chat_node.excerpt_slug:
        try:
            excerpt_notes.append(_vault.get_note(chat_node.excerpt_slug))
        except FileNotFoundError:
            _log.warning("chat %r: excerpt note %r no longer exists", chat_node.slug, chat_node.excerpt_slug)
    user_msg = ChatMessage(role=ChatRole.user, content=req.message)
    assistant_msg = _chat_agent.respond(history, req.message, excerpt_notes=excerpt_notes)
    # append_messages (not save_chat with the pre-call `history` snapshot)
    # re-reads the chat's *current* messages atomically right before
    # writing — closes the race where a DELETE /chats/{slug}/messages/{index}
    # landing while respond() was still running would otherwise get
    # silently reverted by this write.
    _vault.append_messages(chat_node.slug, [user_msg, assistant_msg], model=_chat_agent.model)
    _activity.info("action=chat slug=%s tool_calls=%d", chat_node.slug, len(assistant_msg.tool_calls))
    return ChatResponse(
        chat_slug=chat_node.slug, reply=assistant_msg.content, tool_calls=assistant_msg.tool_calls,
    )


def _regenerate_excerpt_now(slug: str, pinned_indices: list[int], generation: int) -> None:
    """ADR-015: regenerates the chat's single Excerpt note from whatever's
    currently pinned, in whichever mode currently applies
    (ChatAgent.excerpt_mode(), budget-driven) — compressed (LLM-condensed
    Summary via ChatAgent.summarize() + load_excerpt_summary_prompt()) or
    verbatim (no LLM call, no Summary section, pinned turns kept exactly as
    written). Synchronous — call via _regenerate_excerpt_async unless
    already off the request thread.

    `generation` is checked immediately before the actual write: if a newer
    pin/unpin has since been dispatched for this chat, this call's result is
    stale (it was likely computed from an older pinned set, possibly after a
    slow summarize() call) and is discarded rather than overwriting the
    newer request's — eventual — result."""
    chat_node = _vault.get_chat(slug)
    pinned_turns = [chat_node.messages[i] for i in pinned_indices]
    summary: str | None
    if not pinned_turns:
        summary = "(nothing pinned yet)"
    else:
        turns_text = "\n\n".join(f"{m.role.value}: {m.content}" for m in pinned_turns)
        if _chat_agent.excerpt_mode(turns_text) == "verbatim":
            summary = None
        else:
            summary = _chat_agent.summarize(load_excerpt_summary_prompt(), turns_text)
            if summary is None:
                summary = "(summary unavailable — the language model couldn't be reached; raw pinned turns below are still current)"
    with _excerpt_regenerating_lock:
        if _excerpt_generation.get(slug) != generation:
            return  # superseded by a newer pin/unpin — don't overwrite with stale content
        _vault.save_excerpt(slug, summary, pinned_turns)


def _regenerate_excerpt_async(slug: str, pinned_indices: list[int]) -> None:
    """Kicks off _regenerate_excerpt_now on a background thread so
    pin/unpin/delete return immediately — a slow or GPU-contended
    summarize() call (kg extraction competing for the same local model is
    a real, observed cause) must never leave the user staring at a blocked
    request. The UI shows the *previous* Excerpt content plus a visible
    "regenerating" indicator (Chat.excerpt_regenerating, see
    _with_context_usage) until this clears, then refetches."""
    with _excerpt_regenerating_lock:
        generation = _excerpt_generation.get(slug, 0) + 1
        _excerpt_generation[slug] = generation
        _excerpt_regenerating[slug] = True

    def _run() -> None:
        try:
            _regenerate_excerpt_now(slug, pinned_indices, generation)
        except Exception as exc:
            _log.warning("excerpt regeneration failed for chat %r: %s", slug, exc)
        finally:
            with _excerpt_regenerating_lock:
                # Only clear the flag if no newer request has superseded
                # this one — otherwise an older, slower thread finishing
                # after a newer one started would incorrectly tell the UI
                # "done" while the real latest regeneration is still running.
                if _excerpt_generation.get(slug) == generation:
                    _excerpt_regenerating[slug] = False

    threading.Thread(target=_run, daemon=True, name=f"excerpt-regen-{slug}").start()


@app.post("/chats/{slug}/turns/{index}/pin", response_model=Chat)
def set_turn_pinned(slug: str, index: int, req: SetTurnPinnedRequest):
    """Pin/unpin one turn — always a deliberate user action per turn, never
    automatic. Returns immediately with pinned_turns already updated;
    Excerpt regeneration happens in the background (see
    _regenerate_excerpt_async) — the response's excerpt_regenerating flag
    tells the UI to keep showing the previous Excerpt content until it
    clears."""
    try:
        chat_node = _vault.get_chat(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat not found: {slug!r}")
    if index < 0 or index >= len(chat_node.messages):
        raise HTTPException(status_code=400, detail=f"invalid turn index: {index}")

    pinned = set(chat_node.pinned_turns)
    if req.pinned:
        pinned.add(index)
    else:
        pinned.discard(index)
    pinned_indices = sorted(pinned)
    updated = _vault.set_pinned_turns(slug, pinned_indices)
    _regenerate_excerpt_async(slug, pinned_indices)
    _activity.info("action=set_turn_pinned chat_slug=%s index=%d pinned=%s", slug, index, req.pinned)
    return _with_context_usage(updated)


@app.delete("/chats/{slug}/messages/{index}", response_model=Chat)
def delete_chat_message(slug: str, index: int):
    """Manual curation of a chat's history — a research conversation is a
    persistent artifact, not ephemeral, so pruning is a deliberate user
    action rather than automatic summarization (which risks silently
    dropping a real discovery)."""
    try:
        chat_node = _vault.get_chat(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"chat not found: {slug!r}")
    if index < 0 or index >= len(chat_node.messages):
        raise HTTPException(status_code=400, detail=f"message index out of range: {index}")
    messages = chat_node.messages[:index] + chat_node.messages[index + 1:]
    updated = _vault.save_chat(slug, messages)
    # Deleting a turn shifts every later index — pinned_turns must be
    # re-indexed (dropping the deleted turn if it was itself pinned) or the
    # Excerpt would silently start pointing at the wrong turns.
    new_pinned = sorted(i if i < index else i - 1 for i in chat_node.pinned_turns if i != index)
    if new_pinned != chat_node.pinned_turns:
        updated = _vault.set_pinned_turns(slug, new_pinned)
        _regenerate_excerpt_async(slug, new_pinned)
    _activity.info("action=delete_chat_message slug=%s index=%d", slug, index)
    return _with_context_usage(updated)


# ── Vault routes ──────────────────────────────────────────────────────────────

@app.get("/home", response_model=RenderedNode)
def home():
    _vault.ensure_dirs()
    home_path = _vault.default_dirs[NodeType.note] / "home.md"
    if home_path.exists():
        note = _vault.get_note("home")
        html, broken_links, broken_citations = vault_render(note.body, _vault)
    else:
        listing = _vault.list_nodes()
        n_sources = len(listing.sources)
        n_notes = len(listing.notes)
        n_chats = len(listing.chats)
        recent = sorted(
            listing.sources[:3] + listing.notes[:3],
            key=lambda x: x.modified_at,
            reverse=True,
        )[:5]
        recent_lines = "\n".join(f"- [[{n.slug}]] — {n.title}" for n in recent)
        dashboard_md = f"""# Welcome to Prisma

Your research workspace.

| | |
|---|---|
| Sources | {n_sources} |
| Notes | {n_notes} |
| Chats | {n_chats} |

## Recent

{recent_lines or "_Nothing yet — create a note or run a stream._"}
"""
        html, broken_links, broken_citations = vault_render(dashboard_md, _vault)
    return RenderedNode(slug="home", title="Home", node_type=NodeType.note,
                        html=html, broken_links=[], broken_citations=[])


@app.get("/tree", response_model=list[VaultTreeNode])
def get_tree():
    return _vault.get_tree()


class MoveRequest(BaseModel):
    dest_dir: str

class RenameRequest(BaseModel):
    title: str

class CreateDirRequest(BaseModel):
    path: str

class SlugResponse(BaseModel):
    slug: str


class TaintNodeResponse(BaseModel):
    chroma_tainted: bool
    kg_tainted: bool


@app.post("/nodes/{slug}/move", response_model=SlugResponse)
def move_node(slug: str, req: MoveRequest):
    try:
        new_slug = _vault.move_node(slug, req.dest_dir)
        _indexer.mark_stale()
        return {"slug": new_slug}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (FileExistsError, ValueError) as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/nodes/{slug}/rename", response_model=SlugResponse)
def rename_node(slug: str, req: RenameRequest):
    try:
        new_slug = _vault.rename_node(slug, req.title)
        _indexer.mark_stale()
        return {"slug": new_slug}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (FileExistsError, ValueError) as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/nodes/{slug}/taint", response_model=TaintNodeResponse)
def taint_node(slug: str):
    """Force one specific node to be re-extracted/re-embedded on the next
    cycle — without touching the rest of the index/graph. Unlike
    /admin/kg/taint (which just marks the whole index stale), this
    targets a single file via both ChromaIndexer.taint_file and
    KnowledgeGraphService.taint_file (see their docstrings — both work by
    dropping the file's manifest entry and enqueuing it directly)."""
    path = _vault._find_file(slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
    rel = str(path.relative_to(_vault.root))
    chroma_tainted = _chroma.taint_file(rel)
    kg_tainted = _indexer.taint_file(rel)
    return {"chroma_tainted": chroma_tainted, "kg_tainted": kg_tainted}

class OkResponse(BaseModel):
    ok: bool


@app.delete("/nodes/{slug}", response_model=OkResponse)
def delete_node(slug: str):
    try:
        _vault.delete_node(slug)
        _indexer.mark_stale()
        _activity.info("action=delete_node slug=%s", slug)
        broadcast({"type": "vault_change", "action": "delete", "slug": slug})
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/dirs", response_model=OkResponse)
def create_dir(req: CreateDirRequest):
    try:
        _vault.create_dir(req.path)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/notes", response_model=VaultListing)
def list_notes(node_type: Optional[NodeType] = Query(None)):
    return _vault.list_nodes(node_type)


@app.get("/notes/{slug}", response_model=RenderedNode)
def get_note(slug: str, request: Request, format: str = "html"):
    from prisma.storage.models.vault_models import Stream
    try:
        node = _vault.get_any(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
    body = node.body if hasattr(node, "body") else ""
    original_ext = getattr(node, "original_ext", None)
    node_path = getattr(node, "path", None)
    has_md = False

    if original_ext == ".html":
        html_path = node_path if (node_path and node_path.suffix == ".html") else None
        if html_path is None and node_path is not None:
            companion = node_path.with_suffix(".html")
            if companion.exists():
                html_path = companion

        if html_path is not None:
            has_md = bool(_vault.get_md_body(html_path))

        if format == "md" and html_path is not None and has_md:
            md_body = _vault.get_md_body(html_path) or ""
            html, broken_links, broken_citations = vault_render(md_body, _vault)
            prefix = asset_prefix(_vault.root, html_path, str(request.base_url))
            html = rewrite_html(html, prefix, mode="markdown")
            original_ext = None  # render as plain markdown, no iframe
        else:
            import re as _re
            if html_path is not None and node_path and node_path.suffix != ".html":
                body = html_path.read_text(encoding="utf-8")
            styles = "".join(_re.findall(r"<style[^>]*>.*?</style>", body, _re.DOTALL | _re.IGNORECASE))
            m = _re.search(r"<body[^>]*>(.*?)</body>", body, _re.DOTALL | _re.IGNORECASE)
            html = (styles + "\n" + m.group(1).strip()) if m else body
            if html_path is not None:
                prefix = asset_prefix(_vault.root, html_path, str(request.base_url))
                html = rewrite_html(html, prefix, mode="fragment")
            broken_links, broken_citations = [], []
    else:
        html, broken_links, broken_citations = vault_render(body, _vault)

    rn = RenderedNode(
        slug=slug,
        title=node.title,
        node_type=node.node_type,
        html=html,
        broken_links=broken_links,
        broken_citations=broken_citations,
        original_ext=original_ext,
        has_md=has_md,
    )
    if isinstance(node, Stream):
        rn.stream_status = node.status
        rn.refresh_frequency = node.refresh_frequency
        rn.total_papers = node.total_papers
        rn.last_updated = node.last_updated
        rn.next_update = node.next_update
        rn.query = node.query
        rn.collection_key = node.collection_key
    return rn


_ALLOWED_ASSET_EXTS = {
    ".css", ".js", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
}


@app.get("/vault/assets/{asset_path:path}")
def vault_asset(asset_path: str):
    from fastapi.responses import FileResponse
    try:
        candidate_path = _vault.resolve_within_root(asset_path)
    except ValueError:
        raise HTTPException(status_code=403, detail="access denied")
    if candidate_path.suffix.lower() not in _ALLOWED_ASSET_EXTS:
        raise HTTPException(status_code=403, detail="file type not allowed")
    if not candidate_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(candidate_path)


@app.get("/notes/{slug}/view")
def view_html(slug: str, request: Request):
    from fastapi.responses import HTMLResponse
    path = _vault.find_companion(slug)
    if path is None:
        # Standalone .html file (no .md companion)
        found = _vault._find_file(slug)
        if found is not None and found.suffix == ".html":
            path = found
    if path is None:
        raise HTTPException(status_code=404, detail=f"no HTML file for {slug!r}")
    body = path.read_text(encoding="utf-8")
    prefix = asset_prefix(_vault.root, path, str(request.base_url))
    body = rewrite_html(body, prefix, mode="full")
    interceptor = (
        "<script>"
        "document.addEventListener('click',function(e){"
        "var a=e.target.closest('a');if(!a)return;"
        "var h=a.getAttribute('href')||'';"
        "if(h.startsWith('http://')||h.startsWith('https://')){"
        "e.preventDefault();"
        "window.parent.postMessage({type:'open-url',url:h},'*');"
        "}"
        "});"
        "</script>"
    )
    body = body.replace("</body>", interceptor + "</body>", 1)
    if "</body>" not in body:
        body += interceptor
    return HTMLResponse(content=body)


class GenerateMdResponse(BaseModel):
    generated: bool
    slug: str


@app.post("/notes/{slug}/md", status_code=202, response_model=GenerateMdResponse)
def generate_md_format(slug: str):
    try:
        node = _vault.get_any(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
    html_path = getattr(node, "path", None)
    if html_path is None or html_path.suffix != ".html":
        raise HTTPException(status_code=400, detail="node has no HTML format")
    generated = _vault.ensure_md_format(html_path)
    return {"generated": generated, "slug": slug}


class SetTypeRequest(BaseModel):
    node_type: NodeType

@app.patch("/notes/{slug}/type")
def set_note_type(slug: str, body: SetTypeRequest):
    try:
        _vault.set_node_type(slug, body.node_type)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
    return {"slug": slug, "node_type": body.node_type.value}


@app.get("/notes/{slug}/original")
def get_original(slug: str):
    from fastapi.responses import FileResponse
    path = _vault.find_companion(slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no companion file for source {slug!r}")
    return FileResponse(str(path))


class NoteCreateRequest(BaseModel):
    title: str
    body: str = ""
    tags: Optional[list[str]] = None


@app.post("/notes", response_model=RenderedNode, status_code=201)
def create_note(req: NoteCreateRequest):
    note = _vault.create_note(req.title, req.body, req.tags)
    _indexer.mark_stale()
    _activity.info("action=create_note slug=%s title=%r", note.slug, note.title)
    broadcast({"type": "vault_change", "action": "create", "slug": note.slug})
    html, broken_links, broken_citations = vault_render(note.body, _vault)
    return RenderedNode(slug=note.slug, title=note.title, node_type=note.node_type,
                        html=html, broken_links=broken_links, broken_citations=broken_citations)


class NoteSaveRequest(BaseModel):
    body: str


@app.put("/notes/{slug}", response_model=RenderedNode)
def save_note(slug: str, req: NoteSaveRequest):
    try:
        note = _vault.save_note(slug, req.body)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"note not found: {slug!r}")
    _indexer.mark_stale()
    broadcast({"type": "vault_change", "action": "save", "slug": slug})
    html, broken_links, broken_citations = vault_render(note.body, _vault)
    return RenderedNode(slug=note.slug, title=note.title, node_type=note.node_type,
                        html=html, broken_links=broken_links, broken_citations=broken_citations)


class SearchResult(BaseModel):
    slug: str
    title: str
    excerpt: str
    score: float = 1.0


# ── In-memory search index ────────────────────────────────────────────────────
# Keyed by absolute path str → (mtime, slug, title, lower_text, first_lines)
# Rebuilt lazily: only re-reads files whose mtime changed.
_search_index: dict[str, tuple[float, str, str, str, list[str]]] = {}
_search_index_lock = threading.Lock()


def _refresh_search_index() -> None:
    with _search_index_lock:
        seen: set[str] = set()
        for path in _vault._all_md_files():
            key = str(path)
            seen.add(key)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            cached = _search_index.get(key)
            if cached and cached[0] == mtime:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            slug = path.stem
            title = slug
            try:
                node = _vault.get_any(slug)
                title = node.title
            except Exception:
                pass
            _search_index[key] = (mtime, slug, title, text.lower(), text.splitlines())
        # Drop deleted files
        for key in list(_search_index):
            if key not in seen:
                del _search_index[key]


def _text_search(q: str, top_k: int = 30) -> list[SearchResult]:
    terms = [t.lower().strip('"') for t in q.split() if t.strip('"')]
    if not terms:
        return []

    # Expand terms with stems so "learning" also matches "learned", "learns", etc.
    query_stems = _significant_words(q)

    _refresh_search_index()

    results: list[tuple[float, str, str, str]] = []
    with _search_index_lock:
        entries = list(_search_index.values())

    for _mtime, slug, title, lower, lines in entries:
        hits = sum(1 for t in terms if t in lower)
        title_lower = title.lower()
        score = hits * 1.0
        for t in terms:
            if t in title_lower:
                score += 4.0
        if hits == len(terms):
            score += 3.0

        # Stem-overlap bonus — rewards documents that share many stem roots with the query
        doc_stems = _significant_words(title + " " + lower[:500])
        stem_overlap = len(query_stems & doc_stems)
        score += stem_overlap * 0.5

        if score == 0:
            continue

        excerpt = ""
        for line in lines:
            ll = line.lower().strip()
            if ll and any(t in ll for t in terms):
                excerpt = line.strip()[:200]
                break
        results.append((score, slug, title, excerpt))

    results.sort(key=lambda x: -x[0])
    return [
        SearchResult(slug=slug, title=title, excerpt=excerpt, score=score)
        for score, slug, title, excerpt in results[:top_k]
    ]


@app.get("/search")
def search(q: str = Query(..., min_length=1)) -> list[SearchResult]:
    return _text_search(q)


class DeepSearchResult(BaseModel):
    slug: str
    title: str
    excerpt: str
    score: float
    reason: str = ""


def _resolve_source_files(items: list[DeepSearchCandidate], query_stems: frozenset | None = None) -> list[DeepSearchResult]:
    """Map DeepSearchCandidate(source_file, score, reason) to DeepSearchResult, resolving slugs."""
    vault_root = str(_vault.root)
    seen: set[str] = set()
    out: list[tuple[float, str, str, str, str]] = []
    for item in items:
        src = item.source_file
        if not src:
            continue
        slug = Path(vault_root, src).stem
        if slug in seen:
            continue
        seen.add(slug)
        try:
            node = _vault.get_any(slug)
            title = node.title
            body = node.body if hasattr(node, "body") else ""
        except Exception:
            title = slug
            body = ""
        excerpt = body[:200].replace("\n", " ").strip() if body else ""
        score = item.score
        if query_stems:
            doc_stems = _significant_words(title + " " + (body[:500] if body else ""))
            score += len(query_stems & doc_stems) * 0.05
        out.append((score, slug, title, excerpt, item.reason))
    out.sort(key=lambda x: -x[0])
    return [DeepSearchResult(slug=sl, title=ti, excerpt=ex, score=sc, reason=re)
            for sc, sl, ti, ex, re in out]


@app.get("/search/deep")
def deep_search(q: str = Query(..., min_length=1)) -> list[DeepSearchResult]:
    """Semantic search: Ollama reasons over the knowledge graph, falls back to graph scoring."""
    query_stems = _significant_words(q)
    ollama_results = _indexer.ollama_deep_search(q, top_k=15, chroma=_chroma)
    if ollama_results:
        return _resolve_source_files(ollama_results, query_stems=query_stems)

    # Fallback: graph scoring aggregated by file
    graph_nodes = _indexer.ranked_nodes(q, top_k=30)
    if graph_nodes:
        items = [DeepSearchCandidate(source_file=n.source_file, score=n.score, reason=n.label)
                 for n in graph_nodes if n.source_file]
        results = _resolve_source_files(items, query_stems=query_stems)
        # Pad with text search for coverage
        seen = {r.slug for r in results}
        for r in _text_search(q, top_k=10):
            if r.slug not in seen:
                results.append(DeepSearchResult(slug=r.slug, title=r.title,
                                                excerpt=r.excerpt, score=r.score * 0.3))
        results.sort(key=lambda x: -x.score)
        return results[:20]

    # Graph not built — text only
    return [DeepSearchResult(slug=r.slug, title=r.title, excerpt=r.excerpt, score=r.score)
            for r in _text_search(q, top_k=20)]


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


@app.get("/streams", response_model=list[StreamMeta])
def list_streams():
    return [_stream_meta(s) for s in _vault.list_streams()]


@app.get("/streams/{slug}", response_model=StreamMeta)
def get_stream(slug: str):
    try:
        return _stream_meta(_vault.get_stream(slug))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")


@app.get("/streams/{slug}/view", response_model=RenderedNode)
def get_stream_view(slug: str, request: Request, format: str = "html"):
    return get_note(slug, request, format)


class StreamCreateRequest(BaseModel):
    title: str
    query: str
    description: Optional[str] = None
    refresh_frequency: str = "weekly"
    tags: Optional[list[str]] = None


@app.post("/streams", response_model=StreamMeta, status_code=201)
def create_stream(req: StreamCreateRequest):
    s = _vault.create_stream(
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


class StreamPatchRequest(BaseModel):
    title: Optional[str] = None
    query: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    refresh_frequency: Optional[str] = None
    tags: Optional[list[str]] = None


@app.patch("/streams/{slug}", response_model=StreamMeta)
def patch_stream(slug: str, req: StreamPatchRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        s = _vault.save_stream(slug, **updates)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
    return _stream_meta(s)


@app.delete("/streams/{slug}", status_code=204)
def delete_stream(slug: str):
    try:
        _vault.delete_stream(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
    # No mark_stale() -- see create_stream's comment above.
    _activity.info("action=delete_stream slug=%s", slug)


def _run_stream(slug: str, force: bool = False) -> StreamRunResult:
    from prisma.services.stream_runner import run_stream as _runner
    try:
        _vault.get_stream(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")
    broadcast({"type": "stream_progress", "slug": slug, "status": "running"})
    result = _runner(slug, _vault, _zotero, force=force, get_stream_logger=_log_setup.get_stream_logger)
    _activity.info(
        "action=run_stream slug=%s found=%d saved=%d skipped_llm=%d errors=%d",
        slug, result.papers_found, result.papers_saved, result.papers_skipped_llm, len(result.errors),
    )
    broadcast({"type": "stream_progress", "slug": slug, "status": "done",
               "found": result.papers_found, "saved": result.papers_saved})
    return result


@app.post("/streams/{slug}/run", response_model=StreamRunResult)
def run_stream(slug: str, force: bool = Query(False)):
    return _run_stream(slug, force=force)


# ── Zotero routes ─────────────────────────────────────────────────────────────

@app.get("/zotero/status", response_model=ZoteroStatus)
def zotero_status():
    return _zotero.status()


@app.get("/zotero/collections", response_model=list[ZoteroCollection])
def zotero_collections():
    try:
        return _zotero.get_collections()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


class ZoteroStatsResponse(BaseModel):
    total_items: int
    item_type_counts: dict[str, int]
    items_without_doi: int
    items_without_abstract: int
    items_without_authors: int
    quality_score: float


@app.get("/zotero/stats", response_model=ZoteroStatsResponse)
def zotero_stats():
    """Library-wide item-type breakdown and metadata-quality score, computed
    over the same ZoteroClient.get_all_items() used elsewhere — not a
    second, independent client (the old CLI's cleanup.py had its own)."""
    try:
        items = _zotero.get_all_items()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not items:
        return ZoteroStatsResponse(
            total_items=0, item_type_counts={}, items_without_doi=0,
            items_without_abstract=0, items_without_authors=0, quality_score=100.0,
        )

    item_type_counts: dict[str, int] = {}
    items_without_doi = 0
    items_without_abstract = 0
    items_without_authors = 0
    for item in items:
        item_type_counts[item.item_type] = item_type_counts.get(item.item_type, 0) + 1
        if not item.doi:
            items_without_doi += 1
        if not item.abstract_note:
            items_without_abstract += 1
        if not item.authors:
            items_without_authors += 1

    total = len(items)
    quality_score = 100 - (
        (items_without_doi + items_without_abstract + items_without_authors) / (total * 3) * 100
    )
    return ZoteroStatsResponse(
        total_items=total,
        item_type_counts=item_type_counts,
        items_without_doi=items_without_doi,
        items_without_abstract=items_without_abstract,
        items_without_authors=items_without_authors,
        quality_score=quality_score,
    )


class SyncPendingResponse(BaseModel):
    synced: int
    failed: int
    pending_before: int


@app.post("/zotero/sync-pending", response_model=SyncPendingResponse)
def zotero_sync_pending():
    """Flush the offline pending-write queue (data/pending_writes.json) —
    the API equivalent of the old `prisma sync` CLI command. Actions are
    queued here by the review pipeline (coordinator.py) when a Zotero write
    fails while offline; nothing else populates this queue today."""
    from prisma.storage.pending_queue import PendingWriteQueue

    pending_before = PendingWriteQueue().pending_count
    if pending_before == 0:
        return SyncPendingResponse(synced=0, failed=0, pending_before=0)
    if not connectivity.is_online:
        raise HTTPException(status_code=503, detail="offline — cannot sync right now")

    synced, failed = PendingWriteQueue().flush(_zotero)
    return SyncPendingResponse(synced=synced, failed=failed, pending_before=pending_before)


@app.get("/zotero/items", response_model=list[ZoteroItem])
def zotero_items(collection: Optional[str] = Query(None), q: Optional[str] = Query(None)):
    """When both are given, get_collection_items(key, query=q) passes q
    straight through to Zotero's own server-side `q` search (matches across
    title/creators/abstract/etc., not just a client-side title substring)
    scoped to the collection in one API call."""
    try:
        if collection:
            return _zotero.get_collection_items(collection, query=q or None)
        if q:
            return _zotero.search_items(q)
        return _zotero.get_all_items()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


def _fetch_pdf_from_url(url: str | None, doi: str | None) -> bytes | None:
    import re
    import urllib.request

    candidates: list[str] = []
    if url:
        if re.search(r"arxiv\.org/abs/(\S+)", url):
            arxiv_id = re.search(r"arxiv\.org/abs/([^\s?#]+)", url).group(1)
            candidates.append(f"https://arxiv.org/pdf/{arxiv_id}")
        elif url.lower().endswith(".pdf"):
            candidates.append(url)
    if doi and "arxiv" in doi.lower():
        arxiv_id = re.sub(r".*arxiv[./]", "", doi, flags=re.IGNORECASE)
        candidates.append(f"https://arxiv.org/pdf/{arxiv_id}")

    for pdf_url in candidates:
        try:
            req = urllib.request.Request(pdf_url, headers={"User-Agent": "Prisma/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if data[:4] == b"%PDF":
                return data
        except Exception:
            continue
    return None


def _pdf_bytes_to_md(data: bytes) -> str:
    try:
        from docu_craft.renderers.pdf_md import pdf_to_md
        return pdf_to_md(data)
    except Exception:
        return ""


@app.post("/zotero/import/{key}", response_model=RenderedNode, status_code=201)
def zotero_import(key: str):
    from prisma.utils.text import make_citekey
    item = _zotero.get_item(key)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Zotero item not found: {key!r}")

    # Return existing import if already in vault
    for path in _vault._all_md_files():
        raw = path.read_text(encoding="utf-8")
        from prisma.services.vault import _parse_frontmatter
        fm, _ = _parse_frontmatter(raw)
        if fm.get("zotero_key") == key:
            from prisma.services.vault import _file_slug
            slug = _file_slug(path.stem)
            source = _vault.get_source(slug)
            html, broken_links, broken_citations = vault_render(source.body, _vault)
            return RenderedNode(
                slug=source.slug, title=source.title, node_type=source.node_type,
                html=html, broken_links=broken_links, broken_citations=broken_citations,
            )

    pdf_bytes = _zotero.get_pdf_bytes(key)
    if pdf_bytes is None:
        pdf_bytes = _fetch_pdf_from_url(item.url, item.doi)

    if pdf_bytes:
        body = _pdf_bytes_to_md(pdf_bytes)
    else:
        lines = []
        if item.abstract_note:
            lines.append(item.abstract_note)
            lines.append("")
        if item.publication_title:
            lines.append(f"**{item.publication_title}**")
        if item.authors:
            lines.append(", ".join(item.authors))
        if item.doi:
            lines.append(f"DOI: {item.doi}")
        if item.url:
            lines.append(f"URL: {item.url}")
        body = "\n".join(lines)

    citekey = make_citekey(item.authors, item.year, item.title)
    from prisma.services.vault import _slugify, _render_frontmatter
    slug = _vault._unique_slug(_slugify(citekey))
    fm: dict = {
        "type": "source",
        "title": item.title,
        "citekey": citekey,
        "zotero_key": item.key,
        "authors": item.authors,
        "tags": [t.tag for t in item.tags],
    }
    if item.year:
        fm["year"] = item.year
    if item.doi:
        fm["doi"] = item.doi
    if item.url:
        fm["url"] = item.url
    path = _vault.default_dirs[NodeType.source] / f"{slug}.md"
    _vault.ensure_dirs()
    path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
    _indexer.mark_stale()
    source = _vault.get_source(slug)
    _activity.info("action=import_zotero key=%s slug=%s title=%r", key, source.slug, source.title)
    html, broken_links, broken_citations = vault_render(source.body, _vault)
    return RenderedNode(
        slug=source.slug, title=source.title, node_type=source.node_type,
        html=html, broken_links=broken_links, broken_citations=broken_citations,
    )


class DeduplicateResult(BaseModel):
    job_id: str
    status: str


class WouldDeleteEntry(BaseModel):
    key: str
    title: str
    doi: Optional[str] = None
    keep_key: str
    keep_title: str


class DedupJobState(BaseModel):
    """One `_jobs[job_id]` entry for a /maintenance/deduplicate run --
    constructed once and updated via model_copy(update=...) so every
    write site keeps the same field set (previously 4 separate dict
    literals, 3 of which silently dropped `sensitivity` after the initial
    "running" write — a polled job never showed which sensitivity it
    actually ran with)."""
    status: str
    dry_run: bool
    max_level: int
    sensitivity: str
    duplicates_found: int = 0
    items_deleted: int = 0
    would_delete: list[WouldDeleteEntry] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _run_deduplicate(job_id: str, dry_run: bool = False, max_level: int = 3, sensitivity: str = "medium") -> None:
    from prisma.services.dedup import find_all_duplicates
    job = DedupJobState(status="running", dry_run=dry_run, max_level=max_level, sensitivity=sensitivity)
    _jobs[job_id] = job
    _log.info("deduplicate[%s]: start — zotero available=%s dry_run=%s max_level=%d sensitivity=%s", job_id, _zotero.is_available(), dry_run, max_level, sensitivity)
    try:
        items = _zotero.get_all_items()
        _log.info("deduplicate[%s]: fetched %d items", job_id, len(items))
    except Exception as exc:
        _log.error("deduplicate[%s]: failed to fetch items: %s", job_id, exc)
        _jobs[job_id] = job.model_copy(update={"status": "error", "errors": [str(exc)]})
        return

    def _keep(group: list):
        def score(i):
            return (bool(i.abstract_note), bool(i.doi), len(i.authors), i.version or 0)
        return max(group, key=score)

    _log.info("deduplicate[%s]: running find_all_duplicates", job_id)
    try:
        groups = find_all_duplicates(items, zotero=_zotero, log=_log, max_level=max_level, sensitivity=sensitivity)
    except Exception as exc:
        _log.error("deduplicate[%s]: find_all_duplicates failed: %s", job_id, exc, exc_info=True)
        _jobs[job_id] = job.model_copy(update={"status": "error", "errors": [str(exc)]})
        return

    _log.info("deduplicate[%s]: found %d duplicate group(s)", job_id, len(groups))
    duplicates_found = 0
    items_deleted = 0
    would_delete: list[WouldDeleteEntry] = []
    errors: list[str] = []

    for group in groups:
        duplicates_found += len(group) - 1
        keep = _keep(group)
        _log.info("deduplicate[%s]: group size=%d keeping key=%s title=%r", job_id, len(group), keep.key, keep.title)
        for item in group:
            if item.key == keep.key:
                continue
            entry = WouldDeleteEntry(key=item.key, title=item.title, doi=item.doi, keep_key=keep.key, keep_title=keep.title)
            if dry_run:
                would_delete.append(entry)
                _log.info("deduplicate[%s]: dry_run would delete key=%s title=%r (keep=%s)", job_id, item.key, item.title, keep.key)
            else:
                try:
                    # delete_item() catches its own exceptions and returns
                    # bool -- it never raises, so this must check the
                    # return value explicitly, not rely on `except` to
                    # catch a failure (previously counted every call as a
                    # successful deletion regardless of outcome).
                    deleted = _zotero.delete_item(item.key)
                    if deleted:
                        items_deleted += 1
                        _log.info("deduplicate[%s]: deleted key=%s title=%r", job_id, item.key, item.title)
                    else:
                        errors.append(f"{item.key}: delete_item returned False")
                        _log.warning("deduplicate[%s]: failed to delete key=%s", job_id, item.key)
                except Exception as exc:
                    errors.append(f"{item.key}: {exc}")
                    _log.warning("deduplicate[%s]: failed to delete key=%s: %s", job_id, item.key, exc)

    if not dry_run:
        _activity.info("action=deduplicate found=%d deleted=%d errors=%d", duplicates_found, items_deleted, len(errors))
    _log.info("deduplicate[%s]: done — found=%d deleted=%d would_delete=%d errors=%d", job_id, duplicates_found, items_deleted, len(would_delete), len(errors))
    _jobs[job_id] = job.model_copy(update={
        "status": "done", "duplicates_found": duplicates_found,
        "items_deleted": items_deleted, "would_delete": would_delete, "errors": errors,
    })


@app.post("/maintenance/deduplicate", response_model=DeduplicateResult, status_code=202)
def deduplicate_library(
    dry_run: bool = Query(default=False),
    max_level: int = Query(default=3, ge=1, le=5),
    sensitivity: str = Query(default=None),
):
    """
    Deduplicate the Zotero library.

    Levels (cumulative, stops at max_level):
      1 — DOI exact match
      2 — Title exact match (normalized)
      3 — Year ±1 + author last name + first initial  [default stop]
      4 — NLTK stem overlap (certain threshold) → certain match
      5 — NLTK stem overlap (ambiguous threshold) → LLM identity check

    sensitivity (levels 4-5 only): low | medium | high — defaults to analysis.nltk_dedup_sensitivity in config.
      low: certain=13 ambiguous=10 | medium: certain=10 ambiguous=7 | high: certain=7 ambiguous=5
    """
    if not _zotero.is_available():
        raise HTTPException(status_code=503, detail="Zotero not configured")
    if sensitivity is None:
        from prisma.utils.config import ConfigLoader
        sensitivity = ConfigLoader().load().analysis.nltk_dedup_sensitivity
    if sensitivity not in ("low", "medium", "high"):
        raise HTTPException(status_code=422, detail="sensitivity must be low, medium, or high")
    job_id = str(uuid.uuid4())
    _executor.submit(_run_deduplicate, job_id, dry_run, max_level, sensitivity)
    return DeduplicateResult(job_id=job_id, status="running")


class DedupJobStatusResponse(DedupJobState):
    job_id: str


@app.get("/maintenance/deduplicate/{job_id}", response_model=DedupJobStatusResponse)
def deduplicate_status(job_id: str):
    job = _jobs.get(job_id)
    # _jobs is shared with /review (job entries stored as plain dicts there) --
    # a review job_id passed to this dedup-specific endpoint isn't a dedup
    # job, so treat it the same as "not found" rather than raising on
    # job.model_dump() not existing on a dict.
    if job is None or not isinstance(job, DedupJobState):
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, **job.model_dump()}


@app.post("/review", response_model=JobStatus, status_code=202)
def start_review(req: ReviewRequest):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "papers_analyzed": 0, "authors_found": 0,
                     "output_file": "", "content_html": "", "errors": []}
    _executor.submit(_run_review, job_id, req)
    return JobStatus(job_id=job_id, status="pending")


@app.get("/review/{job_id}", response_model=JobStatus)
def get_review(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatus(job_id=job_id, **job)
