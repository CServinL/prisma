"""Note/source CRUD endpoints (/notes/*).

Built via a factory (`build_notes_router`) taking getter/callback callables
rather than raw objects, same reasoning as sync_routes.py's
`build_sync_router`: app.py's `/reload`-style endpoints rebind its module
globals (`global _vault; _vault = VaultService(...)`, similarly for
`_indexer`) at runtime, so a router that captured them by value at
include_router() time would keep talking to a stale, replaced instance
after a reload. `broadcast` is passed in rather than imported directly
because it closes over app.py-local WebSocket connection state
(`_ws_loop`/`_ws_clients`) -- importing it here would be a circular import.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from prisma.services.asset_rewrite import asset_prefix, rewrite_html
from prisma.services.renderer import render as vault_render
from prisma.services.vault import VaultService
from prisma.storage.models.vault_models import NodeType, RenderedNode, Source, Stream, VaultListing

_activity = logging.getLogger("prisma.activity")


class GenerateMdResponse(BaseModel):
    generated: bool
    slug: str


class SetTypeRequest(BaseModel):
    node_type: NodeType


class NoteCreateRequest(BaseModel):
    title: str
    body: str = ""
    tags: Optional[list[str]] = None


class NoteSaveRequest(BaseModel):
    body: str


def render_note(vault: VaultService, slug: str, request: Request, format: str = "html") -> RenderedNode:
    """Core of GET /notes/{slug} -- also called directly by
    GET /streams/{slug}/view (app.py), which reuses this exact rendering
    logic since a Stream is itself a vault node with the same .md/.html
    shape as a note or source."""
    try:
        node = vault.get_any(slug)
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
            has_md = bool(vault.get_md_body(html_path))

        if format == "md" and html_path is not None and has_md:
            md_body = vault.get_md_body(html_path) or ""
            html, broken_links, broken_citations = vault_render(md_body, vault)
            prefix = asset_prefix(vault.root, html_path, str(request.base_url))
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
                prefix = asset_prefix(vault.root, html_path, str(request.base_url))
                html = rewrite_html(html, prefix, mode="fragment")
            broken_links, broken_citations = [], []
    else:
        html, broken_links, broken_citations = vault_render(body, vault)

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


def build_notes_router(
    get_vault: Callable[[], VaultService],
    mark_stale_fn: Callable[[], None],
    broadcast_fn: Callable[..., None],
) -> APIRouter:
    router = APIRouter(prefix="/notes", tags=["notes"])

    @router.get("", response_model=VaultListing)
    def list_notes(node_type: Optional[NodeType] = Query(None)):
        return get_vault().list_nodes(node_type)

    @router.get("/apa")
    def get_apa_citations(slugs: str = Query(..., description="Comma-separated slugs")) -> dict[str, str]:
        """ADR-020: bulk slug -> APA-citation-string lookup, for the chat
        UI's claim source links. A claim's `sources` can point to a Note
        or Chat too, not just a Source (see chat_tools.get_node_text) --
        this only ever resolves genuine Source nodes; anything else, or an
        unresolvable slug, is simply omitted from the response rather than
        erroring the whole batch over one bad slug. Registered before
        `/{slug}` below so "apa" isn't swallowed as a slug parameter."""
        from prisma.services.citation_format import format_apa
        vault = get_vault()
        result: dict[str, str] = {}
        for slug in (s.strip() for s in slugs.split(",")):
            if not slug:
                continue
            try:
                node = vault.get_any(slug)
            except FileNotFoundError:
                continue
            if isinstance(node, Source):
                result[slug] = format_apa(node)
        return result

    @router.get("/{slug}", response_model=RenderedNode)
    def get_note(slug: str, request: Request, format: str = "html"):
        return render_note(get_vault(), slug, request, format)

    @router.get("/{slug}/view")
    def view_html(slug: str, request: Request):
        from fastapi.responses import HTMLResponse
        vault = get_vault()
        path = vault.find_companion(slug)
        if path is None:
            # Standalone .html file (no .md companion)
            found = vault.find_file(slug)
            if found is not None and found.suffix == ".html":
                path = found
        if path is None:
            raise HTTPException(status_code=404, detail=f"no HTML file for {slug!r}")
        body = path.read_text(encoding="utf-8")
        prefix = asset_prefix(vault.root, path, str(request.base_url))
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

    @router.post("/{slug}/md", status_code=202, response_model=GenerateMdResponse)
    def generate_md_format(slug: str):
        """.html: the node itself may BE the .html file with no .md yet
        (a raw import, node.path points straight at it). .pdf: the node
        always has a real .md already (created via create_note()), with the
        .pdf sitting alongside as a companion -- vault.find_companion()
        resolves that case, node.path alone would only ever be the .md.
        Both end up calling the same ensure_md_format(), which branches on
        the companion's own suffix (vault.py)."""
        vault = get_vault()
        try:
            node = vault.get_any(slug)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
        node_path = getattr(node, "path", None)
        companion_path = (
            node_path if (node_path is not None and node_path.suffix == ".html")
            else vault.find_companion(slug)
        )
        if companion_path is None or companion_path.suffix not in (".html", ".pdf"):
            raise HTTPException(status_code=400, detail="node has no HTML or PDF format")
        generated = vault.ensure_md_format(companion_path)
        return {"generated": generated, "slug": slug}

    @router.patch("/{slug}/type")
    def set_note_type(slug: str, body: SetTypeRequest):
        try:
            get_vault().set_node_type(slug, body.node_type)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")
        return {"slug": slug, "node_type": body.node_type.value}

    @router.get("/{slug}/original")
    def get_original(slug: str):
        from fastapi.responses import FileResponse
        path = get_vault().find_companion(slug)
        if path is None:
            raise HTTPException(status_code=404, detail=f"no companion file for source {slug!r}")
        return FileResponse(str(path))

    @router.post("", response_model=RenderedNode, status_code=201)
    def create_note(req: NoteCreateRequest):
        vault = get_vault()
        note = vault.create_note(req.title, req.body, req.tags)
        mark_stale_fn()
        _activity.info("action=create_note slug=%s title=%r", note.slug, note.title)
        broadcast_fn({"type": "vault_change", "action": "create", "slug": note.slug})
        html, broken_links, broken_citations = vault_render(note.body, vault)
        return RenderedNode(slug=note.slug, title=note.title, node_type=note.node_type,
                            html=html, broken_links=broken_links, broken_citations=broken_citations)

    @router.put("/{slug}", response_model=RenderedNode)
    def save_note(slug: str, req: NoteSaveRequest):
        vault = get_vault()
        try:
            note = vault.save_note(slug, req.body)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"note not found: {slug!r}")
        mark_stale_fn()
        broadcast_fn({"type": "vault_change", "action": "save", "slug": slug})
        html, broken_links, broken_citations = vault_render(note.body, vault)
        return RenderedNode(slug=note.slug, title=note.title, node_type=note.node_type,
                            html=html, broken_links=broken_links, broken_citations=broken_citations)

    return router
