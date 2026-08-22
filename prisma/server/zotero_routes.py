"""Zotero library endpoints (/zotero/*).

Built via a factory (`build_zotero_router`) taking getter callables rather
than raw objects, same reasoning as sync_routes.py's `build_sync_router`:
app.py's `/reload`-style endpoints rebind its module globals (`global
_zotero; _zotero = _build_zotero()`, similarly for `_vault`/`_indexer`) at
runtime, so a router that captured them by value at include_router() time
would keep talking to a stale, replaced instance after a reload.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from prisma.connectivity import monitor as connectivity
from prisma.integrations.zotero.client import ZoteroStatus
from prisma.integrations.zotero import ZoteroClient
from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.services.renderer import render as vault_render
from prisma.services.vault import VaultService, pdf_bytes_to_md
from prisma.storage.models.vault_models import RenderedNode
from prisma.storage.models.zotero_models import ZoteroCollection, ZoteroItem

_activity = logging.getLogger("prisma.activity")
_log = logging.getLogger("prisma.zotero_routes")


class ZoteroStatsResponse(BaseModel):
    total_items: int
    item_type_counts: dict[str, int]
    items_without_doi: int
    items_without_abstract: int
    items_without_authors: int
    quality_score: float


class SyncPendingResponse(BaseModel):
    synced: int
    failed: int
    pending_before: int


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
        except Exception as exc:
            _log.debug("pdf candidate %s failed, trying next: %s", pdf_url, exc)
            continue
    return None


def build_zotero_router(
    get_vault: Callable[[], VaultService],
    get_zotero: Callable[[], ZoteroClient],
    get_indexer: Callable[[], KnowledgeGraphClient],
) -> APIRouter:
    router = APIRouter(prefix="/zotero", tags=["zotero"])

    @router.get("/status", response_model=ZoteroStatus)
    def zotero_status():
        return get_zotero().status()

    @router.get("/collections", response_model=list[ZoteroCollection])
    def zotero_collections():
        try:
            return get_zotero().get_collections()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @router.get("/stats", response_model=ZoteroStatsResponse)
    def zotero_stats():
        """Library-wide item-type breakdown and metadata-quality score, computed
        over the same ZoteroClient.get_all_items() used elsewhere — not a
        second, independent client (the old CLI's cleanup.py had its own)."""
        try:
            items = get_zotero().get_all_items()
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

    @router.post("/sync-pending", response_model=SyncPendingResponse)
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

        synced, failed = PendingWriteQueue().flush(get_zotero())
        return SyncPendingResponse(synced=synced, failed=failed, pending_before=pending_before)

    @router.get("/items", response_model=list[ZoteroItem])
    def zotero_items(collection: Optional[str] = Query(None), q: Optional[str] = Query(None)):
        """When both are given, get_collection_items(key, query=q) passes q
        straight through to Zotero's own server-side `q` search (matches across
        title/creators/abstract/etc., not just a client-side title substring)
        scoped to the collection in one API call."""
        zotero = get_zotero()
        try:
            if collection:
                return zotero.get_collection_items(collection, query=q or None)
            if q:
                return zotero.search_items(q)
            return zotero.get_all_items()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @router.post("/import/{key}", response_model=RenderedNode, status_code=201)
    def zotero_import(key: str):
        from prisma.utils.text import make_citekey
        vault = get_vault()
        zotero = get_zotero()
        item = zotero.get_item(key)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Zotero item not found: {key!r}")

        # Return existing import if already in vault
        for path in vault.iter_files():
            raw = path.read_text(encoding="utf-8")
            from prisma.services.vault import _parse_frontmatter
            fm, _ = _parse_frontmatter(raw)
            if fm.get("zotero_key") == key:
                from prisma.services.vault import _file_slug
                slug = _file_slug(path.stem)
                source = vault.get_source(slug)
                html, broken_links, broken_citations = vault_render(source.body, vault)
                return RenderedNode(
                    slug=source.slug, path=str(source.path.relative_to(vault.root).as_posix()),
                    title=source.title, node_type=source.node_type,
                    html=html, broken_links=broken_links, broken_citations=broken_citations,
                )

        pdf_bytes = zotero.get_pdf_bytes(key)
        if pdf_bytes is None:
            pdf_bytes = _fetch_pdf_from_url(item.url, item.doi)

        if pdf_bytes:
            body = pdf_bytes_to_md(pdf_bytes)
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
        source = vault.create_source_from_citekey(
            citekey, item.title, body,
            zotero_key=item.key, authors=item.authors, tags=[t.tag for t in item.tags],
            year=item.year, doi=item.doi, url=item.url,
            journal=item.publication_title, volume=item.volume, issue=item.issue,
            pages=item.pages, item_type=item.item_type,
            publisher=item.get_field("publisher"),
        )
        get_indexer().mark_stale()
        _activity.info("action=import_zotero key=%s slug=%s title=%r", key, source.slug, source.title)
        html, broken_links, broken_citations = vault_render(source.body, vault)
        return RenderedNode(
            slug=source.slug, path=str(source.path.relative_to(vault.root).as_posix()),
            title=source.title, node_type=source.node_type,
            html=html, broken_links=broken_links, broken_citations=broken_citations,
        )

    return router
