"""Common interface every discovery source implements.

`SearchAgent` (`prisma/agents/search_agent.py`) depends on this
abstraction, not on any concrete source module -- adding a new source
means adding one module here plus one registry entry in `__init__.py`,
never touching `SearchAgent` itself.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ...storage.models.agent_models import BookMetadata, PaperMetadata


class SourceSearchResult(BaseModel):
    """What one source's search() call returns -- merged across every
    requested source by SearchAgent into the aggregate SearchResult
    (storage.models.agent_models.SearchResult)."""
    model_config = ConfigDict(populate_by_name=True)

    papers: List[PaperMetadata] = Field(default_factory=list)
    books: List[BookMetadata] = Field(default_factory=list)


class Source(ABC):
    """One discovery source: papers and/or books fetched from one external
    API, enforcing its own quota. `name` must match the corresponding key
    in `storage.models.source_quality.SOURCE_REGISTRY` and
    `utils.config.SearchConfig.valid_sources`.
    """

    name: str

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int,
        published_after: Optional[datetime] = None,
    ) -> SourceSearchResult:
        """Fetch results for `query`, at most `limit` items. Must not
        raise on a network/parse failure -- log and return an empty
        SourceSearchResult, the same contract SearchAgent already relies
        on today for a source that's down. Must call its own
        `prisma.services.rate_limiter.RateLimiter` before every request it
        makes; if the limiter denies (timeout elapsed, or a daily cap
        exhausted), log a warning and return empty rather than blocking
        the whole search."""
        raise NotImplementedError

    def probe(self, timeout: float = 5.0) -> bool:
        """Lightweight reachability check used by SearchAgent.preflight().
        Default assumes reachable; override for a real cheap ping. Must
        never raise."""
        return True
