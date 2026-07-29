"""
Search Agent - Academic papers and books search with quality-based source management

Fetching/parsing/quota-control for each individual source lives in
prisma/integrations/sources/ (one module per source, all implementing the
Source interface in .../sources/base.py). This class only does
cross-source orchestration: picking which sources to search and in what
order, academic-content validation and confidence scoring (applied
uniformly across every source's papers, using that source's real quality
rating), deduplication, and result aggregation.
"""

import logging
from typing import Dict, List
from datetime import datetime

from ..integrations.sources import Source, build_sources
from ..utils.text import significant_words

from ..storage.models.agent_models import SearchResult, PaperMetadata, BookMetadata
from ..storage.models.source_quality import (
    get_source_quality,
    validate_academic_content, get_academic_confidence_score,
    AcademicValidationCriteria
)

logger = logging.getLogger(__name__)


class SearchAgent:
    """Search for academic papers and books across multiple quality-rated sources."""

    def __init__(self):
        self.validation_criteria = AcademicValidationCriteria()

        try:
            from ..utils.config import ConfigLoader
            cfg = ConfigLoader().get_search_config()
            self.default_sources: List[str] = list(cfg.sources)
            self.min_confidence_score: float = cfg.min_confidence_score
            self.prefer_high_quality: bool = cfg.prefer_high_quality
            self.require_academic_validation: bool = cfg.require_academic_validation
            self._sources: Dict[str, Source] = build_sources(cfg)
        except Exception:
            self.default_sources = ["semanticscholar", "arxiv"]
            self.min_confidence_score = 0.5
            self.prefer_high_quality = True
            self.require_academic_validation = True
            self._sources = build_sources()

    @property
    def available_sources(self) -> set[str]:
        """Names of every discovery source actually wired up (excludes
        'zotero', which is handled separately, not a Source). Used by
        callers that need to know which requested source names actually
        require internet access, without hardcoding a second copy of this
        list (see PrismaCoordinator.run_review's offline check)."""
        return set(self._sources.keys())

    def preflight(self, sources: List[str], timeout: float = 5.0) -> List[str]:
        """Return only sources that respond within *timeout* seconds."""
        available: List[str] = []
        for source in sources:
            src = self._sources.get(source.lower())
            if src is None:
                if source.lower() != "zotero":
                    logger.warning("preflight: unknown source %r — skipping", source)
                continue
            try:
                if src.probe(timeout=timeout):
                    available.append(source)
                else:
                    logger.warning("preflight: %s unreachable or over quota — skipping", source)
            except Exception as exc:
                logger.warning("preflight: %s probe raised (%s) — skipping", source, exc)
        return available

    def search(
        self,
        query: str,
        sources: List[str] | None = None,
        limit: int = 10,
        published_after: datetime | None = None,
    ) -> SearchResult:
        """
        Search for papers and books across specified sources with quality prioritization.

        Args:
            query: Search query string
            sources: List of sources to search ('arxiv', 'semanticscholar', etc.)
            limit: Maximum number of items to return per source
            published_after: Only return papers published after this date (stream re-runs
                             use stream.last_updated so we never re-fetch old papers)

        Returns:
            SearchResult with papers and books lists and metadata
        """
        if sources is None:
            sources = list(self.default_sources)
        if self.prefer_high_quality:
            sources = sorted(sources, key=lambda s: get_source_quality(s).value, reverse=True)
            logger.info("Searching sources by quality: %s", sources)

        all_papers = []
        all_books = []
        source_stats = {}

        for source in sources:
            source_quality = get_source_quality(source)
            print(f"[INFO] Searching {source} (Quality: {source_quality.value}⭐)")

            source_stats[source] = {
                'quality': source_quality.value,
                'papers_found': 0,
                'books_found': 0,
                'rejected': 0
            }

            papers_before = len(all_papers)
            books_before = len(all_books)

            src = self._sources.get(source.lower())
            if src is not None:
                result = src.search(query, limit, published_after=published_after)
                validated_papers, rejected = self._validate_papers(result.papers, source_quality)
                all_papers.extend(validated_papers)
                all_books.extend(result.books)
                source_stats[source]['rejected'] = rejected
            elif source.lower() == 'zotero':
                # Zotero isn't a discovery Source (integrations/sources/) --
                # it's the bookmark layer, searched separately in research
                # streams via the Zotero Web API, not here.
                print(f"[INFO] Zotero search - used for caching/deduplication")
            else:
                print(f"[WARNING] Source '{source}' not yet implemented")

            # Update statistics
            source_stats[source]['papers_found'] = len(all_papers) - papers_before
            source_stats[source]['books_found'] = len(all_books) - books_before

        # Remove duplicates and limit results
        unique_papers = self._deduplicate_papers(all_papers)
        unique_books = self._deduplicate_books(all_books)
        limited_papers = unique_papers[:limit]
        limited_books = unique_books[:limit]

        # Print quality summary
        self._print_quality_summary(source_stats, len(limited_papers), len(limited_books))

        return SearchResult(
            papers=limited_papers,
            books=limited_books,
            total_found=len(unique_papers) + len(unique_books),
            sources_searched=sources,
            query=query,
            timestamp=datetime.now()
        )

    def _validate_papers(self, papers: List[PaperMetadata], source_quality) -> tuple[List[PaperMetadata], int]:
        """Academic-content validation + confidence scoring, applied
        uniformly to every source's papers (previously only arxiv and
        semanticscholar did this inline, each with its own copy of the
        same logic, and both hardcoded SourceQuality.FIVE_STAR regardless
        of the real source -- centralizing it here fixes both: every
        paper source is validated the same way, scored against its own
        actual quality rating. Books are never validated -- this always
        was, and still is, papers-only (BookMetadata has no venue/abstract
        concept validate_academic_content checks)."""
        if not self.require_academic_validation:
            return list(papers), 0

        accepted: List[PaperMetadata] = []
        rejected = 0
        for paper in papers:
            is_valid, reasons = validate_academic_content(
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                venue=paper.journal or "",
                criteria=self.validation_criteria,
            )
            if not is_valid:
                logger.debug("%s paper rejected: %s", paper.source, "; ".join(reasons))
                rejected += 1
                continue

            confidence = get_academic_confidence_score(
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                venue=paper.journal or "",
                source_quality=source_quality,
            )
            if confidence < self.min_confidence_score:
                logger.debug("%s paper low confidence: %.2f", paper.source, confidence)
                rejected += 1
                continue

            logger.debug("%s paper accepted with confidence: %.2f", paper.source, confidence)
            accepted.append(paper)
        return accepted, rejected

    # Within-run dedup: ≥5 shared stems → same paper (no LLM; sources are different APIs for same content)
    _STEM_DEDUP_THRESHOLD = 5

    def _deduplicate_papers(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """
        Remove duplicate papers across sources in a single search run.

        Priority:
          1. arxiv_id (arxiv preprint identifier — globally unique for arxiv papers)
          2. DOI (globally unique for published papers)
          3. Exact normalized title
          4. NLTK stem overlap >= threshold (same paper, different API title)

        No LLM used here — duplicates within a single run are near-certain
        when any of these signals fire.
        """
        if not papers:
            return []

        seen_arxiv: set[str] = set()
        seen_doi: set[str] = set()
        seen_title: set[str] = set()
        seen_stems: list[frozenset[str]] = []
        unique: list[PaperMetadata] = []

        for paper in papers:
            # arxiv_id dedup
            arxiv_id = getattr(paper, "arxiv_id", None)
            if arxiv_id and arxiv_id in seen_arxiv:
                continue
            # DOI dedup
            doi = getattr(paper, "doi", None)
            if doi and doi.lower().strip() in seen_doi:
                continue
            # Exact title dedup
            title_key = paper.title.lower().strip()
            if title_key in seen_title:
                continue
            # NLTK stem overlap dedup
            stems = significant_words(paper.title)
            is_dup = any(
                len(stems & existing) >= self._STEM_DEDUP_THRESHOLD
                for existing in seen_stems
            )
            if is_dup:
                continue

            if arxiv_id:
                seen_arxiv.add(arxiv_id)
            if doi:
                seen_doi.add(doi.lower().strip())
            seen_title.add(title_key)
            seen_stems.append(stems)
            unique.append(paper)

        return unique

    def _deduplicate_books(self, books: List[BookMetadata]) -> List[BookMetadata]:
        """Remove duplicate books based on title and ISBN similarity."""
        if not books:
            return []

        unique_books = []
        seen_books = set()

        for book in books:
            # Create a unique key from title and ISBN (if available)
            title_key = book.title.lower().strip()
            isbn_key = book.isbn_13 or book.isbn_10 or ""
            book_key = f"{title_key}|{isbn_key}"

            if book_key not in seen_books:
                seen_books.add(book_key)
                unique_books.append(book)

        return unique_books

    def _print_quality_summary(self, source_stats: Dict, total_papers: int, total_books: int):
        """Print summary of search results by source quality"""
        print(f"\n📊 Search Quality Summary:")
        print(f"   Total Results: {total_papers} papers, {total_books} books")
        print(f"   Sources Used:")

        for source, stats in source_stats.items():
            if stats['papers_found'] + stats['books_found'] > 0:
                quality_stars = "⭐" * stats['quality']
                print(f"   • {source}: {quality_stars} - {stats['papers_found']}P + {stats['books_found']}B")
        print()
