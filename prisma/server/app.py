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

import logging
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
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prisma.server.access_log import AccessLogMiddleware
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
_t("renderer ok")

_t("importing graphify_service")
from prisma.services.graphify_service import GraphifyIndexer
_t("graphify_service ok")

_t("importing zotero")
from prisma.services.zotero import ZoteroMode, ZoteroService
_t("zotero ok")

_t("importing vault_models")
from prisma.storage.models.vault_models import NodeType, RenderedNode, VaultListing, VaultTreeNode
_t("vault_models ok")


def _resolve_vault_root() -> Path:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        root = cfg.get("vault_root", "").strip()
        if root:
            return Path(root).expanduser().resolve()
    except Exception:
        pass
    return Path.home() / "prisma-vault"


def _build_zotero() -> ZoteroService:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        zconf = cfg.get("sources", {}).get("zotero", {})
        api_key = zconf.get("api_key") or None
        user_id = zconf.get("library_id") or None
        mode = ZoteroMode.web_api if api_key else ZoteroMode.offline
        return ZoteroService(mode=mode, api_key=api_key, user_id=user_id)
    except Exception:
        return ZoteroService(mode=ZoteroMode.offline)


def _ollama_model() -> str:
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        return cfg.get("llm", {}).get("model", "qwen2.5-graphify:7b")
    except Exception:
        return "qwen2.5-graphify:7b"


def _index_extensions() -> tuple[str, ...]:
    from prisma.services.graphify_service import DEFAULT_INDEX_EXTENSIONS
    try:
        import yaml
        cfg_path = Path.home() / ".config" / "prisma" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        exts = cfg.get("graphify", {}).get("index_extensions")
        if exts and isinstance(exts, list):
            return tuple(e if e.startswith(".") else f".{e}" for e in exts)
    except Exception:
        pass
    return DEFAULT_INDEX_EXTENSIONS


from prisma.utils.text import significant_words as _significant_words


_t("building vault")
_vault = VaultService(vault_root=_resolve_vault_root())
_t(f"vault root: {_vault.root}")
_t("building indexer")
_indexer = GraphifyIndexer(_vault, ollama_model=_ollama_model(),
                           index_extensions=_index_extensions())
_t("building zotero")
_zotero = _build_zotero()
_t("module-level init done")


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
    _log.info("startup  lifespan: starting indexer")
    _indexer.start()
    _scheduler.start()
    _log.info("startup  lifespan: indexer + stream scheduler started — server ready")
    yield
    _scheduler.stop()
    _indexer.stop()


app = FastAPI(title="Prisma", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost", "http://localhost:1420"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AccessLogMiddleware)

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}


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


class JobStatus(BaseModel):
    job_id: str
    status: str            # pending | running | done | error
    papers_analyzed: int = 0
    authors_found: int = 0
    output_file: str = ""
    content_html: str = ""
    errors: list[str] = []


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/reload")
def reload_server():
    global _vault, _indexer, _zotero
    _indexer.stop()
    _vault = VaultService(vault_root=_resolve_vault_root())
    _zotero = _build_zotero()
    _indexer = GraphifyIndexer(_vault, ollama_model=_ollama_model(), index_extensions=_index_extensions())
    _indexer.start()
    return {"status": "reloaded", "vault_root": str(_vault.root), "zotero_mode": _zotero.mode}


@app.get("/health")
def health():
    return {"status": "ok", "online": connectivity.is_online}


@app.get("/status")
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
        vault_stats = {
            "root": str(_vault.root),
            "notes": len(listing.notes),
            "sources": len(listing.sources),
            "chats": len(listing.chats),
            "streams": len(listing.streams),
        }
    except Exception:
        vault_stats = {"root": str(_vault.root), "notes": 0, "sources": 0, "chats": 0, "streams": 0}

    zotero_info = None
    try:
        zs = _zotero.status()
        zotero_info = {"mode": zs.get("mode"), "available": zs.get("available", False)}
    except Exception:
        pass

    return {
        "online": connectivity.is_online,
        "config": {"ok": config_ok, "error": config_error},
        "pending_jobs": sum(1 for j in _jobs.values() if j["status"] in ("pending", "running")),
        "graphify": _indexer.status(),
        "vault": vault_stats,
        "zotero": zotero_info,
    }


@app.get("/logs")
def get_logs(
    concern: str = Query("server", description="server|access|maintenance|ollama|activity|stream"),
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


@app.post("/graphify/taint")
def graphify_taint():
    """Mark the index stale so the next cycle re-indexes changed files."""
    _indexer.mark_stale()
    return {"status": "stale"}


@app.post("/graphify/drop")
def graphify_drop():
    """Drop all tracked mtimes and graph.json, forcing a full reindex from scratch."""
    _indexer.drop_index()
    return {"status": "dropped"}


@app.post("/render", response_model=RenderResponse)
def render_markdown(req: RenderRequest):
    html, _, _ = vault_render(req.markdown, _vault)
    return RenderResponse(html=html)


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

@app.post("/nodes/{slug}/move")
def move_node(slug: str, req: MoveRequest):
    try:
        new_slug = _vault.move_node(slug, req.dest_dir)
        _indexer.mark_stale()
        return {"slug": new_slug}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (FileExistsError, ValueError) as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/nodes/{slug}/rename")
def rename_node(slug: str, req: RenameRequest):
    try:
        new_slug = _vault.rename_node(slug, req.title)
        _indexer.mark_stale()
        return {"slug": new_slug}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (FileExistsError, ValueError) as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.delete("/nodes/{slug}")
def delete_node(slug: str):
    try:
        _vault.delete_node(slug)
        _indexer.mark_stale()
        _activity.info("action=delete_node slug=%s", slug)
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/dirs")
def create_dir(req: CreateDirRequest):
    try:
        _vault.create_dir(req.path)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/notes", response_model=VaultListing)
def list_notes(node_type: Optional[str] = Query(None)):
    nt = NodeType(node_type) if node_type else None
    return _vault.list_nodes(nt)


@app.get("/notes/{slug}", response_model=RenderedNode)
def get_note(slug: str, format: str = "html"):
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
            import re as _re
            md_body = _vault.get_md_body(html_path) or ""
            html, broken_links, broken_citations = vault_render(md_body, _vault)
            try:
                html_dir = html_path.parent.relative_to(_vault.root)
                base = str(html_dir).replace("\\", "/").rstrip("/")
                prefix = f"/vault/assets/{base}/" if base else "/vault/assets/"
                _ASSET_EXT = r'\.(?:png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf|eot|css|js|map)'
                html = _re.sub(
                    rf'(?<![:\w])(src)="(?!\s*(?:https?|data|javascript):|//|#|/)([^"]+{_ASSET_EXT})"',
                    lambda mo: f'{mo.group(1)}="{prefix}{mo.group(2)}"',
                    html,
                )
            except ValueError:
                pass
            original_ext = None  # render as plain markdown, no iframe
        else:
            import re as _re
            if html_path is not None and node_path and node_path.suffix != ".html":
                body = html_path.read_text(encoding="utf-8")
            styles = "".join(_re.findall(r"<style[^>]*>.*?</style>", body, _re.DOTALL | _re.IGNORECASE))
            m = _re.search(r"<body[^>]*>(.*?)</body>", body, _re.DOTALL | _re.IGNORECASE)
            html = (styles + "\n" + m.group(1).strip()) if m else body
            if html_path is not None:
                try:
                    html_dir = html_path.parent.relative_to(_vault.root)
                    base = str(html_dir).replace("\\", "/").rstrip("/")
                    prefix = f"/vault/assets/{base}/" if base else "/vault/assets/"
                    html = _re.sub(
                        r'(?<![:\w])(src|href)="(?!\s*(?:https?|data|javascript|mailto|tel):|//|#|/)([^"]+)"',
                        lambda mo: f'{mo.group(1)}="{prefix}{mo.group(2)}"',
                        html,
                    )
                except ValueError:
                    pass
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
    return rn


_ALLOWED_ASSET_EXTS = {
    ".css", ".js", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
}


@app.get("/vault/assets/{asset_path:path}")
def vault_asset(asset_path: str):
    import os
    from fastapi.responses import FileResponse
    vault_root = str(_vault.root)
    candidate = os.path.abspath(os.path.join(vault_root, asset_path))
    if not candidate.startswith(vault_root + os.sep) and candidate != vault_root:
        raise HTTPException(status_code=403, detail="access denied")
    candidate_path = Path(candidate)
    if candidate_path.suffix.lower() not in _ALLOWED_ASSET_EXTS:
        raise HTTPException(status_code=403, detail="file type not allowed")
    if not candidate_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(candidate)


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
    try:
        html_dir = path.parent.relative_to(_vault.root)
        base = str(html_dir).replace("\\", "/").rstrip("/")
        prefix = f"{request.base_url}vault/assets/{base}/" if base else f"{request.base_url}vault/assets/"
    except ValueError:
        prefix = str(request.base_url) + "vault/assets/"
    import re as _re

    _ABS = r'(?:https?|data|javascript|mailto|tel):|//'
    _SKIP = rf'(?!\s*(?:{_ABS}|#|/))'

    def _rewrite(val: str) -> str:
        if _re.match(rf'\s*(?:{_ABS}|#|/)', val):
            return val
        return prefix + val

    # 1. WebKitGTK resolves xlink:href="data:..." as a relative URL — convert to SVG 2 href.
    body = _re.sub(r'xlink:href="(data:[^"]*)"', r'href="\1"', body)

    # 2. Standard HTML attributes: src, href, action, poster, data (object)
    body = _re.sub(
        rf'(?<![:\w])(src|href|action|poster|data)="{_SKIP}([^"]*)"',
        lambda m: f'{m.group(1)}="{_rewrite(m.group(2))}"',
        body,
    )

    # 3. srcset — comma-separated list of "url [descriptor]" entries
    def _rewrite_srcset(m: _re.Match) -> str:
        parts = []
        for entry in m.group(1).split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split()
            tokens[0] = _rewrite(tokens[0])
            parts.append(" ".join(tokens))
        return f'srcset="{", ".join(parts)}"'
    body = _re.sub(r'srcset="([^"]*)"', _rewrite_srcset, body)

    # 4. CSS url() — covers both inline styles and <style> blocks
    body = _re.sub(
        rf"""url\(\s*(['"]?){_SKIP}([^'"\)]+)\1\s*\)""",
        lambda m: f'url({m.group(1)}{_rewrite(m.group(2))}{m.group(1)})',
        body,
    )

    # 5. JSON string values that are relative file paths (e.g. in data-* attributes or inline JS)
    body = _re.sub(
        rf'"({_SKIP}[^"]+\.(?:png|jpg|jpeg|gif|webp|svg|woff2?|ttf|eot|css|js))"',
        lambda m: f'"{_rewrite(m.group(1))}"',
        body,
    )
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


@app.post("/notes/{slug}/md", status_code=202)
def generate_md_format(slug: str):
    from prisma.storage.models.vault_models import NodeType as NT
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
    node_type: str

@app.patch("/notes/{slug}/type")
def set_note_type(slug: str, body: SetTypeRequest):
    from prisma.storage.models.vault_models import NodeType as NT
    try:
        nt = NT(body.node_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid node_type {body.node_type!r}")
    try:
        _vault.set_node_type(slug, nt)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
    return {"slug": slug, "node_type": nt.value}


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
    html, broken_links, broken_citations = vault_render(note.body, _vault)
    return RenderedNode(slug=note.slug, title=note.title, node_type=note.node_type,
                        html=html, broken_links=broken_links, broken_citations=broken_citations)


class SearchResult(BaseModel):
    slug: str
    title: str
    excerpt: str
    score: float = 1.0


def _text_search(q: str, top_k: int = 30) -> list[SearchResult]:
    """Fast grep-style search over vault markdown files. All terms must appear (AND)."""
    terms = [t.lower().strip('"') for t in q.split() if t.strip('"')]
    if not terms:
        return []

    results: list[tuple[float, str, str, str]] = []  # (score, slug, title, excerpt)
    for path in _vault._all_md_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lower = text.lower()
        # Require every term to appear somewhere in the document
        if not all(t in lower for t in terms):
            continue
        slug = path.stem
        title = slug
        try:
            node = _vault.get_any(slug)
            title = node.title
        except Exception:
            pass
        title_lower = title.lower()
        score = 0.0
        for t in terms:
            if t in title_lower:
                score += 4.0
            score += 1.0
        # Find a representative excerpt: first line containing any term
        excerpt = ""
        for line in text.splitlines():
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


def _resolve_source_files(items: list[dict]) -> list[DeepSearchResult]:
    """Map [{source_file, score, reason}] to DeepSearchResult, resolving slugs."""
    vault_root = str(_vault.root)
    seen: set[str] = set()
    out: list[tuple[float, str, str, str, str]] = []
    for item in items:
        src = item.get("source_file", "")
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
        out.append((item.get("score", 0.5), slug, title, excerpt, item.get("reason", "")))
    out.sort(key=lambda x: -x[0])
    return [DeepSearchResult(slug=sl, title=ti, excerpt=ex, score=sc, reason=re)
            for sc, sl, ti, ex, re in out]


@app.get("/search/deep")
def deep_search(q: str = Query(..., min_length=1)) -> list[DeepSearchResult]:
    """Semantic search: Ollama reasons over the knowledge graph, falls back to graph scoring."""
    ollama_results = _indexer.ollama_deep_search(q, top_k=15)
    if ollama_results:
        return _resolve_source_files(ollama_results)

    # Fallback: graph scoring aggregated by file
    graph_nodes = _indexer.ranked_nodes(q, top_k=30)
    if graph_nodes:
        items = [{"source_file": n["source_file"], "score": n["score"], "reason": n.get("label", "")}
                 for n in graph_nodes if n.get("source_file")]
        results = _resolve_source_files(items)
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
    tags: list[str] = []


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
    _indexer.mark_stale()
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
    _indexer.mark_stale()
    _activity.info("action=delete_stream slug=%s", slug)


class StreamRunResult(BaseModel):
    slug: str
    papers_found: int
    papers_saved: int
    papers_skipped_llm: int = 0
    sources_used: list[str]
    sources_skipped: list[str]
    errors: list[str] = []


def _run_stream(slug: str, force: bool = False) -> StreamRunResult:
    from datetime import datetime, timedelta
    from prisma.agents.search_agent import SearchAgent
    from prisma.utils.config import ConfigLoader

    _slog = _log_setup.get_stream_logger(slug)
    _run_t0 = time.monotonic()
    _log.info("stream run start: slug=%r force=%s", slug, force)
    _slog.info("--- run start --- force=%s", force)
    try:
        stream = _vault.get_stream(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"stream not found: {slug!r}")

    _slog.info("query=%r next_update=%s", stream.query, stream.next_update)

    if not force and stream.next_update and stream.next_update > datetime.now():
        _slog.info("not due, skipping (use ?force=true to override)")
        return StreamRunResult(
            slug=slug,
            papers_found=0,
            papers_saved=0,
            sources_used=[],
            sources_skipped=[],
            errors=["not due — use ?force=true to override"],
        )

    cfg = ConfigLoader().get_search_config()
    agent = SearchAgent()
    requested = list(cfg.sources)
    _slog.info("preflight check for sources: %s", requested)
    available = agent.preflight(requested)
    skipped = [s for s in requested if s not in available]
    _slog.info("sources available=%s skipped=%s", available, skipped)

    if not available:
        _slog.warning("all sources failed preflight — aborting")
        return StreamRunResult(
            slug=slug,
            papers_found=0,
            papers_saved=0,
            sources_used=[],
            sources_skipped=skipped,
            errors=["all sources failed preflight"],
        )

    _slog.info("searching internet sources (limit=%s)", cfg.default_limit)
    result = agent.search(
        stream.query,
        sources=available,
        limit=cfg.default_limit,
    )
    _slog.info("internet search returned %d papers", len(result.papers))
    papers_saved = 0
    papers_skipped_llm = 0
    errors: list[str] = []

    # Ensure the stream's ZoteroCollection exists
    collection_key = stream.collection_key
    if _zotero.mode != ZoteroMode.offline:
        _slog.info("ensuring Zotero collection exists")
        try:
            collection = _zotero.ensure_collection(stream.title)
            collection_key = collection.key
            _slog.info("collection key=%r", collection_key)
            if collection_key != stream.collection_key:
                _vault.save_stream(slug, collection_key=collection_key)
        except Exception as exc:
            _slog.error("zotero collection error: %s", exc)
            errors.append(f"zotero collection: {exc}")
    else:
        _slog.warning("Zotero offline — papers will not be saved")
        errors.append("Zotero not configured for writes (offline mode) — papers found but not saved")

    # Load collection state once — indexes for fast O(1) dedup before any LLM call
    collection_items: list = []
    collection_item_keys: set[str] = set()
    collection_by_doi: dict[str, object] = {}
    collection_by_title: dict[str, object] = {}
    if collection_key and _zotero.mode != ZoteroMode.offline:
        _slog.info("loading existing collection items for dedup")
        try:
            for item in _zotero.list_items(collection_key=collection_key):
                collection_items.append(item)
                collection_item_keys.add(item.key)
                if item.doi:
                    collection_by_doi[item.doi.lower().strip()] = item
                collection_by_title[item.title.lower().strip()] = item
            _slog.info("collection has %d existing items", len(collection_items))
        except Exception as exc:
            _slog.warning("failed to load collection items: %s", exc)

    _analysis: object = None

    def _get_analysis():
        nonlocal _analysis
        if _analysis is None:
            from prisma.agents.analysis_agent import AnalysisAgent
            _analysis = AnalysisAgent()
        return _analysis

    _item_stems: list[tuple[frozenset[str], object]] = [
        (_significant_words(item.title), item)
        for item in collection_items
    ]

    _STEM_CERTAIN   = 5
    _STEM_AMBIGUOUS = 2

    def _already_in_collection(paper) -> bool:
        if paper.doi and paper.doi.lower().strip() in collection_by_doi:
            _slog.info("dedup DOI: %r already in collection", paper.title)
            return True
        if paper.title.lower().strip() in collection_by_title:
            _slog.info("dedup title: %r already in collection", paper.title)
            return True
        try:
            hit = _zotero.find_by_identifier(
                doi=paper.doi,
                title=paper.title,
                collection_key=collection_key,
            )
            if hit is not None:
                _slog.info("dedup zotero-search: %r matched %r", paper.title, hit.title)
                return True
        except Exception as exc:
            _slog.warning("dedup zotero-search failed: %s — continuing to NLTK", exc)

        incoming_stems = _significant_words(paper.title)
        certain_match = False
        llm_candidates: list[tuple[str, str, object]] = []
        for item_stems, item in _item_stems:
            overlap = len(incoming_stems & item_stems)
            if overlap >= _STEM_CERTAIN:
                _slog.info("dedup stem-certain: %r matched %r (overlap=%d)", paper.title, item.title, overlap)
                certain_match = True
                break
            if overlap >= _STEM_AMBIGUOUS:
                llm_candidates.append((item.title, item.abstract or "", item))

        if certain_match:
            return True
        if not llm_candidates:
            _slog.info("dedup: %r is new (no stem overlap ≥%d)", paper.title, _STEM_AMBIGUOUS)
            return False

        _slog.info("dedup LLM: checking %r against %d ambiguous candidate(s)", paper.title, len(llm_candidates))
        try:
            results = _get_analysis().check_identity_batch(
                paper.title,
                paper.abstract or "",
                [(t, a) for t, a, _ in llm_candidates],
            )
            for identity_result, (_, _, item) in zip(results, llm_candidates):
                if identity_result.are_same:
                    _slog.info("dedup LLM: %r matched %r (confidence=%.2f)", paper.title, item.title, identity_result.confidence)
                    return True
        except Exception as exc:
            _slog.warning("dedup LLM failed: %s — treating as new paper", exc)
        return False

    # Source 1: Zotero library
    library_papers_found = 0
    if collection_key and _zotero.mode != ZoteroMode.offline:
        _slog.info("source=library query=%r limit=%d", stream.query, cfg.default_limit)
        try:
            library_candidates = _zotero.list_items(q=stream.query, limit=cfg.default_limit)
            library_papers_found = len(library_candidates)
            _slog.info("library search returned %d candidates", library_papers_found)
        except Exception as exc:
            _slog.error("library search failed: %s", exc)
            errors.append(f"zotero library search: {exc}")
            library_candidates = []

        new_library_candidates = [
            item for item in library_candidates
            if item.key not in collection_item_keys
        ]
        _slog.info(
            "%d library candidates after collection filter (%d already in collection)",
            len(new_library_candidates), len(library_candidates) - len(new_library_candidates),
        )

        if new_library_candidates:
            _slog.info("batch relevance check for %d library items", len(new_library_candidates))
            relevance_flags = _get_analysis().batch_relevance_check(
                stream.query,
                [(item.key, item.title, item.abstract) for item in new_library_candidates],
            )
            for lib_item, is_relevant in zip(new_library_candidates, relevance_flags):
                _slog.info("library %r → relevant=%s", lib_item.title, is_relevant)
                if not is_relevant:
                    papers_skipped_llm += 1
                    continue
                try:
                    _zotero.add_to_collection(
                        lib_item.key, lib_item.version, collection_key,
                        current_collection_keys=lib_item.collection_keys,
                    )
                    collection_item_keys.add(lib_item.key)
                    collection_by_title[lib_item.title.lower().strip()] = lib_item
                    if lib_item.doi:
                        collection_by_doi[lib_item.doi.lower().strip()] = lib_item
                    papers_saved += 1
                    _slog.info("saved library item key=%r (total saved=%d)", lib_item.key, papers_saved)
                except Exception as exc:
                    _slog.error("add_to_collection failed for key=%r: %s", lib_item.key, exc)
                    errors.append(str(exc))

    # Source 2: Internet — Phase 2a: dedup + bookmark
    _slog.info("source=internet papers=%d", len(result.papers))
    bookmarked: list[tuple[object, object]] = []
    for paper in result.papers:
        _slog.info("internet paper %r doi=%s", paper.title, paper.doi or "none")
        if _zotero.mode == ZoteroMode.offline or not collection_key:
            _slog.info("skipping — Zotero offline or no collection")
            break

        if _already_in_collection(paper):
            continue

        try:
            existing_in_library = _zotero.find_by_identifier(doi=paper.doi, title=paper.title)
            if existing_in_library is not None:
                if collection_key and collection_key in (existing_in_library.collection_keys or []):
                    _slog.info("%r already in collection (item.collections) — skipping", paper.title)
                    continue
                _slog.info("%r already in library key=%r — reusing", paper.title, existing_in_library.key)
                library_item = existing_in_library
            else:
                library_item = _zotero.add_item(paper)
                _slog.info("bookmarked %r → key=%r", paper.title, library_item.key)
            bookmarked.append((paper, library_item))
        except Exception as exc:
            _slog.error("bookmark failed for %r: %s", paper.title, exc)
            errors.append(f"bookmark: {exc}")

    # Phase 2b: batch relevance check
    if bookmarked:
        _slog.info("batch relevance check for %d internet papers", len(bookmarked))
        relevance_flags = _get_analysis().batch_relevance_check(
            stream.query,
            [(lib.key, paper.title, paper.abstract) for paper, lib in bookmarked],
        )
        for (paper, library_item), is_relevant in zip(bookmarked, relevance_flags):
            _slog.info("internet %r → relevant=%s", paper.title, is_relevant)
            if not is_relevant:
                papers_skipped_llm += 1
                continue
            try:
                _zotero.add_to_collection(
                    library_item.key,
                    library_item.version,
                    collection_key,
                    current_collection_keys=library_item.collection_keys,
                )
                collection_item_keys.add(library_item.key)
                collection_by_title[paper.title.lower().strip()] = library_item
                if paper.doi:
                    collection_by_doi[paper.doi.lower().strip()] = library_item
                papers_saved += 1
                _slog.info("saved %r (total saved=%d)", paper.title, papers_saved)
            except Exception as exc:
                _slog.error("add_to_collection failed for %r: %s", paper.title, exc)
                errors.append(str(exc))

    freq_map = {"daily": 1, "weekly": 7, "monthly": 30, "manual": 0}
    days = freq_map.get(stream.refresh_frequency.value, 7)
    next_update = (datetime.now() + timedelta(days=days)) if days else None

    _vault.save_stream(
        slug,
        last_updated=datetime.now(),
        next_update=next_update,
        total_papers=stream.total_papers + papers_saved,
    )

    elapsed_ms = (time.monotonic() - _run_t0) * 1000
    _slog.info(
        "--- run end --- found=%d saved=%d skipped_llm=%d errors=%d elapsed_ms=%.0f next_update=%s",
        len(result.papers) + library_papers_found,
        papers_saved,
        papers_skipped_llm,
        len(errors),
        elapsed_ms,
        next_update,
    )
    _activity.info(
        "action=run_stream slug=%s found=%d saved=%d skipped_llm=%d errors=%d elapsed_ms=%.0f",
        slug,
        len(result.papers) + library_papers_found,
        papers_saved,
        papers_skipped_llm,
        len(errors),
        elapsed_ms,
    )

    return StreamRunResult(
        slug=slug,
        papers_found=len(result.papers) + library_papers_found,
        papers_saved=papers_saved,
        papers_skipped_llm=papers_skipped_llm,
        sources_used=available,
        sources_skipped=skipped,
        errors=errors,
    )


@app.post("/streams/{slug}/run", response_model=StreamRunResult)
def run_stream(slug: str, force: bool = Query(False)):
    t0 = time.monotonic()
    result = _run_stream(slug, force=force)
    return result


# ── Zotero routes ─────────────────────────────────────────────────────────────

@app.get("/zotero/status")
def zotero_status():
    return _zotero.status()


@app.get("/zotero/collections")
def zotero_collections():
    try:
        return _zotero.list_collections()
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/zotero/items")
def zotero_items(collection: Optional[str] = Query(None), q: Optional[str] = Query(None)):
    try:
        return _zotero.list_items(collection_key=collection, q=q)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except FileNotFoundError as e:
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
    from prisma.services.zotero import _make_citekey
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
        if item.abstract:
            lines.append(item.abstract)
            lines.append("")
        if item.publication:
            lines.append(f"**{item.publication}**")
        if item.authors:
            lines.append(", ".join(item.authors))
        if item.doi:
            lines.append(f"DOI: {item.doi}")
        if item.url:
            lines.append(f"URL: {item.url}")
        body = "\n".join(lines)

    citekey = _make_citekey(item.authors, item.year, item.title)
    from prisma.services.vault import _slugify, _render_frontmatter
    slug = _vault._unique_slug(_slugify(citekey))
    fm: dict = {
        "type": "source",
        "title": item.title,
        "citekey": citekey,
        "zotero_key": item.key,
        "authors": item.authors,
        "tags": item.tags,
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
