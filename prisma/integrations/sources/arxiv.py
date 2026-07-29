"""arXiv discovery source -- XML Atom API, no key, no hard-enforced rate
limit, but arXiv's own Terms of Use ask for no more than one request every
3 seconds on a single connection (https://info.arxiv.org/help/api/tou.html).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import PaperMetadata
from ...storage.models.api_response_models import ArXivEntry
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "http://export.arxiv.org/api/query"
_PROBE_URL = f"{_BASE_URL}?search_query=test&max_results=1"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivSource(Source):
    name = "arxiv"

    def __init__(self, requests_per_second: float = 1 / 3):
        self._limiter = RateLimiter(requests_per_second=requests_per_second)

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            r = requests.get(_PROBE_URL, timeout=timeout)
            return r.status_code < 500
        except Exception as exc:
            logger.warning("arxiv probe failed: %s", exc)
            return False

    def search(
        self, query: str, limit: int, published_after: Optional[datetime] = None
    ) -> SourceSearchResult:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("arxiv: rate limit exhausted, skipping this search")
            return SourceSearchResult()
        try:
            search_query = f"all:{quote(query)}"
            if published_after is not None:
                date_str = published_after.strftime("%Y%m%d%H%M%S")
                search_query += f"+AND+submittedDate:[{date_str}+TO+99991231235959]"

            url = (
                f"{_BASE_URL}?search_query={search_query}"
                f"&start=0&max_results={limit}"
                f"&sortBy=submittedDate&sortOrder=descending"
            )
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            papers = []
            for entry in root.findall(f"{_ATOM_NS}entry"):
                paper = _parse_entry(entry)
                if paper:
                    papers.append(paper)
            return SourceSearchResult(papers=papers)
        except Exception as exc:
            logger.error("arXiv search failed: %s", exc)
            return SourceSearchResult()


def _parse_entry(entry) -> Optional[PaperMetadata]:
    try:
        arxiv_id = entry.find(f"{_ATOM_NS}id").text.split("/")[-1]
        authors = [
            {"name": author.find(f"{_ATOM_NS}name").text}
            for author in entry.findall(f"{_ATOM_NS}author")
        ]
        # Validated through ArXivEntry so a missing required field (title,
        # summary, published) raises here rather than surfacing as a
        # confusing downstream AttributeError -- also reuses the model's
        # own title/summary strip+newline-collapse validators instead of
        # duplicating that cleanup inline.
        validated = ArXivEntry.model_validate(
            {
                "id": arxiv_id,
                "title": entry.find(f"{_ATOM_NS}title").text,
                "summary": entry.find(f"{_ATOM_NS}summary").text,
                "authors": authors,
                "published": entry.find(f"{_ATOM_NS}published").text,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            }
        )
        return PaperMetadata(
            title=validated.title,
            authors=[a.name for a in validated.authors],
            abstract=validated.summary,
            source="arxiv",
            arxiv_id=validated.id,
            url=f"https://arxiv.org/abs/{validated.id}",
            pdf_url=validated.pdf_url,
            published_date=validated.published[:10],  # YYYY-MM-DD
            connected_papers_url=f"https://www.connectedpapers.com/search?q={quote(validated.title)}",
            doi=None,
            # arXiv isn't stored anywhere else on this model, but is a real,
            # recognized venue -- needed so SearchAgent's centralized
            # academic-content validation (which checks venue/publisher)
            # doesn't reject every arXiv paper for lacking one.
            journal="arXiv",
            volume=None,
            issue=None,
            pages=None,
        )
    except Exception as exc:
        logger.error("Failed to parse arXiv entry: %s", exc)
        return None
