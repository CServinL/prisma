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
from typing import Dict, Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import PaperMetadata
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
            data = response.json()

            papers = []
            for paper_item in data.get("data", []):
                paper = _parse_paper(paper_item)
                if paper:
                    papers.append(paper)
            return SourceSearchResult(papers=papers)
        except Exception as exc:
            logger.error("Semantic Scholar search failed: %s", exc)
            return SourceSearchResult()


def _parse_paper(paper_data: Dict) -> Optional[PaperMetadata]:
    try:
        title = paper_data.get("title", "").strip()
        if not title:
            return None

        abstract = paper_data.get("abstract", "") or ""

        authors = []
        for author in paper_data.get("authors", []):
            if isinstance(author, dict) and "name" in author:
                authors.append(author["name"])
            elif isinstance(author, str):
                authors.append(author)

        venue = paper_data.get("venue") or ""
        year = paper_data.get("year")
        doi = paper_data.get("doi")
        paper_id = paper_data.get("paperId", "")

        paper_url = paper_data.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"
        published_date = f"{year}-01-01" if year else None

        return PaperMetadata(
            title=title,
            authors=authors,
            abstract=abstract,
            source="semanticscholar",
            url=paper_url,
            pdf_url=None,  # Semantic Scholar doesn't provide direct PDF URLs
            published_date=published_date,
            doi=doi,
            journal=venue,
            volume=None,
            issue=None,
            pages=None,
            arxiv_id=None,
            connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(title)}",
        )
    except Exception as exc:
        logger.error("Failed to parse Semantic Scholar entry: %s", exc)
        return None
