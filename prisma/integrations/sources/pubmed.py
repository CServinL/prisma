"""PubMed discovery source -- NCBI E-utilities (esearch -> esummary ->
efetch). No key required (3 req/s); a free NCBI account API key raises
the limit to 10 req/s (https://support.nlm.nih.gov/kbArticle/?pn=KA-05317).

Three real HTTP round-trips per search() call -- esearch for PMIDs,
esummary for structured metadata, efetch for abstract text (esummary
doesn't include abstracts at all) -- so the rate limiter is acquired
three times per logical search, matching real quota consumption rather
than under-counting it.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import PaperMetadata
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_ESEARCH_URL = f"{_BASE_URL}/esearch.fcgi"
_ESUMMARY_URL = f"{_BASE_URL}/esummary.fcgi"
_EFETCH_URL = f"{_BASE_URL}/efetch.fcgi"


class PubMedSource(Source):
    name = "pubmed"

    def __init__(self, requests_per_second: float = 3.0, api_key: Optional[str] = None):
        self._limiter = RateLimiter(requests_per_second=requests_per_second)
        self._api_key = api_key

    def _params(self, **extra) -> dict:
        params = dict(extra)
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            r = requests.get(
                _ESEARCH_URL,
                params=self._params(db="pubmed", term="test", retmax=1, retmode="json"),
                timeout=timeout,
            )
            return r.status_code < 500
        except Exception as exc:
            logger.warning("pubmed probe failed: %s", exc)
            return False

    def search(
        self, query: str, limit: int, published_after: Optional[datetime] = None
    ) -> SourceSearchResult:
        try:
            pmids = self._esearch(query, limit, published_after)
            if not pmids:
                return SourceSearchResult()
            summaries = self._esummary(pmids)
            abstracts = self._efetch_abstracts(pmids)

            papers = []
            for pmid in pmids:
                summary = summaries.get(pmid)
                if not summary:
                    continue
                paper = _parse_summary(pmid, summary, abstracts.get(pmid, ""))
                if paper:
                    papers.append(paper)
            return SourceSearchResult(papers=papers)
        except Exception as exc:
            logger.error("PubMed search failed: %s", exc)
            return SourceSearchResult()

    def _esearch(self, query: str, limit: int, published_after: Optional[datetime]) -> List[str]:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("pubmed: rate limit exhausted, skipping this search")
            return []
        params = self._params(db="pubmed", term=query, retmax=limit, retmode="json", sort="date")
        if published_after is not None:
            params["datetype"] = "pdat"
            params["mindate"] = published_after.strftime("%Y/%m/%d")
            params["maxdate"] = "3000/12/31"
        response = requests.get(_ESEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("esearchresult", {}).get("idlist", [])

    def _esummary(self, pmids: List[str]) -> Dict[str, dict]:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("pubmed: rate limit exhausted, skipping esummary")
            return {}
        params = self._params(db="pubmed", id=",".join(pmids), retmode="json", version="2.0")
        response = requests.get(_ESUMMARY_URL, params=params, timeout=30)
        response.raise_for_status()
        result = response.json().get("result", {})
        return {uid: result[uid] for uid in result.get("uids", []) if uid in result}

    def _efetch_abstracts(self, pmids: List[str]) -> Dict[str, str]:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("pubmed: rate limit exhausted, skipping efetch (abstracts will be empty)")
            return {}
        params = self._params(db="pubmed", id=",".join(pmids), rettype="abstract", retmode="xml")
        response = requests.get(_EFETCH_URL, params=params, timeout=30)
        response.raise_for_status()

        abstracts: Dict[str, str] = {}
        try:
            root = ET.fromstring(response.content)
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                if pmid_el is None or not pmid_el.text:
                    continue
                parts = [
                    "".join(el.itertext()).strip()
                    for el in article.findall(".//Abstract/AbstractText")
                ]
                abstracts[pmid_el.text] = " ".join(p for p in parts if p)
        except ET.ParseError as exc:
            logger.warning("pubmed: failed to parse efetch abstracts XML: %s", exc)
        return abstracts


def _parse_summary(pmid: str, summary: dict, abstract: str) -> Optional[PaperMetadata]:
    try:
        title = (summary.get("title") or "").strip()
        if not title:
            return None

        authors = [a.get("name", "").strip() for a in summary.get("authors", []) if a.get("name")]

        doi = None
        for article_id in summary.get("articleids", []):
            if article_id.get("idtype") == "doi":
                doi = article_id.get("value")
                break

        journal = summary.get("fulljournalname") or summary.get("source") or ""
        published_date = _normalize_pubdate(summary.get("pubdate", ""))

        return PaperMetadata(
            title=title,
            authors=authors,
            abstract=abstract,
            source="pubmed",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            pdf_url=None,
            published_date=published_date,
            doi=doi,
            journal=journal,
            volume=summary.get("volume") or None,
            issue=summary.get("issue") or None,
            pages=summary.get("pages") or None,
            arxiv_id=None,
            connected_papers_url=None,
        )
    except Exception as exc:
        logger.error("Failed to parse PubMed entry %s: %s", pmid, exc)
        return None


_MONTHS = {
    m: f"{i:02d}"
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


def _normalize_pubdate(pubdate: str) -> Optional[str]:
    """PubMed's `pubdate` is free-form ("2026 Jul", "2026 Jul 15", "2026") --
    normalize to YYYY-MM-DD/YYYY-MM/YYYY, matching the other sources'
    published_date shape, rather than passing NCBI's raw display string
    through unchanged."""
    if not pubdate:
        return None
    parts = pubdate.split()
    year = parts[0]
    if not year.isdigit():
        return pubdate
    if len(parts) == 1:
        return year
    month = _MONTHS.get(parts[1])
    if month is None:
        return year
    if len(parts) == 2:
        return f"{year}-{month}"
    day = parts[2].zfill(2) if parts[2].isdigit() else None
    return f"{year}-{month}-{day}" if day else f"{year}-{month}"
