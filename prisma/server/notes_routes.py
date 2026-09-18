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

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, field_validator

from prisma.services.asset_rewrite import asset_prefix, rewrite_html
from prisma.services.renderer import render as vault_render
from prisma.services.vault import VaultService
from prisma.storage.models.kg_models import ReadSourceResponse
from prisma.storage.models.vault_models import (
    NodeType, RenderedNode, Source, SourceKind, SourceOrigin, Stream, VaultListing,
)

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


def _reject_blank_title(v: Optional[str]) -> Optional[str]:
    """min_length=1 alone counts raw characters, not stripped content -- a
    whitespace-only title (e.g. a single space) passes it despite being
    just as blank as an empty string in practice."""
    if v is not None and not v.strip():
        raise ValueError("title cannot be blank")
    return v


class SourceCreateRequest(BaseModel):
    # max_length matches the existing Query(..., max_length=512) convention
    # for short human-typed strings elsewhere (graph_routes.py/kg_app.py) --
    # without it, an absurdly long title (e.g. one 5000-char word with no
    # whitespace) flows straight into unique_slug()'s filesystem filename,
    # 500ing on OSError instead of failing request validation cleanly.
    title: str = Field(min_length=1, max_length=512)
    body: str = ""
    citekey: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # ge=0: make_citekey()/create_source_from_citekey() both now honor
    # year=0 correctly (falsy-zero fix), but a negative year is just bad
    # data, not a value worth preserving. strict=True: Pydantic's default
    # (lax) mode coerces a JSON bool to int for an int field -- ge=0 alone
    # doesn't reject `year: true`, since True satisfies >=0 once coerced
    # to 1. strict mode still accepts a normal JSON number/null fine, it
    # only blocks cross-type coercion like this one.
    year: Optional[int] = Field(None, ge=0, strict=True)
    doi: Optional[str] = None
    url: Optional[str] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    item_type: Optional[str] = None
    source_kind: SourceKind = SourceKind.paper

    _validate_title = field_validator("title")(_reject_blank_title)


class SourceEditRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=512)
    authors: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    year: Optional[int] = Field(None, ge=0)
    doi: Optional[str] = None
    source_kind: Optional[SourceKind] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    item_type: Optional[str] = None

    _validate_title = field_validator("title")(_reject_blank_title)


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
        path=str(node_path.relative_to(vault.root).as_posix()) if node_path else "",
        title=node.title,
        node_type=node.node_type,
        tags=getattr(node, "tags", []),
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
    if isinstance(node, Source):
        _echo_source_fields(rn, node)
    return rn


def _echo_source_fields(rn: RenderedNode, source: Source) -> None:
    """The one place both render_note() (GET) and _render_source() (create/
    edit/companion-upload) populate a RenderedNode's Source-only fields --
    previously duplicated verbatim in both, so a future field added to one
    and not the other would make GET and the mutating routes silently
    disagree on what they echo back."""
    rn.citekey = source.citekey
    rn.source_kind = source.source_kind
    rn.authors = source.authors
    rn.year = source.year
    rn.doi = source.doi
    rn.journal = source.journal
    rn.volume = source.volume
    rn.issue = source.issue
    rn.pages = source.pages
    rn.publisher = source.publisher
    rn.url = source.url
    rn.item_type = source.item_type


def _render_source(vault: VaultService, source: Source) -> RenderedNode:
    """Builds a full RenderedNode for a Source object already in hand --
    shared by the create/edit/companion-upload routes below, which all
    need the same Source-echo fields render_note() populates for GET.

    Deliberately simpler than render_note(): always renders `source.body`
    as markdown, with none of render_note()'s original_ext-aware companion
    branching (raw-HTML fragment/iframe fallback, get_md_body() lookup) --
    that logic needs a Request (for asset_prefix) this helper doesn't have,
    and more importantly needs to key off whatever the companion's current
    state actually is post-write, which a follow-up GET /notes/{slug}
    already does correctly. So the `html` field in this response can be
    stale/wrong for a Source whose companion is `.html`/`.pdf` with a
    still-empty or partial body -- every current caller (the UI) already
    re-fetches via GET right after create/edit/companion-upload and
    overwrites its local state with that response, not this one's `html`.
    A caller that trusted this endpoint's `html` directly without
    re-fetching would not."""
    rel = str(source.path.relative_to(vault.root).as_posix())
    html, broken_links, broken_citations = vault_render(source.body, vault)
    rn = RenderedNode(
        slug=source.slug, path=rel, title=source.title, node_type=source.node_type,
        tags=source.tags,
        html=html, broken_links=broken_links, broken_citations=broken_citations,
        original_ext=source.original_ext,
    )
    _echo_source_fields(rn, source)
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

    @router.post("/sources", response_model=RenderedNode, status_code=201)
    def create_source(req: SourceCreateRequest):
        """Manual Source creation — the non-Zotero counterpart to
        POST /zotero/import/{key}. Grouped near /apa above, not required
        for correctness (no existing /{slug}-shaped route shares this
        method+path), just for readability alongside the other
        Source-specific routes."""
        from prisma.utils.text import make_citekey
        vault = get_vault()
        citekey = (req.citekey or make_citekey(req.authors, req.year, req.title)).strip()
        if not citekey:
            # make_citekey() can legitimately return "" -- an author name
            # with no ASCII letters after re.sub(r"[^a-z]", "", ...) (e.g.
            # non-Latin script) and no year, with a title whose first word
            # is the same. Letting that through would silently store
            # citekey: "" and 409 every subsequent unrelated source with
            # the same fate on citekey_exists()'s collision check, rather
            # than surfacing the real problem: this source needs an
            # explicit citekey, auto-generation couldn't produce one.
            raise HTTPException(
                status_code=400,
                detail="could not generate a citekey from the given title/authors — provide one explicitly",
            )
        try:
            source = vault.create_source_from_citekey_if_free(
                citekey, req.title, req.body,
                origin=SourceOrigin.upload, source_kind=req.source_kind,
                authors=req.authors, tags=req.tags, year=req.year, doi=req.doi, url=req.url,
                journal=req.journal, volume=req.volume, issue=req.issue, pages=req.pages,
                publisher=req.publisher, item_type=req.item_type,
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        mark_stale_fn()
        _activity.info("action=create_source slug=%s title=%r citekey=%s", source.slug, source.title, citekey)
        rel = str(source.path.relative_to(vault.root).as_posix())
        broadcast_fn({"type": "vault_change", "action": "create", "path": rel})
        return _render_source(vault, source)

    # /{slug}/source and /{slug}/companion, not /sources/{slug} -- matching
    # the same segment order every other action route in this file already
    # uses (/{slug}/type, /{slug}/md, /{slug}/view, /{slug}/read). Using
    # /sources/{slug} instead was a real bug, not just a style choice: it
    # collided with PATCH /{slug}/type below whenever a node's slug is
    # literally "sources" (a plausible index-note name) -- PATCH
    # /notes/sources/type matched *this* route with slug="type" instead of
    # /{slug}/type with slug="sources", silently swallowing the intended
    # type-toggle. See test_set_note_type_not_shadowed_by_a_node_literally_
    # named_sources for the reproduction.
    @router.patch("/{slug}/source", response_model=RenderedNode)
    def edit_source(slug: str, req: SourceEditRequest):
        vault = get_vault()
        try:
            node = vault.get_any(slug)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"source not found: {slug!r}")
        if not isinstance(node, Source):
            raise HTTPException(status_code=400, detail=f"{slug!r} is not a source")
        try:
            source = vault.update_source_bibliographic_fields(
                slug, title=req.title, authors=req.authors, year=req.year, doi=req.doi, tags=req.tags,
                source_kind=req.source_kind,
                journal=req.journal, volume=req.volume, issue=req.issue, pages=req.pages,
                publisher=req.publisher, url=req.url, item_type=req.item_type,
            )
        except FileNotFoundError:
            # A concurrent delete between the get_any() check above and this
            # call -- an unlikely but real window, not just theoretical (see
            # the same class of race citekey_exists()/create_source_from_
            # citekey_if_free() already guard against elsewhere in this file).
            raise HTTPException(status_code=404, detail=f"source not found: {slug!r}")
        mark_stale_fn()
        rel = str(source.path.relative_to(vault.root).as_posix())
        broadcast_fn({"type": "vault_change", "action": "save", "path": rel})
        return _render_source(vault, source)

    @router.post("/{slug}/companion", response_model=RenderedNode)
    async def upload_source_companion(slug: str, file: UploadFile = File(...)):
        vault = get_vault()
        try:
            node = vault.get_any(slug)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"source not found: {slug!r}")
        if not isinstance(node, Source):
            raise HTTPException(status_code=400, detail=f"{slug!r} is not a source")
        data = await file.read()
        try:
            source = vault.attach_source_companion(slug, file.filename or "", data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError:
            # Same concurrent-delete window as edit_source above -- the
            # await file.read() makes it wider here, not narrower.
            raise HTTPException(status_code=404, detail=f"source not found: {slug!r}")
        mark_stale_fn()
        rel = str(source.path.relative_to(vault.root).as_posix())
        broadcast_fn({"type": "vault_change", "action": "save", "path": rel})
        return _render_source(vault, source)

    @router.get("/{slug}", response_model=RenderedNode)
    def get_note(slug: str, request: Request, format: str = "html"):
        return render_note(get_vault(), slug, request, format)

    @router.get("/{slug}/read", response_model=ReadSourceResponse)
    def read_note_source(
        slug: str,
        mode: str = Query("summary", pattern="^(summary|section|literal)$"),
        query: Optional[str] = Query(None, max_length=512),
    ):
        """Bounded, addressable read of one vault document's own raw text
        (no graph involvement) — the REST surface for chat's READ_SOURCE
        tool. `mode`: summary (leading excerpt), section (heading-matched
        slice), literal (matching lines + context). Every mode returns a
        bounded slice, never the whole file."""
        from prisma.services.source_reader import read_source
        try:
            return read_source(get_vault(), slug, mode=mode, query=query)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"node not found: {slug!r}")

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
        rel = str(note.path.relative_to(vault.root).as_posix())
        # "slug" alone isn't enough -- pull.rs's vault_change handler only
        # ever reads msg.path, so a broadcast without it was silently
        # ignored by every connected desktop client's sync engine.
        broadcast_fn({"type": "vault_change", "action": "create", "path": rel})
        html, broken_links, broken_citations = vault_render(note.body, vault)
        return RenderedNode(slug=note.slug, path=rel,
                            title=note.title, node_type=note.node_type,
                            html=html, broken_links=broken_links, broken_citations=broken_citations)

    @router.put("/{slug}", response_model=RenderedNode)
    def save_note(slug: str, req: NoteSaveRequest):
        vault = get_vault()
        try:
            note = vault.save_note(slug, req.body)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"note not found: {slug!r}")
        mark_stale_fn()
        rel = str(note.path.relative_to(vault.root).as_posix())
        broadcast_fn({"type": "vault_change", "action": "save", "path": rel})
        html, broken_links, broken_citations = vault_render(note.body, vault)
        return RenderedNode(slug=note.slug, path=rel,
                            title=note.title, node_type=note.node_type,
                            html=html, broken_links=broken_links, broken_citations=broken_citations)

    return router
