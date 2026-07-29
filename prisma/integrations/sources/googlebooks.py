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
from typing import Dict, Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import BookMetadata
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
            data = response.json()

            books = []
            for item in data.get("items", []):
                book = _parse_item(item)
                if book:
                    books.append(book)
            return SourceSearchResult(books=books)
        except Exception as exc:
            logger.error("Google Books search failed: %s", exc)
            return SourceSearchResult()


def _parse_item(item: Dict) -> Optional[BookMetadata]:
    try:
        volume_info = item.get("volumeInfo", {})

        title = volume_info.get("title", "").strip()
        if not title:
            return None

        authors = volume_info.get("authors", [])
        if not isinstance(authors, list):
            authors = []

        description = volume_info.get("description", "")

        isbn_10 = None
        isbn_13 = None
        for identifier in volume_info.get("industryIdentifiers", []):
            if identifier.get("type") == "ISBN_10":
                isbn_10 = identifier.get("identifier")
            elif identifier.get("type") == "ISBN_13":
                isbn_13 = identifier.get("identifier")

        publisher = volume_info.get("publisher")
        published_date = volume_info.get("publishedDate")

        categories = volume_info.get("categories", [])
        if not isinstance(categories, list):
            categories = []

        page_count = volume_info.get("pageCount")
        language = volume_info.get("language")

        google_url = volume_info.get("infoLink", f"https://books.google.com/books?q={quote(title)}")
        preview_url = volume_info.get("previewLink")

        cover_url = None
        image_links = volume_info.get("imageLinks", {})
        if image_links:
            cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")

        return BookMetadata(
            title=title,
            authors=authors,
            description=description,
            source="googlebooks",
            url=google_url,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            publisher=publisher,
            published_date=published_date,
            page_count=page_count,
            categories=categories,
            language=language,
            preview_url=preview_url,
            cover_url=cover_url,
            oclc=None,
            lccn=None,
            edition=None,
        )
    except Exception as exc:
        logger.error("Failed to parse Google Books entry: %s", exc)
        return None
