import logging
import time
from datetime import datetime, timedelta
from typing import Callable

from prisma.services.dedup import build_index, find_duplicate
from prisma.services.vault import VaultService
from prisma.services.zotero import ZoteroMode, ZoteroService
from prisma.storage.models.vault_models import StreamRunResult
from prisma.utils.text import significant_words


def run_stream(
    slug: str,
    vault: VaultService,
    zotero: ZoteroService,
    *,
    force: bool = False,
    get_stream_logger: Callable[[str], logging.Logger] | None = None,
) -> StreamRunResult:
    from prisma.agents.analysis_agent import AnalysisAgent
    from prisma.agents.search_agent import SearchAgent

    _analysis_instance = None

    def _get_analysis():
        nonlocal _analysis_instance
        if _analysis_instance is None:
            _analysis_instance = AnalysisAgent()
        return _analysis_instance
    from prisma.utils.config import ConfigLoader

    _log = logging.getLogger("prisma.stream_runner")

    if get_stream_logger is not None:
        _slog = get_stream_logger(slug)
    else:
        _slog = logging.getLogger(f"prisma.streams.{slug}")

    _run_t0 = time.monotonic()
    _log.info("stream run start: slug=%r force=%s", slug, force)
    _slog.info("--- run start --- force=%s", force)

    stream = vault.get_stream(slug)

    _query_stems = significant_words(stream.query)
    _STEM_PREFILTER = 2

    def _stem_relevant(title: str) -> bool:
        return len(_query_stems & significant_words(title)) >= _STEM_PREFILTER

    _slog.info("query=%r next_update=%s", stream.query, stream.next_update)

    if not force and stream.next_update and stream.next_update > datetime.now():
        _slog.info("not due, skipping (use force=True to override)")
        return StreamRunResult(
            slug=slug,
            papers_found=0,
            papers_saved=0,
            sources_used=[],
            sources_skipped=[],
            errors=["not due — use force=True to override"],
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
    result = agent.search(stream.query, sources=available, limit=cfg.default_limit)
    _slog.info("internet search returned %d papers", len(result.papers))

    papers_saved = 0
    papers_skipped_llm = 0
    errors: list[str] = []

    collection_key = stream.collection_key
    if zotero.mode != ZoteroMode.offline:
        _slog.info("ensuring Zotero collection exists")
        try:
            collection = zotero.ensure_collection(stream.title)
            collection_key = collection.key
            _slog.info("collection key=%r", collection_key)
            if collection_key != stream.collection_key:
                vault.save_stream(slug, collection_key=collection_key)
        except Exception as exc:
            _slog.error("zotero collection error: %s", exc)
            errors.append(f"zotero collection: {exc}")
    else:
        _slog.warning("Zotero offline — papers will not be saved")
        errors.append("Zotero not configured for writes (offline mode) — papers found but not saved")

    collection_items: list = []
    collection_item_keys: set[str] = set()
    if collection_key and zotero.mode != ZoteroMode.offline:
        _slog.info("loading existing collection items for dedup")
        try:
            collection_items = zotero.list_items(collection_key=collection_key)
            collection_item_keys = {item.key for item in collection_items}
            _slog.info("collection has %d existing items", len(collection_items))
        except Exception as exc:
            _slog.warning("failed to load collection items: %s", exc)

    _dedup_doi, _dedup_title, _dedup_stems = build_index(collection_items)

    def _already_in_collection(paper) -> bool:
        hit = find_duplicate(
            paper, _dedup_doi, _dedup_title, _dedup_stems,
            zotero=zotero, collection_key=collection_key, log=_slog,
        )
        return hit is not None

    # Source 1: Zotero library
    library_papers_found = 0
    if collection_key and zotero.mode != ZoteroMode.offline:
        _slog.info("source=library query=%r limit=%d", stream.query, cfg.default_limit)
        try:
            library_candidates = zotero.list_items(q=stream.query, limit=cfg.default_limit)
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
            stem_filtered = [i for i in new_library_candidates if _stem_relevant(i.title)]
            stem_dropped = len(new_library_candidates) - len(stem_filtered)
            if stem_dropped:
                _slog.info("stem pre-filter dropped %d/%d library items before LLM", stem_dropped, len(new_library_candidates))
            new_library_candidates = stem_filtered
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
                    zotero.add_to_collection(
                        lib_item.key, lib_item.version, collection_key,
                        current_collection_keys=lib_item.collection_keys,
                    )
                    collection_item_keys.add(lib_item.key)
                    _dedup_title[lib_item.title.lower().strip()] = lib_item
                    if lib_item.doi:
                        _dedup_doi[lib_item.doi.lower().strip()] = lib_item
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
        if zotero.mode == ZoteroMode.offline or not collection_key:
            _slog.info("skipping — Zotero offline or no collection")
            break

        if _already_in_collection(paper):
            continue

        try:
            existing_in_library = zotero.find_by_identifier(doi=paper.doi, title=paper.title)
            if existing_in_library is not None:
                if collection_key and collection_key in (existing_in_library.collection_keys or []):
                    _slog.info("%r already in collection (item.collections) — skipping", paper.title)
                    continue
                _slog.info("%r already in library key=%r — reusing", paper.title, existing_in_library.key)
                library_item = existing_in_library
            else:
                library_item = zotero.add_item(paper)
                _slog.info("bookmarked %r → key=%r", paper.title, library_item.key)
            bookmarked.append((paper, library_item))
        except Exception as exc:
            _slog.error("bookmark failed for %r: %s", paper.title, exc)
            errors.append(f"bookmark: {exc}")

    # Phase 2b: batch relevance check (stem pre-filter first)
    if bookmarked:
        stem_filtered = [(p, li) for p, li in bookmarked if _stem_relevant(p.title)]
        stem_dropped = len(bookmarked) - len(stem_filtered)
        if stem_dropped:
            _slog.info("stem pre-filter dropped %d/%d internet papers before LLM", stem_dropped, len(bookmarked))
        bookmarked = stem_filtered
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
                zotero.add_to_collection(
                    library_item.key,
                    library_item.version,
                    collection_key,
                    current_collection_keys=library_item.collection_keys,
                )
                collection_item_keys.add(library_item.key)
                _dedup_title[paper.title.lower().strip()] = library_item
                if paper.doi:
                    _dedup_doi[paper.doi.lower().strip()] = library_item
                papers_saved += 1
                _slog.info("saved %r (total saved=%d)", paper.title, papers_saved)
            except Exception as exc:
                _slog.error("add_to_collection failed for %r: %s", paper.title, exc)
                errors.append(str(exc))

    freq_map = {"daily": 1, "weekly": 7, "monthly": 30, "manual": 0}
    days = freq_map.get(stream.refresh_frequency.value, 7)
    next_update = (datetime.now() + timedelta(days=days)) if days else None

    vault.save_stream(
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

    return StreamRunResult(
        slug=slug,
        papers_found=len(result.papers) + library_papers_found,
        papers_saved=papers_saved,
        papers_skipped_llm=papers_skipped_llm,
        sources_used=available,
        sources_skipped=skipped,
        errors=errors,
    )
