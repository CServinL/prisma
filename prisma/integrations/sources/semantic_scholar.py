"""Semantic Scholar discovery source -- Academic Graph API.

Rate limit is genuinely ambiguous in Semantic Scholar's own published docs
(some pages say 5000 req/5min shared across all unauthenticated users,
others say 1000 req/s shared) -- default to a conservative 1 req/s either
way. An API key doesn't raise that per-second number, it just moves you off
the shared anonymous pool onto a guaranteed-not-throttled-by-others one, so
`requests_per_second` doesn't change with a key here, only the `x-api-key`
header gets added.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import PaperMetadata
from ...storage.models.api_response_models import SemanticScholarPaper
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_PROBE_URL = f"{_BASE_URL}/paper/search?query=test&limit=1"


class SemanticScholarSource(Source):
    name = "semanticscholar"

    def __init__(self, requests_per_second: float = 1.0, api_key: Optional[str] = None):
        self._limiter = RateLimiter(requests_per_second=requests_per_second)
        self._headers = {"x-api-key": api_key} if api_key else {}

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            r = requests.get(_PROBE_URL, headers=self._headers, timeout=timeout)
            return r.status_code < 500
        except Exception as exc:
            logger.warning("semanticscholar probe failed: %s", exc)
            return False

    def search(
        self, query: str, limit: int, published_after: Optional[datetime] = None
    ) -> SourceSearchResult:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("semanticscholar: rate limit exhausted, skipping this search")
            return SourceSearchResult()
        try:
            url = f"{_BASE_URL}/paper/search"
            params: dict = {
                "query": query,
                "limit": min(limit, 100),
                "fields": "paperId,title,abstract,authors,venue,year,doi,url",
            }
            if published_after is not None:
                # Semantic Scholar only has year-level granularity
                params["year"] = f"{published_after.year}-"

            response = requests.get(url, params=params, headers=self._headers, timeout=30)
            response.raise_for_status()
            raw_items = response.json().get("data", [])

            papers = []
            for raw_item in raw_items:
                # One malformed item shouldn't drop the whole response --
                # validated per-item, same resilience the old raw-dict
                # parsing had, but now with real field validation instead of
                # bare .get() calls.
                try:
                    validated = SemanticScholarPaper.model_validate(raw_item)
                    paper = _to_paper_metadata(validated)
                except Exception as exc:
                    logger.debug("Semantic Scholar item failed to parse, skipping: %s", exc)
                    continue
                if paper:
                    papers.append(paper)
            return SourceSearchResult(papers=papers)
        except Exception as exc:
            logger.error("Semantic Scholar search failed: %s", exc)
            return SourceSearchResult()


def _to_paper_metadata(paper: SemanticScholarPaper) -> Optional[PaperMetadata]:
    title = paper.title.strip()
    if not title:
        return None

    authors = [a.name for a in paper.authors if a.name]
    venue = paper.venue or ""
    paper_url = paper.url or f"https://www.semanticscholar.org/paper/{paper.paperId}"
    published_date = f"{paper.year}-01-01" if paper.year else None

    return PaperMetadata(
        title=title,
        authors=authors,
        abstract=paper.abstract or "",
        source="semanticscholar",
        url=paper_url,
        pdf_url=None,  # Semantic Scholar doesn't provide direct PDF URLs
        published_date=published_date,
        doi=paper.doi,
        journal=venue,
        volume=None,
        issue=None,
        pages=None,
        arxiv_id=None,
        connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(title)}",
    )
