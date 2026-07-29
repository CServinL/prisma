"""Open Library discovery source -- Internet Archive's book API.

No key. Default rate limit for anonymous requests is 1 req/s; identified
requests (a descriptive User-Agent) get 3 req/s per Open Library's own
policy, so this always sends one -- a legitimate, free 3x, not a guess.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import requests

from ...services.rate_limiter import RateLimiter
from ...storage.models.agent_models import BookMetadata
from ...storage.models.api_response_models import OpenLibraryDocument, OpenLibraryResponse
from .base import Source, SourceSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://openlibrary.org"
_PROBE_URL = f"{_BASE_URL}/search.json?q=test&limit=1"
_HEADERS = {"User-Agent": "Prisma/1.0 (+https://github.com/CServinL/prisma)"}


class OpenLibrarySource(Source):
    name = "openlibrary"

    def __init__(self, requests_per_second: float = 3.0):
        self._limiter = RateLimiter(requests_per_second=requests_per_second)

    def probe(self, timeout: float = 5.0) -> bool:
        if not self._limiter.acquire(timeout=timeout):
            return False
        try:
            r = requests.get(_PROBE_URL, headers=_HEADERS, timeout=timeout)
            return r.status_code < 500
        except Exception as exc:
            logger.warning("openlibrary probe failed: %s", exc)
            return False

    def search(self, query: str, limit: int, published_after=None) -> SourceSearchResult:
        if not self._limiter.acquire(timeout=30.0):
            logger.warning("openlibrary: rate limit exhausted, skipping this search")
            return SourceSearchResult()
        try:
            search_query = quote(query)
            url = f"{_BASE_URL}/search.json?q={search_query}&limit={limit}"
            response = requests.get(url, headers=_HEADERS, timeout=30)
            response.raise_for_status()

            api_response = OpenLibraryResponse.model_validate(response.json())
            books = []
            for doc in api_response.docs:
                book = _parse_doc(doc)
                if book:
                    books.append(book)
            return SourceSearchResult(books=books)
        except Exception as exc:
            logger.error("Open Library search failed: %s", exc)
            return SourceSearchResult()


def _parse_doc(doc: OpenLibraryDocument) -> Optional[BookMetadata]:
    try:
        title = doc.title.strip()
        if not title:
            return None

        authors = [name.strip() for name in doc.author_name if name.strip()]

        isbn_10 = None
        isbn_13 = None
        for isbn in doc.isbn:
            isbn_clean = isbn.replace("-", "").replace(" ", "")
            if len(isbn_clean) == 10:
                isbn_10 = isbn_clean
            elif len(isbn_clean) == 13:
                isbn_13 = isbn_clean

        publisher = doc.publisher[0] if doc.publisher else None
        published_date = str(doc.first_publish_year) if doc.first_publish_year else None
        subjects = doc.subject[:10]  # cap to 10 subjects
        # `doc` is a Pydantic model, not a dict -- .get() doesn't exist on
        # it. This line previously called doc.get(...) here, which raised
        # AttributeError on every single document and was silently
        # swallowed by the caller's broad except -- Open Library has
        # returned zero results ever since this model was introduced.
        language = doc.language[0] if doc.language else None

        ol_url = f"https://openlibrary.org{doc.key}" if doc.key else f"https://openlibrary.org/search?q={quote(title)}"

        return BookMetadata(
            title=title,
            authors=authors,
            description="",
            source="openlibrary",
            url=ol_url,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            publisher=publisher,
            published_date=published_date,
            subjects=subjects,
            page_count=None,
            language=language,
            oclc=None,
            lccn=None,
            edition=None,
            preview_url=None,
            cover_url=None,
        )
    except Exception as exc:
        logger.error("Failed to parse Open Library entry: %s", exc)
        return None
