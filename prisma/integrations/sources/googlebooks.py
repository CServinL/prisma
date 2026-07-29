"""Google Books discovery source.

No documented per-second limit; the real constraint is a 10,000
requests/day quota, but that quota is per API-key/project -- running
anonymously (no key, today's default) shares Google's unspecified,
much lower anonymous pool instead, so the default here throttles more
conservatively than the with-key case and does not claim the 10k/day cap
belongs to us until a key is actually configured.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import BookMetadata
from ...storage.models.api_response_models import GoogleBooksItem, GoogleBooksVolumeInfo
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.googleapis.com/books/v1/volumes"
_PROBE_URL = f"{_BASE_URL}?q=test&maxResults=1"


class GoogleBooksSource(Source):
    name = "googlebooks"

    def __init__(
        self,
        requests_per_second: float = 0.5,
        daily_cap: Optional[int] = None,
        api_key: Optional[str] = None,
    ):
        self._limiter = RateLimiter(requests_per_second=requests_per_second, daily_cap=daily_cap)
        self._api_key = api_key

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            params = {"q": "test", "maxResults": 1}
            if self._api_key:
                params["key"] = self._api_key
            r = requests.get(_BASE_URL, params=params, timeout=timeout)
            return r.status_code < 500
        except Exception as exc:
            logger.warning("googlebooks probe failed: %s", exc)
            return False

    def search(self, query: str, limit: int, published_after=None) -> SourceSearchResult:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("googlebooks: rate limit exhausted, skipping this search")
            return SourceSearchResult()
        try:
            params = {"q": query, "maxResults": min(limit, 40)}
            if self._api_key:
                params["key"] = self._api_key
            response = requests.get(_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            raw_items = response.json().get("items", [])

            books = []
            for raw_item in raw_items:
                # Validated per-item, not via the GoogleBooksResponse
                # wrapper, so one malformed item doesn't drop the whole
                # response -- same resilience the old raw-dict parsing had.
                try:
                    validated = GoogleBooksItem.model_validate(raw_item)
                    book = _to_book_metadata(validated.volumeInfo)
                except Exception as exc:
                    logger.debug("Google Books item failed to parse, skipping: %s", exc)
                    continue
                if book:
                    books.append(book)
            return SourceSearchResult(books=books)
        except Exception as exc:
            logger.error("Google Books search failed: %s", exc)
            return SourceSearchResult()


def _to_book_metadata(volume_info: GoogleBooksVolumeInfo) -> Optional[BookMetadata]:
    title = volume_info.title.strip()
    if not title:
        return None

    isbn_10 = None
    isbn_13 = None
    for identifier in volume_info.industryIdentifiers:
        if identifier.get("type") == "ISBN_10":
            isbn_10 = identifier.get("identifier")
        elif identifier.get("type") == "ISBN_13":
            isbn_13 = identifier.get("identifier")

    google_url = volume_info.infoLink or f"https://books.google.com/books?q={quote(title)}"

    cover_url = None
    if volume_info.imageLinks:
        cover_url = volume_info.imageLinks.get("thumbnail") or volume_info.imageLinks.get("smallThumbnail")

    return BookMetadata(
        title=title,
        authors=volume_info.authors,
        description=volume_info.description or "",
        source="googlebooks",
        url=google_url,
        isbn_10=isbn_10,
        isbn_13=isbn_13,
        publisher=volume_info.publisher,
        published_date=volume_info.publishedDate,
        page_count=volume_info.pageCount,
        categories=volume_info.categories,
        language=volume_info.language,
        preview_url=volume_info.previewLink,
        cover_url=cover_url,
        oclc=None,
        lccn=None,
        edition=None,
    )
