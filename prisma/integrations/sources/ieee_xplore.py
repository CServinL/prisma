"""IEEE Xplore discovery source -- Metadata API
(https://developer.ieee.org/docs/read/IEEE_Xplore_Metadata_API_Overview).

UNVERIFIED AGAINST A REAL KEY as of 2026-07-29 -- an API key is required
even to make one request (no anonymous mode at all, unlike every other
source here), and the user doesn't have one yet. Field names below come
from IEEE's own published docs (developer.ieee.org/docs/read/
Metadata_API_responses and .../Metadata_API_details), not from a live
response, so treat the parsing as a best-effort first pass to correct
once real responses are available. The rate limit (1 req / 2s, no daily
cap) is a deliberately conservative placeholder -- IEEE does not publish
a rate limit or daily quota anywhere in their public docs; get the real
numbers from IEEE's API user guide (emailed after registration) and
update `requests_per_second`/`daily_cap` via config once you have them,
rather than trusting this default long-term.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import PaperMetadata
from ...storage.models.api_response_models import IEEEXploreArticle
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


class IEEEXploreSource(Source):
    name = "ieee_xplore"

    def __init__(
        self,
        requests_per_second: float = 0.5,
        daily_cap: Optional[int] = None,
        api_key: Optional[str] = None,
    ):
        self._limiter = RateLimiter(requests_per_second=requests_per_second, daily_cap=daily_cap)
        self._api_key = api_key

    def _configured(self) -> bool:
        if not self._api_key:
            logger.warning("ieee_xplore: no api_key configured — skipping (key is required, no anonymous mode)")
            return False
        return True

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._configured():
            return False
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            r = requests.get(
                _BASE_URL,
                params={"apikey": self._api_key, "querytext": "test", "max_records": 1},
                timeout=timeout,
            )
            return r.status_code < 500
        except Exception as exc:
            logger.warning("ieee_xplore probe failed: %s", exc)
            return False

    def search(
        self, query: str, limit: int, published_after: Optional[datetime] = None
    ) -> SourceSearchResult:
        if not self._configured():
            return SourceSearchResult()
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("ieee_xplore: rate limit exhausted, skipping this search")
            return SourceSearchResult()
        try:
            params = {
                "apikey": self._api_key,
                "querytext": query,
                "max_records": min(limit, 200),  # IEEE's own documented per-query cap
            }
            if published_after is not None:
                params["start_year"] = published_after.year

            response = requests.get(_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            papers = []
            for raw_article in data.get("articles", []):
                # Validated per-article, not via a top-level wrapper, so one
                # malformed article doesn't drop the whole batch -- and
                # `authors` is intentionally typed Any on the model (its
                # real shape is unconfirmed), so _extract_authors still
                # does the interpretation after validation.
                try:
                    validated = IEEEXploreArticle.model_validate(raw_article)
                    paper = _to_paper_metadata(validated)
                except Exception as exc:
                    logger.debug("IEEE Xplore article failed to parse, skipping: %s", exc)
                    continue
                if paper:
                    papers.append(paper)
            return SourceSearchResult(papers=papers)
        except Exception as exc:
            logger.error("IEEE Xplore search failed: %s", exc)
            return SourceSearchResult()


def _extract_authors(authors_field) -> List[str]:
    if isinstance(authors_field, dict):
        # documented shape: {"authors": [{"full_name": "...", ...}, ...]}
        entries = authors_field.get("authors", [])
    elif isinstance(authors_field, list):
        entries = authors_field
    else:
        entries = []

    names = []
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("full_name") or entry.get("name")
            if name:
                names.append(name)
        elif isinstance(entry, str):
            names.append(entry)
    return names


def _to_paper_metadata(article: IEEEXploreArticle) -> Optional[PaperMetadata]:
    title = article.title.strip()
    if not title:
        return None

    published_date = article.publication_date or (
        str(article.publication_year) if article.publication_year else None
    )
    url = article.html_url or (
        f"https://ieeexplore.ieee.org/document/{article.article_number}" if article.article_number else None
    )
    if not url:
        return None

    return PaperMetadata(
        title=title,
        authors=_extract_authors(article.authors),
        abstract=article.abstract or "",
        source="ieee_xplore",
        url=url,
        pdf_url=article.pdf_url,
        published_date=published_date,
        doi=article.doi,
        journal=article.publication_title or "",
        volume=article.volume,
        issue=article.issue,
        pages=f"{article.start_page}-{article.end_page}" if article.start_page and article.end_page else None,
        arxiv_id=None,
        connected_papers_url=None,
    )
